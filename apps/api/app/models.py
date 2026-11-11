"""Модель данных (глава 10 ТЗ). Массивы хранятся в JSON для переносимости SQLite/PostgreSQL."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, new_id, utcnow


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(16))  # intern | mentor | lead
    team_id: Mapped[str] = mapped_column(String(64), ForeignKey("teams.id"))
    gender: Mapped[str] = mapped_column(String(1), default="m")
    title: Mapped[str] = mapped_column(String(200), default="")


class InternProfile(Base):
    __tablename__ = "intern_profiles"
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    mentor_id: Mapped[str] = mapped_column(String(64))
    lead_id: Mapped[str] = mapped_column(String(64))
    hrbp_id: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[date] = mapped_column(Date)
    program_months: Mapped[int] = mapped_column(Integer, default=6)
    region: Mapped[str] = mapped_column(String(100), default="")
    repos: Mapped[list] = mapped_column(JSON, default=list)
    jira_projects: Mapped[list] = mapped_column(JSON, default=list)
    learning_budget: Mapped[int] = mapped_column(Integer, default=0)
    share_topics: Mapped[bool] = mapped_column(Boolean, default=False)
    is_absent_today: Mapped[bool] = mapped_column(Boolean, default=False)
    day_offset: Mapped[int] = mapped_column(Integer, default=0)
    seen_privacy: Mapped[bool] = mapped_column(Boolean, default=False)


class ChecklistStep(Base):
    __tablename__ = "checklist_steps"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16))
    order: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class InternStep(Base):
    __tablename__ = "intern_steps"
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    step_id: Mapped[str] = mapped_column(String(64), ForeignKey("checklist_steps.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="todo")  # todo | in_progress | done | hidden
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | in_progress | review | done
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Новый чат")
    task_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("tasks.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="guide")  # guide | direct
    include_in_journal: Mapped[bool] = mapped_column(Boolean, default=False)
    unresolved: Mapped[bool] = mapped_column(Boolean, default=False)
    guide_topic: Mapped[str | None] = mapped_column(String(32), nullable=True)
    guide_streak: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(String(64), ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # steps, guide, hint, question, attachments
    feedback: Mapped[str | None] = mapped_column(String(8), nullable=True)  # yes | no
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(String(64), ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(8))  # image | log
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(500))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    person_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200), default="")
    team: Mapped[str] = mapped_column(String(200), default="")
    topics: Mapped[list] = mapped_column(JSON, default=list)
    how_to_ask: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    source_chat_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    source_chat_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    source_chat_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    source_chat_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    include_in_export: Mapped[bool] = mapped_column(Boolean, default=True)
    shared_with_mentor: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PracticeTask(Base):
    __tablename__ = "practice_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topic: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    criterion: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | done
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300))
    system: Mapped[str] = mapped_column(String(64), default="Confluence")
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    team_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_level: Mapped[str] = mapped_column(String(8), default="team")  # public | team | lead
    space: Mapped[str] = mapped_column(String(8), default="team")  # team | global
    sensitivity: Mapped[str] = mapped_column(String(16), default="low")
    topic_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[date] = mapped_column(Date)


class DocChunk(Base):
    __tablename__ = "doc_chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    heading: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    terms: Mapped[list] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)


class AccessFormPreset(Base):
    __tablename__ = "access_form_presets"
    team_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fields: Mapped[list] = mapped_column(JSON, default=list)


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    type: Mapped[str] = mapped_column(String(32))  # access_request | absence_request | doc_conflict_report
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | confirmed | cancelled | failed
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # pending | granted | rejected | sent
    approver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocIssue(Base):
    __tablename__ = "doc_issues"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text, default="")
    reported_by_action_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # task | access | absence | system
    text: Mapped[str] = mapped_column(String(500))
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Digest(Base):
    __tablename__ = "digests"
    intern_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    day: Mapped[date] = mapped_column("date", Date, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    props: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Flag(Base):
    __tablename__ = "flags"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class AccessLog(Base):
    __tablename__ = "access_log"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    viewer_id: Mapped[str] = mapped_column(String(64), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resource: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16), default="read")
    decision: Mapped[str] = mapped_column(String(8))  # allow | deny
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
