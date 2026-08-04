# D:\precision_agent\api\memory.py
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import asyncio

from core.memory.ledger import append_ledger, read_ledger
from core.memory.profile import get_profile, upsert_profile
from core.memory.views import generate_recent_summary, update_profile_from_ledger
from core.memory.policy import sanitize_for_ledger, should_auto_summarize, is_allowed_event_type
from core.memory.search import search_memory, add_memory

router = APIRouter()


# ── 请求/响应模型 ──────────────────────────────────────────

class LedgerWriteRequest(BaseModel):
    user_id: str = Field(..., description="用户唯一标识（企业微信UserID / 小程序openid均可）")
    event_type: str = Field(default="conversation_turn", description="事件类型")
    data: Dict[str, Any] = Field(..., description="事件数据体")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="元数据")
    auto_summarize: bool = Field(default=True, description="是否异步生成摘要")

    class Config:
        extra = "allow"


class LedgerWriteResponse(BaseModel):
    event_id: str
    status: str


class ProfileReadResponse(BaseModel):
    user_id: str
    profile: Optional[Dict[str, Any]]
    recent_summary: Optional[Dict[str, Any]]


class ProfileUpdateRequest(BaseModel):
    user_id: str
    role: Optional[str] = Field(default=None, description="领域角色：marketing / management / other")
    name: Optional[str] = Field(default=None)
    preferences: Optional[Dict[str, Any]] = Field(default=None)
    devices: Optional[Dict[str, Any]] = Field(default=None)
    expertise_domain: Optional[Dict[str, Any]] = Field(default=None)

    class Config:
        extra = "allow"


class MemorySearchResponse(BaseModel):
    user_id: str
    query: str
    results: List[Dict[str, Any]]


# ── 后台任务 ───────────────────────────────────────────────

async def _async_summarize_and_index(user_id: str):
    """后台异步任务：生成摘要 → 写入 Chroma + 更新 SQLite Profile"""
    try:
        summary = await generate_recent_summary(user_id, days=1)
        if not summary.get("summary"):
            return

        # 1. 写入 Chroma logos_memory
        content = f"【{user_id} 近期摘要】{summary['summary']}\n"
        content += f"关注话题：{', '.join(summary.get('topics', []))}\n"
        content += f"意图：{summary.get('intent', '')}"

        await add_memory(
            user_id=user_id,
            content=content,
            memory_type="daily_summary",
            metadata={
                "topics": summary.get("topics", []),
                "intent": summary.get("intent", ""),
                "devices": summary.get("devices", []),
                "preferences": summary.get("preferences", {})
            }
        )

        # 2. 更新 SQLite Profile
        profile = get_profile(user_id) or {}
        
        current_topics = profile.get("recent_topics") or {}
        if isinstance(current_topics, dict):
            for topic in summary.get("topics", []):
                current_topics[topic] = current_topics.get(topic, 0) + 1
        
        current_devices = profile.get("devices") or {}
        if isinstance(current_devices, dict):
            for device in summary.get("devices", []):
                current_devices[device] = current_devices.get(device, 0) + 1
        
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
        print(f"[_async_summarize] 已为用户 {user_id} 更新记忆摘要和 Profile")

    except Exception as e:
        print(f"[_async_summarize] Error for {user_id}: {e}")


# ── API 端点 ───────────────────────────────────────────────

@router.post("/memory/ledger", response_model=LedgerWriteResponse)
async def write_ledger(request: LedgerWriteRequest):
    """
    写入 Ledger（对话结束后由 Dify 调用）。
    自动脱敏 + 可选异步摘要生成。
    """
    try:
        if not is_allowed_event_type(request.event_type):
            raise HTTPException(
                status_code=400,
                detail=f"不允许的事件类型: {request.event_type}"
            )

        # 隐私过滤
        safe_data = sanitize_for_ledger(request.data)

        event_id = append_ledger(
            user_id=request.user_id,
            event_type=request.event_type,
            data=safe_data,
            metadata=request.metadata
        )

        # 异步生成摘要并索引到 Chroma
        if request.auto_summarize and should_auto_summarize(request.event_type):
            asyncio.create_task(_async_summarize_and_index(request.user_id))

        return LedgerWriteResponse(event_id=event_id, status="ok")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ledger write failed: {str(e)}")


@router.get("/memory/profile", response_model=ProfileReadResponse)
async def read_profile(user_id: str = Query(..., description="用户ID")):
    """
    读取用户档案 + 近期摘要（Planner 前由 Dify 调用）。
    """
    try:
        profile = get_profile(user_id)
        recent_summary = None

        if profile:
            recent_summary = await generate_recent_summary(user_id, days=1)

        return ProfileReadResponse(
            user_id=user_id,
            profile=profile,
            recent_summary=recent_summary
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile read failed: {str(e)}")


@router.post("/memory/profile")
async def write_profile(request: ProfileUpdateRequest):
    """
    更新用户档案（Dify 显式触发，低频重要操作）。
    """
    try:
        update_data = {
            k: v for k, v in request.dict().items()
            if v is not None and k != "user_id"
        }
        upsert_profile(request.user_id, **update_data)
        return {"user_id": request.user_id, "status": "ok"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile update failed: {str(e)}")


@router.get("/memory/search", response_model=MemorySearchResponse)
async def memory_search(
    user_id: str = Query(..., description="用户ID"),
    query: str = Query(..., description="检索 query"),
    top_k: int = Query(default=5, ge=1, le=20)
):
    """
    语义检索用户记忆（供 retrieve 内部调用或 Dify 显式调用）。
    严格按 user_id 隔离。
    """
    try:
        results = await search_memory(user_id, query, top_k)
        return MemorySearchResponse(
            user_id=user_id,
            query=query,
            results=results
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory search failed: {str(e)}")


@router.post("/memory/summarize")
async def trigger_summarize(
    user_id: str = Query(..., description="用户ID"),
    days: int = Query(default=7, ge=1, le=30)
):
    """
    手动触发档案更新（从 Ledger 重新生成摘要并更新 Profile）。
    用于 Dify 工作流中的显式归档节点。
    """
    try:
        profile = await update_profile_from_ledger(user_id)
        return {
            "user_id": user_id,
            "status": "ok",
            "profile": profile
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summarize failed: {str(e)}")