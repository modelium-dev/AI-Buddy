"""HTTP-транспорт MCP (JSON-RPC 2.0 поверх POST /mcp): initialize, tools/list, tools/call."""
from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from mock_corp.tools import ToolError, call_tool, list_tools

app = FastAPI(title="mock-corp", description="Имитация корпоративных сервисов для «Путь стажёра». Данные вымышленные.")


def _ok(req_id, result: dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _err(req_id, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "tools": len(list_tools())}


@app.get("/tools")
def tools() -> dict:
    return {"tools": list_tools()}


@app.post("/mcp")
async def mcp(request: Request) -> Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _err(None, -32700, "Parse error")
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    if method == "initialize":
        return _ok(req_id, {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                            "serverInfo": {"name": "mock-corp", "version": "0.1.0"}})
    if method and method.startswith("notifications/"):
        return Response(status_code=202)
    if method == "tools/list":
        return _ok(req_id, {"tools": list_tools()})
    if method == "tools/call":
        user = (params.get("_meta") or {}).get("user") or {"id": request.headers.get("x-user-id"), "role": request.headers.get("x-user-role")}
        try:
            data = call_tool(params.get("name", ""), params.get("arguments") or {}, user)
        except ToolError as exc:
            error = {"error": {"code": exc.code, "message": exc.message}}
            return _ok(req_id, {"isError": True, "structuredContent": error,
                                "content": [{"type": "text", "text": json.dumps(error, ensure_ascii=False)}]})
        return _ok(req_id, {"isError": False, "structuredContent": data,
                            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]})
    return _err(req_id, -32601, "Method not found")
