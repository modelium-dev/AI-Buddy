"""Провайдеры LLM и эмбеддингов, заменяемые конфигом (LLM_PROVIDER)."""
from __future__ import annotations

from app.config import get_settings
from app.llm.base import Embedder, LLMClient, LLMError
from app.llm.fake import FakeLLM, HashEmbedder
from app.llm.openai_compat import OpenAICompatibleEmbedder, OpenAICompatibleLLM

__all__ = ["Embedder", "LLMClient", "LLMError", "get_llm", "get_embedder", "set_llm", "set_embedder"]

_llm: LLMClient | None = None
_embedder: Embedder | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        s = get_settings()
        if s.llm_provider == "openai_compatible":
            _llm = OpenAICompatibleLLM(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_timeout_seconds)
        else:
            _llm = FakeLLM()
    return _llm


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = get_settings()
        if s.llm_provider == "openai_compatible":
            _embedder = OpenAICompatibleEmbedder(s.llm_base_url, s.llm_api_key, s.embeddings_model, s.llm_timeout_seconds)
        else:
            _embedder = HashEmbedder()
    return _embedder


def set_llm(llm: LLMClient | None) -> None:
    global _llm
    _llm = llm


def set_embedder(embedder: Embedder | None) -> None:
    global _embedder
    _embedder = embedder
