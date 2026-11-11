"""Общие зависимости роутов."""
from __future__ import annotations

from fastapi import Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.orchestrator import Orchestrator
from app.authz import Resource, authorize
from app.config import get_settings
from app.db import get_session
from app.errors import forbidden, not_found
from app.llm import get_embedder, get_llm
from app.mcp_client import get_mcp
from app.models import Chat, Message
from app.security import Subject, current_subject, intern_only
from app.services.common import InternContext, intern_context


async def intern_ctx(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> InternContext:
    return await intern_context(session, subject.id)


async def load_owned_chat(session: AsyncSession, subject: Subject, chat_id: str) -> Chat:
    """Чужой chat_id → 404; роль наставника/лида → 403 и запись отказа в access_log."""
    chat = await session.get(Chat, chat_id)
    if subject.role != "intern":
        if chat is not None:
            await authorize(session, subject, "read", Resource(type="chat_message", owner_id=chat.user_id))
            await session.commit()
        raise forbidden("Чаты стажёра доступны только самому стажёру")
    if chat is None or chat.user_id != subject.id:
        raise not_found("Чат не найден")
    return chat


async def owned_chat(chat_id: str = Path(...), subject: Subject = Depends(current_subject),
                     session: AsyncSession = Depends(get_session)) -> Chat:
    return await load_owned_chat(session, subject, chat_id)


async def owned_message(message_id: str = Path(...), subject: Subject = Depends(current_subject),
                        session: AsyncSession = Depends(get_session)) -> Message:
    message = await session.get(Message, message_id)
    if message is None and subject.role == "intern":
        raise not_found("Сообщение не найдено")
    if message is None:
        raise forbidden("Сообщения стажёра доступны только самому стажёру")
    await load_owned_chat(session, subject, message.chat_id)
    return message


def orchestrator() -> Orchestrator:
    return Orchestrator(get_llm(), get_embedder(), get_mcp(), get_settings())
