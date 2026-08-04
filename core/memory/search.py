"""
Memory Search — Chroma logos_memory 语义检索
按 user_id 隔离，不参与 RRF 融合
"""
import time
import json
import asyncio
import threading
from typing import List, Dict, Any
from core.chroma_client import get_chroma_client, get_embedding_function
from core.config import get_settings

settings = get_settings()
_chroma_lock = threading.Lock()


def _get_memory_collection():
    """获取 logos_memory collection 单例"""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.MEMORY_COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"}
    )


def _clean_meta(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chroma metadata 严格限制：
    - 只接受 str / int / float / bool
    - list 必须非空（且不同版本支持不稳定，干脆序列化为字符串）
    - 空值、空字符串、空列表、空字典全部过滤
    """
    result = {}
    for k, v in metadata.items():
        if v is None:
            continue
        if isinstance(v, bool):
            result[k] = v
        elif isinstance(v, (int, float)):
            result[k] = v
        elif isinstance(v, str):
            if v.strip():
                result[k] = v
        elif isinstance(v, (list, dict, tuple)):
            s = json.dumps(v, ensure_ascii=False)
            if s not in ("[]", "{}", '""', ""):
                result[k] = s
    return result


async def search_memory(user_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    语义检索用户记忆。
    按 user_id 过滤，避免父子领域交叉污染。
    """
    def _do_search():
        with _chroma_lock:
            try:
                collection = _get_memory_collection()
                embed_fn = get_embedding_function()
                query_embeddings = embed_fn([query])

                results = collection.query(
                    query_embeddings=query_embeddings,
                    n_results=top_k,
                    where={"user_id": user_id},
                    include=["documents", "metadatas", "distances"]
                )

                output = []
                if not results or not results.get("ids") or not results["ids"][0]:
                    return output

                for i, doc_id in enumerate(results["ids"][0]):
                    distance = results["distances"][0][i]
                    score = max(0.0, 1.0 - distance)

                    output.append({
                        "content": results["documents"][0][i],
                        "source": "memory",
                        "score": round(score, 4),
                        "metadata": results["metadatas"][0][i]
                    })

                output.sort(key=lambda x: x["score"], reverse=True)
                return output

            except Exception as e:
                print(f"[search_memory] Error: {e}")
                return []

    return await asyncio.to_thread(_do_search)


async def add_memory(
    user_id: str,
    content: str,
    memory_type: str = "summary",
    metadata: Dict[str, Any] = None
) -> bool:
    """
    向 logos_memory 添加记忆片段。
    自动清理 metadata 格式，兼容 Chroma 限制。
    """
    def _do_add():
        with _chroma_lock:
            try:
                collection = _get_memory_collection()
                doc_id = f"{user_id}_{memory_type}_{int(time.time() * 1000)}"

                meta = {"user_id": user_id, "memory_type": memory_type, "timestamp": time.time()}

                if metadata:
                    cleaned = _clean_meta(metadata)
                    meta.update(cleaned)

                collection.add(
                    ids=[doc_id],
                    documents=[content],
                    metadatas=[meta]
                )
                print(f"[add_memory] 成功写入: {doc_id[:50]}...")
                return True
            except Exception as e:
                print(f"[add_memory] Error: {e}")
                return False

    return await asyncio.to_thread(_do_add)


async def delete_old_memories(user_id: str, before_timestamp: float) -> int:
    """
    删除指定时间之前的记忆（TTL 清理）。
    返回删除数量。
    """
    def _do_delete():
        with _chroma_lock:
            try:
                collection = _get_memory_collection()
                results = collection.get(
                    where={
                        "$and": [
                            {"user_id": user_id},
                            {"timestamp": {"$lt": before_timestamp}}
                        ]
                    }
                )
                ids = results.get("ids", [])
                if ids:
                    collection.delete(ids=ids)
                return len(ids)
            except Exception as e:
                print(f"[delete_old_memories] Error: {e}")
                return 0

    return await asyncio.to_thread(_do_delete)