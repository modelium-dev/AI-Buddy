"""MCP-клиент к mock-corp: таймаут 5 с, один повтор, типизированные ошибки, контекст пользователя в каждом вызове.

Транспорты:
* http      — JSON-RPC 2.0 (tools/call) на {MCP_URL}/mcp;
* inprocess — прямой вызов модуля mock_corp (тесты и локальный запуск без второго процесса).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings


class McpError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # forbidden | not_found | invalid_input | unavailable
        self.message = message


class McpClient:
    def __init__(self, url: str, timeout: float = 5.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self._transport = transport
        self._seq = 0

    async def call(self, tool: str, args: dict[str, Any] | None = None, user: dict[str, str] | None = None) -> dict[str, Any]:
        user = user or {"id": "system", "role": "system"}
        last: Exception | None = None
        for _attempt in range(2):  # один повтор при сетевой ошибке/таймауте
            try:
                return await asyncio.wait_for(self._call_once(tool, args or {}, user), timeout=self.timeout)
            except McpError:
                raise
            except (asyncio.TimeoutError, httpx.HTTPError) as exc:
                last = exc
        raise McpError("unavailable", f"Сервис {tool.split('.')[0]} не ответил: {type(last).__name__}")

    async def _call_once(self, tool: str, args: dict, user: dict) -> dict:
        if self.url == "inprocess":
            from mock_corp.tools import ToolError, call_tool

            try:
                return call_tool(tool, args, user)
            except ToolError as exc:
                raise McpError(exc.code, exc.message) from exc
        self._seq += 1
        body = {"jsonrpc": "2.0", "id": self._seq, "method": "tools/call",
                "params": {"name": tool, "arguments": args, "_meta": {"user": user}}}
        async with httpx.AsyncClient(base_url=self.url, transport=self._transport, timeout=self.timeout) as client:
            response = await client.post("/mcp", json=body)
            response.raise_for_status()
            data = response.json()
        if "error" in data:
            raise McpError("invalid_input", data["error"].get("message", "Ошибка MCP"))
        result = data.get("result") or {}
        structured = result.get("structuredContent") or {}
        if result.get("isError"):
            err = structured.get("error", {})
            raise McpError(err.get("code", "invalid_input"), err.get("message", "Ошибка инструмента"))
        return structured


_client: McpClient | None = None


def get_mcp() -> McpClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = McpClient(s.mcp_url, s.mcp_timeout_seconds)
    return _client


def set_mcp(client: McpClient | None) -> None:
    global _client
    _client = client


def as_user(subject_id: str, role: str) -> dict[str, str]:
    return {"id": subject_id, "role": role}
