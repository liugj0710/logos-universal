# D:\precision_agent\api\synthesize.py
"""
Λόγος Agent · /api/v1/synthesize
职责：基于检索结果生成结构化深度报告
v0.4.4: 并行化内部检索与图谱查询；强制后台 build 阈值；适配 180s Dify 超时
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import asyncio

from core.synthesize import generate_report
from core.config import get_settings

router = APIRouter()
settings = get_settings()


# ───────────────────────────────────────────────
# 请求/响应模型
# ───────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    original_query: str = Field(..., description="用户的原始问题")
    sub_queries: List[str] = Field(default=[], description="Planner 拆解的子查询列表")
    target_entity: Optional[str] = Field(default=None, description="核心分析对象")
    skill_hint: str = Field(default="default_deep", description="报告类型提示")
    retrieved_chunks: List[Dict[str, Any]] = Field(
        default=[], description="retrieve 返回的检索结果（强烈推荐传入，避免内部二次检索）"
    )
    memory_context: Optional[str] = Field(default=None, description="记忆上下文")
    graph_context: Optional[str] = Field(default=None, description="知识图谱上下文（可选）")
    user_id: Optional[str] = Field(default=None, description="用户ID，用于Ledger记录")

    class Config:
        extra = "allow"


class SynthesizeResponse(BaseModel):
    markdown_report: str = Field(..., description="完整 Markdown 报告，可直接展示")
    structured_data: Dict[str, Any] = Field(..., description="结构化数据，供系统消费")
    citation_cleaned: bool = Field(default=False, description="是否经过轻量引用清理")
    model: str = Field(default="deepseek-v4-pro")
    skill_used: str = Field(default="default_deep")
    status: str = Field(default="success", description="success | partial | failed")
    error_message: Optional[str] = Field(default=None)
    graph_context_injected: bool = Field(default=False, description="是否注入了图谱上下文")
    auto_retrieved: bool = Field(default=False, description="是否由 Synthesize 内部自动执行了检索")


# ───────────────────────────────────────────────
# API 端点
# ───────────────────────────────────────────────

@router.post("/synthesize", response_model=SynthesizeResponse)
async def deep_synthesize(request: SynthesizeRequest):
    """
    深度报告生成 API — v0.4.4 性能优化版

    【Dify 调用建议】
    1. 务必传入 retrieved_chunks（由前序 Retrieve Tool 返回），避免 Synthesize 内部二次检索
    2. 不要在此前置同步调用 GraphRAG Build，图谱构建由 Retrieve 后台自动完成
    3. 总耗时预算：传入 chunks 时约 90-120s；不传入时约 150-180s（刚好卡线）
    """
    t_start = asyncio.get_event_loop().time()
    auto_retrieved = False

    try:
        # 子查询封顶
        sub_queries = request.sub_queries[:5] if request.sub_queries else [request.original_query]

        # ── 阶段 A：并行获取检索结果 + 图谱上下文 ──
        async def _auto_retrieve() -> List[Dict[str, Any]]:
            """内部自动检索（仅当 Dify 未传 chunks 时触发）"""
            nonlocal auto_retrieved
            if request.retrieved_chunks:
                return request.retrieved_chunks
            try:
                from api.retrieve import deep_hybrid_retrieve, RetrieveRequest
                retrieve_req = RetrieveRequest(
                    sub_queries=sub_queries,
                    skill_hint=request.skill_hint,
                    top_k=5,
                    user_id=request.user_id,
                    memory_context=request.memory_context
                )
                # 手动构造 BackgroundTasks，避免 FastAPI 依赖注入问题
                retrieve_res = await deep_hybrid_retrieve(retrieve_req, BackgroundTasks())
                chunks = retrieve_res.retrieved_chunks

                # 截断每个 chunk 到 1500 字，压缩 LLM 上下文
                for chunk in chunks:
                    content = chunk.get("content", "")
                    if len(content) > 1500:
                        chunk["content"] = content[:1500] + "...[内容已截断]"

                auto_retrieved = True
                print(f"[synthesize] 内部自动检索完成，{len(chunks)} 条 chunks")
                return chunks
            except Exception as e:
                print(f"[synthesize] 内部自动检索失败: {e}")
                return []

        async def _auto_graph_query() -> str:
            """内部自动图谱查询（仅当 Dify 未传 graph_context 时触发）"""
            if request.graph_context:
                return request.graph_context
            try:
                from core.graphrag.query_engine import get_query_engine
                engine = get_query_engine()
                graph_result = engine.global_query(
                    query=request.original_query,
                    top_k_entities=5,
                    depth=2
                )
                ctx = graph_result.get("answer_context", "")
                print(f"[synthesize] GraphRAG 上下文自动注入: {len(ctx)} 字")
                return ctx
            except Exception as e:
                print(f"[synthesize] GraphRAG 查询失败（非阻塞）: {e}")
                return ""

        # 并行执行：检索和图谱查询互不阻塞
        chunks_task = asyncio.create_task(_auto_retrieve())
        graph_task = asyncio.create_task(_auto_graph_query())

        retrieved_chunks = await chunks_task
        graph_context = await graph_task
        graph_context_injected = bool(graph_context)

        # ── 阶段 B：报告生成（耗时大头，约 60-90s）──
        result = await generate_report(
            original_query=request.original_query,
            sub_queries=sub_queries,
            target_entity=request.target_entity,
            skill_hint=request.skill_hint,
            retrieved_chunks=retrieved_chunks,
            memory_context=request.memory_context,
            graph_context=graph_context
        )

        # ── 阶段 C：异步记账 ──
        if request.user_id:
            try:
                from core.memory.ledger import append_ledger
                asyncio.create_task(asyncio.to_thread(
                    append_ledger,
                    request.user_id,
                    "deep_lane_complete",
                    {
                        "query": request.original_query,
                        "sub_queries": sub_queries,
                        "skill_hint": request.skill_hint,
                        "chunks_used": len(retrieved_chunks),
                        "citation_cleaned": result.get("citation_cleaned", False),
                        "graph_context_injected": graph_context_injected,
                        "auto_retrieved": auto_retrieved,
                        "elapsed_sec": round(asyncio.get_event_loop().time() - t_start, 2)
                    },
                    {"source": "synthesize", "model": "deepseek-v4-pro"}
                ))
            except Exception as e:
                print(f"[synthesize] Ledger 写入失败: {e}")

        elapsed = round(asyncio.get_event_loop().time() - t_start, 2)
        print(f"[synthesize] 总耗时: {elapsed}s | auto_retrieved={auto_retrieved} | graph_injected={graph_context_injected}")

        return SynthesizeResponse(
            markdown_report=result["markdown_report"],
            structured_data=result["structured_data"],
            citation_cleaned=result.get("citation_cleaned", False),
            model=result.get("model", "deepseek-v4-pro"),
            skill_used=result.get("skill_used", request.skill_hint),
            status="success",
            graph_context_injected=graph_context_injected,
            auto_retrieved=auto_retrieved
        )

    except Exception as e:
        error_detail = f"{type(e).__name__}: {str(e) or '无详细描述'}"
        error_msg = f"报告生成失败: {error_detail}"
        print(f"[synthesize] {error_msg}")

        fallback_markdown = f"""# 报告生成异常

很抱歉，基于当前检索结果生成深度报告时遇到了技术问题。

**原始问题**：{request.original_query}

**错误信息**：{error_detail}

**建议**：
1. 稍后重试
2. 简化问题后重新提问
3. 联系管理员检查外部引擎状态
"""

        fallback_structured = {
            "executive_summary": f"报告生成失败: {error_detail}",
            "sections": [{"title": "错误信息", "content": error_detail, "citations": []}],
            "citations": [],
            "key_insights": ["报告生成失败，请重试"],
            "confidence": "low",
            "skill_used": request.skill_hint,
            "model": "deepseek-v4-pro",
            "error": error_detail
        }

        return SynthesizeResponse(
            markdown_report=fallback_markdown,
            structured_data=fallback_structured,
            citation_cleaned=False,
            model="deepseek-v4-pro",
            skill_used=request.skill_hint,
            status="failed",
            error_message=error_msg,
            graph_context_injected=False,
            auto_retrieved=False
        )