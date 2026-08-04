# D:\precision_agent\api\planner.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import asyncio

from core.llm import call_llm
from core.config import get_settings

router = APIRouter()
settings = get_settings()


class PlannerRequest(BaseModel):
    query: str
    context: Optional[str] = Field(default="", description="额外上下文")
    user_id: Optional[str] = Field(default=None, description="用户ID，用于记忆检索")


class PlannerResponse(BaseModel):
    sub_queries: List[str]
    target_entity: Optional[str]
    skill_hint: str
    reasoning: str
    memory_injected: bool = False


SYSTEM_PROMPT = """你是一个问题拆解专家。请将用户的问题拆分为 1-3 个子查询，便于多源检索。

【规则】
1. 每个子查询必须独立、可检索
2. 子查询总数不超过 3 个
3. 识别 target_entity（核心分析对象）和 skill_hint（技能类型）
4. 如果问题不清晰，返回单个子查询即可

【skill_hint 选项】
- market_swot: 行业 SWOT 分析
- tech_timeline: 技术发展历程
- competitive_matrix: 竞品对比
- default_deep: 通用深度分析

【输出格式】
必须按以下 JSON 输出，不要有任何额外解释：

{
  "sub_queries": ["子查询1", "子查询2"],
  "target_entity": "核心实体",
  "skill_hint": "default_deep",
  "reasoning": "拆解理由"
}"""


@router.post("/planner", response_model=PlannerResponse)
async def deep_query_planner(request: PlannerRequest):
    try:
        # v0.3.0: 自动读取用户记忆
        memory_context = ""
        memory_injected = False

        if request.user_id:
            try:
                from core.memory.profile import get_profile
                from core.memory.search import search_memory

                profile = get_profile(request.user_id)
                if profile:
                    mem_parts = []
                    if profile.get("role"):
                        mem_parts.append(f"用户角色：{profile['role']}")
                    if profile.get("expertise_domain"):
                        domains = list(profile["expertise_domain"].keys())
                        if domains:
                            mem_parts.append(f"专业领域：{', '.join(domains)}")
                    if profile.get("recent_topics"):
                        topics = sorted(
                            profile["recent_topics"].items(),
                            key=lambda x: x[1],
                            reverse=True
                        )[:5]
                        mem_parts.append(f"近期关注：{', '.join([t[0] for t in topics])}")
                    if profile.get("last_summary"):
                        mem_parts.append(f"近期摘要：{profile['last_summary'][:100]}")

                    memory_context = "；".join(mem_parts)
                    memory_injected = True
                    print(f"[planner] 记忆注入 ({request.user_id}): {memory_context[:80]}...")

                # 语义检索近期记忆片段
                mem_results = await search_memory(request.user_id, request.query, top_k=2)
                if mem_results:
                    mem_text = "；".join([m["content"][:80] for m in mem_results])
                    if memory_context:
                        memory_context += f"。相关记忆：{mem_text}"
                    else:
                        memory_context = f"相关记忆：{mem_text}"
                    memory_injected = True

            except Exception as e:
                print(f"[planner] 记忆读取失败: {e}")

        # 拼接上下文
        context_parts = []
        if request.context:
            context_parts.append(request.context)
        if memory_context:
            context_parts.append(f"【用户记忆上下文】{memory_context}")

        full_context = "\n".join(context_parts) if context_parts else "无"

        user_prompt = f"用户问题：{request.query}\n上下文：{full_context}"

        response = await call_llm(
            model="deepseek-v4-flash",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=500,
            json_mode=True
        )

        import json
        result = json.loads(response)

        # v0.3.0: 异步写入 Ledger（记录本次查询）
        if request.user_id:
            try:
                from core.memory.ledger import append_ledger
                asyncio.create_task(asyncio.to_thread(
                    append_ledger,
                    request.user_id,
                    "conversation_turn",
                    {
                        "query": request.query,
                        "sub_queries": result.get("sub_queries", [request.query]),
                        "skill_hint": result.get("skill_hint", "default_deep")
                    },
                    {"source": "planner", "memory_injected": memory_injected}
                ))
            except Exception as e:
                print(f"[planner] Ledger 写入失败: {e}")

        return PlannerResponse(
            sub_queries=result.get("sub_queries", [request.query]),
            target_entity=result.get("target_entity"),
            skill_hint=result.get("skill_hint", "default_deep"),
            reasoning=result.get("reasoning", ""),
            memory_injected=memory_injected
        )

    except Exception as e:
        return PlannerResponse(
            sub_queries=[request.query],
            target_entity=None,
            skill_hint="default_deep",
            reasoning=f"拆解失败，fallback到原始查询: {str(e)}",
            memory_injected=False
        )