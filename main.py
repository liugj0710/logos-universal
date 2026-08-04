# main.py
import asyncio
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import os
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
loop.set_default_executor(ThreadPoolExecutor(max_workers=50))

from api import planner, retrieve, health, memory, synthesize, citation_validator, graphrag


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # ── 优雅关闭：保存图谱 + 释放浏览器 + 关闭 LLM 连接池 ──
    try:
        from core.graphrag.graph_store import get_knowledge_graph
        from core.graphrag.community import get_community_engine
        from core.search_baidu import close_baidu_browser
        from core.search_bing import close_bing_browser
        from core.llm import close_llm_client

        kg = get_knowledge_graph()
        ce = get_community_engine()
        kg.save()
        ce.save()
        print("[shutdown] GraphRAG 图谱已保存")

        close_baidu_browser()
        close_bing_browser()
        await close_llm_client()
    except Exception as e:
        print(f"[shutdown] 资源释放异常: {e}")


app = FastAPI(
    title="Λόγος External Engine",
    description="Nous Lab 棱镜系统外部引擎 · Phase 4 GraphRAG",
    version="0.4.0",  # Phase 4 开始，版本提升到 0.4.0
    lifespan=lifespan
)

app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(planner.router, prefix="/api/v1", tags=["Planner"])
app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieve"])
app.include_router(memory.router, prefix="/api/v1", tags=["Memory"])
app.include_router(synthesize.router, prefix="/api/v1", tags=["Synthesize"])
app.include_router(citation_validator.router, prefix="/api/v1", tags=["Citation Validator"])
app.include_router(graphrag.router, prefix="/api/v1", tags=["GraphRAG"])


@app.get("/")
async def root():
    return {
        "service": "Λόγος External Engine",
        "version": "0.4.0",
        "status": "running",
        "memory_service": "enabled",
        "synthesize": "enabled",
        "citation_validator": "enabled",
        "graphrag": "enabled"
    }


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("UVICORN_RELOAD", "false").lower() in ("true", "1", "yes")
    uvicorn.run("main:app", host=host, port=port, reload=reload)
