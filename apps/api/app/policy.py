import enum
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select

from app.models import (
    Document,
    DocumentTeamGrant,
    DocumentUserGrant,
    DocumentVisibility,
    EmployeeProfile,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    TeamMembership,
    User,
)


class Capability(str, enum.Enum):
    MANAGE_ORGANIZATION = "manage_organization"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_PEOPLE = "manage_people"
    UPLOAD_DOCUMENTS = "upload_documents"
    MANAGE_ALL_DOCUMENTS = "manage_all_documents"
    VIEW_AUDIT = "view_audit"


ROLE_CAPABILITIES: dict[OrganizationRole, frozenset[Capability]] = {
    OrganizationRole.OWNER: frozenset(Capability),
    OrganizationRole.ADMIN: frozenset(Capability),
    OrganizationRole.MANAGER: frozenset({Capability.MANAGE_PEOPLE, Capability.UPLOAD_DOCUMENTS}),
    OrganizationRole.MEMBER: frozenset({Capability.UPLOAD_DOCUMENTS}),
}


@dataclass(frozen=True)
class AuthenticatedUser:
    user: User
    session_id: uuid.UUID
    auth_identity_id: uuid.UUID


@dataclass(frozen=True)
class OrganizationContext:
    user: User
    organization: Organization
    membership: OrganizationMembership

    @property
    def capabilities(self) -> frozenset[Capability]:
        return ROLE_CAPABILITIES[self.membership.role]


def require_capability(context: OrganizationContext, capability: Capability) -> None:
    if capability not in context.capabilities:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")


def document_access_predicate(context: OrganizationContext):  # type: ignore[no-untyped-def]
    if context.membership.role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}:
        return Document.organization_id == context.organization.id
    explicit_user = exists(
        select(DocumentUserGrant.id).where(
            DocumentUserGrant.organization_id == context.organization.id,
            DocumentUserGrant.document_id == Document.id,
            DocumentUserGrant.user_id == context.user.id,
        )
    )
    team_access = exists(
        select(DocumentTeamGrant.id)
        .join(
            TeamMembership,
            and_(
                TeamMembership.organization_id == DocumentTeamGrant.organization_id,
                TeamMembership.team_id == DocumentTeamGrant.team_id,
            ),
        )
        .join(
            EmployeeProfile,
            and_(
                EmployeeProfile.organization_id == TeamMembership.organization_id,
                EmployeeProfile.id == TeamMembership.employee_profile_id,
            ),
        )
        .where(
            DocumentTeamGrant.organization_id == context.organization.id,
            DocumentTeamGrant.document_id == Document.id,
            EmployeeProfile.user_id == context.user.id,
        )
    )
    return and_(
        Document.organization_id == context.organization.id,
        or_(
            Document.visibility == DocumentVisibility.ORGANIZATION,
            Document.owner_user_id == context.user.id,
            explicit_user,
            team_access,
        ),
    )


def can_manage_document(context: OrganizationContext, document: Document) -> bool:
    return Capability.MANAGE_ALL_DOCUMENTS in context.capabilities or (
        Capability.UPLOAD_DOCUMENTS in context.capabilities
        and document.owner_user_id == context.user.id
    )
