"""Цепочка эскалации и брокер знакомств (раздел 7.5 ТЗ)."""
from __future__ import annotations

import json

from app.assistant.text import short_topic
from app.llm.base import LLMClient, LLMError
from app.mcp_client import McpClient, McpError

WEB = {"id": "web", "name": "Внешний источник", "title": "Только общие вещи (праздники, нормы ТК), с пометкой «проверьте у HR»",
       "team": "", "topics": [], "gender": "m", "weekly_limit": 0, "weekly_load": 0}

CHAINS = {
    "cdlc": ["mentor", "manager"],
    "org": ["manager", "hrbp"],
    "infra": ["manager", "hrbp"],
    "other": ["mentor", "manager", "hrbp", "web"],
}

REASONS = {
    "mentor": "Ваш наставник — первый адресат по коду, задачам и процессам команды",
    "manager": "Руководитель: доступы к проектам, отсутствия, техника, цели",
    "hrbp": "HR BP: оформление отсутствий, обучение, документы",
    "owner": "Владелец по CODEOWNERS",
}


async def _relation(mcp: McpClient, intern_id: str, kind: str) -> dict:
    tool = {"mentor": "org.get_mentor", "manager": "org.get_manager", "hrbp": "org.get_hrbp"}[kind]
    return await mcp.call(tool, {"user_id": intern_id})


async def escalation_chain(mcp: McpClient, intern_id: str, group: str, *, no_sources: bool = False) -> list[dict]:
    kinds = CHAINS["other"] if no_sources else CHAINS.get(group, CHAINS["other"])
    chain: list[dict] = []
    for kind in kinds:
        if kind == "web":
            chain.append(dict(WEB))
            continue
        try:
            person = await _relation(mcp, intern_id, kind)
        except McpError:
            continue
        person["relation"] = kind
        if all(p.get("id") != person["id"] for p in chain):
            chain.append(person)
    return chain


async def find_owner(mcp: McpClient, text: str) -> tuple[dict, str] | None:
    try:
        found = await mcp.call("git.find_owner", {"service": text})
        person = await mcp.call("org.get_profile", {"user_id": found["owner_id"]})
    except McpError:
        return None
    return person, found["path"]


def is_overloaded(person: dict) -> bool:
    limit = int(person.get("weekly_limit") or 0)
    return limit > 0 and int(person.get("weekly_load") or 0) >= limit


def pick_available(primary: dict, chain: list[dict]) -> tuple[dict, str | None]:
    """Эксперт перегружен (expert_weekly_limit) → предлагаем следующего по цепочке."""
    if not is_overloaded(primary):
        return primary, None
    for person in chain:
        if person.get("id") not in (primary.get("id"), "web") and not is_overloaded(person):
            return person, f"{primary['name']} на этой неделе загружен, поэтому предлагаю {person['name']}."
    return primary, None


def template_message(person: dict, intern_name: str, female: bool, topic: str, task_title: str | None) -> dict:
    first = person.get("first") or person["name"].split()[0]
    me = intern_name.split()[0]
    checked = "посмотрела" if female else "посмотрел"
    found = "нашла" if female else "нашёл"
    task = f", работаю над задачей «{task_title}»" if task_title else ""
    if person.get("relation") == "mentor":
        text = f"{first}, привет! Разбираюсь с вопросом «{topic}»{task}. В вики и FAQ {checked}, но ответа не {found}. Подскажешь, где посмотреть или к кому обратиться?"
    else:
        text = (f"{first}, добрый день! Я {me}, стажёр в Payments{task}. Разбираюсь с вопросом «{topic}». Документацию {checked}, "
                f"но остался вопрос. Подскажете, где посмотреть, или найдёте 20 минут на этой неделе?")
    return {"message": text, "questions": [], "duration": "обычно 20 минут"}


async def broker_message(llm: LLMClient, person: dict, intern_name: str, female: bool, topic: str, task_title: str | None) -> dict:
    fallback = template_message(person, intern_name, female, topic, task_title)
    if llm.is_fake:
        return fallback
    prompt = [
        {"role": "system", "content": "ROLE: помощник по профессиональной коммуникации. TASK: сформулируй обращение, показывающее, что стажёр уже "
                                      "проверил документы. FORMAT: JSON {\"message\":\"2–3 предложения\",\"questions\":[\"..\"],\"duration\":\"20 минут\"}. "
                                      "Тон уважительный, без извинений за беспокойство."},
        {"role": "user", "content": f"Стажёр {intern_name} обращается к {person['name']} ({person.get('title', '')}) по теме «{topic}». "
                                    f"Задача: {task_title or 'нет'}."},
    ]
    try:
        data = json.loads(await llm.complete(prompt, json_mode=True))
        if isinstance(data.get("message"), str) and data["message"].strip():
            return {"message": data["message"].strip(), "questions": [str(q) for q in data.get("questions", [])][:3],
                    "duration": str(data.get("duration") or "обычно 20 минут")}
    except (json.JSONDecodeError, LLMError, AttributeError):
        pass
    return fallback


def person_card(person: dict, *, reason: str, message: dict, chain: list[dict] | None = None, chain_label: str = "",
                compact: bool = False, note: str | None = None) -> dict:
    return {
        "person_id": person.get("id"), "name": person["name"], "role": person.get("title", ""), "team": person.get("team", ""),
        "handle": person.get("handle", ""), "reason": reason, "how_to_ask": message["message"], "questions": message.get("questions", []),
        "duration": message.get("duration", "обычно 20 минут"), "compact": compact, "note": note,
        "chain": [{"id": p.get("id"), "name": p["name"], "role": p.get("title", "")} for p in (chain or [])],
        "chain_label": chain_label,
    }


def topic_for(text: str) -> str:
    return short_topic(text, 7)
