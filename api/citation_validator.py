# D:\precision_agent\api\citation_validator.py
"""
Λόγος Agent · /api/v1/validate_citations
职责：独立引用验证 API，供 Dify 工作流可选调用
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Dict, Any

from core.citation_validator import validate_citations

router = APIRouter()


# ───────────────────────────────────────────────
# 请求/响应模型
# ───────────────────────────────────────────────

class ValidateRequest(BaseModel):
    report_structured_data: Dict[str, Any] = Field(
        ...,
        description="synthesize 输出的 structured_data，必须包含 citations 和 sections"
    )
    retrieved_chunks: List[Dict[str, Any]] = Field(
        ...,
        description="原始检索结果，用于验证引用来源真实性"
    )

    class Config:
        extra = "allow"


class ValidateResponse(BaseModel):
    valid: bool = Field(..., description="是否通过校验（无高危问题）")
    issues: List[Dict[str, Any]] = Field(default=[], description="发现的问题清单")
    suggestions: List[str] = Field(default=[], description="修正建议")
    stats: Dict[str, Any] = Field(default={}, description="校验统计")


# ───────────────────────────────────────────────
# API 端点
# ───────────────────────────────────────────────

@router.post("/validate_citations", response_model=ValidateResponse)
async def validate_citations_api(request: ValidateRequest):
    """
    引用验证 API

    对 synthesize 生成的报告进行事实核查：
    - 来源是否真实存在于检索结果中
    - 引用摘录是否与原文一致
    - 章节是否有引用支撑
    - 关键结论是否有证据支撑

    零成本本地规则，不调用任何外部 API，响应时间 <100ms。
    """
    result = validate_citations(
        report_structured_data=request.report_structured_data,
        retrieved_chunks=request.retrieved_chunks
    )

    return ValidateResponse(
        valid=result["valid"],
        issues=result["issues"],
        suggestions=result["suggestions"],
        stats=result["stats"]
    )
