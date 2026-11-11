"""Простая обработка русского текста: токены, грубые основы, стоп-слова."""
from __future__ import annotations

import re

STOPWORDS = {
    "как", "где", "что", "кто", "кого", "кому", "чем", "это", "этот", "эта", "эти", "мне", "меня", "мой", "моя", "мои", "моё", "мою",
    "для", "при", "про", "над", "под", "без", "или", "ли", "не", "нет", "да", "есть", "был", "была", "было", "будет", "нужно",
    "нужен", "нужна", "надо", "можно", "какой", "какая", "какие", "какую", "такое", "такой", "вот", "уже", "ещё", "еще", "все",
    "всё", "его", "её", "их", "она", "они", "оно", "тут", "там", "здесь", "сейчас", "подскажи", "подскажите", "покажи", "расскажи",
    "скажи", "пожалуйста", "привет", "лежит", "находится", "получить", "сделать", "делать", "нам", "вам", "нас", "вас", "так",
    "когда", "почему", "зачем", "the", "and", "for", "with", "что-то", "через", "чтобы", "если", "тоже", "очень",
}

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9][a-zA-Zа-яА-ЯёЁ0-9\-]*")


def tokens(text: str) -> list[str]:
    return [w.lower().replace("ё", "е") for w in _WORD.findall(text or "")]


def stem(word: str) -> str:
    return word[:5] if len(word) > 5 else word


def stems(text: str) -> list[str]:
    return [stem(w) for w in tokens(text) if len(w) >= 3 and w not in STOPWORDS]


def query_stems(text: str) -> list[str]:
    seen: list[str] = []
    for s in stems(text):
        if s not in seen:
            seen.append(s)
    return seen


def short_topic(text: str, words: int = 6) -> str:
    cleaned = re.sub(r"[?!.]+$", "", (text or "").strip())
    parts = cleaned.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def first_sentences(text: str, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: dot + 1] if dot > 80 else cut.rstrip() + "…"
