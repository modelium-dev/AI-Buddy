"""Синхронизация задач из трекера (события task.created / task.updated / task.closed через опрос)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.mcp_client import McpClient
from app.models import InternProfile, Task
from app.services.common import notify


def _date(value) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


async def sync_tasks(session: AsyncSession, mcp: McpClient, intern_id: str, *, notify_changes: bool = True) -> list[Task]:
    data = await mcp.call("tracker.list_tasks", {"intern_id": intern_id})
    existing = {t.external_id: t for t in (await session.execute(select(Task).where(Task.intern_id == intern_id))).scalars()}
    silent = not existing or not notify_changes
    result: list[Task] = []
    for ext in data.get("tasks", []):
        task = existing.get(ext["id"])
        done = ext.get("status") == "done"
        if task is None:
            task = Task(external_id=ext["id"], intern_id=intern_id, title=ext["title"], description=ext.get("description", ""),
                        status=ext.get("status", "new"), deadline=_date(ext.get("deadline")), created_by=ext.get("created_by", ""), locked=done)
            session.add(task)
            await session.flush()
            if not silent:  # task.created → пустая папка + уведомление
                await notify(session, intern_id, "task", f"Наставник создал задачу «{task.title}»", {"route": "task", "id": task.id})
        else:
            if done and not task.locked and not silent:  # task.closed → папка блокируется
                await notify(session, intern_id, "task", f"Задача «{task.title}» закрыта в трекере", {"route": "task", "id": task.id})
            task.title = ext["title"]
            task.description = ext.get("description", "")  # task.updated → описание и срок из трекера
            task.deadline = _date(ext.get("deadline"))
            task.status = ext.get("status", task.status)
            task.locked = done
        task.synced_at = utcnow()
        result.append(task)
    return result


async def sync_all(session: AsyncSession, mcp: McpClient) -> int:
    ids = [p.user_id for p in (await session.execute(select(InternProfile))).scalars()]
    for intern_id in ids:
        await sync_tasks(session, mcp, intern_id)
    await session.commit()
    return len(ids)
