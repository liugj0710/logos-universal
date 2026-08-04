"""
Profile — 用户结构化档案卡（SQLite）
父子双用户隔离：按 user_id 隔离，role 字段区分领域
"""
import os
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from core.config import get_settings

settings = get_settings()
_db_lock = threading.Lock()


def _get_db_path() -> str:
    return os.path.abspath(settings.PROFILE_DB_PATH)


def _init_db():
    """初始化 SQLite 表（幂等）"""
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    with _db_lock:
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    role TEXT DEFAULT '',
                    name TEXT DEFAULT '',
                    preferences TEXT DEFAULT '{}',
                    devices TEXT DEFAULT '{}',
                    expertise_domain TEXT DEFAULT '{}',
                    recent_topics TEXT DEFAULT '{}',
                    last_summary TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.commit()


def _serialize_field(value: Any) -> str:
    """将 dict/list 序列化为 JSON 字符串"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value is not None else '{}'


def _deserialize_field(value: Optional[str], default: Any = None) -> Any:
    """将 JSON 字符串反序列化"""
    if value is None:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """读取用户档案。不存在则返回 None。"""
    _init_db()
    db_path = _get_db_path()

    with _db_lock:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM profiles WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()

    if not row:
        return None

    profile = dict(row)
    # 反序列化 JSON 字段
    for field in ["preferences", "devices", "expertise_domain", "recent_topics"]:
        profile[field] = _deserialize_field(profile.get(field), {})

    return profile


def upsert_profile(user_id: str, **kwargs) -> Dict[str, Any]:
    """
    更新或创建用户档案。
    JSON 字段（preferences/devices/expertise_domain/recent_topics）自动合并。
    """
    _init_db()
    db_path = _get_db_path()
    now = datetime.now(timezone.utc).isoformat()

    existing = get_profile(user_id) or {}

    # 可更新的字段
    scalar_fields = ["role", "name", "last_summary"]
    json_fields = ["preferences", "devices", "expertise_domain", "recent_topics"]

    # 合并标量字段
    for field in scalar_fields:
        if field in kwargs and kwargs[field] is not None:
            existing[field] = kwargs[field]

    # 合并 JSON 字段（深度合并 dict）
    for field in json_fields:
        if field in kwargs and kwargs[field] is not None:
            new_val = kwargs[field]
            old_val = existing.get(field) or {}
            if isinstance(new_val, dict) and isinstance(old_val, dict):
                old_val.update(new_val)
                existing[field] = old_val
            else:
                existing[field] = new_val

    # 确保基础字段
    existing["user_id"] = user_id
    existing["updated_at"] = now
    if not existing.get("created_at"):
        existing["created_at"] = now

    # 序列化后写入
    with _db_lock:
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                INSERT INTO profiles (
                    user_id, role, name, preferences, devices,
                    expertise_domain, recent_topics, last_summary,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    role=excluded.role,
                    name=excluded.name,
                    preferences=excluded.preferences,
                    devices=excluded.devices,
                    expertise_domain=excluded.expertise_domain,
                    recent_topics=excluded.recent_topics,
                    last_summary=excluded.last_summary,
                    updated_at=excluded.updated_at
            """, (
                user_id,
                existing.get("role", ""),
                existing.get("name", ""),
                _serialize_field(existing.get("preferences", {})),
                _serialize_field(existing.get("devices", {})),
                _serialize_field(existing.get("expertise_domain", {})),
                _serialize_field(existing.get("recent_topics", {})),
                existing.get("last_summary", ""),
                existing.get("created_at", now),
                now
            ))
            conn.commit()

    return get_profile(user_id)