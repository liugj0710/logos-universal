# D:\precision_agent\core\config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080")
    CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", ".\\chroma_db")

    DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
    DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "http://localhost")
    DIFY_DATASET_IDS = os.getenv("DIFY_DATASET_IDS", "")

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8000))

    # Phase 3: Ollama Embedding
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
    OLLAMA_BATCH_SIZE = int(os.getenv("OLLAMA_BATCH_SIZE", "32"))

    # Phase 2.5: Memory System
    LEDGER_DIR = os.getenv("LEDGER_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ledger"))
    PROFILE_DB_PATH = os.getenv("PROFILE_DB_PATH", ".\\data\\profiles\\profiles.db")
    MEMORY_COLLECTION_NAME = os.getenv("MEMORY_COLLECTION_NAME", "logos_memory")
    LEDGER_TTL_DAYS = int(os.getenv("LEDGER_TTL_DAYS", "30"))

_settings = None

def get_settings():
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings