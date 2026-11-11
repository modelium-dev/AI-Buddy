"""Режим без ключа (LLM_PROVIDER=fake): детерминированные ответы и хеш-эмбеддинги для тестов."""
from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator

from app.assistant.text import stems


class FakeLLM:
    name = "fake"
    is_fake = True

    async def complete(self, messages: list[dict], *, json_mode: bool = False) -> str:
        return "{}" if json_mode else ""

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        text = await self.complete(messages)
        for word in text.split(" "):
            yield word + " "


class HashEmbedder:
    """Мешок основ слов, захешированный в вектор фиксированной длины."""

    name = "hash"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for stem in stems(text):
            idx = int(hashlib.md5(stem.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]
