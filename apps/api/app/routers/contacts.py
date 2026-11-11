"""Знакомства (паспорт знакомств). Видит только стажёр."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import ApiError, conflict, not_found
from app.mcp_client import McpError, get_mcp
from app.models import Chat, Contact
from app.schemas import ContactIn, ContactPatch
from app.security import Subject, intern_only
from app.services.common import events
from app.views import contact_view

router = APIRouter(tags=["contacts"])


@router.get("/contacts")
async def list_contacts(q: str | None = None, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(Contact).where(Contact.intern_id == subject.id).order_by(Contact.created_at.desc()))).scalars().all()
    if q:
        needle = q.lower()
        rows = [c for c in rows if needle in " ".join([c.name, c.role, c.team, c.note, c.how_to_ask, *(c.topics or [])]).lower()]
    return [contact_view(c) for c in rows]


@router.post("/contacts", status_code=201)
async def create_contact(body: ContactIn, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    data = body.model_dump()
    if body.person_id:
        exists = (await session.execute(select(Contact).where(Contact.intern_id == subject.id, Contact.person_id == body.person_id))).scalars().first()
        if exists:
            raise conflict("Этот человек уже в знакомствах")
        try:
            person = await get_mcp().call("org.get_profile", {"user_id": body.person_id})
        except McpError as exc:
            raise not_found("Сотрудник не найден") from exc
        data.update(name=person["name"], role=data["role"] or person.get("title", ""), team=data["team"] or person.get("team", ""),
                    topics=data["topics"] or person.get("topics", []))
    elif not body.name:
        raise ApiError(422, "invalid_input", "Укажите person_id или name")
    title = None
    if body.source_chat_id:
        chat = await session.get(Chat, body.source_chat_id)
        if chat is None or chat.user_id != subject.id:
            raise not_found("Чат не найден")
        title = chat.title
    contact = Contact(intern_id=subject.id, person_id=body.person_id, name=data["name"], role=data["role"], team=data["team"],
                      topics=data["topics"], how_to_ask=data["how_to_ask"], note=data["note"], source_chat_id=body.source_chat_id,
                      source_chat_title=title)
    session.add(contact)
    await events.emit(session, subject.id, "contact_saved", {"person_id": body.person_id})
    await session.commit()
    return contact_view(contact)


async def _owned(session: AsyncSession, subject: Subject, contact_id: str) -> Contact:
    contact = await session.get(Contact, contact_id)
    if contact is None or contact.intern_id != subject.id:
        raise not_found("Контакт не найден")
    return contact


@router.patch("/contacts/{contact_id}")
async def patch_contact(contact_id: str, body: ContactPatch, subject: Subject = Depends(intern_only),
                        session: AsyncSession = Depends(get_session)) -> dict:
    contact = await _owned(session, subject, contact_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(contact, "how_to_ask" if key == "how_to_ask" else key, value)
    await session.commit()
    return contact_view(contact)


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> None:
    contact = await _owned(session, subject, contact_id)
    await session.delete(contact)
    await session.commit()
