"""Ключ-значение для rate limit и идемпотентности: Redis или память (тесты, локальный запуск)."""
from __future__ import annotations

import time
from typing import Protocol


class KV(Protocol):
    async def incr_window(self, key: str, window_seconds: int) -> int: ...
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...


class MemoryKV:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    def _alive(self, key: str) -> tuple[str, float] | None:
        item = self._data.get(key)
        if item and item[1] < time.monotonic():
            self._data.pop(key, None)
            return None
        return item

    async def incr_window(self, key: str, window_seconds: int) -> int:
        item = self._alive(key)
        count = int(item[0]) + 1 if item else 1
        expires = item[1] if item else time.monotonic() + window_seconds
        self._data[key] = (str(count), expires)
        return count

    async def get(self, key: str) -> str | None:
        item = self._alive(key)
        return item[0] if item else None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl_seconds)


class RedisKV:  # pragma: no cover - требует запущенного Redis
    def __init__(self, url: str) -> None:
        from redis import asyncio as aioredis

        self._r = aioredis.from_url(url, decode_responses=True)

    async def incr_window(self, key: str, window_seconds: int) -> int:
        count = await self._r.incr(key)
        if count == 1:
            await self._r.expire(key, window_seconds)
        return int(count)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._r.set(key, value, ex=ttl_seconds)


_kv: KV | None = None


def get_kv() -> KV:
    global _kv
    if _kv is None:
        from app.config import get_settings

        url = get_settings().redis_url
        _kv = MemoryKV() if url.startswith("memory") else RedisKV(url)
    return _kv


def reset_kv(kv: KV | None = None) -> None:
    global _kv
    _kv = kv
