"""RBAC + ABAC: единая функция решения authorize() (раздел 4.2 ТЗ).

decide() — чистая функция (таблица правил, легко тестируется).
ensure() — вычисляет отношение к субъекту данных, решает, пишет access_log и бросает ошибку.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import forbidden, not_found
from app.models import AccessLog, InternProfile
from app.security import Subject

PERSONAL = {"chat", "chat_message", "attachment", "contact", "practice", "action", "privacy_settings"}
ORG = {"checklist_progress", "task", "access_request_status", "absence"}


@dataclass(frozen=True)
class Resource:
    type: str
    owner_id: str | None = None
    team_id: str | None = None
    access_level: str = "team"  # public | team | lead
    space: str = "team"  # team | global
    sensitivity: str = "low"  # low | org | personal
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allow


ALLOW = lambda reason: Decision(True, reason)
DENY = lambda reason: Decision(False, reason)


def decide(subject: Subject, relation: str, action: str, resource: Resource) -> Decision:
    """relation: self | mentor_of | manager_of | none."""
    t = resource.type
    if t in PERSONAL:
        return ALLOW("owner") if relation == "self" else DENY("personal_data")
    if t == "journal_entry":
        if relation == "self":
            return ALLOW("owner")
        if relation in ("mentor_of", "manager_of") and action == "read" and resource.extra.get("shared"):
            return ALLOW("shared_by_intern")
        return DENY("personal_data")
    if t == "topic":
        if relation == "self":
            return ALLOW("owner")
        if relation == "mentor_of" and resource.extra.get("share_topics"):
            return ALLOW("intern_consent")
        return DENY("no_consent")
    if t in ORG:
        if relation == "self":
            return ALLOW("owner") if action == "read" or t == "checklist_progress" else DENY("read_only")
        if action != "read":
            if t == "task" and action == "create" and relation == "mentor_of":
                return ALLOW("mentor_creates_task")
            return DENY("read_only")
        if relation in ("mentor_of", "manager_of"):
            return ALLOW("org_data_default")
        if subject.role == "lead" and resource.team_id == subject.team_id and t in ("task", "checklist_progress", "absence", "access_request_status"):
            return ALLOW("lead_team_view")
        return DENY("not_attached")
    if t == "document":
        if action == "request_access" and resource.space == "global":
            return DENY("global_space_not_granted")
        if resource.access_level == "lead":
            return ALLOW("lead_document") if subject.role == "lead" else DENY("lead_only")
        if resource.access_level == "public":
            return ALLOW("public")
        return ALLOW("team") if resource.team_id in (None, subject.team_id) else DENY("other_team")
    if t == "mentor_page":
        return ALLOW("mentor") if subject.role == "mentor" else DENY("mentor_only")
    return DENY("unknown_resource")


def allowed_access_levels(subject: Subject) -> list[str]:
    return ["public", "team", "lead"] if subject.role == "lead" else ["public", "team"]


async def relation_to(session: AsyncSession, subject: Subject, owner_id: str | None) -> str:
    if owner_id is None:
        return "none"
    if owner_id == subject.id:
        return "self"
    profile = await session.get(InternProfile, owner_id)
    if profile is None:
        return "none"
    if profile.mentor_id == subject.id:
        return "mentor_of"
    if profile.lead_id == subject.id:
        return "manager_of"
    return "none"


async def log_access(session: AsyncSession, subject: Subject, owner_id: str | None, resource: str, action: str, decision: Decision) -> None:
    session.add(AccessLog(viewer_id=subject.id, subject_id=owner_id, resource=resource, action=action,
                          decision="allow" if decision.allow else "deny", reason=decision.reason))


async def authorize(session: AsyncSession, subject: Subject, action: str, resource: Resource) -> Decision:
    relation = await relation_to(session, subject, resource.owner_id)
    decision = decide(subject, relation, action, resource)
    if relation != "self":
        await log_access(session, subject, resource.owner_id, resource.type, action, decision)
    return decision


async def ensure(session: AsyncSession, subject: Subject, action: str, resource: Resource, *, hide: bool = False) -> None:
    """hide=True: при отказе отвечаем 404, чтобы не раскрывать существование ресурса."""
    decision = await authorize(session, subject, action, resource)
    if not decision:
        await session.commit()
        raise not_found() if hide else forbidden()
