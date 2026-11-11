"""Мок-авторизация: JWT с claim-ами sub, role, team (как в корпоративных системах)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session, utcnow
from app.errors import ApiError, forbidden
from app.models import User

ROLES = ("intern", "mentor", "lead")


@dataclass(frozen=True)
class Subject:
    id: str
    role: str
    team_id: str
    name: str
    gender: str = "m"

    @property
    def is_female(self) -> bool:
        return self.gender == "f"


def issue_token(user: User) -> str:
    s = get_settings()
    payload = {"sub": user.id, "role": user.role, "team": user.team_id, "exp": utcnow() + timedelta(hours=s.jwt_ttl_hours)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ApiError(401, "unauthorized", "Токен недействителен или истёк") from exc


async def current_subject(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Subject:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized", "Нужен заголовок Authorization: Bearer <token>")
    claims = decode_token(authorization.split(" ", 1)[1].strip())
    user = await session.get(User, claims.get("sub"))
    if user is None or user.role not in ROLES:
        raise ApiError(401, "unauthorized", "Пользователь не найден")
    return Subject(id=user.id, role=user.role, team_id=user.team_id, name=user.name, gender=user.gender)


def require_role(*roles: str):
    async def _dep(subject: Subject = Depends(current_subject)) -> Subject:
        if subject.role not in roles:
            raise forbidden("Раздел недоступен для вашей роли")
        return subject

    return _dep


intern_only = require_role("intern")
mentor_only = require_role("mentor")
