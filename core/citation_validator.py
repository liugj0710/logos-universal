# D:\precision_agent\core\citation_validator.py
"""
Λόγος Agent · Citation Validator
引用验证规则引擎 — 零成本本地规则，不调用任何 LLM
职责：核查 synthesize 生成的报告中，引用是否真实存在于检索结果中
"""

from typing import List, Dict, Any, Optional
import re
from difflib import SequenceMatcher


# ───────────────────────────────────────────────
# 公共接口
# ───────────────────────────────────────────────

def validate_citations(
    report_structured_data: Dict[str, Any],
    retrieved_chunks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    深度校验：完整四轮规则检查

    Args:
        report_structured_data: synthesize 输出的 structured_data
            {
                "executive_summary": str,
                "sections": [{"title", "content", "citations": [...]}],
                "citations": [{"id", "source", "url", "quote"}],
                "key_insights": [str]
            }
        retrieved_chunks: retrieve 返回的原始结果列表
            每条至少包含 {"chunk_id"|"id", "content", "url", "source", "title"}

    Returns:
        {"valid": bool, "issues": [...], "suggestions": [...], "stats": {...}}
    """
    issues: List[Dict[str, Any]] = []
    suggestions: List[str] = []

    # 建立 chunk 索引：支持按 chunk_id / url / source 查找
    chunk_index = _build_chunk_index(retrieved_chunks)

    # 扁平化所有 citation（sections 内 + 顶层 citations）
    all_citations = _collect_all_citations(report_structured_data)

    # ── 规则 1：来源存在性 ──
    _check_source_existence(all_citations, chunk_index, issues)

    # ── 规则 2：内容一致性（模糊匹配） ──
    _check_content_consistency(all_citations, chunk_index, issues)

    # ── 规则 3：章节引用完整性 ──
    _check_section_coverage(report_structured_data.get("sections", []), issues)

    # ── 规则 4：关键结论支撑性 ──
    _check_insight_support(
        report_structured_data.get("key_insights", []),
        all_citations,
        issues
    )

    # ── 生成建议 ──
    suggestions = _generate_suggestions(issues)

    # ── 统计 ──
    stats = _build_stats(all_citations, issues, chunk_index)

    high_count = sum(1 for i in issues if i.get("severity") == "high")

    return {
        "valid": high_count == 0,
        "issues": issues,
        "suggestions": suggestions,
        "stats": stats
    }


def light_validate_citations(
    citations: List[Dict[str, Any]],
    retrieved_chunks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    轻量校验：仅检查来源存在性，用于 synthesize 内部快速过滤
    返回：过滤后的 citation 列表（移除来源不存在的）
    """
    chunk_index = _build_chunk_index(retrieved_chunks)
    cleaned = []

    for c in citations:
        cid = c.get("id") or c.get("source") or c.get("url")
        if cid and cid in chunk_index:
            cleaned.append(c)
        # 来源不存在的直接丢弃，不报错（轻量策略）

    return cleaned


# ───────────────────────────────────────────────
# 内部实现
# ───────────────────────────────────────────────

def _build_chunk_index(chunks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """建立多键索引，支持 chunk_id / id / url / source 查找"""
    index: Dict[str, Dict[str, Any]] = {}
    for chunk in chunks:
        # 主键：chunk_id 或 id
        for key in ("chunk_id", "id"):
            val = chunk.get(key)
            if val:
                index[str(val)] = chunk
        # 辅助键：url
        url = chunk.get("url")
        if url:
            index[str(url)] = chunk
        # 辅助键：title（用于模糊匹配兜底）
        title = chunk.get("title")
        if title:
            index[f"title:{title}"] = chunk
    return index


def _collect_all_citations(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """收集报告中所有 citation，去重"""
    seen = set()
    result = []

    # 顶层 citations
    top_citations = report_data.get("citations", [])
    if isinstance(top_citations, list):
        for c in top_citations:
            if not isinstance(c, dict):
                continue
            key = c.get("id") or c.get("source") or c.get("quote", "")[:30]
            if key not in seen:
                seen.add(key)
                result.append(c)
    elif isinstance(top_citations, dict):
        c = top_citations
        key = c.get("id") or c.get("source") or c.get("quote", "")[:30]
        if key not in seen:
            seen.add(key)
            result.append(c)

    # sections 内的 citations
    sections = report_data.get("sections", [])
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue  # 修复：跳过非 dict 的 section
            sec_citations = sec.get("citations", [])
            if not isinstance(sec_citations, list):
                continue
            for c in sec_citations:
                if not isinstance(c, dict):
                    continue
                key = c.get("id") or c.get("source") or c.get("quote", "")[:30]
                if key not in seen:
                    seen.add(key)
                    result.append(c)

    return result


def _check_source_existence(
    citations: List[Dict[str, Any]],
    chunk_index: Dict[str, Dict[str, Any]],
    issues: List[Dict[str, Any]]
) -> None:
    """规则 1：每个 citation 必须能在检索结果中找到来源"""
    for i, c in enumerate(citations):
        keys = [c.get(k) for k in ("id", "source", "url") if c.get(k)]
        found = any(str(k) in chunk_index for k in keys)
        if not found:
            issues.append({
                "type": "missing_source",
                "severity": "high",
                "citation_index": i,
                "citation": c,
                "reason": f"引用的来源不在检索结果中（id={c.get('id')}, source={c.get('source')}, url={c.get('url')})"
            })


def _check_content_consistency(
    citations: List[Dict[str, Any]],
    chunk_index: Dict[str, Dict[str, Any]],
    issues: List[Dict[str, Any]]
) -> None:
    """规则 2：引用摘录必须与原始 chunk 内容匹配"""
    for i, c in enumerate(citations):
        quote = c.get("quote", "").strip()
        if not quote:
            continue

        # 找到对应的 chunk
        chunk = None
        for k in ("id", "source", "url"):
            val = c.get(k)
            if val and str(val) in chunk_index:
                chunk = chunk_index[str(val)]
                break

        if not chunk:
            continue  # 已在规则 1 中报告

        chunk_content = chunk.get("content", "")
        similarity = _fuzzy_match(quote, chunk_content)

        if similarity < 0.3:
            issues.append({
                "type": "content_mismatch",
                "severity": "high",
                "citation_index": i,
                "citation": c,
                "reason": f"引用摘录与原始内容相似度仅 {similarity:.2f}，疑似编造",
                "similarity": round(similarity, 3),
                "chunk_preview": chunk_content[:200]
            })
        elif similarity < 0.5:
            issues.append({
                "type": "content_weak_match",
                "severity": "medium",
                "citation_index": i,
                "citation": c,
                "reason": f"引用摘录与原始内容相似度 {similarity:.2f}，建议核实",
                "similarity": round(similarity, 3),
                "chunk_preview": chunk_content[:200]
            })


def _check_section_coverage(
    sections: List[Dict[str, Any]],
    issues: List[Dict[str, Any]]
) -> None:
    """规则 3：每个 section 至少有一个 citation"""
    for idx, sec in enumerate(sections):
        if not isinstance(sec, dict):
            issues.append({
                "type": "section_format_error",
                "severity": "medium",
                "section_index": idx,
                "section_title": "格式异常（非字典）",
                "reason": "该章节数据结构异常，无法解析引用"
            })
            continue
        sec_citations = sec.get("citations", [])
        if not sec_citations:
            issues.append({
                "type": "missing_citation",
                "severity": "medium",
                "section_index": idx,
                "section_title": sec.get("title", "未命名章节"),
                "reason": "该章节无任何引用支撑，结论可信度存疑"
            })


def _check_insight_support(
    insights: List[str],
    citations: List[Dict[str, Any]],
    issues: List[Dict[str, Any]]
) -> None:
    """规则 4：关键洞察必须有近似引用支撑"""
    for insight in insights:
        insight_text = str(insight).strip()
        if not insight_text:
            continue

        # 检查是否有任何 citation 的 quote 与该洞察相关
        best_match = 0.0
        for c in citations:
            quote = c.get("quote", "")
            sim = _fuzzy_match(insight_text, quote)
            if sim > best_match:
                best_match = sim

        if best_match < 0.3:
            issues.append({
                "type": "unsupported_claim",
                "severity": "medium",
                "claim": insight_text,
                "reason": "关键洞察缺乏直接引用支撑，可能为过度推断",
                "best_match_score": round(best_match, 3)
            })


def _generate_suggestions(issues: List[Dict[str, Any]]) -> List[str]:
    """根据问题生成修正建议"""
    suggestions = []

    high_issues = [i for i in issues if i.get("severity") == "high"]
    if high_issues:
        suggestions.append(
            f"发现 {len(high_issues)} 个高危引用问题，建议修正或移除相关引用后重新生成"
        )

    missing_citations = [i for i in issues if i.get("type") == "missing_citation"]
    if missing_citations:
        titles = [i.get("section_title", "") for i in missing_citations]
        suggestions.append(
            f"章节 [{', '.join(titles)}] 缺乏引用支撑，建议补充数据来源"
        )

    unsupported = [i for i in issues if i.get("type") == "unsupported_claim"]
    if unsupported:
        suggestions.append(
            f"{len(unsupported)} 条关键洞察缺乏引用支撑，建议添加对应来源"
        )

    return suggestions


def _build_stats(
    citations: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
    chunk_index: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """生成统计信息"""
    valid_sources = 0
    for c in citations:
        for k in ("id", "source", "url"):
            if c.get(k) and str(c[k]) in chunk_index:
                valid_sources += 1
                break

    return {
        "total_citations": len(citations),
        "valid_sources": valid_sources,
        "missing_sources": sum(1 for i in issues if i.get("type") == "missing_source"),
        "content_mismatches": sum(1 for i in issues if i.get("type") == "content_mismatch"),
        "weak_matches": sum(1 for i in issues if i.get("type") == "content_weak_match"),
        "missing_citations": sum(1 for i in issues if i.get("type") == "missing_citation"),
        "unsupported_claims": sum(1 for i in issues if i.get("type") == "unsupported_claim"),
        "high_severity_issues": sum(1 for i in issues if i.get("severity") == "high"),
        "medium_severity_issues": sum(1 for i in issues if i.get("severity") == "medium")
    }


# ───────────────────────────────────────────────
# 工具函数
# ───────────────────────────────────────────────

def _fuzzy_match(a: str, b: str) -> float:
    """
    计算两段文本的相似度（0.0 ~ 1.0）
    先清理空白和标点，再做 SequenceMatcher
    """
    if not a or not b:
        return 0.0

    # 清理：转小写、去空白、去常见标点
    def clean(text: str) -> str:
        text = text.lower()
        text = re.sub(r'[\s\n\r\t]+', '', text)
        # 移除中英文标点（使用 str.translate 避免正则引号嵌套问题）
        import string
        puncts = string.punctuation + "，。、；：（）《》【】！？"
        text = text.translate(str.maketrans('', '', puncts))
        return text

    ca, cb = clean(a), clean(b)
    if not ca or not cb:
        return 0.0

    return SequenceMatcher(None, ca, cb).ratio()
