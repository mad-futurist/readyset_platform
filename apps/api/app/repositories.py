import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus, DocumentVersion, EmployeeProfile, Team
from app.policy import OrganizationContext, document_access_predicate


class PeopleRepository:
    """All entry points require an explicit organization boundary."""

    def __init__(self, db: Session, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    def get_profile(self, profile_id: uuid.UUID) -> EmployeeProfile | None:
        return self.db.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.organization_id == self.organization_id,
                EmployeeProfile.id == profile_id,
            )
        )

    def get_team(self, team_id: uuid.UUID) -> Team | None:
        return self.db.scalar(
            select(Team).where(
                Team.organization_id == self.organization_id,
                Team.id == team_id,
            )
        )


class DocumentRepository:
    """Tenant and ACL filters are structural, not optional caller conventions."""

    def __init__(self, db: Session, context: OrganizationContext) -> None:
        self.db = db
        self.context = context

    def readable_query(self) -> Select[tuple[Document]]:
        return select(Document).where(
            Document.status == DocumentStatus.ACTIVE,
            document_access_predicate(self.context),
        )

    def get_readable(self, document_id: uuid.UUID) -> Document | None:
        return self.db.scalar(self.readable_query().where(Document.id == document_id))

    def get_in_organization(self, document_id: uuid.UUID) -> Document | None:
        return self.db.scalar(
            select(Document).where(
                Document.organization_id == self.context.organization.id,
                Document.id == document_id,
                Document.status == DocumentStatus.ACTIVE,
            )
        )

    def get_version(self, document_id: uuid.UUID, version_id: uuid.UUID) -> DocumentVersion | None:
        return self.db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.organization_id == self.context.organization.id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.id == version_id,
            )
        )
