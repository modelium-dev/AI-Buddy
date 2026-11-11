"""Журнал достижений: только то, чем поделился стажёр. Записи — снимки текста, живут дольше чатов."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import intern_ctx
from app.errors import not_found
from app.llm import get_llm
from app.models import Chat, JournalEntry
from app.schemas import JournalCreate, JournalDraftIn, JournalExportIn, JournalPatch, JournalSuggestIn
from app.security import Subject, intern_only
from app.services import journal as svc
from app.services.common import InternContext, events
from app.views import journal_view

router = APIRouter(tags=["journal"])

NOTE = "Запись остаётся в журнале, даже если удалить чат. Саму запись можно удалить здесь."


@router.get("/journal")
async def list_entries(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(select(JournalEntry).where(JournalEntry.intern_id == subject.id)
                                  .order_by(JournalEntry.created_at.desc()))).scalars()
    return {"note": NOTE, "entries": [journal_view(e) for e in rows]}


@router.post("/journal/suggest")
async def suggest(body: JournalSuggestIn, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    """Предложения строятся только по выбранным чатам и ничего не сохраняют."""
    chats = (await session.execute(select(Chat).where(Chat.id.in_(body.chat_ids), Chat.user_id == subject.id))).scalars().all()
    if not chats:
        raise not_found("Чаты не найдены")
    items = await svc.suggest(session, get_llm(), chats)
    return {"items": items, "empty_text": None if items else "В выбранных чатах не нашлось результатов работы. Запись можно добавить вручную."}


@router.post("/journal", status_code=201)
async def create_entries(body: JournalCreate, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    created = []
    for item in body.entries:
        title = None
        if item.source_chat_id:
            chat = await session.get(Chat, item.source_chat_id)
            if chat is None or chat.user_id != subject.id:
                raise not_found("Чат не найден")
            title = chat.title
        entry = JournalEntry(intern_id=subject.id, text=item.text.strip(), source_chat_id=item.source_chat_id, source_chat_title=title)
        session.add(entry)
        created.append(entry)
    await events.emit(session, subject.id, "journal_entry_added", {"count": len(created)})
    await session.commit()
    return {"entries": [journal_view(e) for e in created]}


async def _owned(session: AsyncSession, subject: Subject, entry_id: str) -> JournalEntry:
    entry = await session.get(JournalEntry, entry_id)
    if entry is None or entry.intern_id != subject.id:
        raise not_found("Запись не найдена")
    return entry


@router.patch("/journal/{entry_id}")
async def patch_entry(entry_id: str, body: JournalPatch, subject: Subject = Depends(intern_only),
                      session: AsyncSession = Depends(get_session)) -> dict:
    entry = await _owned(session, subject, entry_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(entry, key, value.strip() if isinstance(value, str) else value)
    await session.commit()
    return journal_view(entry)


@router.delete("/journal/{entry_id}", status_code=204)
async def delete_entry(entry_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> None:
    await session.delete(await _owned(session, subject, entry_id))
    await session.commit()


@router.post("/journal/draft")
async def draft(body: JournalDraftIn, ctx: InternContext = Depends(intern_ctx), session: AsyncSession = Depends(get_session)) -> dict:
    stmt = select(JournalEntry).where(JournalEntry.intern_id == ctx.user.id)
    stmt = stmt.where(JournalEntry.id.in_(body.entry_ids)) if body.entry_ids else stmt.where(JournalEntry.include_in_export.is_(True))
    entries = (await session.execute(stmt)).scalars().all()
    if not entries:
        raise not_found("Нет записей для черновика")
    team = ctx.user.team_id.capitalize()
    return {"text": svc.draft_text(ctx.user.name, team, ctx.day, ctx.total, entries), "entry_ids": [e.id for e in entries]}


@router.post("/journal/export")
async def export(body: JournalExportIn, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> Response:
    pdf = svc.render_pdf(body.title, body.text)
    await events.emit(session, subject.id, "journal_exported", {"chars": len(body.text)})
    await session.commit()
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="journal.pdf"'})
