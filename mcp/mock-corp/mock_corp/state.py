"""Состояние имитаций в памяти. Сбрасывается инструментом admin.reset."""
from __future__ import annotations

import copy
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def seed_dir() -> Path:
    return Path(os.environ.get("SEED_DIR", str(REPO_ROOT / "seed")))


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _next_weekday(start: date, weekday: int) -> date:
    days = (weekday - start.weekday()) % 7 or 7
    return start + timedelta(days=days)


PEOPLE = {
    "boris": {"id": "boris", "name": "Борис Н.", "first": "Борис", "title": "Наставник", "team": "Payments", "handle": "@boris.n",
              "topics": ["Первая задача", "Код-ревью", "Процессы команды"], "gender": "m", "weekly_limit": 10, "weekly_load": 3, "region": "Москва"},
    "maria": {"id": "maria", "name": "Мария К.", "first": "Мария", "title": "Тимлид Payments", "team": "Payments", "handle": "@maria.k",
              "topics": ["Доступы к проектам", "Отгулы и отпуск", "Цели стажировки"], "gender": "f", "weekly_limit": 6, "weekly_load": 2, "region": "Москва"},
    "igor": {"id": "igor", "name": "Игорь Л.", "first": "Игорь", "title": "Владелец сервиса Billing", "team": "Billing", "handle": "@igor.l",
             "topics": ["Billing", "Платёжный шлюз", "Ревью кода Billing"], "gender": "m", "weekly_limit": 3, "weekly_load": 1, "region": "Москва"},
    "oleg": {"id": "oleg", "name": "Олег Р.", "first": "Олег", "title": "DevOps, тестовые стенды", "team": "Platform", "handle": "@oleg.r",
             "topics": ["Тестовые стенды", "CI/CD", "Деплой и секреты"], "gender": "m", "weekly_limit": 4, "weekly_load": 2, "region": "Москва"},
    "sveta": {"id": "sveta", "name": "Света М.", "first": "Света", "title": "HR BP", "team": "HR", "handle": "@sveta.m",
              "topics": ["Отпуск и отгулы", "Бюджет на обучение", "Документы и ПДн"], "gender": "f", "weekly_limit": 20, "weekly_load": 5, "region": "Москва"},
    "anya": {"id": "anya", "name": "Аня Соколова", "first": "Аня", "title": "Стажёр", "team": "Payments", "handle": "@anya.s",
             "topics": [], "gender": "f", "weekly_limit": 0, "weekly_load": 0, "region": "Москва"},
    "dima": {"id": "dima", "name": "Дима Орлов", "first": "Дима", "title": "Стажёр", "team": "Payments", "handle": "@dima.o",
             "topics": [], "gender": "m", "weekly_limit": 0, "weekly_load": 0, "region": "Казань"},
}

RELATIONS = {
    "anya": {"mentor": "boris", "manager": "maria", "hrbp": "sveta"},
    "dima": {"mentor": "boris", "manager": "maria", "hrbp": "sveta"},
}

CODEOWNERS = {
    "billing-service": [
        {"path": "/services/billing/", "owner": "igor"},
        {"path": "/infra/stands/", "owner": "oleg"},
        {"path": "/docs/", "owner": "maria"},
    ]
}

SERVICE_ALIASES = {
    "billing": "/services/billing/", "биллинг": "/services/billing/", "платеж": "/services/billing/", "платёж": "/services/billing/",
    "оплат": "/services/billing/", "стенд": "/infra/stands/", "stand": "/infra/stands/", "ci": "/infra/stands/", "деплой": "/infra/stands/",
    "пайплайн": "/infra/stands/", "docs": "/docs/", "документац": "/docs/",
}

ACCESS_PRESETS = {
    "payments": {
        "fields": [
            {"key": "project_key", "label": "Ключ проекта Jira", "type": "string", "required": True, "hint": "Например, PAY"},
            {"key": "justification", "label": "Обоснование", "type": "text", "required": True, "hint": "Для какой задачи нужен доступ"},
            {"key": "level", "label": "Уровень доступа", "type": "enum", "required": True, "options": ["read", "write", "administration"],
             "hint": "Минимально достаточный — read"},
            {"key": "space_or_page", "label": "Страница или пространство Confluence", "type": "string", "required": False, "hint": ""},
            {"key": "watch_issue_types", "label": "Наблюдение за задачами", "type": "list", "required": False, "hint": "Типы задач"},
            {"key": "cost_center", "label": "Центр затрат", "type": "string", "required": True, "hint": "Кастомное поле команды Payments"},
        ],
        "defaults": {"project_key": "PAY", "level": "read", "space_or_page": "Payments / Платёжный модуль",
                     "watch_issue_types": ["Bug", "Story"], "cost_center": "CC-PAY-01"},
        "projects": {"PAY": {"owner": "maria"}, "PLATFORM": {"owner": "oleg"}},
    }
}


def _load_wiki() -> dict[str, dict]:
    pages: dict[str, dict] = {}
    wiki = seed_dir() / "wiki"
    if not wiki.exists():
        return pages
    for path in sorted(wiki.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta: dict = {}
        body = raw
        if raw.startswith("---"):
            _, front, body = raw.split("---", 2)
            meta = yaml.safe_load(front) or {}
        meta.setdefault("id", path.stem)
        meta["body"] = body.strip()
        meta["updated_at"] = str(meta.get("updated_at", ""))
        pages[meta["id"]] = meta
    return pages


def _initial() -> dict:
    t = _today()
    friday = _next_weekday(t, 4)
    tasks = {
        "PAY-214": {"id": "PAY-214", "intern_id": "anya", "title": "Платёжный модуль", "status": "in_progress",
                    "deadline": friday.isoformat(), "created_by": "boris", "created_at": (t - timedelta(days=8)).isoformat(),
                    "description": "Добавить в сервис Billing обработку статуса платежа «возврат» (refund). Статус приходит из тестового платёжного "
                                   "шлюза, сохраняется в истории платежа и отдаётся в API /payments/{id}.\n\nПокрыть тестами, открыть pull request в dev. "
                                   "Ревью — по CODEOWNERS."},
        "PAY-221": {"id": "PAY-221", "intern_id": "anya", "title": "Гайд по ревью", "status": "new",
                    "deadline": (t + timedelta(days=10)).isoformat(), "created_by": "boris", "created_at": t.isoformat(),
                    "description": "Прочитать «Правила код-ревью» и собрать памятку для стажёров: что проверить перед тем, как звать ревьюера. "
                                   "Одна страница в Confluence, пространство Payments."},
        "PAY-198": {"id": "PAY-198", "intern_id": "anya", "title": "Настроить окружение", "status": "done",
                    "deadline": (t - timedelta(days=8)).isoformat(), "created_by": "boris", "created_at": (t - timedelta(days=11)).isoformat(),
                    "description": "Собрать billing-service локально, запустить тесты, получить доступ к Bitbucket."},
    }
    return {
        "people": copy.deepcopy(PEOPLE),
        "tasks": tasks,
        "tracker_version": 1,
        "task_counter": 230,
        "access_requests": {},
        "access_counter": 1041,
        "absence_requests": {},
        "absence_counter": 300,
        "absence_balance": {"anya": 12, "dima": 14},
        "wiki": _load_wiki(),
    }


STATE: dict = _initial()


def reset() -> None:
    STATE.clear()
    STATE.update(_initial())
