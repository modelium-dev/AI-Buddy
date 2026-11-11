from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import ApiError
from app.models import InternProfile, User
from app.schemas import LoginIn
from app.security import ROLES, Subject, current_subject, intern_only, issue_token
from app.services.common import intern_context

router = APIRouter(tags=["auth"])

FIRST_ENTRY = ("Здесь можно задавать любые вопросы. Ваши чаты видите только вы. Наставник видит ваш прогресс по чек-листу и статусы задач, "
               "но не ваши вопросы.")


async def _profile(session: AsyncSession, user: User) -> dict:
    data = {"id": user.id, "name": user.name, "role": user.role, "team_id": user.team_id, "title": user.title, "gender": user.gender}
    if user.role == "intern":
        ctx = await intern_context(session, user.id)
        p = ctx.profile
        data["intern"] = {"day": ctx.day, "total_days": ctx.total, "stage": {"id": ctx.stage.id, "label": ctx.stage.label},
                          "mentor_id": p.mentor_id, "lead_id": p.lead_id, "hrbp_id": p.hrbp_id, "program_months": p.program_months,
                          "region": p.region, "repos": p.repos, "jira_projects": p.jira_projects, "learning_budget": p.learning_budget,
                          "is_absent_today": p.is_absent_today}
        data["privacy"] = {"share_topics": p.share_topics, "seen_privacy": p.seen_privacy, "first_entry_text": FIRST_ENTRY}
    return data


@router.get("/auth/users")
async def demo_users(session: AsyncSession = Depends(get_session)) -> list[dict]:
    users = (await session.execute(select(User).where(User.role.in_(ROLES)).order_by(User.role.desc(), User.id))).scalars()
    return [{"id": u.id, "name": u.name, "role": u.role, "title": u.title, "can_login": True} for u in users]


@router.post("/auth/login")
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> dict:
    user = await session.get(User, body.user_id)
    if user is None or user.role not in ROLES:
        raise ApiError(404, "not_found", "Тестовый пользователь не найден")
    return {"access_token": issue_token(user), "token_type": "bearer", "user": await _profile(session, user)}


@router.get("/me")
async def me(subject: Subject = Depends(current_subject), session: AsyncSession = Depends(get_session)) -> dict:
    user = await session.get(User, subject.id)
    return await _profile(session, user)


@router.post("/me/privacy-ack")
async def privacy_ack(subject: Subject = Depends(intern_only), session: AsyncSession = Depends(get_session)) -> dict:
    profile = await session.get(InternProfile, subject.id)
    profile.seen_privacy = True
    await session.commit()
    return {"seen_privacy": True}
