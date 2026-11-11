"""Действия: заявка на доступ (главное действие), заявка на отгул, сообщение о расхождении. Подтверждает только человек."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import ApiError, not_found
from app.mcp_client import McpError, as_user, get_mcp
from app.models import AccessFormPreset, Action
from app.schemas import ActionPatch
from app.security import Subject, intern_only
from app.services import actions as svc

router = APIRouter(tags=["actions"])


async def _owned(session: AsyncSession, subject: Subject, action_id: str) -> Action:
    action = await session.get(Action, action_id)
    if action is None or action.intern_id != subject.id:
        raise not_found("Действие не найдено")
    return action


async def _approver_name(action: Action) -> str | None:
    if not action.approver_id:
        return None
    try:
        person = await get_mcp().call("org.get_profile", {"user_id": action.approver_id})
    except McpError:
        return None
    title = person.get("title") or ""
    return f"{person['name']}, {title[:1].lower()}{title[1:]}" if title else person["name"]


@router.get("/access/presets")
async def presets(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    try:
        return await get_mcp().call("access.get_options", {"team": subject.team_id}, as_user(subject.id, subject.role))
    except McpError:
        preset = await session.get(AccessFormPreset, subject.team_id)
        if preset is None:
            raise not_found("Пресет команды не найден")
        return {"team": subject.team_id, "fields": preset.fields, "defaults": {}, "levels": list(svc.LEVELS)}


@router.get("/actions")
async def list_actions(type: str | None = None, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> list[dict]:
    stmt = select(Action).where(Action.intern_id == subject.id).order_by(Action.created_at.desc())
    if type:
        stmt = stmt.where(Action.type == type)
    return [svc.action_view(a) for a in (await session.execute(stmt)).scalars()]


@router.get("/actions/{action_id}")
async def get_action(action_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    action = await _owned(session, subject, action_id)
    return svc.action_view(action, await _approver_name(action))


@router.patch("/actions/{action_id}")
async def patch_action(action_id: str, body: ActionPatch, subject: Subject = Depends(intern_only),
                       session: AsyncSession = Depends(get_session)) -> dict:
    action = await _owned(session, subject, action_id)
    await svc.update_draft(action, body.model_dump(exclude_unset=True))
    await session.commit()
    return svc.action_view(action, await _approver_name(action))


@router.post("/actions/{action_id}/confirm")
async def confirm(action_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    action = await _owned(session, subject, action_id)
    name = await _approver_name(action)
    await svc.confirm(session, get_mcp(), subject, action, name)
    await session.commit()
    return svc.action_view(action, name)


@router.post("/actions/{action_id}/cancel")
async def cancel(action_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    action = await _owned(session, subject, action_id)
    await svc.cancel(action)
    await session.commit()
    return svc.action_view(action)


@router.get("/actions/{action_id}/reminder")
async def reminder(action_id: str, subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    """Черновик напоминания согласующему. Отправляет стажёр сам (в Mattermost) — сервис ничего не шлёт."""
    action = await _owned(session, subject, action_id)
    if action.type != "access_request" or action.external_status != "pending":
        raise ApiError(409, "conflict", "Напоминание нужно только для заявки на согласовании")
    name = await _approver_name(action)
    return {"action_id": action.id, "text": svc.reminder_text(action, name), "channel": "Mattermost", "sent": False}
