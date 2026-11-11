"""Начальная схема (глава 10 ТЗ).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-11
"""
from alembic import op

from app import models  # noqa: F401
from app.db import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Схема совпадает с моделями SQLAlchemy один к одному; следующие изменения — отдельными ревизиями.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
