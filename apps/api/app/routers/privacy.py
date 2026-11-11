"""Экран «Приватность»: честно и в соответствии с реальным поведением API."""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import AccessLog, Chat, InternProfile, User
from app.routers.chats import delete_chats
from app.schemas import PrivacySettings
from app.security import Subject, intern_only
from app.services.common import events

router = APIRouter(tags=["privacy"])

COLUMNS = ["intern", "mentor", "lead", "hr", "ai_provider"]
MATRIX = [
    {"data": "Чаты и вопросы", "intern": "yes", "mentor": "no", "lead": "no", "hr": "no", "ai_provider": "Текст запроса — для ответа"},
    {"data": "Вложения", "intern": "yes", "mentor": "no", "lead": "no", "hr": "no", "ai_provider": "Логи — для ответа"},
    {"data": "Знакомства и заметки", "intern": "yes", "mentor": "no", "lead": "no", "hr": "no", "ai_provider": "no"},
    {"data": "Журнал достижений", "intern": "yes", "mentor": "Только записи, которыми вы поделились", "lead": "Только записи, которыми вы поделились",
     "hr": "no", "ai_provider": "Выбранные чаты — по кнопке «Предложить записи»"},
    {"data": "Прогресс чек-листа", "intern": "yes", "mentor": "Да, по умолчанию", "lead": "yes", "hr": "no", "ai_provider": "no"},
    {"data": "Задачи и их статусы", "intern": "yes", "mentor": "yes", "lead": "По команде", "hr": "no", "ai_provider": "Описание задачи — в чатах задачи"},
    {"data": "Статусы заявок на доступ", "intern": "yes", "mentor": "yes", "lead": "yes", "hr": "no", "ai_provider": "no"},
    {"data": "Отсутствие (отгул, отпуск)", "intern": "yes", "mentor": "yes", "lead": "yes", "hr": "no", "ai_provider": "no"},
]
FLOWS = [
    {"title": "Вы задаёте вопрос", "text": "Текст и вложения хранятся в базе сервиса. Доступ к ним есть только у вашей учётной записи."},
    {"title": "Поиск по документам вашей роли", "text": "Ассистент ищет только в документах, доступных стажёру. Закрытые документы в поиск не попадают."},
    {"title": "Ответ готовит провайдер ИИ", "text": "Текст вопроса и найденные фрагменты уходят провайдеру из конфигурации. В рабочей версии его "
                                                   "заменяют на внутренний шлюз компании."},
    {"title": "Ответ сохраняется в вашем чате", "text": "Удаление чата удаляет сообщения и вложения полностью. Записи журнала — отдельные копии."},
]


def _provider() -> dict:
    s = get_settings()
    if s.llm_provider == "openai_compatible":
        return {"mode": "openai_compatible", "host": urlparse(s.llm_base_url).hostname, "model": s.llm_model, "external": True}
    return {"mode": "fake", "host": None, "model": "детерминированные ответы без внешнего провайдера", "external": False}


@router.get("/privacy")
async def privacy(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    profile = await session.get(InternProfile, subject.id)
    matrix = [dict(row) for row in MATRIX]
    matrix.append({"data": "Тема, над которой работаете", "intern": "yes", "mentor": "yes" if profile.share_topics else "Только если разрешите",
                   "lead": "no", "hr": "no", "ai_provider": "no"})
    logs = (await session.execute(select(AccessLog).where(AccessLog.subject_id == subject.id, AccessLog.viewer_id != subject.id)
                                  .order_by(AccessLog.created_at.desc()).limit(20))).scalars().all()
    names = {u.id: u.name for u in (await session.execute(select(User))).scalars()}
    await events.emit(session, subject.id, "privacy_opened")
    await session.commit()
    return {
        "summary": "Ваши чаты видите только вы. Это правило работает на уровне сервера.",
        "columns": COLUMNS, "matrix": matrix, "flows": FLOWS, "ai_provider": _provider(),
        "settings": {"share_topics": profile.share_topics},
        "checklist_visible_to_mentor_by_default": True,
        "first_entry_text": "Здесь можно задавать любые вопросы. Ваши чаты видите только вы. Наставник видит ваш прогресс по чек-листу и "
                            "статусы задач, но не ваши вопросы.",
        "access_log": [{"viewer_id": log.viewer_id, "viewer_name": names.get(log.viewer_id, log.viewer_id), "resource": log.resource,
                        "decision": log.decision, "reason": log.reason, "created_at": log.created_at.isoformat()} for log in logs],
    }


@router.put("/privacy/settings")
async def update_settings(body: PrivacySettings, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    profile = await session.get(InternProfile, subject.id)
    profile.share_topics = body.share_topics
    await session.commit()
    return {"share_topics": profile.share_topics}


@router.delete("/privacy/chats")
async def delete_all_chats(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    ids = [c.id for c in (await session.execute(select(Chat).where(Chat.user_id == subject.id))).scalars()]
    await delete_chats(session, ids)
    await session.commit()
    return {"deleted": len(ids), "kept": "Записи журнала и знакомства остались"}
