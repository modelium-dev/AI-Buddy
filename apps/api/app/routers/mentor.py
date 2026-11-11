"""Страница наставника «Мои стажёры» (P1): прогресс, задачи, заявки, отсутствие. Никаких текстов вопросов."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Resource, authorize, ensure
from app.db import get_session
from app.domain import MENTOR_HELP, ONE_TO_ONE
from app.errors import ApiError
from app.mcp_client import McpError, as_user, get_mcp
from app.models import Action, ChecklistStep, DocIssue, InternProfile, InternStep, JournalEntry, Task
from app.schemas import MentorTaskIn
from app.security import Subject, mentor_only
from app.services.common import intern_context
from app.services.tasks import sync_tasks
from app.views import task_view

router = APIRouter(tags=["mentor"])


async def _intern_view(session: AsyncSession, subject: Subject, profile: InternProfile) -> dict:
    ctx = await intern_context(session, profile.user_id)
    owner = profile.user_id
    for resource in ("checklist_progress", "task", "access_request_status", "absence"):
        await ensure(session, subject, "read", Resource(type=resource, owner_id=owner, team_id=ctx.user.team_id))
    try:
        await sync_tasks(session, get_mcp(), owner)
    except McpError:
        pass
    steps = (await session.execute(select(ChecklistStep).order_by(ChecklistStep.order))).scalars().all()
    statuses = {s.step_id: s.status for s in (await session.execute(select(InternStep).where(InternStep.intern_id == owner))).scalars()}
    visible = [s for s in steps if statuses.get(s.id, "todo") != "hidden"]
    tasks = (await session.execute(select(Task).where(Task.intern_id == owner).order_by(Task.created_at.desc()))).scalars().all()
    requests = (await session.execute(select(Action).where(Action.intern_id == owner, Action.type == "access_request",
                                                           Action.status == "confirmed"))).scalars().all()
    absences = (await session.execute(select(Action).where(Action.intern_id == owner, Action.type == "absence_request",
                                                           Action.status == "confirmed"))).scalars().all()
    issues = (await session.execute(select(DocIssue).where(DocIssue.intern_id == owner).order_by(DocIssue.created_at.desc()))).scalars().all()
    topic_allowed = await authorize(session, subject, "read", Resource(type="topic", owner_id=owner, extra={"share_topics": profile.share_topics}))
    shared = (await session.execute(select(JournalEntry).where(JournalEntry.intern_id == owner, JournalEntry.shared_with_mentor.is_(True)))).scalars()
    current_task = next((t for t in tasks if t.status in ("in_progress", "review")), None)
    view = {
        "intern": {"id": ctx.user.id, "name": ctx.user.name, "team": ctx.user.team_id, "day": ctx.day, "total_days": ctx.total,
                   "stage": {"id": ctx.stage.id, "label": ctx.stage.label}},
        "is_absent_today": profile.is_absent_today,
        "checklist": {"done": sum(1 for s in visible if statuses.get(s.id) == "done"), "total": len(visible),
                      "current_stage": [{"id": s.id, "title": s.title, "status": statuses.get(s.id, "todo")} for s in steps if s.stage == ctx.stage.id]},
        "tasks": [task_view(t) for t in tasks],
        "access_requests": [{"id": a.id, "number": a.external_id, "project_key": a.payload.get("project_key"), "level": a.payload.get("level"),
                             "status": a.external_status} for a in requests],
        "absences": [{"id": a.id, "number": a.external_id, "date_from": a.payload.get("date_from"), "status": a.external_status} for a in absences],
        "doc_issues": [{"id": i.id, "summary": i.summary, "document_ids": i.document_ids, "status": i.status, "created_at": i.created_at.isoformat()}
                       for i in issues],
        "shared_journal": [{"id": e.id, "text": e.text, "created_at": e.created_at.isoformat()} for e in shared],
        "help_template": MENTOR_HELP[ctx.stage.id],
        "one_to_one_phrase": ONE_TO_ONE[ctx.stage.id],
        "chats_access": "denied",
    }
    if topic_allowed:  # без согласия поле просто отсутствует
        view["topic"] = current_task.title if current_task else "Онбординг"
    return view


@router.get("/mentor/interns")
async def interns(subject: Subject = Depends(mentor_only), session: AsyncSession = Depends(get_session)) -> dict:
    profiles = (await session.execute(select(InternProfile).where(InternProfile.mentor_id == subject.id).order_by(InternProfile.user_id))).scalars().all()
    result = [await _intern_view(session, subject, p) for p in profiles]
    await session.commit()
    return {"note": "Чаты, вопросы и знакомства стажёров недоступны: это правило работает на уровне API.", "interns": result}


@router.post("/mentor/tasks", status_code=201)
async def create_task(body: MentorTaskIn, subject: Subject = Depends(mentor_only), session: AsyncSession = Depends(get_session)) -> dict:
    profile = await session.get(InternProfile, body.intern_id)
    if profile is None:
        raise ApiError(404, "not_found", "Стажёр не найден")
    await ensure(session, subject, "create", Resource(type="task", owner_id=body.intern_id))
    try:
        created = await get_mcp().call("tracker.create_task", {"intern_id": body.intern_id, "title": body.title, "description": body.description,
                                                               "deadline": body.deadline.isoformat() if body.deadline else None,
                                                               "created_by": subject.id}, as_user(subject.id, subject.role))
    except McpError as exc:
        raise ApiError(502, exc.code, exc.message) from exc
    tasks = await sync_tasks(session, get_mcp(), body.intern_id)
    await session.commit()
    task = next(t for t in tasks if t.external_id == created["id"])
    return task_view(task)
