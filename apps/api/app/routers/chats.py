"""Чаты, сообщения (SSE), вложения, обратная связь. Тексты чатов доступны только владельцу."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.orchestrator import Outcome, Turn
from app.config import get_settings
from app.db import database, get_session, new_id, utcnow
from app.deps import orchestrator, owned_chat, owned_message
from app.errors import ApiError, conflict, not_found
from app.kv import get_kv
from app.mcp_client import McpError, get_mcp
from app.models import Action, Attachment, Chat, Contact, JournalEntry, Message, Task
from app.schemas import ChatCreate, ChatPatch, FeedbackIn, MessageIn
from app.security import Subject, intern_only
from app.services.actions import action_view
from app.services.common import events, intern_context
from app.services.tasks import sync_tasks
from app.views import chat_view, message_view, task_view

router = APIRouter(tags=["chats"])

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
LOG_TYPES = {"text/plain", "text/x-log", "application/octet-stream"}
MAX_UPLOAD = 5 * 1024 * 1024


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


@router.get("/chats")
async def list_chats(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    try:
        await sync_tasks(session, get_mcp(), subject.id)
        await session.commit()
    except McpError:
        await session.rollback()
    tasks = (await session.execute(select(Task).where(Task.intern_id == subject.id).order_by(Task.created_at.desc()))).scalars().all()
    chats = (await session.execute(select(Chat).where(Chat.user_id == subject.id).order_by(Chat.updated_at.desc()))).scalars().all()
    return {
        "tasks": [{"task": task_view(t), "chats": [chat_view(c) for c in chats if c.task_id == t.id]} for t in tasks],
        "history": [chat_view(c) for c in chats if c.task_id is None],
        "empty_tasks_text": "Пока задач нет. Они появятся, когда наставник создаст задачу.",
    }


@router.post("/chats", status_code=201)
async def create_chat(body: ChatCreate, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    if body.task_id:
        task = await session.get(Task, body.task_id)
        if task is None or task.intern_id != subject.id:
            raise not_found("Задача не найдена")
        if task.locked:
            raise conflict("Задача закрыта в трекере: новые чаты недоступны, старые можно читать")
    chat = Chat(user_id=subject.id, title=body.title or "Новый чат", task_id=body.task_id)
    session.add(chat)
    await events.emit(session, subject.id, "chat_created", {"in_task": bool(body.task_id)})
    await session.commit()
    return chat_view(chat)


@router.patch("/chats/{chat_id}")
async def patch_chat(body: ChatPatch, chat: Chat = Depends(owned_chat), session: AsyncSession = Depends(get_session)) -> dict:
    if body.title is not None:
        chat.title = body.title
    if body.include_in_journal is not None:
        chat.include_in_journal = body.include_in_journal
    if body.mode is not None:
        chat.mode = body.mode
    await session.commit()
    return chat_view(chat)


async def delete_chats(session: AsyncSession, chat_ids: list[str]) -> None:
    """Физическое удаление с каскадом. Записи журнала и знакомства остаются (ссылка обнуляется, название сохраняется)."""
    if not chat_ids:
        return
    for att in (await session.execute(select(Attachment).where(Attachment.chat_id.in_(chat_ids)))).scalars():
        Path(att.path).unlink(missing_ok=True)
    await session.execute(delete(Attachment).where(Attachment.chat_id.in_(chat_ids)))
    await session.execute(delete(Message).where(Message.chat_id.in_(chat_ids)))
    await session.execute(update(JournalEntry).where(JournalEntry.source_chat_id.in_(chat_ids)).values(source_chat_id=None))
    await session.execute(update(Contact).where(Contact.source_chat_id.in_(chat_ids)).values(source_chat_id=None))
    await session.execute(update(Action).where(Action.chat_id.in_(chat_ids)).values(chat_id=None))
    await session.execute(delete(Chat).where(Chat.id.in_(chat_ids)))


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(chat: Chat = Depends(owned_chat), session: AsyncSession = Depends(get_session)) -> None:
    await delete_chats(session, [chat.id])
    await session.commit()


@router.get("/chats/{chat_id}/messages")
async def get_messages(chat: Chat = Depends(owned_chat), session: AsyncSession = Depends(get_session)) -> dict:
    messages = (await session.execute(select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at))).scalars().all()
    actions = {a.id: action_view(a) for a in (await session.execute(select(Action).where(Action.chat_id == chat.id))).scalars()}
    task = await session.get(Task, chat.task_id) if chat.task_id else None
    return {"chat": chat_view(chat), "task": task_view(task) if task else None, "messages": [message_view(m, actions) for m in messages]}


@router.post("/chats/{chat_id}/attachments", status_code=201)
async def upload(file: UploadFile = File(...), chat: Chat = Depends(owned_chat), session: AsyncSession = Depends(get_session)) -> dict:
    content_type = (file.content_type or "").lower()
    name = Path(file.filename or "file").name
    if content_type in IMAGE_TYPES:
        kind = "image"
    elif content_type in LOG_TYPES or name.endswith((".log", ".txt")):
        kind = "log"
    else:
        raise ApiError(415, "unsupported_type", "Можно прикрепить изображение или лог (.log, .txt)")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, "too_large", "Файл больше 5 МБ")
    folder = Path(get_settings().attachments_dir)
    folder.mkdir(parents=True, exist_ok=True)
    att = Attachment(chat_id=chat.id, user_id=chat.user_id, kind=kind, filename=name, size=len(data), path="")
    session.add(att)
    await session.flush()
    path = folder / f"{att.id}_{name}"
    path.write_bytes(data)  # содержимое не исполняется и не интерпретируется
    att.path = str(path)
    await session.commit()
    return {"id": att.id, "kind": kind, "filename": name, "size": len(data), "warning": "Не отправляйте пароли и токены."}


async def _turn_stream(chat_id: str, subject: Subject, text: str, mode: str, assistant_id: str, *, force_direct: bool = False,
                       attachment_ids: list[str] | None = None) -> AsyncIterator[str]:
    """Отдельная сессия БД на время потока: не зависит от жизненного цикла зависимостей запроса."""
    async with database.session() as session:
        try:
            chat = await session.get(Chat, chat_id)
            intern = await intern_context(session, subject.id)
            history_rows = (await session.execute(select(Message).where(Message.chat_id == chat_id)
                                                  .order_by(Message.created_at.desc()).limit(7))).scalars().all()
            history = [{"role": "user" if m.role == "user" else "assistant", "content": m.content} for m in reversed(history_rows)][:-1]
            attachments: list[str] = []
            for att in (await session.execute(select(Attachment).where(Attachment.id.in_(attachment_ids or []),
                                                                       Attachment.chat_id == chat_id))).scalars():
                if att.kind == "log":
                    attachments.append(Path(att.path).read_text(encoding="utf-8", errors="replace")[:4000])
            turn = Turn(session=session, subject=subject, intern=intern, chat=chat, text=text, mode=mode, force_direct=force_direct,
                        history=history, attachments=attachments, message_id=assistant_id)
            out = Outcome()
            async for name, data in orchestrator().answer(turn, out):
                yield sse(name, data)
            meta = {**out.meta}
            if out.error:
                meta["error"] = out.error
            session.add(Message(id=assistant_id, chat_id=chat_id, role="assistant", content=out.text, route=out.route, mode=mode,
                                sources=out.sources, blocks=out.blocks, meta=meta))
            chat.updated_at = utcnow()
            chat.unresolved = False
            await session.commit()
            yield sse("done", {"message_id": assistant_id, "route": out.route, "mode": mode, "guide": out.meta.get("guide")})
        except Exception as exc:  # pragma: no cover - страховка: ошибка не должна обрывать поток без события
            await session.rollback()
            yield sse("error", {"code": "internal", "message": "Не получилось ответить. Попробуйте ещё раз.", "detail": type(exc).__name__})


async def _replay(message: Message) -> AsyncIterator[str]:
    """Повтор по Idempotency-Key: отдаём сохранённый ответ без повторного выполнения."""
    for step in (message.meta or {}).get("steps", []):
        yield sse("status", {"step": "replay", "text": step})
    if message.content:
        yield sse("token", {"text": message.content})
    for src in message.sources or []:
        yield sse("source", src)
    for block in message.blocks or []:
        data = {k: v for k, v in block.items() if k != "type"}
        yield sse(block.get("type", "notice"), data)
    yield sse("done", {"message_id": message.id, "route": message.route, "mode": message.mode, "guide": (message.meta or {}).get("guide"),
                       "replayed": True})


def _stream(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _rate_limit(subject: Subject) -> None:
    count = await get_kv().incr_window(f"rl:messages:{subject.id}", 60)
    if count > get_settings().rate_limit_per_minute:
        raise ApiError(429, "rate_limited", "Слишком много сообщений. Подождите минуту.")


@router.post("/chats/{chat_id}/messages")
async def post_message(body: MessageIn, chat: Chat = Depends(owned_chat), subject: Subject = Depends(intern_only),
                       session: AsyncSession = Depends(get_session),
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> StreamingResponse:
    kv = get_kv()
    if idempotency_key:
        known = await kv.get(f"idem:{subject.id}:{idempotency_key}")
        if known:
            message = await session.get(Message, known)
            if message is not None:
                return _stream(_replay(message))
            raise conflict("Запрос с этим Idempotency-Key ещё обрабатывается")
    task = await session.get(Task, chat.task_id) if chat.task_id else None
    if task is not None and task.locked:
        raise conflict("Задача закрыта в трекере: чат доступен только для чтения")
    await _rate_limit(subject)
    text = body.text.strip()
    if not text:
        raise ApiError(422, "invalid_input", "Пустое сообщение")
    attachments = []
    if body.attachment_ids:
        rows = (await session.execute(select(Attachment).where(Attachment.id.in_(body.attachment_ids), Attachment.chat_id == chat.id))).scalars().all()
        attachments = [{"id": a.id, "kind": a.kind, "filename": a.filename} for a in rows]
    user_msg = Message(chat_id=chat.id, role="user", content=text, meta={"attachments": attachments})
    session.add(user_msg)
    await session.flush()
    if attachments:
        await session.execute(update(Attachment).where(Attachment.id.in_([a["id"] for a in attachments])).values(message_id=user_msg.id))
    if chat.title == "Новый чат":
        chat.title = _title(text)
    chat.mode = body.mode
    chat.updated_at = utcnow()
    await session.commit()
    assistant_id = new_id()
    if idempotency_key:
        await kv.set(f"idem:{subject.id}:{idempotency_key}", assistant_id, 24 * 3600)
    chat_id = chat.id
    await session.close()  # поток работает в своей сессии
    return _stream(_turn_stream(chat_id, subject, text, body.mode, assistant_id, attachment_ids=[a["id"] for a in attachments]))


@router.post("/messages/{message_id}/feedback")
async def feedback(body: FeedbackIn, message: Message = Depends(owned_message), subject: Subject = Depends(intern_only),
                   session: AsyncSession = Depends(get_session)) -> dict:
    if message.role != "assistant":
        raise ApiError(400, "invalid_input", "Оценить можно только ответ ассистента")
    message.feedback = "yes" if body.helpful else "no"
    chat = await session.get(Chat, message.chat_id)
    last = (await session.execute(select(Message).where(Message.chat_id == chat.id, Message.role == "assistant")
                                  .order_by(Message.created_at.desc()).limit(1))).scalars().first()
    if last is not None and last.id == message.id:
        chat.unresolved = not body.helpful
    await events.emit(session, subject.id, "answer_helpful" if body.helpful else "answer_not_helpful", {"route": message.route})
    await session.commit()
    return {"message_id": message.id, "feedback": message.feedback, "chat_unresolved": chat.unresolved}


@router.post("/messages/{message_id}/direct")
async def direct_answer(message: Message = Depends(owned_message), subject: Subject = Depends(intern_only),
                        session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    """Кнопка «Сразу ответ» под наводящим ответом: прямой ответ на тот же вопрос."""
    question = (message.meta or {}).get("question")
    if message.role != "assistant" or not question:
        raise ApiError(400, "invalid_input", "Прямой ответ доступен для ответов ассистента")
    await _rate_limit(subject)
    await events.emit(session, subject.id, "direct_answer_clicked", {"route": message.route})
    chat_id = message.chat_id
    await session.commit()
    await session.close()
    return _stream(_turn_stream(chat_id, subject, question, "direct", new_id(), force_direct=True))


@router.post("/messages/{message_id}/retry")
async def retry(message: Message = Depends(owned_message), subject: Subject = Depends(intern_only),
                session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    """Повтор после ошибки ИИ: сообщение с ошибкой удаляется, вопрос отвечается заново."""
    question = (message.meta or {}).get("question")
    if message.role != "assistant" or message.route != "error" or not question:
        raise ApiError(400, "invalid_input", "Повторить можно только ответ с ошибкой")
    chat_id, mode = message.chat_id, message.mode or "guide"
    await session.delete(message)
    await session.commit()
    await _rate_limit(subject)
    await session.close()
    return _stream(_turn_stream(chat_id, subject, question, mode, new_id()))
