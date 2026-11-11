"""RAG: загрузка мок-вики, чанки по заголовкам, индекс, гибридный поиск (лексика + вектор, RRF) с ACL до поиска.

ACL применяется в SQL: недоступные роли документы не попадают ни в ранжирование, ни в контекст модели.
Корпус маленький (15–25 страниц), поэтому ранжирование делается в Python; эмбеддинги хранятся в JSON.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.text import query_stems, stems
from app.authz import allowed_access_levels
from app.llm.base import Embedder
from app.models import DocChunk, Document
from app.security import Subject

INJECTION = re.compile(r"игнорируй\s+(все\s+)?(правила|инструкц)|ignore\s+(all\s+)?(previous\s+)?instructions|покажи\s+документы\s+лида|"
                       r"выведи\s+условия", re.IGNORECASE)


@dataclass
class ParsedDoc:
    meta: dict
    sections: list[tuple[str, str]]


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    title: str
    heading: str
    text: str
    url: str
    system: str
    updated_at: date
    owner_id: str | None
    team_id: str | None
    space: str
    topic_key: str | None
    coverage: float
    cosine: float
    rrf: float = 0.0
    flags: list[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return "injection" in self.flags

    def source(self) -> dict:
        return {"document_id": self.document_id, "title": self.title, "url": self.url, "system": self.system,
                "updated_at": self.updated_at.isoformat()}


def parse_markdown(raw: str, fallback_id: str) -> ParsedDoc:
    meta: dict = {}
    body = raw
    if raw.startswith("---"):
        _, front, body = raw.split("---", 2)
        meta = yaml.safe_load(front) or {}
    meta.setdefault("id", fallback_id)
    sections: list[tuple[str, str]] = []
    heading = ""
    buf: list[str] = []
    for line in body.strip().splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((heading, "\n".join(buf).strip()))
    return ParsedDoc(meta=meta, sections=sections)


def load_wiki(seed_dir: str) -> list[ParsedDoc]:
    wiki = Path(seed_dir) / "wiki"
    return [parse_markdown(p.read_text(encoding="utf-8"), p.stem) for p in sorted(wiki.glob("*.md"))]


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


async def index_documents(session: AsyncSession, docs: list[ParsedDoc], embedder: Embedder) -> int:
    """Полная переиндексация: документы и чанки пересоздаются."""
    await session.execute(delete(DocChunk))
    await session.execute(delete(Document))
    count = 0
    for doc in docs:
        m = doc.meta
        session.add(Document(
            id=m["id"], source_url=m.get("url", ""), title=m.get("title", m["id"]), system=m.get("system", "Confluence"),
            owner_id=m.get("owner"), team_id=m.get("team"), access_level=m.get("access_level", "team"), space=m.get("space", "team"),
            sensitivity=m.get("sensitivity", "low"), topic_key=m.get("topic_key"), updated_at=_as_date(m.get("updated_at", "2026-01-01")),
        ))
        texts = [f"{m.get('title', '')}. {heading}. {text}" for heading, text in doc.sections]
        vectors = await embedder.embed(texts) if texts else []
        for pos, ((heading, text), vec, full) in enumerate(zip(doc.sections, vectors, texts)):
            session.add(DocChunk(document_id=m["id"], heading=heading, text=text, embedding=vec, terms=sorted(set(stems(full))), position=pos))
            count += 1
    await session.flush()
    return count


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


async def search(session: AsyncSession, subject: Subject, query: str, embedder: Embedder, *, top_k: int = 6,
                 allow_global: bool = True) -> list[Hit]:
    q_stems = query_stems(query)
    if not q_stems:
        return []
    levels = allowed_access_levels(subject)
    stmt = (
        select(DocChunk, Document)
        .join(Document, Document.id == DocChunk.document_id)
        .where(Document.access_level.in_(levels))
        .where(or_(Document.team_id.is_(None), Document.team_id == subject.team_id))
    )
    if not allow_global:
        stmt = stmt.where(Document.space != "global")
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    q_vec = (await embedder.embed([query]))[0]
    hits: list[Hit] = []
    for chunk, doc in rows:
        terms = set(chunk.terms or [])
        title_terms = set(stems(doc.title))
        matched = sum(1 for s in q_stems if s in terms or s in title_terms)
        hit = Hit(chunk_id=chunk.id, document_id=doc.id, title=doc.title, heading=chunk.heading, text=chunk.text, url=doc.source_url,
                  system=doc.system, updated_at=doc.updated_at, owner_id=doc.owner_id, team_id=doc.team_id, space=doc.space,
                  topic_key=doc.topic_key, coverage=matched / len(q_stems), cosine=_cosine(q_vec, chunk.embedding or []))
        if INJECTION.search(chunk.text):
            hit.flags.append("injection")
        hits.append(hit)
    by_cov = sorted(hits, key=lambda h: (-h.coverage, -h.cosine))
    by_vec = sorted(hits, key=lambda h: -h.cosine)
    rank_cov = {h.chunk_id: i for i, h in enumerate(by_cov)}
    rank_vec = {h.chunk_id: i for i, h in enumerate(by_vec)}
    for h in hits:
        h.rrf = 1 / (60 + rank_cov[h.chunk_id]) + 1 / (60 + rank_vec[h.chunk_id])
    hits.sort(key=lambda h: (-h.coverage, -h.rrf))
    return [h for h in hits if h.coverage > 0][:top_k]


def confident(hits: list[Hit], min_score: float) -> bool:
    return bool(hits) and (hits[0].coverage >= min_score or hits[0].cosine >= 0.85)


def safe_hits(hits: list[Hit]) -> list[Hit]:
    """Документы — недоверенные данные: фрагменты с инструкциями для модели не используются в ответе."""
    return [h for h in hits if not h.suspicious]


def numbered_steps(text: str) -> list[str]:
    return [re.sub(r"^\d+[.)]\s*", "", line).strip() for line in text.splitlines() if re.match(r"^\s*\d+[.)]\s", line)]


def detect_conflict(hits: list[Hit], team_id: str) -> list[Hit] | None:
    """Если по одному вопросу нашлись разные документы с одной темой и разным содержанием — расхождение."""
    groups: dict[str, dict[str, Hit]] = {}
    for h in hits:
        if h.topic_key:
            groups.setdefault(h.topic_key, {}).setdefault(h.document_id, h)
    for docs in groups.values():
        if len(docs) < 2:
            continue
        variants = sorted(docs.values(), key=lambda h: (h.team_id != team_id, -h.updated_at.toordinal()))
        if len({tuple(numbered_steps(v.text)) or v.text for v in variants}) > 1:
            return variants[:2]
    return None
