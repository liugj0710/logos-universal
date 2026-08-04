# core/memory/views.py
"""
Views — 从 Ledger 生成摘要和档案卡更新
调用 DeepSeek-V4 Flash 生成对话摘要
"""
import json
from typing import Dict, Any, List
from core.memory.ledger import read_ledger
from core.memory.profile import get_profile, upsert_profile
from core.llm import call_llm

_SUMMARIZE_SYSTEM_PROMPT = """你是一个对话摘要生成器。请根据用户对话记录，生成结构化摘要。

【任务】
1. 生成对话主题摘要（2-3句话，中文）
2. 提取用户关注的3-5个关键词/话题
3. 推断用户当前意图或需求
4. 识别用户提到的设备、工具、偏好（如有）

【输出格式】
严格按以下 JSON 输出，不要有任何额外解释：
{
  "summary": "对话摘要",
  "topics": ["话题1", "话题2"],
  "intent": "意图描述",
  "devices": ["设备1"],
  "preferences": {"偏好键": "偏好值"}
}"""


async def generate_recent_summary(user_id: str, days: int = 1) -> Dict[str, Any]:
    """
    生成最近 N 天的对话摘要。
    无记录时返回空结构。
    """
    records = read_ledger(user_id, days=days, limit=50)
    if not records:
        return {
            "summary": "",
            "topics": [],
            "intent": "",
            "devices": [],
            "preferences": {}
        }

    context_lines = []
    for r in reversed(records):
        data = r.get("data", {})
        q = data.get("query", "")
        a = data.get("response_summary", "")
        if q:
            context_lines.append(f"Q: {q}")
        if a:
            context_lines.append(f"A: {a}")

    context = "\n".join(context_lines)
    if not context.strip():
        return {
            "summary": "",
            "topics": [],
            "intent": "",
            "devices": [],
            "preferences": {}
        }

    try:
        response = await call_llm(
            model="deepseek-v4-flash",
            system_prompt=_SUMMARIZE_SYSTEM_PROMPT,
            user_prompt=f"【用户对话记录】\n{context}",
            temperature=0.3,
            max_tokens=600,
            json_mode=True
        )
        result = json.loads(response)
        return {
            "summary": result.get("summary", ""),
            "topics": result.get("topics", []),
            "intent": result.get("intent", ""),
            "devices": result.get("devices", []),
            "preferences": result.get("preferences", {})
        }
    except Exception as e:
        print(f"[generate_recent_summary] LLM 生成失败: {e}")
        return {
            "summary": "",
            "topics": [],
            "intent": "",
            "devices": [],
            "preferences": {}
        }


async def update_profile_from_ledger(user_id: str) -> Dict[str, Any]:
    """
    从 Ledger 自动更新用户档案。
    """
    summary = await generate_recent_summary(user_id, days=7)

    profile = get_profile(user_id) or {}

    # 合并 recent_topics
    current_topics = profile.get("recent_topics") or {}
    if isinstance(current_topics, dict):
        for topic in summary.get("topics", []):
            current_topics[topic] = current_topics.get(topic, 0) + 1
    else:
        current_topics = {t: 1 for t in summary.get("topics", [])}

    # 合并 devices
    current_devices = profile.get("devices") or {}
    if isinstance(current_devices, dict):
        for device in summary.get("devices", []):
            current_devices[device] = current_devices.get(device, 0) + 1
    else:
        current_devices = {d: 1 for d in summary.get("devices", [])}

    # 合并 preferences
    current_prefs = profile.get("preferences") or {}
    if isinstance(current_prefs, dict):
        new_prefs = summary.get("preferences", {})
        if isinstance(new_prefs, dict):
            current_prefs.update(new_prefs)

    upsert_profile(
        user_id=user_id,
        recent_topics=current_topics,
        devices=current_devices,
        preferences=current_prefs,
        last_summary=summary.get("summary", "")
    )

    return get_profile(user_id)