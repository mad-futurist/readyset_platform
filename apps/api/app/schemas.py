import enum
import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import (
    DocumentStatus,
    DocumentVisibility,
    EmployeeStatus,
    IngestionStatus,
    MembershipStatus,
    OrganizationRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRead(ORMModel):
    id: uuid.UUID
    primary_email: EmailStr
    display_name: str
    avatar_url: str | None


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    password: str


class TokenRequest(BaseModel):
    token: str


class OrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str


class MembershipRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: OrganizationRole
    status: MembershipStatus
    user: UserRead | None = None
    organization: OrganizationRead | None = None


class AuthResponse(BaseModel):
    user: UserRead
    memberships: list[MembershipRead]
    csrf_token: str


class DeliveryStatus(str, enum.Enum):
    SENT = "SENT"
    FAILED = "FAILED"
    UNDISCLOSED = "UNDISCLOSED"


class RegistrationResponse(BaseModel):
    message: str
    delivery_status: DeliveryStatus
    development_verification_token: str | None = None


class MessageResponse(BaseModel):
    message: str
    delivery_status: DeliveryStatus = DeliveryStatus.UNDISCLOSED
    development_token: str | None = None


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=80)


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class InvitationCreate(BaseModel):
    email: EmailStr
    role: OrganizationRole = OrganizationRole.MEMBER


class InvitationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: EmailStr
    role: OrganizationRole
    status: str
    expires_at: datetime
    development_token: str | None = None
    delivery_status: DeliveryStatus = DeliveryStatus.UNDISCLOSED


class MembershipRoleUpdate(BaseModel):
    role: OrganizationRole


class OwnershipTransferRequest(BaseModel):
    membership_id: uuid.UUID


class RejectNullPatchModel(BaseModel):
    non_nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value: object) -> object:
        if isinstance(value, dict):
            null_fields = cls.non_nullable_fields.intersection(
                key for key, item in value.items() if item is None
            )
            if null_fields:
                fields = ", ".join(sorted(null_fields))
                raise ValueError(f"Fields may be omitted but cannot be null: {fields}")
        return value


class EmployeeProfileCreate(BaseModel):
    user_id: uuid.UUID | None = None
    display_name: str = Field(min_length=1, max_length=255)
    work_email: EmailStr | None = None
    job_title: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    seniority: str | None = Field(default=None, max_length=100)
    manager_profile_id: uuid.UUID | None = None
    start_date: date | None = None
    timezone: str | None = Field(default=None, max_length=100)
    locale: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmployeeProfileUpdate(RejectNullPatchModel):
    non_nullable_fields = frozenset({"display_name", "status", "metadata"})
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    work_email: EmailStr | None = None
    job_title: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    seniority: str | None = Field(default=None, max_length=100)
    manager_profile_id: uuid.UUID | None = None
    start_date: date | None = None
    timezone: str | None = Field(default=None, max_length=100)
    locale: str | None = Field(default=None, max_length=20)
    status: EmployeeStatus | None = None
    metadata: dict[str, Any] | None = None


class EmployeeProfileRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None
    display_name: str
    work_email: str | None
    job_title: str | None
    department: str | None
    seniority: str | None
    manager_profile_id: uuid.UUID | None
    start_date: date | None
    timezone: str | None
    locale: str | None
    status: EmployeeStatus
    profile_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=2000)


class TeamRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime


class TeamMemberCreate(BaseModel):
    employee_profile_id: uuid.UUID


class DocumentVersionRead(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    ingestion_status: IngestionStatus
    created_by_user_id: uuid.UUID
    created_at: datetime


class DocumentRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    description: str | None
    document_type: str | None
    domain: str | None
    owner_user_id: uuid.UUID
    visibility: DocumentVisibility
    status: DocumentStatus
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DocumentUpdate(RejectNullPatchModel):
    non_nullable_fields = frozenset({"title", "visibility"})
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    document_type: str | None = Field(default=None, max_length=100)
    domain: str | None = Field(default=None, max_length=100)
    visibility: DocumentVisibility | None = None


class DocumentGrantUpdate(BaseModel):
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    team_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class DocumentGrantRead(BaseModel):
    user_ids: list[uuid.UUID]
    team_ids: list[uuid.UUID]


class AuditEventRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    event_metadata: dict[str, Any]
    created_at: datetime


class Page[PageItem](BaseModel):
    items: list[PageItem]
    page: int
    page_size: int
    total: int
