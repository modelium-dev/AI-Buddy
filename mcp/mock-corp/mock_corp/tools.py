"""Инструменты mock-corp. Каждый принимает аргументы и контекст пользователя (id, role).

Ошибки типизированы: forbidden | not_found | invalid_input.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from mock_corp import state as st

S = st.STATE


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _person(pid: str) -> dict:
    p = S["people"].get(pid)
    if p is None:
        raise ToolError("not_found", f"Сотрудник {pid} не найден")
    return dict(p)


def _require(args: dict, *keys: str) -> None:
    missing = [k for k in keys if args.get(k) in (None, "")]
    if missing:
        raise ToolError("invalid_input", "Не хватает полей: " + ", ".join(missing))


def _page_visible(page: dict, role: str) -> bool:
    return page.get("access_level") != "lead" or role == "lead"


def _public_page(page: dict) -> dict:
    return {k: page.get(k) for k in ("id", "title", "url", "system", "owner", "team", "access_level", "space", "updated_at", "topic_key")}


# ---------- wiki ----------
def wiki_search_pages(args: dict, user: dict) -> dict:
    _require(args, "query")
    words = [w for w in re.findall(r"\w+", str(args["query"]).lower()) if len(w) > 3]
    role = args.get("role") or user.get("role", "intern")
    found = []
    for page in S["wiki"].values():
        if not _page_visible(page, role):
            continue
        text = (page.get("title", "") + " " + page.get("body", "")).lower()
        score = sum(1 for w in words if w[:5] in text)
        if score:
            found.append({**_public_page(page), "score": score})
    found.sort(key=lambda p: -p["score"])
    return {"pages": found[:10]}


def wiki_get_page(args: dict, user: dict) -> dict:
    _require(args, "id")
    page = S["wiki"].get(args["id"])
    role = args.get("role") or user.get("role", "intern")
    if page is None or not _page_visible(page, role):
        raise ToolError("not_found", "Страница не найдена")  # существование закрытых страниц не раскрываем
    return {**_public_page(page), "body": page["body"]}


# ---------- tracker ----------
def tracker_list_tasks(args: dict, user: dict) -> dict:
    intern_id = args.get("intern_id")
    tasks = [dict(t) for t in S["tasks"].values() if not intern_id or t["intern_id"] == intern_id]
    return {"tasks": tasks, "version": S["tracker_version"]}


def tracker_get_task(args: dict, user: dict) -> dict:
    _require(args, "id")
    task = S["tasks"].get(args["id"])
    if task is None:
        raise ToolError("not_found", "Задача не найдена")
    return dict(task)


def tracker_create_task(args: dict, user: dict) -> dict:
    if user.get("role") not in ("mentor", "lead", "system"):
        raise ToolError("forbidden", "Создавать задачи могут наставник или лид")
    _require(args, "intern_id", "title")
    if args["intern_id"] not in st.RELATIONS:
        raise ToolError("not_found", "Стажёр не найден")
    S["task_counter"] += 1
    task_id = f"PAY-{S['task_counter']}"
    S["tasks"][task_id] = {
        "id": task_id, "intern_id": args["intern_id"], "title": str(args["title"])[:300], "status": "new",
        "deadline": args.get("deadline"), "created_by": args.get("created_by") or user.get("id", "boris"),
        "created_at": _now()[:10], "description": str(args.get("description") or ""),
    }
    S["tracker_version"] += 1
    return dict(S["tasks"][task_id])


def tracker_update_task(args: dict, user: dict) -> dict:
    if user.get("role") not in ("mentor", "lead", "system"):
        raise ToolError("forbidden", "Менять задачи могут наставник или лид")
    _require(args, "id")
    task = S["tasks"].get(args["id"])
    if task is None:
        raise ToolError("not_found", "Задача не найдена")
    if args.get("status") is not None:
        if args["status"] not in ("new", "in_progress", "review", "done"):
            raise ToolError("invalid_input", "Неизвестный статус")
        task["status"] = args["status"]
    for key in ("deadline", "description", "title"):
        if args.get(key) is not None:
            task[key] = args[key]
    S["tracker_version"] += 1
    return dict(task)


# ---------- git ----------
def git_get_codeowners(args: dict, user: dict) -> dict:
    repo = args.get("repo") or "billing-service"
    return {"repo": repo, "entries": list(st.CODEOWNERS.get(repo, []))}


def _resolve_path(args: dict) -> str | None:
    if args.get("path"):
        return str(args["path"])
    service = str(args.get("service") or "").lower()
    for alias, path in st.SERVICE_ALIASES.items():
        if alias in service:
            return path
    return None


def git_find_owner(args: dict, user: dict) -> dict:
    path = _resolve_path(args)
    if path is None:
        raise ToolError("not_found", "Владелец не найден")
    for entry in st.CODEOWNERS["billing-service"]:
        if path.startswith(entry["path"]):
            return {"path": entry["path"], "owner_id": entry["owner"], "source": "CODEOWNERS · billing-service"}
    raise ToolError("not_found", "Владелец не найден")


def git_list_reviewers(args: dict, user: dict) -> dict:
    owner = git_find_owner(args, user)
    return {"path": owner["path"], "reviewers": [owner["owner_id"]]}


# ---------- access ----------
def access_get_options(args: dict, user: dict) -> dict:
    team = args.get("team") or "payments"
    preset = st.ACCESS_PRESETS.get(team)
    if preset is None:
        raise ToolError("not_found", "Пресет команды не найден")
    return {"team": team, "fields": preset["fields"], "defaults": preset["defaults"], "levels": ["read", "write", "administration"]}


def access_suggest_approver(args: dict, user: dict) -> dict:
    """Правила: документ → автор/тимлид; Jira-проект → владелец проекта; страница → владелец; пространство → владелец;
    глобальное пространство → не выдаётся."""
    kind = args.get("resource_type", "jira_project")
    key = str(args.get("key") or "").upper()
    if kind == "global_space":
        raise ToolError("forbidden", "К общему глобальному пространству доступ не выдаётся")
    if kind == "jira_project":
        project = st.ACCESS_PRESETS["payments"]["projects"].get(key)
        if project is None:
            raise ToolError("not_found", "Проект не найден")
        return {"approver_id": project["owner"], "rule": "jira_project_owner"}
    if kind in ("confluence_page", "confluence_space", "document"):
        return {"approver_id": "maria", "rule": f"{kind}_owner"}
    return {"approver_id": None, "rule": "request_system"}


def access_create_request(args: dict, user: dict) -> dict:
    payload = args.get("payload") or {}
    if str(payload.get("space_or_page", "")).lower() in ("global", "общее", "общее пространство"):
        raise ToolError("forbidden", "К общему глобальному пространству доступ не выдаётся")
    if not payload.get("project_key"):
        raise ToolError("invalid_input", "Не указан проект")
    approver = access_suggest_approver({"resource_type": "jira_project", "key": payload["project_key"]}, user)
    S["access_counter"] += 1
    number = f"ACC-{S['access_counter']}"
    S["access_requests"][number] = {"number": number, "requester": user.get("id"), "payload": payload, "status": "pending",
                                    "approver_id": approver["approver_id"], "created_at": _now(), "reason": None}
    return dict(S["access_requests"][number])


def access_get_request(args: dict, user: dict) -> dict:
    _require(args, "number")
    req = S["access_requests"].get(args["number"])
    if req is None:
        raise ToolError("not_found", "Заявка не найдена")
    return dict(req)


def access_decide(args: dict, user: dict) -> dict:
    """Решение согласующего (вызывается только dev-панелью)."""
    _require(args, "number", "decision")
    req = S["access_requests"].get(args["number"])
    if req is None:
        raise ToolError("not_found", "Заявка не найдена")
    if args["decision"] not in ("granted", "rejected"):
        raise ToolError("invalid_input", "decision: granted | rejected")
    req["status"] = args["decision"]
    req["reason"] = args.get("reason")
    return dict(req)


# ---------- absence ----------
def absence_get_balance(args: dict, user: dict) -> dict:
    uid = args.get("user_id") or user.get("id")
    return {"user_id": uid, "days_left": S["absence_balance"].get(uid, 0), "note": "Тестовые данные. Нормы уточняйте по ТК РФ у HR."}


def absence_create_request(args: dict, user: dict) -> dict:
    _require(args, "date_from")
    uid = user.get("id")
    rel = st.RELATIONS.get(uid)
    if rel is None:
        raise ToolError("forbidden", "Заявку на отсутствие подаёт сам сотрудник")
    S["absence_counter"] += 1
    number = f"ABS-{S['absence_counter']}"
    S["absence_requests"][number] = {"number": number, "user_id": uid, "date_from": args["date_from"], "date_to": args.get("date_to") or args["date_from"],
                                     "kind": args.get("kind", "day_off"), "status": "pending", "approvers": [rel["manager"], rel["hrbp"]]}
    return dict(S["absence_requests"][number])


def absence_get_request(args: dict, user: dict) -> dict:
    _require(args, "number")
    req = S["absence_requests"].get(args["number"])
    if req is None:
        raise ToolError("not_found", "Заявка не найдена")
    return dict(req)


# ---------- org ----------
def org_get_profile(args: dict, user: dict) -> dict:
    _require(args, "user_id")
    return _person(args["user_id"])


def _relation(args: dict, kind: str) -> dict:
    _require(args, "user_id")
    rel = st.RELATIONS.get(args["user_id"])
    if rel is None:
        raise ToolError("not_found", "Связи сотрудника не найдены")
    return _person(rel[kind])


def org_get_manager(args: dict, user: dict) -> dict:
    return _relation(args, "manager")


def org_get_hrbp(args: dict, user: dict) -> dict:
    return _relation(args, "hrbp")


def org_get_mentor(args: dict, user: dict) -> dict:
    return _relation(args, "mentor")


def admin_reset(args: dict, user: dict) -> dict:
    st.reset()
    return {"ok": True}


def _schema(props: dict[str, str], required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": required or []}


TOOLS: dict[str, tuple[Callable[[dict, dict], dict], str, dict]] = {
    "wiki.search_pages": (wiki_search_pages, "Поиск страниц вики с учётом роли", _schema({"query": "string", "role": "string"}, ["query"])),
    "wiki.get_page": (wiki_get_page, "Страница вики (закрытые для роли — not_found)", _schema({"id": "string", "role": "string"}, ["id"])),
    "tracker.list_tasks": (tracker_list_tasks, "Задачи стажёра и версия трекера", _schema({"intern_id": "string"})),
    "tracker.get_task": (tracker_get_task, "Задача по ключу", _schema({"id": "string"}, ["id"])),
    "tracker.create_task": (tracker_create_task, "Создать задачу (наставник)",
                            _schema({"intern_id": "string", "title": "string", "description": "string", "deadline": "string", "created_by": "string"},
                                    ["intern_id", "title"])),
    "tracker.update_task": (tracker_update_task, "Изменить статус, срок или описание",
                            _schema({"id": "string", "status": "string", "deadline": "string", "description": "string", "title": "string"}, ["id"])),
    "git.get_codeowners": (git_get_codeowners, "CODEOWNERS репозитория", _schema({"repo": "string"})),
    "git.find_owner": (git_find_owner, "Владелец пути или сервиса", _schema({"path": "string", "service": "string"})),
    "git.list_reviewers": (git_list_reviewers, "Ревьюеры для пути", _schema({"path": "string", "service": "string"})),
    "access.get_options": (access_get_options, "Пресет полей заявки команды", _schema({"team": "string"})),
    "access.suggest_approver": (access_suggest_approver, "Кто согласует ресурс", _schema({"resource_type": "string", "key": "string"})),
    "access.create_request": (access_create_request, "Создать заявку на доступ (только после подтверждения человеком)",
                              _schema({"payload": "object"}, ["payload"])),
    "access.get_request": (access_get_request, "Статус заявки", _schema({"number": "string"}, ["number"])),
    "access.decide": (access_decide, "Решение согласующего (dev)", _schema({"number": "string", "decision": "string", "reason": "string"},
                                                                          ["number", "decision"])),
    "absence.get_balance": (absence_get_balance, "Остаток дней отсутствия", _schema({"user_id": "string"})),
    "absence.create_request": (absence_create_request, "Заявка на отгул (только после подтверждения)",
                               _schema({"date_from": "string", "date_to": "string", "kind": "string"}, ["date_from"])),
    "absence.get_request": (absence_get_request, "Статус заявки на отсутствие", _schema({"number": "string"}, ["number"])),
    "org.get_profile": (org_get_profile, "Профиль сотрудника", _schema({"user_id": "string"}, ["user_id"])),
    "org.get_manager": (org_get_manager, "Руководитель сотрудника", _schema({"user_id": "string"}, ["user_id"])),
    "org.get_hrbp": (org_get_hrbp, "HR BP сотрудника", _schema({"user_id": "string"}, ["user_id"])),
    "org.get_mentor": (org_get_mentor, "Наставник стажёра", _schema({"user_id": "string"}, ["user_id"])),
    "admin.reset": (admin_reset, "Сбросить демо-данные", _schema({})),
}


def list_tools() -> list[dict[str, Any]]:
    return [{"name": name, "description": desc, "inputSchema": schema} for name, (_, desc, schema) in TOOLS.items()]


def call_tool(name: str, args: dict | None, user: dict | None) -> dict:
    if name not in TOOLS:
        raise ToolError("not_found", f"Инструмент {name} не найден")
    return TOOLS[name][0](args or {}, user or {})
