# core/rewrite.py
"""
Query Rewriting 层 — 将子查询改写为检索友好变体
v0.3.0 新增：支持注入记忆上下文（memory_context），影响改写方向
"""
import json
import re
from typing import List, Optional

from core.llm import call_llm

REWRITE_SYSTEM_PROMPT = """你是一个查询优化专家。你的任务是将用户子查询改写为更适合文档检索的形式。

【改写规则】
1. 去除口语化、情绪化表达
2. 补全指代不明的部分（如「这个」、「它」）
3. 保留核心实体和约束条件
4. 生成 1-2 个不同表述的检索变体，覆盖不同关键词组合
5. 每个变体不超过 30 字

【输出格式】
必须按以下 JSON 输出，不要有任何额外解释：

{
  "rewritten_queries": [
    "检索变体1",
    "检索变体2"
  ]
}"""


async def rewrite_query(sub_query: str, context: Optional[str] = None) -> List[str]:
    """
    调用 DeepSeek-V4 Flash 改写单个子查询。
    v0.3.0: 新增 context 参数，用于注入记忆上下文（用户偏好、近期关注等）。
    返回: 1-2 个检索变体（包含原始查询）
    """
    user_prompt_parts = []
    if context:
        user_prompt_parts.append(f"【用户背景上下文】\n{context}\n")
    user_prompt_parts.append(f"请对以下子查询进行改写：\n\n【原始子查询】\n{sub_query}")
    user_prompt = "\n".join(user_prompt_parts)

    try:
        response = await call_llm(
            model="deepseek-v4-flash",
            system_prompt=REWRITE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=200,
            json_mode=True
        )

        content = response.strip()
        rewritten = []

        # 策略1: 直接 JSON 解析
        try:
            data = json.loads(content)
            rewritten = data.get("rewritten_queries", [])
            if isinstance(rewritten, list) and rewritten:
                print(f"[rewrite_query] JSON 直接解析成功: {rewritten}")
        except json.JSONDecodeError:
            pass

        # 策略2: 提取 ```json 代码块
        if not rewritten and "```" in content:
            parts = content.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    data = json.loads(part)
                    if "rewritten_queries" in data and isinstance(data["rewritten_queries"], list):
                        rewritten = data["rewritten_queries"]
                        print(f"[rewrite_query] 代码块提取成功: {rewritten}")
                        break
                except (json.JSONDecodeError, AttributeError):
                    continue

        # 策略3: 正则精准提取 rewritten_queries 数组内容
        if not rewritten:
            array_match = re.search(
                r'"rewritten_queries"\s*:\s*\[(.*?)\]',
                content,
                re.DOTALL
            )
            if array_match:
                array_content = array_match.group(1)
                rewritten = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', array_content)
                if rewritten:
                    print(f"[rewrite_query] 正则数组提取成功: {rewritten}")

        # 策略4: 兜底 — 提取所有双引号字符串
        if not rewritten:
            all_matches = re.findall(r'"([^"]{5,})"', content)
            noise_keys = {"rewritten_queries", "query", "sub_query", "result", "output"}
            rewritten = [m for m in all_matches if m not in noise_keys]
            if rewritten:
                print(f"[rewrite_query] 正则兜底提取: {rewritten}")

        # 清理和限制
        rewritten = [
            q.strip() for q in rewritten
            if q and isinstance(q, str) and len(q.strip()) > 3
        ]
        rewritten = list(dict.fromkeys(rewritten))[:2]

        # 保底：确保原始查询在列表中
        if sub_query not in rewritten:
            rewritten.insert(0, sub_query)

        return rewritten[:2]

    except Exception as e:
        print(f"[rewrite_query] 改写失败: {e}，fallback 返回原始查询")
        return [sub_query]