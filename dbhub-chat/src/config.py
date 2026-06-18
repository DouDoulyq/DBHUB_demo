"""配置管理 —— 从环境变量 / .env 文件读取所有配置。"""

import os
from dotenv import load_dotenv

# override=True：.env 中的值覆盖系统环境变量（避免残留旧 Key）
load_dotenv(override=True)


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"缺少必需的环境变量: {key}")
    return value


# ── LLM ─────────────────────────────────────────────
LLM_API_KEY = _require("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# ── DBHub MCP ─────────────────────────────────────────
DBHUB_MCP_URL = os.getenv("DBHUB_MCP_URL", "http://localhost:8080")

# ── App ───────────────────────────────────────────────
APP_TITLE = os.getenv("APP_TITLE", "演示demo")
APP_PORT = int(os.getenv("APP_PORT", "8501"))
