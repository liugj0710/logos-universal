# D:\precision_agent\core\llm.py
import httpx
import json
from core.config import get_settings

settings = get_settings()

# 模块级 AsyncClient 复用连接池
_client = None

def _get_client() -> httpx.AsyncClient:
    """获取或创建复用的 AsyncClient"""
    global _client
    if _client is None:
        # 保险设置：连接10s，读写180s，防止大报告生成超时
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
        )
    return _client

async def close_llm_client():
    """优雅关闭连接池（在应用关闭时调用）"""
    global _client
    if _client:
        await _client.aclose()
        _client = None

async def call_llm(
    model: str = "deepseek-v4-flash",
    system_prompt: str = "",
    user_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 500,
    json_mode: bool = False
) -> str:
    """
    调用 DeepSeek API（兼容 OpenAI 格式）
    model: deepseek-chat (Flash) / deepseek-reasoner (Pro)
    """
    headers = {
        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    client = _get_client()
    # 显式指定请求级超时，双重保险
    response = await client.post(
        f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=180.0
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]
