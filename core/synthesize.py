# D:\precision_agent\core\synthesize.py
"""
Λόγος Agent · Synthesize 核心引擎
职责：基于检索结果生成结构化深度报告（双格式输出）
模型：DeepSeek-V4 Pro
v0.4.5.5: 
  - 引用格式改为 [1][2] 数字上标，统一放文末
  - 删除段落级来源锚定卡片注入
  - 新增多源整合与禁止元分析约束
  - 给检索结果加编号，方便 LLM 引用
"""

import json
import re
import uuid
import traceback
from typing import List, Dict, Any, Optional, Tuple

from core.llm import call_llm
from core.citation_validator import light_validate_citations


# ───────────────────────────────────────────────
# Skill 模板定义（v0.4.5.5 更新 special_requirements）
# ───────────────────────────────────────────────

SKILL_TEMPLATES = {
    "market_swot": {
        "name": "行业 SWOT 分析",
        "structure": [
            "执行摘要",
            "行业概况与背景",
            "优势 (Strengths)",
            "劣势 (Weaknesses)",
            "机会 (Opportunities)",
            "威胁 (Threats)",
            "战略建议与行动路径",
            "风险提示"
        ],
        "special_requirements": """
- SWOT 四象限必须基于检索到的真实数据，不能凭常识编造
- 每个象限至少包含 2-3 个具体要点，每个要点必须有 citation 支撑
- 战略建议部分必须结合 SWOT 交叉分析（如 SO 策略、WO 策略等）
- 如检索结果不足以支撑某象限，用[unverified]标注该要点，一句话说明即可，不要展开论述数据缺口
"""
    },
    "tech_timeline": {
        "name": "技术发展历程",
        "structure": [
            "执行摘要",
            "技术背景与定义",
            "发展阶段总览",
            "关键里程碑时间线",
            "当前技术成熟度评估",
            "未来发展趋势预测",
            "核心参与者与生态"
        ],
        "special_requirements": """
- 时间线必须按时间顺序排列，每个里程碑标注大致年份
- 每个里程碑必须有 citation 支撑，不能凭记忆编造年份或事件
- 当前技术成熟度评估必须基于检索到的最新信息
- 预测部分必须明确标注"[基于现有趋势的推断]"
- 如某时期缺乏资料，直接跳过或标注[信息不足]，不要解释为什么找不到
"""
    },
    "competitive_matrix": {
        "name": "竞品对比矩阵",
        "structure": [
            "执行摘要",
            "对比对象概述",
            "核心维度对比矩阵（表格）",
            "各对象详细分析",
            "差异化优势总结",
            "竞争格局判断",
            "建议与风险提示"
        ],
        "special_requirements": """
- 必须包含至少一个 Markdown 表格形式的对比矩阵
- 表格列应包含：对比维度、对象A、对象B、对象C（如检索结果涉及）
- 每个单元格的数据必须有 citation 支撑
- 差异化优势总结必须基于表格数据，不能引入表格外的新信息
- 如果检索结果只涉及单一对象，转为"深度剖析"模式，一句话说明即可
"""
    },
    "default_deep": {
        "name": "通用深度分析",
        "structure": [
            "执行摘要",
            "问题背景与定义",
            "核心分析",
            "关键发现与证据",
            "结论与建议",
            "数据局限性与风险提示"
        ],
        "special_requirements": """
- 报告结构应灵活适配用户问题的具体维度
- 核心分析部分可按子查询维度组织章节
- 每个关键发现必须有 citation 支撑
- 结论必须严格限定在检索结果支撑范围内
- 数据局限性一句话诚实披露即可，禁止用"资料不足"填充整段篇幅
- 报告必须有实质技术内容，禁止写成"元分析"（即大量篇幅在分析为什么写不出来）
- 必须整合至少 3-5 条不同检索来源，不能仅围绕单一条目展开
"""
    }
}


# ───────────────────────────────────────────────
# 公共接口
# ───────────────────────────────────────────────

async def generate_report(
    original_query: str,
    sub_queries: List[str],
    target_entity: Optional[str],
    skill_hint: str,
    retrieved_chunks: List[Dict[str, Any]],
    memory_context: Optional[str] = None,
    graph_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    生成结构化深度报告
    v0.4.5.5: 引用格式改为数字上标，删除段落级锚定卡片

    Returns:
        {
            "markdown_report": str,
            "structured_data": Dict,
            "citation_cleaned": bool,
            "model": "deepseek-v4-pro",
            "skill_used": str
        }
    """
    try:
        return await _generate_report_core(
            original_query, sub_queries, target_entity,
            skill_hint, retrieved_chunks, memory_context, graph_context
        )
    except Exception as e:
        print(f"[synthesize] generate_report 异常: {type(e).__name__}: {e}")
        traceback.print_exc()

        return {
            "markdown_report": _build_error_report(original_query, skill_hint, str(e) or "未知错误"),
            "structured_data": {
                "executive_summary": f"报告生成异常: {str(e) or '未知错误'}",
                "sections": [{"title": "错误信息", "content": str(e) or "未知错误", "citations": []}],
                "citations": [],
                "key_insights": ["报告生成失败，请重试"],
                "confidence": "low",
                "skill_used": skill_hint,
                "model": "deepseek-v4-pro",
                "error": str(e) or "未知错误"
            },
            "citation_cleaned": False,
            "model": "deepseek-v4-pro",
            "skill_used": skill_hint
        }


async def _generate_report_core(
    original_query: str,
    sub_queries: List[str],
    target_entity: Optional[str],
    skill_hint: str,
    retrieved_chunks: List[Dict[str, Any]],
    memory_context: Optional[str] = None,
    graph_context: Optional[str] = None
) -> Dict[str, Any]:
    """报告生成核心逻辑"""

    # 防御：过滤非 dict 的 chunk
    safe_chunks = [c for c in retrieved_chunks if isinstance(c, dict)]
    if not safe_chunks:
        return {
            "markdown_report": _build_no_data_report(original_query, skill_hint),
            "structured_data": {
                "executive_summary": f"检索结果不足，无法生成关于「{original_query}」的深度报告。",
                "sections": [{"title": "数据缺失", "content": "当前检索未返回有效信息，请稍后重试或调整问题。", "citations": []}],
                "citations": [],
                "key_insights": ["检索结果为空或不相关"],
                "confidence": "low",
                "skill_used": skill_hint,
                "model": "deepseek-v4-pro"
            },
            "citation_cleaned": False,
            "model": "deepseek-v4-pro",
            "skill_used": skill_hint
        }

    # 1. 为 chunk 注入唯一 ID
    chunks_with_id = _inject_chunk_ids(safe_chunks)

    # 2. 构造提示词
    system_prompt = _build_system_prompt(skill_hint, target_entity)
    user_prompt = _build_user_prompt(
        original_query=original_query,
        sub_queries=sub_queries,
        target_entity=target_entity,
        memory_context=memory_context,
        graph_context=graph_context,
        chunks=chunks_with_id
    )

    # 3. 调用 LLM
    raw_output = await call_llm(
        model="deepseek-v4-pro",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=8000,
        json_mode=False
    )

    # 防御：call_llm 返回 None 或空字符串
    if not raw_output or not isinstance(raw_output, str):
        print(f"[synthesize] LLM 返回空或无效内容: {type(raw_output)}={raw_output!r}")
        raw_output = raw_output or ""

    # 4. 解析双格式
    structured_data, markdown_report = _parse_dual_format(raw_output)

    if not structured_data:
        structured_data, markdown_report = _fallback_parse(raw_output, skill_hint)

    # 5. 内部轻量校验
    all_citations = _collect_citations(structured_data)
    cleaned_citations = light_validate_citations(all_citations, chunks_with_id)
    citation_cleaned = len(cleaned_citations) < len(all_citations)

    # 更新 structured_data 中的 citations
    structured_data = _update_citations(structured_data, cleaned_citations)

    # 5.5 v0.4.5.5: 删除段落级来源锚定卡片注入，引用统一由 LLM 在文末列出
    # markdown_report = _inject_citation_anchors(markdown_report, chunks_with_id)  # 已注释

    # 6. 补充元数据
    structured_data["skill_used"] = skill_hint
    structured_data["model"] = "deepseek-v4-pro"
    if "confidence" not in structured_data:
        structured_data["confidence"] = "medium"

    return {
        "markdown_report": markdown_report,
        "structured_data": structured_data,
        "citation_cleaned": citation_cleaned,
        "model": "deepseek-v4-pro",
        "skill_used": skill_hint,
        "raw_token_usage": len(raw_output)
    }


# ───────────────────────────────────────────────
# Prompt 构造（v0.4.5.5 重写）
# ───────────────────────────────────────────────

def _build_system_prompt(skill_hint: str, target_entity: Optional[str]) -> str:
    """构建系统提示词"""
    template = SKILL_TEMPLATES.get(skill_hint, SKILL_TEMPLATES["default_deep"])

    structure_text = "\n".join(
        f"{i+1}. {sec}" for i, sec in enumerate(template["structure"])
    )

    entity_hint = f"\n核心分析对象：{target_entity}" if target_entity else ""

    return f"""你是 Λόγος（逻各斯）深度分析引擎的"战地记者"。
你的任务是基于检索到的真实资料，生成一份严谨、有据可查的结构化深度报告。

【报告类型】{template["name"]}
【报告结构】{entity_hint}
{structure_text}

【特殊要求】
{template["special_requirements"]}

【输出格式 - 严格遵循】
你必须按以下精确格式输出，不要有任何额外前言或结语：

===STRUCTURED_DATA===
{{"executive_summary": "...", "sections": [...], "citations": [...], "key_insights": [...], "confidence": "high|medium|low", "skill_used": "{skill_hint}"}}
===MARKDOWN_REPORT===
# 报告标题
...

===STRUCTURED_DATA=== 和 ===MARKDOWN_REPORT=== 之间的内容必须是合法 JSON。
===MARKDOWN_REPORT=== 之后的内容必须是完整 Markdown 报告。

【引用格式规范】
1. 正文中使用 [1][2][3] 数字上标标记引用，对应文末参考文献编号
2. 每个关键数据、事实、对比结论必须至少有一个数字引用
3. 禁止在正文中插入块级来源卡片或 "📎 来源锚定" 等打断阅读的内容
4. 所有来源信息统一放在报告最底部，用 "==========" 长横线隔开：
   ==========
   参考文献：
   [1] chunk_xxx: 来源标题 - 链接
   [2] chunk_xxx: 来源标题 - 链接
5. citation 格式必须是 JSON 对象：{{"id": "chunk_id", "source": "来源名", "url": "链接", "quote": "原文摘录"}}
6. citation.id 必须严格对应下方【检索结果】中的 chunk_id，不能编造
7. 引用摘录 quote 必须与原文高度一致（允许省略中间内容，但首尾必须真实）

【多源整合要求】
8. 报告必须整合至少 3-5 条不同检索来源，不能仅围绕单一条目展开
9. 不同来源的观点要交叉对比、相互印证，形成完整分析视角
10. 禁止以"资料不足"、"检索结果有限"、"信息存在缺口"为由，用免责说明填充篇幅
11. 基于已有资料直接输出完整技术分析，信息薄弱处用[unverified]标注即可，不要整段解释为什么没资料
12. 报告必须有实质技术内容，禁止写成"元分析"（即大量篇幅在分析为什么写不出来或资料缺了什么）

【知识图谱使用规则】
13. 下方【知识图谱上下文】提供概念关联参考，但 citation 仍必须指向【检索结果】中的 chunk_id
14. 如果图谱信息与检索结果冲突，以检索结果为准
15. 不要为图谱中的信息单独创建 citation，除非该信息也在检索结果中出现

【语言风格】
- 专业、客观、去情绪化
- 使用自然、平等的对话风格（非僧侣化）
- 数据驱动，结论必须有证据支撑
- 不确定的地方明确标注"[unverified]"或"基于现有信息推断"

【自检纪律 - Reflection】
生成完成后，在最终输出前请自检：
1. 每个 citation.id 是否都能在检索结果中找到对应 chunk？
2. 是否存在逻辑跳跃或过度推断？
3. 是否遗漏了用户问题的某个维度？
4. 结论是否超出了检索结果支撑的范围？
5. 是否有任何数据是凭记忆或常识编造的？
6. 报告正文是否使用了 [1][2] 数字上标引用？文末是否有完整的参考文献列表？
7. 报告是否整合了至少 3 个不同来源？是否过度依赖单一条目？
8. 是否有大篇幅的"资料不足"类元分析？如有，替换为实质内容或删除。
9. 正文中是否插入了块级来源卡片？如有，删除并改为文末参考文献。

如有问题，在输出前修正。"""


def _build_user_prompt(
    original_query: str,
    sub_queries: List[str],
    target_entity: Optional[str],
    memory_context: Optional[str],
    graph_context: Optional[str],
    chunks: List[Dict[str, Any]]
) -> str:
    """构造用户提示词（v0.4.5.5: 给 chunk 加编号）"""
    parts = []

    parts.append(f"【原始问题】\n{original_query}\n")

    if sub_queries:
        parts.append("【子查询拆解】")
        for i, sq in enumerate(sub_queries, 1):
            parts.append(f"{i}. {sq}")
        parts.append("")

    if target_entity:
        parts.append(f"【核心分析对象】{target_entity}\n")

    if memory_context:
        parts.append(f"【用户记忆上下文】\n{memory_context}\n")

    if graph_context:
        parts.append(f"【知识图谱上下文】\n{graph_context}\n")
        parts.append("注意：以上图谱信息来自历史知识库的结构化抽取，仅供参考。所有 citation 必须指向下方【检索结果】中的 chunk。\n")

    # 检索结果格式化（加编号）
    parts.append("【检索结果】")
    parts.append("以下是你生成报告的唯一信息来源，已按编号排列。正文中使用 [1][2] 等数字引用对应编号：\n")

    for idx, chunk in enumerate(chunks, 1):
        if not isinstance(chunk, dict):
            continue
        cid = chunk.get("chunk_id", "unknown")
        source = chunk.get("source", "unknown")
        url = chunk.get("url", "")
        title = chunk.get("title", "无标题")
        content = chunk.get("content", "")

        parts.append(f"---")
        parts.append(f"[{idx}] [chunk_id: {cid}] [source: {source}] [url: {url}]")
        parts.append(f"[title: {title}]")
        parts.append(f"{content}")
        parts.append("")

    parts.append("---\n")
    parts.append("请基于以上检索结果生成报告。记住：禁止编造任何未在检索结果中出现的数据、年份、公司名称或统计数据。")

    return "\n".join(parts)


# ───────────────────────────────────────────────
# 双格式解析（无变更）
# ───────────────────────────────────────────────

def _parse_dual_format(raw_output: str) -> Tuple[Optional[Dict], str]:
    """
    从 LLM 输出中解析 structured_data 和 markdown_report
    返回: (structured_data_dict, markdown_report_str)
    """
    if not raw_output:
        return None, ""

    # 尝试匹配分隔符格式
    pattern = r'===STRUCTURED_DATA===\s*(.*?)\s*===MARKDOWN_REPORT===\s*(.*)'
    match = re.search(pattern, raw_output, re.DOTALL)

    if match:
        json_str = match.group(1).strip()
        markdown = match.group(2).strip()

        try:
            structured = json.loads(json_str)
            return structured, markdown
        except json.JSONDecodeError as e:
            print(f"[synthesize] JSON 解析失败（分隔符格式）: {e}")

    # Fallback 1：尝试找 JSON 对象（最外层花括号）
    json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
    if json_match:
        try:
            structured = json.loads(json_match.group(0))
            markdown = raw_output[json_match.end():].strip()
            markdown = re.sub(r'^===MARKDOWN_REPORT===\s*', '', markdown)
            return structured, markdown
        except json.JSONDecodeError as e:
            print(f"[synthesize] JSON 解析失败（fallback）: {e}")

    return None, raw_output.strip()


def _fallback_parse(raw_output: str, skill_hint: str) -> Tuple[Dict, str]:
    """
    解析完全失败时的兜底：把整个输出当 Markdown，structured_data 尽力提取
    """
    structured = {
        "executive_summary": _extract_summary(raw_output),
        "sections": [{"title": "完整报告", "content": raw_output, "citations": []}],
        "citations": [],
        "key_insights": _extract_insights(raw_output),
        "confidence": "low",
        "skill_used": skill_hint
    }
    return structured, raw_output.strip()


def _extract_summary(text: str) -> str:
    """尽力提取执行摘要"""
    if not text:
        return ""
    match = re.search(r'#+\s*.*?\n\s*(.+?)(?=\n#|\n---|$)', text, re.DOTALL)
    if match:
        summary = match.group(1).strip()
        return summary[:300]
    return text[:300].strip()


def _extract_insights(text: str) -> List[str]:
    """尽力提取关键洞察（找列表项）"""
    if not text:
        return []
    insights = []
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('- ') or line.startswith('* ') or re.match(r'^\d+\.\s', line):
            content = re.sub(r'^[-*\d\.\s]+', '', line).strip()
            if len(content) > 10 and len(content) < 200:
                insights.append(content)
        if len(insights) >= 5:
            break
    return insights


# ───────────────────────────────────────────────
# 辅助函数（无变更）
# ───────────────────────────────────────────────

def _inject_chunk_ids(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """为没有 chunk_id 的 chunk 注入唯一 ID"""
    result = []
    for i, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        new_chunk = dict(chunk)
        if not new_chunk.get("chunk_id") and not new_chunk.get("id"):
            new_chunk["chunk_id"] = f"chunk_{i:03d}_{uuid.uuid4().hex[:6]}"
        elif not new_chunk.get("chunk_id"):
            new_chunk["chunk_id"] = str(new_chunk["id"])
        result.append(new_chunk)
    return result


def _collect_citations(structured_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """收集 structured_data 中的所有 citation，过滤非 dict"""
    citations = []
    seen = set()

    # 顶层 citations（必须是列表或单个 dict）
    top_citations = structured_data.get("citations", [])
    if isinstance(top_citations, list):
        for c in top_citations:
            if not isinstance(c, dict):
                continue
            key = c.get("id") or c.get("source") or str(c)
            if key not in seen:
                seen.add(key)
                citations.append(c)
    elif isinstance(top_citations, dict):
        c = top_citations
        key = c.get("id") or c.get("source") or str(c)
        if key not in seen:
            seen.add(key)
            citations.append(c)

    # sections 内的 citations
    sections = structured_data.get("sections", [])
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_citations = sec.get("citations", [])
            if not isinstance(sec_citations, list):
                continue
            for c in sec_citations:
                if not isinstance(c, dict):
                    continue
                key = c.get("id") or c.get("source") or str(c)
                if key not in seen:
                    seen.add(key)
                    citations.append(c)

    return citations


def _update_citations(
    structured_data: Dict[str, Any],
    cleaned_citations: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """用清理后的 citation 更新 structured_data"""
    valid_ids = set()
    for c in cleaned_citations:
        if not isinstance(c, dict):
            continue
        for k in ("id", "source", "url"):
            if c.get(k):
                valid_ids.add(str(c[k]))

    # 更新顶层 citations
    structured_data["citations"] = [
        c for c in cleaned_citations if isinstance(c, dict)
    ]

    # 更新 sections 内的 citations
    sections = structured_data.get("sections", [])
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec["citations"] = [
                c for c in sec.get("citations", [])
                if isinstance(c, dict) and any(str(c.get(k)) in valid_ids for k in ("id", "source", "url") if c.get(k))
            ]

    return structured_data


def _build_no_data_report(original_query: str, skill_hint: str) -> str:
    """无有效检索结果时的 fallback 报告"""
    return f"""# 报告生成异常：检索结果不足

很抱歉，关于「{original_query}」的深度报告无法生成。

**原因**：当前检索未返回与问题相关的有效信息。可能的原因包括：
1. 检索源暂时不可用（搜索引擎超时、知识库连接异常）
2. 问题涉及的信息超出当前知识库覆盖范围
3. 网络波动导致检索中断

**建议**：
1. 稍后重试
2. 调整问题表述，使用更通用的关键词
3. 联系管理员检查外部引擎和知识库状态

---
*报告类型：{SKILL_TEMPLATES.get(skill_hint, SKILL_TEMPLATES["default_deep"])["name"]}*
"""


def _build_error_report(original_query: str, skill_hint: str, error_msg: str) -> str:
    """生成失败时的 fallback 报告"""
    return f"""# 报告生成异常

很抱歉，基于当前检索结果生成深度报告时遇到了技术问题。

**原始问题**：{original_query}

**错误信息**：{error_msg}

**建议**：
1. 稍后重试
2. 简化问题后重新提问
3. 联系管理员检查外部引擎状态

---
*报告类型：{SKILL_TEMPLATES.get(skill_hint, SKILL_TEMPLATES["default_deep"])["name"]}*
"""


# ───────────────────────────────────────────────
# v0.4.5.5: Citation 锚定函数已弃用，保留代码供回滚
# ───────────────────────────────────────────────

def _inject_citation_anchors(markdown_report: str, chunks: List[Dict[str, Any]]) -> str:
    """
    [已弃用] v0.4.5.5 起不再调用此函数。
    引用统一由 LLM 在报告末尾的参考文献中列出，不再在段落间插入卡片。
    保留函数体以便需要时回滚到 v0.4.5 行为。
    """
    return markdown_report
