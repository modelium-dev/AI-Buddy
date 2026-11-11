"""OpenAI-совместимый провайдер: /chat/completions (в т. ч. поток) и /embeddings. Провайдер меняется конфигом."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.llm.base import LLMError


class OpenAICompatibleLLM:
    name = "openai_compatible"
    is_fake = False

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, transport=self._transport,
                                 headers={"Authorization": f"Bearer {self.api_key}"})

    async def complete(self, messages: list[dict], *, json_mode: bool = False) -> str:
        body: dict = {"model": self.model, "messages": messages, "temperature": 0.2}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            async with self._client() as client:
                response = await client.post("/chat/completions", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise LLMError("llm_timeout", "Модель не ответила вовремя") from exc
        except httpx.HTTPError as exc:
            raise LLMError("llm_unavailable", f"Провайдер ИИ недоступен: {type(exc).__name__}") from exc
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("llm_bad_response", "Неожиданный ответ провайдера") from exc

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        body = {"model": self.model, "messages": messages, "temperature": 0.2, "stream": True}
        try:
            async with self._client() as client:
                async with client.stream("POST", "/chat/completions", json=body) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            delta = json.loads(payload)["choices"][0].get("delta", {}).get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
        except httpx.TimeoutException as exc:
            raise LLMError("llm_timeout", "Модель не ответила вовремя") from exc
        except httpx.HTTPError as exc:
            raise LLMError("llm_unavailable", f"Провайдер ИИ недоступен: {type(exc).__name__}") from exc


class OpenAICompatibleEmbedder:
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, transport=self._transport,
                                         headers={"Authorization": f"Bearer {self.api_key}"}) as client:
                response = await client.post("/embeddings", json={"model": self.model, "input": texts})
                response.raise_for_status()
                data = response.json()["data"]
        except httpx.HTTPError as exc:
            raise LLMError("llm_unavailable", f"Эмбеддинги недоступны: {type(exc).__name__}") from exc
        return [item["embedding"] for item in sorted(data, key=lambda d: d.get("index", 0))]
