"""Служебное: health, события, флаги, метрики, поиск по базе знаний с учётом прав."""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.retrieval import safe_hits, search
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.llm import get_embedder
from app.mcp_client import McpError, get_mcp
from app.models import Event, Message
from app.schemas import EventIn
from app.security import Subject, current_subject
from app.services.common import EVENT_NAMES, all_flags, events

router = APIRouter(tags=["service"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover
        db_ok = False
    try:
        await get_mcp().call("org.get_profile", {"user_id": "boris"})
        mcp_ok = True
    except McpError:
        mcp_ok = False
    s = get_settings()
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "mcp": mcp_ok, "llm_provider": s.llm_provider, "dev_mode": s.dev_mode}


@router.post("/events", status_code=202)
async def post_event(body: EventIn, subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    if body.name not in EVENT_NAMES:
        raise ApiError(400, "invalid_input", "Неизвестное событие")
    await events.emit(session, subject.id, body.name, body.props)
    await session.commit()
    return {"accepted": True}


@router.get("/flags")
async def flags(subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    return await all_flags(session)


@router.get("/knowledge/search")
async def knowledge_search(q: str, subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    """Поиск по базе знаний с ACL роли (лид видит документы lead, стажёр — нет)."""
    hits = safe_hits(await search(session, subject, q, get_embedder(), top_k=get_settings().rag_top_k))
    return {"items": [{**h.source(), "heading": h.heading, "snippet": h.text[:300], "score": round(h.coverage, 2)} for h in hits]}


async def _summary(session: AsyncSession) -> dict:
    names = Counter(dict((await session.execute(select(Event.name, func.count()).group_by(Event.name))).all()))
    routes = Counter(dict((await session.execute(select(Message.route, func.count()).where(Message.role == "assistant")
                                                 .group_by(Message.route))).all()))
    answers = sum(routes.values()) or 1
    with_person = names.get("person_card_shown", 0)
    return {
        "events": dict(names), "routes": {str(k): v for k, v in routes.items()},
        "closed_without_person": round(max(0, answers - with_person) / answers, 3),
        "led_to_person": round(with_person / answers, 3),
        "not_helpful_share": round(names.get("answer_not_helpful", 0) / answers, 3),
        "direct_answer_share": round(names.get("direct_answer_clicked", 0) / answers, 3),
        "access_granted": names.get("access_granted", 0), "access_confirmed": names.get("access_confirmed", 0),
    }


@router.get("/metrics/summary")
async def metrics_summary(subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    if subject.role == "intern":
        raise ApiError(403, "forbidden", "Сводка доступна наставнику и лиду")
    return await _summary(session)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(session: AsyncSession = Depends(get_session)) -> str:
    data = await _summary(session)
    lines = ["# TYPE buddy_events_total counter"]
    lines += [f'buddy_events_total{{name="{k}"}} {v}' for k, v in sorted(data["events"].items())]
    lines.append("# TYPE buddy_answers_total counter")
    lines += [f'buddy_answers_total{{route="{k}"}} {v}' for k, v in sorted(data["routes"].items())]
    lines.append(f"buddy_led_to_person_ratio {data['led_to_person']}")
    return "\n".join(lines) + "\n"
