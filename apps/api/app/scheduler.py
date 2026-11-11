"""Планировщик (имитация ИИ-крона): синхронизация задач и утренние сводки «На чём остановились»."""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.db import database
from app.mcp_client import McpError, get_mcp
from app.models import InternProfile
from app.services.common import intern_context
from app.services.home import build_digest
from app.services.tasks import sync_all


async def sync_job() -> None:
    async with database.session() as session:
        try:
            await sync_all(session, get_mcp())
        except McpError:
            await session.rollback()


async def digest_job() -> int:
    async with database.session() as session:
        ids = [p.user_id for p in (await session.execute(select(InternProfile))).scalars()]
        for intern_id in ids:
            await build_digest(session, await intern_context(session, intern_id))
        await session.commit()
        return len(ids)


def start_scheduler() -> AsyncIOScheduler:  # pragma: no cover
    scheduler = AsyncIOScheduler()
    scheduler.add_job(sync_job, "interval", seconds=get_settings().task_sync_seconds)
    scheduler.add_job(digest_job, "cron", hour=8, minute=0)
    scheduler.start()
    return scheduler
