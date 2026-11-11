"""Главная: этап, нормализация, «На чём остановились» (кэш в digests), следующий шаг, задачи на сегодня."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.orchestrator import next_step
from app.db import utcnow
from app.domain import DEFAULT_SUGGESTIONS, NORMALIZATION, STAGES, SUGGESTIONS, today
from app.models import Chat, Digest, InternStep, Notification, Task
from app.services.common import InternContext


async def build_digest(session: AsyncSession, intern: InternContext) -> dict:
    chats = (await session.execute(select(Chat).where(Chat.user_id == intern.user.id).order_by(Chat.updated_at.desc()))).scalars().all()
    unresolved = next((c for c in chats if c.unresolved), None)
    last = unresolved or (chats[0] if chats else None)
    if last is None:
        text = "Пока нечего продолжать. Задайте первый вопрос — здесь появится, на чём вы остановились."
    else:
        text = f"В последний раз вы разбирались с вопросом «{last.title}»."
        if unresolved:
            text += f" Не решено: {unresolved.title.lower()} — ответ не помог, можно спросить ещё раз или сразу пойти к человеку."
    data = {"chat_id": last.id if last else None, "chat_title": last.title if last else None, "unresolved": bool(unresolved)}
    digest = await session.get(Digest, {"intern_id": intern.user.id, "day": today()})
    if digest is None:
        session.add(Digest(intern_id=intern.user.id, day=today(), text=text, data=data))
    else:
        digest.text, digest.data, digest.generated_at = text, data, utcnow()
    return {"text": text, **data}


def stages_view(intern: InternContext) -> list[dict]:
    idx = next(i for i, s in enumerate(STAGES) if s.id == intern.stage.id)
    result = []
    for i, s in enumerate(STAGES):
        progress = None
        if i == idx:
            span = max(1, s.end - s.start + 1) if s.end < 9999 else max(1, intern.total - s.start + 1)
            progress = round(min(1.0, max(0.0, (intern.day - s.start + 1) / span)), 2)
        result.append({"id": s.id, "label": s.label, "state": "done" if i < idx else "current" if i == idx else "next", "progress": progress})
    return result


async def home_view(session: AsyncSession, intern: InternContext) -> dict:
    step = await next_step(session, intern)
    tasks = (await session.execute(select(Task).where(Task.intern_id == intern.user.id, Task.status.in_(("in_progress", "review")))
                                   .order_by(Task.deadline))).scalars().all()
    unread = (await session.execute(select(Notification).where(Notification.user_id == intern.user.id, Notification.read.is_(False))
                                    .order_by(Notification.created_at.desc()))).scalars().all()
    step_status = None
    if step is not None:
        row = await session.get(InternStep, {"intern_id": intern.user.id, "step_id": step.id})
        step_status = row.status if row else "todo"
    return {
        "stage": {"id": intern.stage.id, "label": intern.stage.label},
        "day": intern.day, "total_days": intern.total,
        "stages": stages_view(intern),
        "normalization_text": NORMALIZATION[intern.stage.id],
        "digest": await build_digest(session, intern),
        "next_step": None if step is None else {"step_id": step.id, "title": step.title, "topic": step.topic, "status": step_status,
                                                 "note": "Шаблон. В вашей команде может отличаться."},
        "tasks_today": [{"id": t.id, "title": t.title, "status": t.status, "deadline": t.deadline.isoformat() if t.deadline else None}
                        for t in tasks],
        "suggestions": SUGGESTIONS.get(intern.stage.id, DEFAULT_SUGGESTIONS),
        "notifications": [{"id": n.id, "kind": n.kind, "text": n.text, "target": n.target, "created_at": n.created_at.isoformat()}
                          for n in unread],
        "privacy_note": "Ваши чаты видите только вы",
    }
