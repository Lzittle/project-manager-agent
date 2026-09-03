"""集中配置管理：从 backend/.env 读取配置，相对路径锚定到 backend 目录。

用法：from core.config import settings
     settings.APP_NAME / settings.DATABASE_URL / ...
"""
from pathlib import Path
import os
from dotenv import load_dotenv

# backend/ 目录（本文件位于 backend/core/config.py，向上两级）
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)  # 显式指定 .env 路径，避免受启动目录影响


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _resolve_sqlite_url(url: str) -> str:
    """sqlite 相对路径 URL -> 锚定到 backend 目录的绝对路径 URL。

    例: sqlite:///./project_manager.db -> sqlite:///D:/.../backend/project_manager.db
    """
    if url.startswith("sqlite:///"):
        rest = url[len("sqlite:///"):]
        p = Path(rest)
        if not p.is_absolute():
            p = BASE_DIR / p
        return f"sqlite:///{p.resolve().as_posix()}"
    return url


def _resolve_dir(raw: str) -> str:
    """相对目录 -> 锚定到 backend 目录的绝对目录路径。"""
    p = Path(raw)
    return str((BASE_DIR / p).resolve() if not p.is_absolute() else p.resolve())


class Settings:
    # 应用
    APP_NAME: str = _get("APP_NAME", "项目管理Agent")
    APP_HOST: str = _get("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(_get("APP_PORT", "8000"))

    # 业务数据库
    DATABASE_URL: str = _resolve_sqlite_url(_get("DATABASE_URL", "sqlite:///./project_manager.db"))

    # 向量库 ChromaDB
    CHROMA_PERSIST_DIR: str = _resolve_dir(_get("CHROMA_PERSIST_DIR", "./chroma_db"))
    CHROMA_COLLECTION: str = _get("CHROMA_COLLECTION", "knowledge_docs")

    # 大模型（openai 兼容接口）
    OPENAI_API_KEY: str = _get("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = _get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = _get("LLM_MODEL", "gpt-4o-mini")

    @property
    def has_api_key(self) -> bool:
        return bool(self.OPENAI_API_KEY) and not self.OPENAI_API_KEY.startswith("sk-xxx")


settings = Settings()
