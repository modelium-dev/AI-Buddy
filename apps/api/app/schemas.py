"""Тела запросов (Pydantic v2). Ответы описаны в API.md и OpenAPI (/docs)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    user_id: str = Field(examples=["anya"])


class StepPatch(BaseModel):
    status: Literal["todo", "in_progress", "done", "hidden"]


class PracticePatch(BaseModel):
    status: Literal["open", "done"]


class ChatCreate(BaseModel):
    task_id: str | None = None
    title: str | None = Field(default=None, max_length=200)


class ChatPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    include_in_journal: bool | None = None
    mode: Literal["guide", "direct"] | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["guide", "direct"] = "guide"
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


class FeedbackIn(BaseModel):
    helpful: bool


class ActionPatch(BaseModel):
    project_key: str | None = None
    justification: str | None = Field(default=None, max_length=2000)
    level: str | None = None
    space_or_page: str | None = None
    watch_issue_types: list[str] | None = None
    cost_center: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    kind: str | None = None
    reason: str | None = None
    text: str | None = Field(default=None, max_length=4000)


class ContactIn(BaseModel):
    person_id: str | None = None
    name: str | None = Field(default=None, max_length=200)
    role: str = Field(default="", max_length=200)
    team: str = Field(default="", max_length=200)
    topics: list[str] = Field(default_factory=list)
    how_to_ask: str = Field(default="", max_length=2000)
    note: str = Field(default="", max_length=2000)
    source_chat_id: str | None = None


class ContactPatch(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=200)
    topics: list[str] | None = None
    how_to_ask: str | None = Field(default=None, max_length=2000)


class JournalSuggestIn(BaseModel):
    chat_ids: list[str] = Field(min_length=1, max_length=50)


class JournalItemIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    source_chat_id: str | None = None


class JournalCreate(BaseModel):
    entries: list[JournalItemIn] = Field(min_length=1, max_length=20)


class JournalPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    include_in_export: bool | None = None
    shared_with_mentor: bool | None = None


class JournalDraftIn(BaseModel):
    entry_ids: list[str] = Field(default_factory=list)


class JournalExportIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    title: str = "Журнал достижений"


class PrivacySettings(BaseModel):
    share_topics: bool


class MentorTaskIn(BaseModel):
    intern_id: str
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    deadline: date | None = None


class EventIn(BaseModel):
    name: str
    props: dict = Field(default_factory=dict)


class DevTaskUpdate(BaseModel):
    task_id: str
    status: Literal["new", "in_progress", "review", "done"] | None = None
    deadline: date | None = None
    description: str | None = None
    shift_days: int | None = None


class DevDecision(BaseModel):
    action_id: str
    reason: str | None = None


class DevDays(BaseModel):
    days: int = 1
    intern_id: str = "anya"


class DevFlag(BaseModel):
    enabled: bool = True
