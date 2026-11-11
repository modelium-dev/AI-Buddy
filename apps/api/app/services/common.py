"""Общие сервисы: события (EventSink), флаги, уведомления, профиль стажёра."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import Stage, intern_day, stage_for_day, total_days
from app.errors import not_found
from app.models import Event, Flag, InternProfile, Notification, User

EVENT_NAMES = {
    "chat_created", "message_sent", "answer_helpful", "answer_not_helpful", "direct_answer_clicked",
    "person_card_shown", "contact_saved", "access_draft_shown", "access_confirmed", "access_granted",
    "conflict_shown", "conflict_reported", "practice_generated", "practice_done", "checklist_step_done",
    "journal_entry_added", "journal_exported", "privacy_opened",
}


class EventSink(Protocol):
    async def emit(self, session: AsyncSession, user_id: str | None, name: str, props: dict[str, Any] | None = None) -> None: ...


class DbEventSink:
    """Реализация в БД. В проде заменяется на Kafka/Clickstream с тем же интерфейсом."""

    async def emit(self, session: AsyncSession, user_id: str | None, name: str, props: dict[str, Any] | None = None) -> None:
        session.add(Event(user_id=user_id, name=name, props=props or {}))


events: EventSink = DbEventSink()

DEFAULT_FLAGS: dict[str, Any] = {"guide_mode_default": "guide", "llm_fail_next": False}


async def get_flag(session: AsyncSession, key: str) -> Any:
    flag = await session.get(Flag, key)
    return flag.value if flag else DEFAULT_FLAGS.get(key)


async def set_flag(session: AsyncSession, key: str, value: Any) -> None:
    flag = await session.get(Flag, key)
    if flag is None:
        session.add(Flag(key=key, value=value))
    else:
        flag.value = value


async def all_flags(session: AsyncSession) -> dict[str, Any]:
    result = dict(DEFAULT_FLAGS)
    for flag in (await session.execute(select(Flag))).scalars():
        result[flag.key] = flag.value
    return result


async def notify(session: AsyncSession, user_id: str, kind: str, text: str, target: dict | None = None) -> Notification:
    n = Notification(user_id=user_id, kind=kind, text=text, target=target or {})
    session.add(n)
    return n


@dataclass
class InternContext:
    user: User
    profile: InternProfile
    day: int
    stage: Stage
    total: int


async def intern_context(session: AsyncSession, intern_id: str) -> InternContext:
    user = await session.get(User, intern_id)
    profile = await session.get(InternProfile, intern_id)
    if user is None or profile is None:
        raise not_found("Стажёр не найден")
    day = intern_day(profile.start_date, profile.day_offset)
    return InternContext(user=user, profile=profile, day=day, stage=stage_for_day(day), total=total_days(profile.program_months))
