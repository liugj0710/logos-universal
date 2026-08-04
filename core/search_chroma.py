"""
Chroma 向量检索实现 — v0.2.5 修复：
- 全部同步操作包裹 asyncio.to_thread
- 加 threading.Lock 防止并发访问 sqlite 导致锁冲突 / default_tenant 错误
- 使用 chroma_client.get_embedding_function() 单例，避免重复 API 探测
"""
from typing import List, Dict, Any
import asyncio
import threading

from core.chroma_client import get_collection, get_embedding_function

# 全局锁：Chroma PersistentClient 底层是 sqlite，不支持并发访问
_chroma_lock = threading.Lock()


async def search_chroma(query: str, top_k: int = 10, skill_hint: str = "default_deep") -> List[Dict[str, Any]]:
    """
    从 Chroma 向量库检索相关文档。
    手动生成 embedding 绕过 ChromaDB 的 embed_query 调用链。
    所有同步操作包裹在 asyncio.to_thread 中，并用锁保证串行访问 sqlite。
    使用单例 EmbeddingFunction 避免重复 API 探测。
    """
    def _do_search():
        with _chroma_lock:
            try:
                collection = get_collection()

                # 使用单例 embedding function，避免重复 API 探测
                embed_fn = get_embedding_function()
                query_embeddings = embed_fn([query])

                results = collection.query(
                    query_embeddings=query_embeddings,
                    n_results=top_k,
                    include=["documents", "metadatas", "distances"]
                )

                output = []
                if not results or not results.get("ids"):
                    return output

                for i, doc_id in enumerate(results["ids"][0]):
                    distance = results["distances"][0][i]
                    score = max(0.0, 1.0 - distance)

                    output.append({
                        "title": results["metadatas"][0][i].get("title", "未知来源"),
                        "url": results["metadatas"][0][i].get("source", ""),
                        "content": results["documents"][0][i],
                        "source": "chroma",
                        "score": round(score, 4),
                    })

                output.sort(key=lambda x: x["score"], reverse=True)
                return output

            except Exception as e:
                print(f"[search_chroma] Error: {e}")
                return []

    return await asyncio.to_thread(_do_search)
