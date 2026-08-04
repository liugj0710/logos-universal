"""
Dify 知识库检索实现 — v0.2.6 修复：
- 单个知识库请求超时从 5 秒提升到 10 秒，避免 Dify 内部 embedding 慢导致失败
- 区分 TimeoutError 和其他异常，日志更清晰
- 增加重试机制（知识库级别 1 次重试）
- 保留模块级缓存和 asyncio.Lock 防并发重复请求

调用 Dify Dataset API 检索知识库中的相关文档片段。
Dify 版本: 1.14.2
API Endpoint: POST /v1/datasets/{dataset_id}/retrieve
"""
import os
import requests
import asyncio
import time
from typing import List, Dict, Any

from core.config import get_settings

settings = get_settings()

# 模块级缓存（所有线程共享）
_dify_dataset_ids: List[str] = None
_dify_cache_lock = asyncio.Lock()

# v0.2.6: 内层请求超时（秒）
DIFY_REQUEST_TIMEOUT = 10


def _get_dify_headers():
    """获取 Dify API 请求头"""
    return {
        "Authorization": f"Bearer {settings.DIFY_API_KEY}",
        "Content-Type": "application/json"
    }


def _list_datasets_sync() -> List[str]:
    """同步版本：列出 Dify 中所有可用的知识库 ID"""
    try:
        url = f"{settings.DIFY_BASE_URL}/v1/datasets"
        resp = requests.get(url, headers=_get_dify_headers(), timeout=DIFY_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"[search_dify_kb] 获取知识库列表失败: {resp.status_code} {resp.text[:300]}")
            return []

        data = resp.json()
        datasets = data.get("data", [])
        ids = [d.get("id") for d in datasets if d.get("id")]
        names = [d.get("name", "unknown") for d in datasets if d.get("id")]
        print(f"[search_dify_kb] 自动发现 {len(ids)} 个知识库: {list(zip(names, ids))}")
        return ids

    except requests.exceptions.Timeout:
        print(f"[search_dify_kb] 获取知识库列表超时({DIFY_REQUEST_TIMEOUT}s)")
        return []
    except Exception as e:
        print(f"[search_dify_kb] 获取知识库列表异常: {e}")
        return []


def _retrieve_dataset_sync(dataset_id: str, query: str, top_k: int) -> List[Dict[str, Any]]:
    """同步版本：从单个知识库检索文档片段（超时 10 秒，带 1 次重试）"""
    url = f"{settings.DIFY_BASE_URL}/v1/datasets/{dataset_id}/retrieve"

    payload = {
        "query": query,
        "retrieval_model": {
            "search_method": "hybrid_search",
            "top_k": top_k,
            "reranking_enable": False,
            "score_threshold_enabled": False
        }
    }

    def _do_request(api_url, attempt=1):
        try:
            resp = requests.post(api_url, json=payload, headers=_get_dify_headers(), timeout=DIFY_REQUEST_TIMEOUT)
            return resp
        except requests.exceptions.Timeout:
            print(f"[search_dify_kb] 知识库 {dataset_id} 请求超时({DIFY_REQUEST_TIMEOUT}s)，尝试 {attempt}")
            return None
        except Exception as e:
            print(f"[search_dify_kb] 知识库 {dataset_id} 请求异常: {e}，尝试 {attempt}")
            return None

    # 第一次请求
    resp = _do_request(url, attempt=1)

    # 404 时切换 console api
    if resp is not None and resp.status_code == 404:
        console_url = f"{settings.DIFY_BASE_URL}/console/api/datasets/{dataset_id}/retrieve"
        resp = _do_request(console_url, attempt=1)

    # 超时或异常时重试 1 次
    if resp is None:
        print(f"[search_dify_kb] 知识库 {dataset_id} 首次请求失败，1 秒后重试...")
        time.sleep(1)
        resp = _do_request(url, attempt=2)
        if resp is not None and resp.status_code == 404:
            console_url = f"{settings.DIFY_BASE_URL}/console/api/datasets/{dataset_id}/retrieve"
            resp = _do_request(console_url, attempt=2)

    if resp is None:
        return []

    if resp.status_code != 200:
        err_text = resp.text[:500]
        print(f"[search_dify_kb] 知识库 {dataset_id} 检索失败: {resp.status_code} {err_text}")
        return []

    try:
        data = resp.json()
    except Exception as e:
        print(f"[search_dify_kb] 知识库 {dataset_id} 响应 JSON 解析失败: {e}")
        return []

    records = data.get("records", [])

    output = []
    for rec in records:
        segment = rec.get("segment", {})
        document = rec.get("document", {})
        score = rec.get("score", 0)

        content = segment.get("content", "")
        if not content:
            continue

        # v0.4.5 修复: Dify 分段策略产生大量短片段(标题/表格单元格/图片说明)
        # 分层过滤：高置信度短片段保留作为上下文锚点，低置信度长片段才过滤
        content_len = len(content)
        if content_len < 50 and score < 0.5:
            # 太短且置信度低 → 丢弃
            continue
        if content_len < 200 and score < 0.3:
            # 较短且置信度很低 → 丢弃
            continue
        # 其余情况保留（包括高置信度的标题/摘要，以及正常长度的正文）

        output.append({
            "title": document.get("name", "Dify KB"),
            "url": f"dify://dataset/{dataset_id}/document/{document.get('id', '')}",
            "content": content,
            "source": "dify_kb",
            "score": round(score, 4),
        })

    return output


def _do_search_dify(query: str, top_k: int, dataset_ids: List[str] = None) -> List[Dict[str, Any]]:
    """同步执行全部 Dify 检索逻辑"""
    if not settings.DIFY_API_KEY:
        print("[search_dify_kb] DIFY_API_KEY 未配置，跳过 Dify KB 检索")
        return []

    # 如果没有传入 dataset_ids，尝试从环境变量获取
    if dataset_ids is None:
        dataset_ids_str = settings.DIFY_DATASET_IDS
        dataset_ids = [d.strip() for d in dataset_ids_str.split(",") if d.strip()]
        if not dataset_ids:
            dataset_ids = _list_datasets_sync()
            if not dataset_ids:
                print("[search_dify_kb] 未找到可用知识库")
                return []

    all_records = []
    per_dataset_top_k = max(1, top_k // max(1, len(dataset_ids)) + 2)

    for dataset_id in dataset_ids:
        try:
            records = _retrieve_dataset_sync(dataset_id, query, per_dataset_top_k)
            if records:
                all_records.extend(records)
                print(f"[search_dify_kb] 知识库 {dataset_id} 返回 {len(records)} 条")
            else:
                print(f"[search_dify_kb] 知识库 {dataset_id} 无结果")
        except Exception as e:
            print(f"[search_dify_kb] 检索知识库 {dataset_id} 失败: {e}")

    # 按 score 降序排序，取 top_k
    all_records.sort(key=lambda x: x.get("score", 0), reverse=True)
    final = all_records[:top_k]

    # v0.4.5: 输出过滤统计
    short_kept = sum(1 for r in final if len(r.get("content", "")) < 200)
    print(f"[search_dify_kb] 总计返回 {len(final)} 条 (来自 {len(dataset_ids)} 个知识库), "
          f"其中短片段(<200字)保留 {short_kept} 条")
    return final


async def search_dify_kb(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """
    从 Dify 知识库检索相关文档片段。
    所有同步操作包裹在 asyncio.to_thread 中，避免阻塞事件循环。
    知识库 ID 列表首次获取后缓存（进程级）。
    """
    global _dify_dataset_ids

    # 快速路径：缓存已存在
    if _dify_dataset_ids is not None:
        return await asyncio.to_thread(_do_search_dify, query, top_k, _dify_dataset_ids)

    # 慢速路径：首次获取（带锁，防止并发重复请求）
    async with _dify_cache_lock:
        # 双重检查：其他协程可能已填充缓存
        if _dify_dataset_ids is not None:
            return await asyncio.to_thread(_do_search_dify, query, top_k, _dify_dataset_ids)

        # 优先使用环境变量配置
        dataset_ids_str = settings.DIFY_DATASET_IDS
        configured_ids = [d.strip() for d in dataset_ids_str.split(",") if d.strip()]
        if configured_ids:
            _dify_dataset_ids = configured_ids
            print(f"[search_dify_kb] 使用环境变量配置的知识库: {configured_ids}")
        else:
            _dify_dataset_ids = await asyncio.to_thread(_list_datasets_sync)

        if not _dify_dataset_ids:
            print("[search_dify_kb] 未找到可用知识库，请配置 DIFY_DATASET_IDS 或检查 API 权限")
            return []

    return await asyncio.to_thread(_do_search_dify, query, top_k, _dify_dataset_ids)
