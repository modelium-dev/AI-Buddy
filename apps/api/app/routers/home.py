"""Главная, чек-лист, практика, уведомления."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.orchestrator import create_practice
from app.db import get_session, utcnow
from app.deps import intern_ctx
from app.domain import PRACTICE, STAGES
from app.errors import ApiError, not_found
from app.mcp_client import McpError, get_mcp
from app.models import ChecklistStep, InternStep, Notification, PracticeTask
from app.schemas import PracticePatch, StepPatch
from app.security import Subject, current_subject, intern_only
from app.services.common import InternContext, events
from app.services.home import home_view
from app.services.tasks import sync_tasks
from app.views import notification_view, practice_view

router = APIRouter(tags=["home"])


@router.get("/home")
async def home(ctx: InternContext = Depends(intern_ctx), session: AsyncSession = Depends(get_session)) -> dict:
    try:
        await sync_tasks(session, get_mcp(), ctx.user.id)
    except McpError:
        pass  # трекер недоступен — показываем последние синхронизированные данные
    data = await home_view(session, ctx)
    await session.commit()
    return data


@router.get("/checklist")
async def checklist(ctx: InternContext = Depends(intern_ctx), session: AsyncSession = Depends(get_session)) -> dict:
    steps = (await session.execute(select(ChecklistStep).order_by(ChecklistStep.order))).scalars().all()
    statuses = {s.step_id: s.status for s in (await session.execute(select(InternStep).where(InternStep.intern_id == ctx.user.id))).scalars()}
    stages = []
    for stage in STAGES:
        items = [{"id": s.id, "title": s.title, "topic": s.topic, "has_practice": s.topic in PRACTICE, "status": statuses.get(s.id, "todo")}
                 for s in steps if s.stage == stage.id]
        visible = [i for i in items if i["status"] != "hidden"]
        stages.append({"id": stage.id, "label": stage.label, "current": stage.id == ctx.stage.id, "steps": items,
                       "done": sum(1 for i in visible if i["status"] == "done"), "total": len(visible)})
    return {"note": "Шаблон, а не обязательство: в вашей команде порядок может отличаться.", "current_stage": ctx.stage.id, "stages": stages}


@router.patch("/checklist/{step_id}")
async def patch_step(step_id: str, body: StepPatch, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(ChecklistStep, step_id) is None:
        raise not_found("Шаг не найден")
    row = await session.get(InternStep, {"intern_id": subject.id, "step_id": step_id})
    if row is None:
        row = InternStep(intern_id=subject.id, step_id=step_id)
        session.add(row)
    row.status, row.updated_at = body.status, utcnow()
    if body.status == "done":
        await events.emit(session, subject.id, "checklist_step_done", {"step_id": step_id})
    await session.commit()
    return {"step_id": step_id, "status": body.status}


@router.post("/checklist/{step_id}/practice")
async def step_practice(step_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    step = await session.get(ChecklistStep, step_id)
    if step is None:
        raise not_found("Шаг не найден")
    if step.topic not in PRACTICE:
        raise ApiError(400, "no_practice", "Для этого шага нет практики")
    items = await create_practice(session, subject.id, step.topic, step.id, None)
    await events.emit(session, subject.id, "practice_generated", {"topic": step.topic})
    await session.commit()
    return {"step_id": step.id, "topic": step.topic, "label": PRACTICE[step.topic][0], "items": items}


@router.get("/practice")
async def list_practice(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(PracticeTask).where(PracticeTask.intern_id == subject.id).order_by(PracticeTask.created_at))).scalars()
    return [practice_view(p) for p in rows]


@router.patch("/practice/{practice_id}")
async def patch_practice(practice_id: str, body: PracticePatch, subject: Subject = Depends(intern_only),
                         session: AsyncSession = Depends(get_session)) -> dict:
    task = await session.get(PracticeTask, practice_id)
    if task is None or task.intern_id != subject.id:
        raise not_found("Задание не найдено")
    task.status = body.status
    if body.status == "done":
        await events.emit(session, subject.id, "practice_done", {"topic": task.topic})
    await session.commit()
    return practice_view(task)


@router.get("/notifications")
async def notifications(subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(select(Notification).where(Notification.user_id == subject.id)
                                  .order_by(Notification.created_at.desc()).limit(50))).scalars().all()
    return {"unread": sum(1 for n in rows if not n.read), "items": [notification_view(n) for n in rows]}


@router.post("/notifications/read-all")
async def read_all(subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(update(Notification).where(Notification.user_id == subject.id).values(read=True))
    await session.commit()
    return {"unread": 0}


@router.post("/notifications/{notification_id}/read")
async def read_one(notification_id: str, subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != subject.id:
        raise not_found("Уведомление не найдено")
    n.read = True
    await session.commit()
    return notification_view(n)
