"""Действия через корпоративные сервисы. Ассистент готовит черновик, подтверждает человек (отдельный API, не LLM)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.errors import ApiError, conflict
from app.mcp_client import McpClient, McpError, as_user
from app.models import Action, ChecklistStep, DocIssue, InternProfile
from app.security import Subject
from app.services.common import events, notify

LEVELS = {"read": "Чтение", "write": "Запись", "administration": "Администрирование"}


def _timeline(action: Action, status: str, text: str) -> None:
    result = dict(action.result or {})
    result["timeline"] = [*result.get("timeline", []), {"status": status, "text": text, "at": utcnow().isoformat()}]
    action.result = result
    action.updated_at = utcnow()


def action_view(action: Action, approver_name: str | None = None) -> dict:
    return {
        "id": action.id, "type": action.type, "status": action.status, "external_id": action.external_id,
        "external_status": action.external_status, "payload": action.payload, "approver_id": action.approver_id,
        "approver_name": approver_name, "chat_id": action.chat_id, "message_id": action.message_id,
        "timeline": (action.result or {}).get("timeline", []), "checklist_prompt": (action.result or {}).get("checklist_prompt"),
        "issue_id": (action.result or {}).get("issue_id"), "error": (action.result or {}).get("error"),
        "created_at": action.created_at.isoformat(), "confirmed_at": action.confirmed_at.isoformat() if action.confirmed_at else None,
    }


async def update_draft(action: Action, changes: dict) -> Action:
    if action.status != "draft":
        raise conflict("Черновик уже подтверждён или отменён")
    payload = dict(action.payload)
    if action.type == "access_request":
        allowed = {"project_key", "justification", "level", "space_or_page", "watch_issue_types", "cost_center"}
        if "level" in changes and changes["level"] not in LEVELS:
            raise ApiError(400, "invalid_input", "level: read | write | administration")
    elif action.type == "absence_request":
        allowed = {"date_from", "date_to", "kind", "reason"}
    else:
        allowed = {"text"}
    for key, value in changes.items():
        if key in allowed and value is not None:
            payload[key] = value
    action.payload = payload
    action.updated_at = utcnow()
    return action


async def confirm(session: AsyncSession, mcp: McpClient, subject: Subject, action: Action, approver_name: str | None) -> Action:
    """Идемпотентно: повторное подтверждение возвращает тот же результат без нового вызова сервиса."""
    if action.status == "confirmed":
        return action
    if action.status != "draft":
        raise conflict("Подтвердить можно только черновик")
    user = as_user(subject.id, subject.role)
    try:
        if action.type == "access_request":
            if str(action.payload.get("space_or_page", "")).strip().lower() in ("global", "общее", "общее пространство"):
                raise McpError("forbidden", "К общему глобальному пространству доступ не выдаётся")
            res = await mcp.call("access.create_request", {"payload": action.payload}, user)
            action.external_id, action.external_status = res["number"], res["status"]
            _timeline(action, "confirmed", "Подтверждено вами")
            _timeline(action, "sent", f"Отправлено ({res['number']})")
            _timeline(action, "pending", f"Ждёт согласования у {approver_name or 'согласующего'}")
            await events.emit(session, subject.id, "access_confirmed", {"number": res["number"]})
        elif action.type == "absence_request":
            res = await mcp.call("absence.create_request", dict(action.payload), user)
            action.external_id, action.external_status = res["number"], res["status"]
            _timeline(action, "confirmed", "Подтверждено вами")
            _timeline(action, "sent", f"Отправлено ({res['number']})")
            _timeline(action, "pending", "Ждёт согласования: руководитель, затем HR BP")
        elif action.type == "doc_conflict_report":
            count = (await session.execute(select(func.count()).select_from(DocIssue))).scalar_one()
            issue = DocIssue(id=f"DOC-{17 + count}", intern_id=action.intern_id, document_ids=action.payload.get("document_ids", []),
                             summary="Расхождение в инструкциях", text=action.payload.get("text", ""), reported_by_action_id=action.id)
            session.add(issue)
            action.external_id, action.external_status = issue.id, "sent"
            action.result = {**(action.result or {}), "issue_id": issue.id}
            _timeline(action, "confirmed", "Подтверждено вами")
            _timeline(action, "sent", f"Отправлено владельцу и наставнику ({issue.id})")
            profile = await session.get(InternProfile, action.intern_id)
            if profile is not None:
                await notify(session, profile.mentor_id, "doc_issue", f"Новое замечание к документам: {issue.id}", {"route": "mentor"})
            await events.emit(session, subject.id, "conflict_reported", {"issue": issue.id})
        else:  # pragma: no cover
            raise conflict("Неизвестный тип действия")
    except McpError as exc:
        action.status = "failed"
        action.result = {**(action.result or {}), "error": {"code": exc.code, "message": exc.message}}
        _timeline(action, "failed", exc.message)
        await session.commit()
        raise ApiError(403 if exc.code == "forbidden" else 502, exc.code, exc.message) from exc
    action.status = "confirmed"
    action.confirmed_at = utcnow()
    return action


async def cancel(action: Action) -> Action:
    if action.status == "cancelled":
        return action
    if action.status != "draft":
        raise conflict("Отменить можно только черновик")
    action.status = "cancelled"
    _timeline(action, "cancelled", "Отменено. Ничего не отправлено")
    return action


async def decide(session: AsyncSession, mcp: McpClient, action: Action, decision: str, reason: str | None = None) -> Action:
    """Решение согласующего (имитация из dev-панели) → уведомление стажёру, предложение закрыть шаг чек-листа."""
    if action.type != "access_request" or action.external_status != "pending":
        raise conflict("Заявка не ждёт согласования")
    await mcp.call("access.decide", {"number": action.external_id, "decision": decision, "reason": reason}, {"id": "system", "role": "system"})
    action.external_status = decision
    if decision == "granted":
        _timeline(action, "granted", "Доступ выдан")
        step = (await session.execute(select(ChecklistStep).where(ChecklistStep.topic == "access"))).scalars().first()
        if step is not None:
            action.result = {**action.result, "checklist_prompt": {"step_id": step.id, "title": step.title}}
        await notify(session, action.intern_id, "access", f"Доступ выдан: Jira {action.payload.get('project_key')} · {action.external_id}",
                     {"route": "chat", "id": action.chat_id, "action_id": action.id})
        await events.emit(session, action.intern_id, "access_granted", {"number": action.external_id})
    else:
        text = reason or "Укажите задачу, для которой нужен доступ, и минимальный уровень"
        _timeline(action, "rejected", f"Отклонено: {text}")
        await notify(session, action.intern_id, "access", f"Заявку {action.external_id} вернули на уточнение",
                     {"route": "chat", "id": action.chat_id, "action_id": action.id})
    return action


def reminder_text(action: Action, approver_name: str | None) -> str:
    first = (approver_name or "Коллега").split()[0]
    level = LEVELS.get(action.payload.get("level", "read"), "Чтение")
    return (f"{first}, добрый день! Напоминаю про заявку {action.external_id} на доступ к Jira-проекту {action.payload.get('project_key')} "
            f"(уровень «{level}»). Она нужна для работы над задачей. Если что-то нужно уточнить — подскажите.")
