# D:\precision_agent\api\health.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "logos-engine",
        "version": "0.4.0"  # v0.4.5.2 修复: 与 main.py 版本号同步
    }
