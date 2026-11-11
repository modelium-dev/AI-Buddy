"""Настройки из переменных окружения (.env.example в корне репозитория)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./buddy.db"
    redis_url: str = "memory://"

    llm_provider: str = "fake"  # fake | openai_compatible
    llm_base_url: str = "https://api.example.com/v1"
    llm_api_key: str = ""
    llm_model: str = "__MODEL_NAME__"
    embeddings_model: str = "__MODEL_NAME__"
    llm_timeout_seconds: float = 30.0

    jwt_secret: str = "dev-only-secret"
    jwt_ttl_hours: int = 24
    dev_mode: bool = True

    mcp_url: str = "inprocess"  # inprocess | http://mock-corp:8001
    mcp_timeout_seconds: float = 5.0

    seed_dir: str = str(REPO_ROOT / "seed")
    prompts_dir: str = str(REPO_ROOT / "prompts")
    attachments_dir: str = "./attachments"
    pdf_font_paths: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf;C:/Windows/Fonts/arial.ttf"

    rag_top_k: int = 6
    rag_min_score: float = 0.5
    rate_limit_per_minute: int = 20
    task_sync_seconds: int = 30
    scheduler_enabled: bool = False
    seed_on_start: bool = False
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
