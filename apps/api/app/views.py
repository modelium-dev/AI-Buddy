"""Сериализация моделей в JSON-ответы."""
from __future__ import annotations

from app.models import Chat, Contact, JournalEntry, Message, Notification, PracticeTask, Task

TASK_LABELS = {"new": "Новая", "in_progress": "В работе", "review": "На ревью", "done": "Закрыта в трекере"}


def iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def task_view(t: Task) -> dict:
    return {"id": t.id, "external_id": t.external_id, "title": t.title, "description": t.description, "status": t.status,
            "status_label": TASK_LABELS.get(t.status, t.status), "deadline": iso(t.deadline), "created_by": t.created_by,
            "locked": t.locked, "synced_at": iso(t.synced_at)}


def chat_view(c: Chat) -> dict:
    return {"id": c.id, "title": c.title, "task_id": c.task_id, "mode": c.mode, "include_in_journal": c.include_in_journal,
            "unresolved": c.unresolved, "guide": {"topic": c.guide_topic, "streak": c.guide_streak} if c.guide_topic else None,
            "created_at": iso(c.created_at), "updated_at": iso(c.updated_at)}


def message_view(m: Message, actions: dict | None = None) -> dict:
    blocks = []
    for block in m.blocks or []:
        b = dict(block)
        if actions and b.get("action_id") in actions:
            b["action"] = actions[b["action_id"]]
        blocks.append(b)
    meta = m.meta or {}
    return {"id": m.id, "chat_id": m.chat_id, "role": m.role, "content": m.content, "route": m.route, "mode": m.mode, "sources": m.sources or [],
            "blocks": blocks, "steps": meta.get("steps", []), "guide": meta.get("guide"), "attachments": meta.get("attachments", []),
            "feedback": m.feedback, "created_at": iso(m.created_at)}


def contact_view(c: Contact) -> dict:
    return {"id": c.id, "person_id": c.person_id, "name": c.name, "role": c.role, "team": c.team, "topics": c.topics or [],
            "how_to_ask": c.how_to_ask, "note": c.note, "source_chat_id": c.source_chat_id, "source_chat_title": c.source_chat_title,
            "created_at": iso(c.created_at)}


def journal_view(e: JournalEntry) -> dict:
    deleted = e.source_chat_id is None and e.source_chat_title is not None
    return {"id": e.id, "text": e.text, "source_chat_id": e.source_chat_id, "source_chat_title": e.source_chat_title, "chat_deleted": deleted,
            "source_label": (f"Чат удалён · «{e.source_chat_title}»" if deleted else f"Из чата «{e.source_chat_title}»" if e.source_chat_title
                             else "Добавлено вручную"),
            "include_in_export": e.include_in_export, "shared_with_mentor": e.shared_with_mentor, "created_at": iso(e.created_at)}


def notification_view(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "text": n.text, "target": n.target or {}, "read": n.read, "created_at": iso(n.created_at)}


def practice_view(p: PracticeTask) -> dict:
    return {"id": p.id, "step_id": p.step_id, "topic": p.topic, "task": p.text, "criterion": p.criterion, "status": p.status,
            "message_id": p.message_id, "created_at": iso(p.created_at)}
