"""Журнал достижений: предложения только по выбранным чатам, черновик, экспорт в PDF."""
from __future__ import annotations

import json
from pathlib import Path

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.base import LLMClient, LLMError
from app.models import Chat, JournalEntry, Message


async def suggest(session: AsyncSession, llm: LLMClient, chats: list[Chat]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    transcripts: list[str] = []
    for chat in chats:
        messages = (await session.execute(select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at))).scalars().all()
        for m in messages:
            if m.role == "user":
                transcripts.append(f"[{chat.title}] Стажёр: {m.content}")
            hint = (m.meta or {}).get("hint")
            if m.role == "assistant" and hint and hint not in seen and m.feedback != "no":
                seen.add(hint)
                items.append({"text": hint, "chat_id": chat.id, "chat_title": chat.title})
    if not llm.is_fake and transcripts:
        prompt = [{"role": "system", "content": "Предложи 1–5 записей для журнала достижений стажёра по выбранным чатам. Первое лицо, без "
                                                "выдуманных фактов. Верни JSON {\"items\": [{\"text\": \"...\", \"chat_title\": \"...\"}]}."},
                  {"role": "user", "content": "\n".join(transcripts)[:8000]}]
        try:
            data = json.loads(await llm.complete(prompt, json_mode=True))
            by_title = {c.title: c.id for c in chats}
            llm_items = [{"text": str(i["text"]), "chat_id": by_title.get(i.get("chat_title")), "chat_title": i.get("chat_title")}
                         for i in data.get("items", []) if isinstance(i, dict) and i.get("text")]
            if llm_items:
                items = llm_items
        except (json.JSONDecodeError, LLMError, AttributeError):
            pass
    return items[:5]


def draft_text(name: str, team: str, day: int, total: int, entries: list[JournalEntry]) -> str:
    lines = [e.text.rstrip(".") for e in sorted(entries, key=lambda e: e.created_at)]
    body = "\n".join(f"— {line};" for line in lines)
    if body.endswith(";"):
        body = body[:-1] + "."
    return f"{name}, стажёр команды {team}. День {day} из {total}.\n\nЗа это время я:\n{body}"


def _font_path() -> str | None:
    for candidate in get_settings().pdf_font_paths.split(";"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


TRANSLIT = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
                          "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
                          "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
                          "—": "-", "«": '"', "»": '"', "–": "-", "…": "..."})


def render_pdf(title: str, text: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    font = _font_path()
    if font:
        pdf.add_font("Body", "", font)
        pdf.set_font("Body", size=16)
        convert = lambda s: s
    else:  # без TTF-шрифта кириллица недоступна во встроенных шрифтах — транслитерация
        pdf.set_font("Helvetica", size=16)
        convert = lambda s: "".join(ch.translate(TRANSLIT) if ch.lower() == ch else ch.lower().translate(TRANSLIT).capitalize()
                                    for ch in s).encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, 10, convert(title))
    pdf.ln(4)
    pdf.set_font_size(12)
    pdf.multi_cell(0, 7, convert(text))
    pdf.ln(6)
    pdf.set_font_size(9)
    pdf.multi_cell(0, 5, convert("Черновик из прототипа «Путь стажёра». Тестовые данные, не регламенты Авито."))
    return bytes(pdf.output())
