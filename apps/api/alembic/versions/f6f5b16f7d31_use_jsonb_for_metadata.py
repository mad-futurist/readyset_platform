"""Use JSONB for flexible metadata on PostgreSQL.

Revision ID: f6f5b16f7d31
Revises: a42f85c9d319
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f6f5b16f7d31"
down_revision: str | None = "a42f85c9d319"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "employee_profiles",
        "profile_metadata",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="profile_metadata::jsonb",
        existing_nullable=False,
    )
    op.alter_column(
        "audit_events",
        "event_metadata",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="event_metadata::jsonb",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_events",
        "event_metadata",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        postgresql_using="event_metadata::json",
        existing_nullable=False,
    )
    op.alter_column(
        "employee_profiles",
        "profile_metadata",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        postgresql_using="profile_metadata::json",
        existing_nullable=False,
    )
