from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class LLMError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # llm_timeout | llm_unavailable | llm_bad_response
        self.message = message


class LLMClient(Protocol):
    name: str
    is_fake: bool

    async def complete(self, messages: list[dict], *, json_mode: bool = False) -> str: ...

    def stream(self, messages: list[dict]) -> AsyncIterator[str]: ...


class Embedder(Protocol):
    name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
