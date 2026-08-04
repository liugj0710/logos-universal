"""
Ledger — 只追加的原始事件日志（真相源）
存储：JSONL，按 user_id 分目录，按日期分文件
"""
import os
import json
import uuid
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from core.config import get_settings

settings = get_settings()
_ledger_lock = threading.Lock()


def _get_ledger_dir(user_id: str) -> str:
    """获取用户 Ledger 目录"""
    dir_path = os.path.join(os.path.abspath(settings.LEDGER_DIR), user_id)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


def _list_ledger_files(user_id: str, days: int) -> List[str]:
    """列出最近 N 天的 Ledger 文件路径（从新到旧）"""
    dir_path = _get_ledger_dir(user_id)
    if not os.path.exists(dir_path):
        return []

    files = []
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        fpath = os.path.join(dir_path, f"ledger_{date_str}.jsonl")
        if os.path.exists(fpath):
            files.append(fpath)
    return files


def append_ledger(
    user_id: str,
    event_type: str,
    data: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    追加写入 Ledger。
    返回 event_id。
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "data": data,
        "metadata": metadata or {}
    }

    dir_path = _get_ledger_dir(user_id)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(dir_path, f"ledger_{today_str}.jsonl")

    with _ledger_lock:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event["event_id"]


def read_ledger(
    user_id: str,
    days: int = 7,
    limit: int = 100,
    event_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    读取最近 N 天的 Ledger 记录。
    按时间倒序，最多返回 limit 条。
    """
    files = _list_ledger_files(user_id, days)
    records = []

    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if event_type and record.get("event_type") != event_type:
                            continue
                        records.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[read_ledger] 读取文件失败 {filepath}: {e}")
            continue

    # 按时间倒序，限制条数
    records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return records[:limit]