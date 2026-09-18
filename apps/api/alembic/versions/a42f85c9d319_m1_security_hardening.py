"""M1 security hardening and relational integrity

Revision ID: a42f85c9d319
Revises: d24151675ee0
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a42f85c9d319"
down_revision: str | None = "d24151675ee0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Legacy sessions and OAuth states cannot be bound safely; invalidate rather than guess.
    op.add_column("sessions", sa.Column("auth_identity_id", sa.Uuid(), nullable=True))
    op.execute("DELETE FROM sessions")
    op.create_foreign_key(
        "fk_sessions_auth_identity",
        "sessions",
        "auth_identities",
        ["auth_identity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("sessions", "auth_identity_id", nullable=False)
    op.create_index("ix_sessions_auth_identity_id", "sessions", ["auth_identity_id"])

    op.add_column("oauth_login_states", sa.Column("binding_hash", sa.LargeBinary(32)))
    op.execute("DELETE FROM oauth_login_states")
    op.alter_column("oauth_login_states", "binding_hash", nullable=False)

    # Repair any impossible legacy pointer before installing the stronger same-document FK.
    op.execute(
        """
        UPDATE documents AS d
        SET current_version_id = (
            SELECT dv.id
            FROM document_versions AS dv
            WHERE dv.organization_id = d.organization_id AND dv.document_id = d.id
            ORDER BY dv.version_number DESC, dv.id
            LIMIT 1
        )
        WHERE current_version_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM document_versions AS current
            WHERE current.organization_id = d.organization_id
              AND current.document_id = d.id
              AND current.id = d.current_version_id
          )
        """
    )
    op.drop_constraint("fk_document_current_version", "documents", type_="foreignkey")
    op.create_unique_constraint(
        "uq_document_version_org_document_id",
        "document_versions",
        ["organization_id", "document_id", "id"],
    )
    op.create_foreign_key(
        "fk_document_current_version",
        "documents",
        "document_versions",
        ["organization_id", "id", "current_version_id"],
        ["organization_id", "document_id", "id"],
        ondelete="RESTRICT",
    )

    # Tenant-owned user principals must have a membership row. Membership status remains policy.
    constraints = (
        (
            "fk_employee_membership",
            "employee_profiles",
            ["organization_id", "user_id"],
            "RESTRICT",
        ),
        (
            "fk_document_owner_membership",
            "documents",
            ["organization_id", "owner_user_id"],
            "RESTRICT",
        ),
        (
            "fk_document_version_creator_membership",
            "document_versions",
            ["organization_id", "created_by_user_id"],
            "RESTRICT",
        ),
        (
            "fk_document_user_grant_principal_membership",
            "document_user_grants",
            ["organization_id", "user_id"],
            "CASCADE",
        ),
        (
            "fk_document_user_grant_creator_membership",
            "document_user_grants",
            ["organization_id", "created_by_user_id"],
            "RESTRICT",
        ),
        (
            "fk_document_team_grant_creator_membership",
            "document_team_grants",
            ["organization_id", "created_by_user_id"],
            "RESTRICT",
        ),
        (
            "fk_invitation_inviter_membership",
            "organization_invitations",
            ["organization_id", "invited_by_user_id"],
            "RESTRICT",
        ),
        (
            "fk_invitation_acceptor_membership",
            "organization_invitations",
            ["organization_id", "accepted_by_user_id"],
            "RESTRICT",
        ),
    )
    for name, table, columns, ondelete in constraints:
        op.create_foreign_key(
            name,
            table,
            "organization_memberships",
            columns,
            ["organization_id", "user_id"],
            ondelete=ondelete,
        )

    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY organization_id ORDER BY joined_at, id
            ) AS owner_rank
            FROM organization_memberships
            WHERE role = 'OWNER' AND status = 'ACTIVE'
        )
        UPDATE organization_memberships AS membership
        SET role = 'ADMIN'
        FROM ranked
        WHERE membership.id = ranked.id AND ranked.owner_rank > 1
        """
    )
    op.create_index(
        "uq_active_owner_per_organization",
        "organization_memberships",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("role = 'OWNER' AND status = 'ACTIVE'"),
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY organization_id, normalized_email ORDER BY created_at DESC, id DESC
            ) AS invitation_rank
            FROM organization_invitations
            WHERE status = 'PENDING'
        )
        UPDATE organization_invitations AS invitation
        SET status = 'REVOKED'
        FROM ranked
        WHERE invitation.id = ranked.id AND ranked.invitation_rank > 1
        """
    )
    op.create_index(
        "uq_pending_invitation_org_email",
        "organization_invitations",
        ["organization_id", "normalized_email"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_pending_invitation_org_email", table_name="organization_invitations")
    op.drop_index("uq_active_owner_per_organization", table_name="organization_memberships")
    for name, table in (
        ("fk_invitation_acceptor_membership", "organization_invitations"),
        ("fk_invitation_inviter_membership", "organization_invitations"),
        ("fk_document_team_grant_creator_membership", "document_team_grants"),
        ("fk_document_user_grant_creator_membership", "document_user_grants"),
        ("fk_document_user_grant_principal_membership", "document_user_grants"),
        ("fk_document_version_creator_membership", "document_versions"),
        ("fk_document_owner_membership", "documents"),
        ("fk_employee_membership", "employee_profiles"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")
    op.drop_constraint("fk_document_current_version", "documents", type_="foreignkey")
    op.drop_constraint("uq_document_version_org_document_id", "document_versions", type_="unique")
    op.create_foreign_key(
        "fk_document_current_version",
        "documents",
        "document_versions",
        ["organization_id", "current_version_id"],
        ["organization_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_column("oauth_login_states", "binding_hash")
    op.drop_index("ix_sessions_auth_identity_id", table_name="sessions")
    op.drop_constraint("fk_sessions_auth_identity", "sessions", type_="foreignkey")
    op.drop_column("sessions", "auth_identity_id")
