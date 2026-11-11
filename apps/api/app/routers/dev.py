"""Dev-панель (только DEV_MODE=true): имитация трекера, согласующих, времени и сбоев ИИ."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import database, get_session
from app.errors import ApiError, not_found
from app.llm import get_embedder
from app.mcp_client import McpError, get_mcp
from app.models import Action, InternProfile, Task
from app.schemas import DevDays, DevDecision, DevFlag, DevTaskUpdate, MentorTaskIn
from app.seed import seed_all
from app.services import actions as svc
from app.services.common import set_flag
from app.services.tasks import sync_all, sync_tasks
from app.views import task_view

SYSTEM = {"id": "system", "role": "system"}


def dev_enabled() -> None:
    if not get_settings().dev_mode:
        raise ApiError(404, "not_found", "Not Found")


router = APIRouter(prefix="/dev", tags=["dev"], dependencies=[Depends(dev_enabled)])


@router.post("/tracker/create-task", status_code=201)
async def create_task(body: MentorTaskIn, session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(InternProfile, body.intern_id) is None:
        raise not_found("Стажёр не найден")
    created = await get_mcp().call("tracker.create_task", {"intern_id": body.intern_id, "title": body.title, "description": body.description,
                                                           "deadline": body.deadline.isoformat() if body.deadline else None,
                                                           "created_by": "boris"}, SYSTEM)
    tasks = await sync_tasks(session, get_mcp(), body.intern_id)
    await session.commit()
    return task_view(next(t for t in tasks if t.external_id == created["id"]))


@router.post("/tracker/update-task")
async def update_task(body: DevTaskUpdate, session: AsyncSession = Depends(get_session)) -> dict:
    task = await session.get(Task, body.task_id)
    if task is None:
        raise not_found("Задача не найдена")
    args: dict = {"id": task.external_id}
    if body.status:
        args["status"] = body.status
    if body.description is not None:
        args["description"] = body.description
    deadline = body.deadline
    if body.shift_days:
        deadline = (task.deadline or date.today()) + timedelta(days=body.shift_days)
    if deadline:
        args["deadline"] = deadline.isoformat()
    await get_mcp().call("tracker.update_task", args, SYSTEM)
    await sync_tasks(session, get_mcp(), task.intern_id)
    await session.commit()
    await session.refresh(task)
    return task_view(task)


async def _decide(session: AsyncSession, action_id: str, decision: str, reason: str | None) -> dict:
    action = await session.get(Action, action_id)
    if action is None:
        raise not_found("Заявка не найдена")
    await svc.decide(session, get_mcp(), action, decision, reason)
    await session.commit()
    return svc.action_view(action)


@router.post("/access/approve")
async def approve(body: DevDecision, session: AsyncSession = Depends(get_session)) -> dict:
    return await _decide(session, body.action_id, "granted", body.reason)


@router.post("/access/reject")
async def reject(body: DevDecision, session: AsyncSession = Depends(get_session)) -> dict:
    return await _decide(session, body.action_id, "rejected", body.reason)


@router.post("/advance-day")
async def advance_day(body: DevDays, session: AsyncSession = Depends(get_session)) -> dict:
    profile = await session.get(InternProfile, body.intern_id)
    if profile is None:
        raise not_found("Стажёр не найден")
    profile.day_offset += body.days
    await session.commit()
    return {"intern_id": body.intern_id, "day_offset": profile.day_offset}


@router.post("/llm/fail-next")
async def fail_next(body: DevFlag, session: AsyncSession = Depends(get_session)) -> dict:
    await set_flag(session, "llm_fail_next", body.enabled)
    await session.commit()
    return {"llm_fail_next": body.enabled}


@router.post("/sync")
async def sync(session: AsyncSession = Depends(get_session)) -> dict:
    return {"synced_interns": await sync_all(session, get_mcp())}


@router.post("/reset")
async def reset() -> dict:
    try:
        await get_mcp().call("admin.reset", {}, SYSTEM)
    except McpError as exc:
        raise ApiError(502, exc.code, exc.message) from exc
    await database.drop_all()
    await database.create_all()
    async with database.session() as session:
        await seed_all(session, get_mcp(), get_embedder(), get_settings().seed_dir)
    return {"reset": True}
