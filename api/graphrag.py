# D:\precision_agent\api\graphrag.py
"""
Λόγος Agent · GraphRAG API 路由
Phase 4: 实体关系图 + 社区摘要 + 图检索
v0.4.4-fix3: 删除重复的 _async_graph_build，统一使用 batch 抽取版
"""

import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from core.graphrag.extractor import extract_entities_relations
from core.graphrag.graph_store import get_knowledge_graph
from core.graphrag.community import get_community_engine
from core.graphrag.query_engine import get_query_engine

router = APIRouter()


# ───────────────────────────────────────────────
# 请求/响应模型
# ───────────────────────────────────────────────

class ExtractRequest(BaseModel):
    text: str = Field(..., description="待抽取的文本内容")
    source_chunk: Optional[str] = Field(default=None, description="来源 chunk ID")


class ExtractResponse(BaseModel):
    entities: List[Dict[str, Any]]
    relations: List[Dict[str, Any]]
    added: bool


class GraphQueryRequest(BaseModel):
    query: str = Field(..., description="查询语句")
    top_k_entities: int = Field(default=5, ge=1, le=20)
    depth: int = Field(default=2, ge=1, le=3)


class GraphQueryResponse(BaseModel):
    query: str
    matched_entities: List[Dict[str, Any]]
    subgraph: Dict[str, Any]
    relevant_communities: List[Dict[str, Any]]
    answer_context: str


class BuildGraphRequest(BaseModel):
    chunks: List[Dict[str, Any]] = Field(..., description="检索结果 chunks")
    user_id: Optional[str] = Field(default=None)
    background: bool = Field(default=False, description="是否后台异步处理，避免超时")


class BuildGraphResponse(BaseModel):
    status: str
    entities_added: int
    relations_added: int
    graph_stats: Dict[str, Any]
    task_id: Optional[str] = None


class EntityDetailResponse(BaseModel):
    found: bool
    entity: Optional[Dict[str, Any]] = None
    neighbors: Optional[List[Dict[str, Any]]] = None
    subgraph: Optional[Dict[str, Any]] = None
    community_id: Optional[int] = None


class CommunityListResponse(BaseModel):
    communities: List[Dict[str, Any]]
    inter_community_relations: List[Dict[str, Any]]


# ───────────────────────────────────────────────
# API 端点
# ───────────────────────────────────────────────

@router.post("/graphrag/extract", response_model=ExtractResponse)
async def graphrag_extract(request: ExtractRequest):
    """
    从文本中抽取实体关系并入库
    """
    try:
        entities, relations = await extract_entities_relations(
            text=request.text,
            source_chunk=request.source_chunk
        )

        kg = get_knowledge_graph()
        kg.add_entities_relations(entities, relations, source_chunk=request.source_chunk)
        kg.save()

        return ExtractResponse(
            entities=entities,
            relations=relations,
            added=True
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"抽取失败: {str(e)}")


@router.post("/graphrag/query", response_model=GraphQueryResponse)
async def graphrag_query(request: GraphQueryRequest):
    """
    图检索查询：基于查询找到相关实体，展开子图，聚合社区信息
    返回可用于 Synthesize 的 answer_context
    """
    try:
        engine = get_query_engine()
        result = engine.global_query(
            query=request.query,
            top_k_entities=request.top_k_entities,
            depth=request.depth
        )
        return GraphQueryResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图查询失败: {str(e)}")


@router.post("/graphrag/build", response_model=BuildGraphResponse)
async def graphrag_build(request: BuildGraphRequest):
    """
    从检索结果批量构建/增量更新知识图谱
    v0.4.4: 同步模式也使用批量抽取；强制后台阈值调高到 20
    """
    import uuid

    task_id = str(uuid.uuid4())[:8]
    CHUNK_SYNC_LIMIT = 20  # 调高：测试脚本 5-10 个 chunks 可走同步批量

    # 防御性强制后台：只有超大批量才后台，避免 Dify 傻等
    if not request.background and len(request.chunks) > CHUNK_SYNC_LIMIT:
        print(f"[graphrag/build] 强制后台模式: chunks={len(request.chunks)} > {CHUNK_SYNC_LIMIT}")
        asyncio.create_task(_async_graph_build(task_id, request.chunks))
        return BuildGraphResponse(
            status="accepted",
            entities_added=0,
            relations_added=0,
            graph_stats={},
            task_id=task_id
        )

    # 同步批量模式（测试脚本 + 小批量生产调用）
    try:
        from core.graphrag.extractor import extract_entities_relations_batch
        kg = get_knowledge_graph()

        valid_items = []
        for i, chunk in enumerate(request.chunks):
            if not isinstance(chunk, dict):
                continue
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id") or chunk.get("id", f"chunk_{i}")
            if len(content) < 100:
                continue
            valid_items.append((content, chunk_id))

        total_entities = 0
        total_relations = 0
        processed = len(valid_items)
        skipped = len(request.chunks) - len(valid_items)

        if valid_items:
            print(f"[graphrag/build] 同步批量抽取: {len(valid_items)} 个 chunks")
            batch_results = await extract_entities_relations_batch(valid_items)
            for entities, relations, chunk_id in batch_results:
                kg.add_entities_relations(entities, relations, source_chunk=chunk_id)
                total_entities += len(entities)
                total_relations += len(relations)
                print(f"[graphrag/build] {chunk_id}: entities={len(entities)}, relations={len(relations)}")

        save_ok = kg.save()
        print(f"[graphrag/build] 完成: processed={processed}, skipped={skipped}, "
              f"entities={total_entities}, relations={total_relations}, saved={save_ok}")

        return BuildGraphResponse(
            status="success",
            entities_added=total_entities,
            relations_added=total_relations,
            graph_stats=kg.get_stats(),
            task_id=task_id
        )
    except Exception as e:
        print(f"[graphrag/build] 异常: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"图谱构建失败: {str(e)}")


async def _async_graph_build(task_id: str, chunks: List[Dict[str, Any]]) -> None:
    """
    后台异步构建图谱（v0.4.4 批量抽取版）
    v0.4.4-fix3: 统一使用 extract_entities_relations_batch，避免串行单条超时
    """
    try:
        from core.graphrag.extractor import extract_entities_relations_batch
        kg = get_knowledge_graph()

        valid_items = []
        for i, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id") or chunk.get("id", f"chunk_{i}")
            if len(content) < 100:
                continue
            valid_items.append((content, chunk_id))

        total_entities = 0
        total_relations = 0
        processed = len(valid_items)
        skipped = len(chunks) - len(valid_items)

        if valid_items:
            print(f"[graphrag/build/bg] 任务 {task_id}: 批量抽取 {len(valid_items)} 个 chunks")
            batch_results = await extract_entities_relations_batch(valid_items)
            for entities, relations, chunk_id in batch_results:
                kg.add_entities_relations(entities, relations, source_chunk=chunk_id)
                total_entities += len(entities)
                total_relations += len(relations)

        save_ok = kg.save()
        print(f"[graphrag/build/bg] 任务 {task_id} 完成: "
              f"processed={processed}, skipped={skipped}, "
              f"entities={total_entities}, relations={total_relations}, saved={save_ok}")

    except Exception as e:
        print(f"[graphrag/build/bg] 任务 {task_id} 整体异常: {e}")
        import traceback
        traceback.print_exc()


@router.get("/graphrag/entities")
async def list_entities(
    query: Optional[str] = None,
    entity_type: Optional[str] = None,
    top_k: int = 50
):
    """
    列出/搜索实体
    """
    try:
        kg = get_knowledge_graph()

        if query:
            results = kg.search_entities(query, top_k)
        else:
            results = []
            for node, data in kg.graph.nodes(data=True):
                item = dict(data)
                item["name"] = node
                if entity_type and item.get("type") != entity_type:
                    continue
                results.append(item)
            results = results[:top_k]

        return {"entities": results, "total": kg.graph.number_of_nodes()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"实体列表失败: {str(e)}")


@router.get("/graphrag/entity/{entity_name}")
async def get_entity_detail(entity_name: str):
    """
    获取实体详情（含邻居和子图）
    """
    try:
        engine = get_query_engine()
        result = engine.query_entity(entity_name, include_neighbors=True)
        return EntityDetailResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"实体查询失败: {str(e)}")


@router.get("/graphrag/communities")
async def list_communities():
    """
    列出所有社区及其间关系
    """
    try:
        ce = get_community_engine()
        communities = ce.get_all_communities()

        if not communities:
            return CommunityListResponse(communities=[], inter_community_relations=[])

        return CommunityListResponse(
            communities=list(communities.values()),
            inter_community_relations=ce.get_inter_community_relations()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"社区列表失败: {str(e)}")


@router.post("/graphrag/communities/build")
async def build_communities(resolution: float = 1.0):
    """
    重新执行社区发现和摘要生成
    """
    try:
        ce = get_community_engine()
        communities = await ce.build_all_summaries(resolution=resolution)
        return {
            "status": "success",
            "community_count": len(communities),
            "communities": list(communities.values())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"社区构建失败: {str(e)}")


@router.post("/graphrag/save")
async def save_graph():
    """手动保存图谱到磁盘"""
    try:
        kg = get_knowledge_graph()
        ce = get_community_engine()
        kg.save()
        ce.save()
        return {"status": "success", "message": "图谱已保存"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


@router.post("/graphrag/load")
async def load_graph():
    """手动从磁盘加载图谱"""
    try:
        kg = get_knowledge_graph()
        ce = get_community_engine()
        kg.load()
        ce.load()
        return {
            "status": "success",
            "message": "图谱已加载",
            "stats": kg.get_stats()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载失败: {str(e)}")
