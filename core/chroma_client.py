"""
Chroma 向量库客户端封装 + Ollama Embedding 调用
v0.2.5 修复：
- PersistentClient 单例缓存，避免重复创建 sqlite 连接导致并发锁冲突
- OllamaEmbeddingFunction 单例缓存，避免重复 API 探测
- 新增 get_embedding_function() 供外部直接获取单例
"""
import os
import time
import requests
from typing import List

import chromadb
from chromadb.config import Settings as ChromaSettings

from core.config import get_settings

settings = get_settings()

# 单例缓存
_chroma_client = None
_embedding_function = None


class OllamaEmbeddingFunction:
    """Ollama Embedding 封装，自动探测可用 API，空 embedding 直接报错"""

    def __init__(self, host: str = None, model: str = None, batch_size: int = 32):
        self.host = host or settings.OLLAMA_HOST
        self.model = model or settings.OLLAMA_EMBED_MODEL
        self.batch_size = batch_size or settings.OLLAMA_BATCH_SIZE
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._api_mode = None  # 缓存探测到的可用 API

    def name(self) -> str:
        return f"ollama-{self.model}"

    def embed_query(self, input=None, **kwargs) -> List[float]:
        """ChromaDB query() 调用 - 单条查询"""
        text = input or kwargs.get("text") or ""
        result = self._embed_single(text)
        if not result or len(result) == 0:
            raise RuntimeError(
                f"Ollama 返回空 embedding。请先在 Mac Studio 执行: ollama run {self.model}"
            )
        return result

    def __call__(self, input: List[str]) -> List[List[float]]:
        """ChromaDB add() 调用 - 批量"""
        if not input:
            return []
        results = []
        for text in input:
            emb = self._embed_single(text)
            if not emb or len(emb) == 0:
                raise RuntimeError(
                    f"Ollama 返回空 embedding。文本: '{text[:50]}...' "
                    f"请先在 Mac Studio 执行: ollama run {self.model}"
                )
            results.append(emb)
            time.sleep(0.03)
        return results

    def _embed_single(self, text: str) -> List[float]:
        """单条 embedding，自动探测 API 模式并缓存"""
        if self._api_mode:
            return self._try_api(self._api_mode, text) or []

        for mode in ["embed_batch", "embeddings_prompt", "embeddings_input"]:
            result = self._try_api(mode, text)
            if result and len(result) > 0:
                self._api_mode = mode
                print(f"[Ollama] 检测到可用 API 模式: {mode}")
                return result
        return []

    def _try_api(self, mode: str, text: str) -> List[float]:
        if mode == "embed_batch":
            try:
                r = self._session.post(
                    f"{self.host}/api/embed",
                    json={"model": self.model, "input": [text]},
                    timeout=60
                )
                if r.status_code == 200:
                    data = r.json()
                    embs = data.get("embeddings")
                    if embs and len(embs) > 0:
                        return embs[0]
            except Exception:
                pass

        elif mode == "embeddings_prompt":
            try:
                r = self._session.post(
                    f"{self.host}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=60
                )
                if r.status_code == 200:
                    emb = r.json().get("embedding")
                    if emb and len(emb) > 0:
                        return emb
            except Exception:
                pass

        elif mode == "embeddings_input":
            try:
                r = self._session.post(
                    f"{self.host}/api/embeddings",
                    json={"model": self.model, "input": [text]},
                    timeout=60
                )
                if r.status_code == 200:
                    data = r.json()
                    embs = data.get("embeddings")
                    if embs and len(embs) > 0:
                        return embs[0]
                    emb = data.get("embedding")
                    if emb and len(emb) > 0:
                        return emb
            except Exception:
                pass

        return []


def get_chroma_client():
    """获取单例 PersistentClient，避免重复创建 sqlite 连接"""
    global _chroma_client
    if _chroma_client is None:
        db_path = os.path.abspath(settings.CHROMA_DB_PATH)
        os.makedirs(db_path, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=db_path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False)
        )
    return _chroma_client


def get_embedding_function():
    """获取单例 OllamaEmbeddingFunction，避免重复 API 探测"""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = OllamaEmbeddingFunction()
    return _embedding_function


def get_collection(client: chromadb.Client = None):
    """获取单例 Collection，复用 EmbeddingFunction 实例"""
    if client is None:
        client = get_chroma_client()
    return client.get_or_create_collection(
        name="logos_private_kb",
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"}
    )
