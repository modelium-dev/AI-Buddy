"""Задачи-папки из трекера. Стажёр их не создаёт и не удаляет."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import not_found
from app.mcp_client import McpError, get_mcp
from app.models import Chat, Task
from app.security import Subject, intern_only
from app.services.tasks import sync_tasks
from app.views import chat_view, task_view

router = APIRouter(tags=["tasks"])


async def _sync(session: AsyncSession, intern_id: str) -> None:
    try:
        await sync_tasks(session, get_mcp(), intern_id)
        await session.commit()
    except McpError:
        await session.rollback()


@router.get("/tasks")
async def list_tasks(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> list[dict]:
    await _sync(session, subject.id)
    tasks = (await session.execute(select(Task).where(Task.intern_id == subject.id).order_by(Task.created_at.desc()))).scalars()
    return [task_view(t) for t in tasks]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    await _sync(session, subject.id)
    task = await session.get(Task, task_id)
    if task is None or task.intern_id != subject.id:
        raise not_found("Задача не найдена")
    chats = (await session.execute(select(Chat).where(Chat.task_id == task.id).order_by(Chat.updated_at.desc()))).scalars()
    return {
        **task_view(task),
        "chats": [chat_view(c) for c in chats],
        "can_create_chat": not task.locked,
        "notes": ["Описание и срок обновляются из трекера автоматически. Ассистент знает это описание в каждом чате задачи.",
                  "Папку нельзя удалить: она синхронизирована с трекером. Чаты внутри удалить можно."],
    }
