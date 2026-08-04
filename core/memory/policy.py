"""
Policy — 记忆读写策略 + 隐私过滤规则引擎
"""
import re
import json
from typing import Dict, Any

# 敏感信息正则模式（隐私过滤）
SENSITIVE_PATTERNS = [
    (r'\b(sk-[a-zA-Z0-9]{20,})\b', 'api_key'),           # DeepSeek / OpenAI API Key
    (r'\b(password|passwd|pwd|密钥|密码)\s*[:=]\s*\S+', 'credential'),
    (r'\b\d{17}[\dXx]\b', 'id_card'),                  # 身份证号（18位）
    (r'\b1[3-9]\d{9}\b', 'phone'),                     # 手机号
    (r'\b\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\b', 'birthday'),  # 出生日期
]

# 自动触发摘要生成的事件类型
AUTO_SUMMARIZE_EVENT_TYPES = {"conversation_turn", "deep_lane_complete"}

# 允许写入 Ledger 的事件类型
ALLOWED_EVENT_TYPES = {
    "conversation_turn",
    "deep_lane_complete",
    "explicit_profile_update",
    "user_feedback",
    "system_event"
}


def sanitize_for_ledger(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    隐私过滤：扫描 data 中所有字符串值，脱敏敏感信息。
    返回安全后的 data 副本。
    """
    text = json.dumps(data, ensure_ascii=False)

    for pattern, label in SENSITIVE_PATTERNS:
        text = re.sub(pattern, f"[REDACTED:{label}]", text, flags=re.IGNORECASE)

    return json.loads(text)


def should_auto_summarize(event_type: str) -> bool:
    """该事件类型是否应触发自动摘要生成？"""
    return event_type in AUTO_SUMMARIZE_EVENT_TYPES


def should_update_profile(event_type: str) -> bool:
    """该事件类型是否应触发档案卡更新评估？"""
    return event_type in {"conversation_turn", "explicit_profile_update"}


def is_allowed_event_type(event_type: str) -> bool:
    """该事件类型是否允许写入 Ledger？"""
    return event_type in ALLOWED_EVENT_TYPES


def get_ledger_ttl_days() -> int:
    """Ledger 热数据保留天数（30 天后可压缩归档）"""
    from core.config import get_settings
    return get_settings().LEDGER_TTL_DAYS