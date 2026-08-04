# D:\precision_agent\core\fusion.py
from typing import List, Dict
import hashlib
from difflib import SequenceMatcher

def rrf_fusion(results_list: List[List[Dict]], k: int = 60) -> List[Dict]:
    """
    Reciprocal Rank Fusion (RRF)
    对所有检索结果按排名倒数融合得分
    """
    scores = {}

    for results in results_list:
        for rank, item in enumerate(results):
            # 用 content 的 hash 作为唯一标识
            key = hashlib.md5(item.get("content", "").encode()).hexdigest()

            if key not in scores:
                scores[key] = {
                    "item": item,
                    "score": 0.0
                }

            # RRF 公式: score += 1 / (k + rank)
            scores[key]["score"] += 1.0 / (k + rank + 1)

    # 按得分排序
    fused = sorted(scores.values(), key=lambda x: x["score"], reverse=True)

    # 返回排序后的结果
    return [x["item"] for x in fused]

def _text_similarity(a: str, b: str) -> float:
    """计算两段文本的相似度（0-1）"""
    if not a or not b:
        return 0.0
    # 取前 500 字符做快速比较
    return SequenceMatcher(None, a[:500], b[:500]).ratio()

def deduplicate_by_content(results: List[Dict], threshold: float = 0.85) -> List[Dict]:
    """
    基于语义相似度去重（v0.2.1 升级）
    策略：
    1. 先用 MD5 hash 快速去重完全重复内容
    2. 再用 SequenceMatcher 做语义相似度去重（阈值 0.85）
    3. 保留 score 更高的版本
    """
    # 第一层：精确去重（MD5）
    seen_hashes = set()
    deduped = []

    for item in results:
        content = item.get("content", "")
        if not content:
            continue

        key = hashlib.md5(content[:500].encode()).hexdigest()

        if key not in seen_hashes:
            seen_hashes.add(key)
            deduped.append(item)

    # 第二层：语义相似度去重
    final_results = []
    for item in deduped:
        content = item.get("content", "")
        is_duplicate = False

        for existing in final_results:
            existing_content = existing.get("content", "")
            sim = _text_similarity(content, existing_content)

            if sim >= threshold:
                # 保留 score 更高的版本
                if item.get("score", 0) > existing.get("score", 0):
                    final_results[final_results.index(existing)] = item
                is_duplicate = True
                break

        if not is_duplicate:
            final_results.append(item)

    return final_results
