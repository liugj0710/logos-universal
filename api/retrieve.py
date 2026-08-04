# D:\precision_agent\api\retrieve.py
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, validator
from typing import List, Dict, Optional, Union, Any
import asyncio
import time

from core.llm import call_llm
from core.rewrite import rewrite_query
from core.search import search_bing, search_baidu, search_chroma, search_dify_kb
from core.memory.search import search_memory
from core.fusion import rrf_fusion, deduplicate_by_content
from core.config import get_settings
from core.graphrag.extractor import extract_entities_relations
from core.graphrag.graph_store import get_knowledge_graph

router = APIRouter()
settings = get_settings()


class RetrieveRequest(BaseModel):
    sub_queries: Union[List[str], str, None] = []
    skill_hint: str = "default_deep"
    top_k: Union[int, str] = 10
    user_id: Optional[str] = None
    memory_context: Optional[str] = None

    @validator('sub_queries', pre=True, always=True)
    def parse_sub_queries(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            parsed = [q.strip() for q in v.replace('\n', ',').split(',') if q.strip()]
            return parsed if parsed else []
        if isinstance(v, list):
            cleaned = []
            for item in v:
                if item is None:
                    continue
                s = str(item).strip()
                if s:
                    cleaned.append(s)
            return cleaned
        s = str(v).strip()
        return [s] if s else []

    @validator('top_k', pre=True, always=True)
    def parse_top_k(cls, v):
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 10
        if isinstance(v, int):
            return v
        return 10

    class Config:
        extra = 'allow'


class RetrieveResponse(BaseModel):
    original_sub_queries: List[str]
    rewritten_queries: List[List[str]]
    retrieved_chunks: List[Dict]
    source_stats: Dict
    memory_injected: bool = False


# ───────────────────────────────────────────────
# v0.4.5.2 新增: Fast Lane 轻量检索端点
# ───────────────────────────────────────────────

class FastRetrieveRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    top_k: int = 5
    include_memory: bool = True
    include_dify_kb: bool = True

    class Config:
        extra = "allow"


class FastRetrieveResponse(BaseModel):
    query: str
    memory_results: List[Dict[str, Any]]
    dify_kb_results: List[Dict[str, Any]]
    total_results: int
    latency_ms: float


async def _search_with_timeout(search_fn, query, top_k, skill_hint=None, timeout=30):
    try:
        if skill_hint is not None:
            return await asyncio.wait_for(search_fn(query, top_k=top_k, skill_hint=skill_hint), timeout=timeout)
        else:
            return await asyncio.wait_for(search_fn(query, top_k=top_k), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[retrieve] {search_fn.__name__}('{query[:30]}...') 超时({timeout}s)，跳过")
        return []
    except Exception as e:
        print(f"[retrieve] {search_fn.__name__}('{query[:30]}...') 异常: {e}")
        return []


async def _fast_memory_search(user_id: str, query: str, top_k: int, timeout: float = 8.0):
    """Fast Lane 专用记忆检索，低超时"""
    try:
        return await asyncio.wait_for(search_memory(user_id, query, top_k), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[fast_retrieve] memory search 超时({timeout}s)")
        return []
    except Exception as e:
        print(f"[fast_retrieve] memory search 异常: {e}")
        return []


async def _fast_dify_search(query: str, top_k: int, timeout: float = 8.0):
    """Fast Lane 专用 Dify KB 检索，低超时"""
    try:
        return await asyncio.wait_for(search_dify_kb(query, top_k), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[fast_retrieve] dify_kb search 超时({timeout}s)")
        return []
    except Exception as e:
        print(f"[fast_retrieve] dify_kb search 异常: {e}")
        return []


@router.post("/fast_retrieve", response_model=FastRetrieveResponse)
async def fast_retrieve(request: FastRetrieveRequest):
    """
    Fast Lane 轻量检索端点（v0.4.5.2）。
    并行查询 Memory + Dify KB，低延迟（< 5s），供 Dify Fast Lane 直接调用。
    不走网页搜索、不走 Planner、不走 Synthesize、不走 RRF 融合。
    """
    start_time = time.time()

    # v0.4.5.2 修复: 空查询防御
    if not request.query or not request.query.strip():
        return FastRetrieveResponse(
            query=request.query or "",
            memory_results=[],
            dify_kb_results=[],
            total_results=0,
            latency_ms=0.0
        )

    tasks = []
    flags = []

    if request.include_memory and request.user_id:
        tasks.append(_fast_memory_search(request.user_id, request.query, request.top_k))
        flags.append("memory")

    if request.include_dify_kb:
        tasks.append(_fast_dify_search(request.query, request.top_k))
        flags.append("dify_kb")

    if not tasks:
        return FastRetrieveResponse(
            query=request.query,
            memory_results=[],
            dify_kb_results=[],
            total_results=0,
            latency_ms=0.0
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    memory_results = []
    dify_kb_results = []

    for flag, result in zip(flags, results):
        if isinstance(result, Exception):
            print(f"[fast_retrieve] {flag} 异常: {result}")
            continue
        if flag == "memory":
            memory_results = result if result else []
        elif flag == "dify_kb":
            dify_kb_results = result if result else []

    latency_ms = round((time.time() - start_time) * 1000, 2)

    print(f"[fast_retrieve] query='{request.query[:40]}...' "
          f"memory={len(memory_results)} dify_kb={len(dify_kb_results)} "
          f"latency={latency_ms}ms")

    return FastRetrieveResponse(
        query=request.query,
        memory_results=memory_results,
        dify_kb_results=dify_kb_results,
        total_results=len(memory_results) + len(dify_kb_results),
        latency_ms=latency_ms
    )


@router.post("/retrieve", response_model=RetrieveResponse)
async def deep_hybrid_retrieve(request: RetrieveRequest, background_tasks: BackgroundTasks):
    try:


        # Step 0: 子查询封顶
        sub_queries = request.sub_queries[:5] if request.sub_queries else ["default query"]
        if not sub_queries:
            sub_queries = ["default query"]

        # Step 0.5: 记忆检索（改写输入注入，不参与 RRF）
        memory_context = request.memory_context
        memory_injected = False

        if request.user_id and not memory_context:
            try:
                from core.memory.search import search_memory
                mem_results = await search_memory(
                    request.user_id,
                    " ".join(sub_queries),
                    top_k=3
                )
                if mem_results:
                    memory_context = "\n".join([
                        f"- {m['content']}" for m in mem_results
                    ])
                    print(f"[retrieve] 记忆上下文注入 ({request.user_id}): {memory_context[:80]}...")
                    memory_injected = True
            except Exception as e:
                print(f"[retrieve] 记忆检索失败: {e}")

        # Step 1: 并行改写（注入记忆上下文）
        rewrite_tasks = [
            rewrite_query(q, context=memory_context) for q in sub_queries
        ]
        rewritten_groups = await asyncio.gather(*rewrite_tasks)

        # Step 2: 扁平化去重
        all_queries = list(set([
            q for group in rewritten_groups for q in group
        ]))
        if not all_queries:
            all_queries = sub_queries

        # Step 3: 并行检索
        # v0.3.2: Bing/Baidu 网页搜索已恢复（DrissionPage 升级后修复）
        WEB_TOP_K = 5
        KB_TOP_K = 10

        search_tasks = []
        for query in all_queries:
            search_tasks.append(_search_with_timeout(search_bing, query, WEB_TOP_K, timeout=60))
            search_tasks.append(_search_with_timeout(search_baidu, query, WEB_TOP_K, timeout=60))
            search_tasks.append(_search_with_timeout(search_chroma, query, KB_TOP_K, skill_hint=request.skill_hint, timeout=30))
            search_tasks.append(_search_with_timeout(search_dify_kb, query, KB_TOP_K, timeout=25))

        all_results = await asyncio.wait_for(
            asyncio.gather(*search_tasks, return_exceptions=True),
            timeout=120.0
        )

        valid_results = [r for r in all_results if not isinstance(r, Exception)]

        # Step 4: RRF 融合 + 去重
        fused_results = rrf_fusion(valid_results, k=60)
        deduped = deduplicate_by_content(fused_results)

        # Step 5: 内容质量过滤
        quality_filtered = [
            r for r in deduped
            if len(r.get("content", "")) >= 200
        ]

        # v0.3.0: 异步写入 Ledger
        if request.user_id:
            try:
                from core.memory.ledger import append_ledger
                asyncio.create_task(asyncio.to_thread(
                    append_ledger,
                    request.user_id,
                    "conversation_turn",
                    {
                        "query": " | ".join(sub_queries),
                        "retrieved_count": len(quality_filtered),
                        "skill_hint": request.skill_hint
                    },
                    {"source": "retrieve", "memory_injected": memory_injected}
                ))
            except Exception as e:
                print(f"[retrieve] Ledger 写入失败: {e}")

        # Phase 4: 后台触发 GraphRAG 构建（不阻塞返回，使用 FastAPI BackgroundTasks）
        background_tasks.add_task(_background_graph_build, quality_filtered)

        return RetrieveResponse(
            original_sub_queries=sub_queries,
            rewritten_queries=rewritten_groups,
            retrieved_chunks=quality_filtered[:request.top_k],
            source_stats={
                "total_queries": len(all_queries),
                "total_raw_results": sum(len(r) for r in valid_results),
                "after_fusion": len(deduped),
                "after_quality_filter": len(quality_filtered),
                "final_returned": min(len(quality_filtered), request.top_k),
                "memory_injected": memory_injected
            },
            memory_injected=memory_injected
        )

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Retrieve timeout: 检索总耗时超过 120 秒")
    except Exception as e:
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        print(f"[retrieve] 致命错误: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Retrieve failed: {str(e)}")

# ───────────────────────────────────────────────
# Phase 4: 后台 GraphRAG 构建
# ───────────────────────────────────────────────

# v0.4.5: 全局后台构建信号量，限制并发为 2，避免拖慢前台 synthesize
_bg_build_semaphore = None


def _get_bg_semaphore():
    global _bg_build_semaphore
    if _bg_build_semaphore is None:
        import asyncio
        _bg_build_semaphore = asyncio.Semaphore(2)
    return _bg_build_semaphore


def _background_graph_build(chunks: List[Dict[str, Any]]) -> None:
    """
    后台异步构建知识图谱（v0.4.5 并发限制版）
    使用 Semaphore(2) 限制同时运行的后台 build 数量，避免占用全部 LLM 调用队列。
    """
    import asyncio

    async def _build():
        sem = _get_bg_semaphore()
        async with sem:
            try:
                from core.graphrag.extractor import extract_entities_relations_batch
                kg = get_knowledge_graph()
                total_entities = 0
                total_relations = 0
                processed = 0
                skipped = 0

                # 过滤有效 chunks
                valid_items = []
                for i, chunk in enumerate(chunks):
                    if not isinstance(chunk, dict):
                        skipped += 1
                        continue
                    content = chunk.get("content", "")
                    chunk_id = chunk.get("chunk_id") or chunk.get("id", f"chunk_{i}")
                    if len(content) < 100:
                        skipped += 1
                        continue
                    valid_items.append((content, chunk_id))

                print(f"[bg_graph_build] 开始后台构建，{len(valid_items)} 个有效 chunks")

                if not valid_items:
                    print("[bg_graph_build] 无有效 chunks，跳过")
                    return

                # v0.4.4: 批量抽取（每批最多 4 个，总长度 < 2500）
                batch_results = await extract_entities_relations_batch(valid_items)

                for entities, relations, chunk_id in batch_results:
                    kg.add_entities_relations(entities, relations, source_chunk=chunk_id)
                    total_entities += len(entities)
                    total_relations += len(relations)
                    processed += 1

                save_ok = kg.save()
                print(f"[bg_graph_build] 完成: processed={processed}, skipped={skipped}, "
                      f"entities={total_entities}, relations={total_relations}, saved={save_ok}")

            except Exception as e:
                print(f"[bg_graph_build] 后台构建整体异常: {e}")
                import traceback
                traceback.print_exc()

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_build())
    except RuntimeError:
        # v0.4.5 修复: 没有运行中的事件循环时，创建新循环
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(_build())
