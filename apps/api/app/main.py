"""Точка входа FastAPI. OpenAPI — /docs, все ручки под префиксом /api."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import database
from app.errors import install_error_handlers
from app.mcp_client import McpError
from app.routers import actions, auth, chats, contacts, dev, home, journal, mentor, misc, privacy, tasks


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover - запускается uvicorn, в тестах БД готовит conftest
    s = get_settings()
    if database.engine is None:
        database.init(s.database_url)
    if s.seed_on_start:
        from app.cli import seed_if_empty

        await seed_if_empty()
    scheduler = None
    if s.scheduler_enabled:
        from app.scheduler import start_scheduler

        scheduler = start_scheduler()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await database.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Путь стажёра (AI-buddy) API", version="0.1.0", lifespan=lifespan,
                  description="Backend прототипа «Путь стажёра». Тестовые данные, не регламенты Авито. Описание ручек — API.md.")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")], allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])
    install_error_handlers(app)

    @app.exception_handler(McpError)
    async def _mcp_error(_: Request, exc: McpError) -> JSONResponse:
        status = {"forbidden": 403, "not_found": 404, "invalid_input": 400}.get(exc.code, 503)
        return JSONResponse(status_code=status, content={"error": {"code": exc.code, "message": exc.message}})

    for module in (auth, home, chats, tasks, actions, contacts, journal, privacy, mentor, misc, dev):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
