import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.audit import record_audit
from app.config import Settings, get_settings
from app.dependencies import Csrf, CurrentUser, Db, OrgContext
from app.models import (
    AuthIdentity,
    InvitationStatus,
    MembershipStatus,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationRole,
)
from app.policy import Capability, require_capability
from app.schemas import (
    InvitationCreate,
    InvitationRead,
    MembershipRead,
    MembershipRoleUpdate,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
    TokenRequest,
)
from app.security import hash_token, normalize_email, random_token, slugify

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[MembershipRead])
def list_organizations(db: Db, current: CurrentUser) -> list[OrganizationMembership]:
    return list(
        db.scalars(
            select(OrganizationMembership)
            .where(
                OrganizationMembership.user_id == current.user.id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(OrganizationMembership.joined_at)
        )
    )


@router.post("", response_model=OrganizationRead, status_code=201)
def create_organization(
    payload: OrganizationCreate, request: Request, db: Db, current: CurrentUser, csrf: Csrf
) -> Organization:
    base = slugify(payload.slug or payload.name)
    slug = base
    if db.scalar(select(Organization.id).where(Organization.slug == slug)):
        slug = f"{base[:70]}-{str(uuid.uuid4())[:8]}"
    organization = Organization(
        name=payload.name.strip(), slug=slug, created_by_user_id=current.user.id
    )
    db.add(organization)
    db.flush()
    db.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=current.user.id,
            role=OrganizationRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )
    record_audit(
        db,
        action="organization.created",
        resource_type="organization",
        resource_id=organization.id,
        organization_id=organization.id,
        actor_user_id=current.user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return organization


@router.patch("/current", response_model=OrganizationRead)
def update_organization(
    payload: OrganizationUpdate, db: Db, context: OrgContext, csrf: Csrf
) -> Organization:
    require_capability(context, Capability.MANAGE_ORGANIZATION)
    context.organization.name = payload.name.strip()
    record_audit(
        db,
        action="organization.updated",
        resource_type="organization",
        resource_id=context.organization.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    db.commit()
    return context.organization


@router.get("/current/members", response_model=list[MembershipRead])
def list_members(db: Db, context: OrgContext) -> list[OrganizationMembership]:
    return list(
        db.scalars(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == context.organization.id)
            .order_by(OrganizationMembership.joined_at)
        )
    )


@router.post("/current/invitations", response_model=InvitationRead, status_code=201)
def invite_member(
    payload: InvitationCreate,
    db: Db,
    context: OrgContext,
    csrf: Csrf,
    settings: Settings = Depends(get_settings),
) -> InvitationRead:
    require_capability(context, Capability.MANAGE_MEMBERS)
    if payload.role == OrganizationRole.OWNER:
        raise HTTPException(status_code=422, detail="Ownership must be transferred explicitly")
    normalized = normalize_email(str(payload.email))
    raw = random_token()
    invitation = OrganizationInvitation(
        id=uuid.uuid4(),
        organization_id=context.organization.id,
        email=str(payload.email),
        normalized_email=normalized,
        role=payload.role,
        token_hash=hash_token(raw),
        invited_by_user_id=context.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)
    record_audit(
        db,
        action="member.invited",
        resource_type="invitation",
        resource_id=invitation.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
        metadata={"email": normalized, "role": payload.role.value},
    )
    db.commit()
    result = InvitationRead.model_validate(invitation)
    result.development_token = raw if not settings.is_production else None
    return result


@router.post("/invitations/accept", response_model=MembershipRead)
def accept_invitation(
    payload: TokenRequest, db: Db, current: CurrentUser, csrf: Csrf
) -> OrganizationMembership:
    invitation = db.scalar(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.token_hash == hash_token(payload.token),
            OrganizationInvitation.status == InvitationStatus.PENDING,
            OrganizationInvitation.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if not invitation or invitation.normalized_email != current.user.normalized_email:
        raise HTTPException(status_code=400, detail="Invalid or expired invitation")
    verified = db.scalar(
        select(AuthIdentity.id).where(
            AuthIdentity.user_id == current.user.id,
            AuthIdentity.email_verified_at.is_not(None),
        )
    )
    if not verified:
        raise HTTPException(
            status_code=403, detail="Verify your email before accepting invitations"
        )
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == invitation.organization_id,
            OrganizationMembership.user_id == current.user.id,
        )
    )
    if membership:
        membership.status = MembershipStatus.ACTIVE
        membership.role = invitation.role
        membership.revoked_at = None
    else:
        membership = OrganizationMembership(
            id=uuid.uuid4(),
            organization_id=invitation.organization_id,
            user_id=current.user.id,
            role=invitation.role,
        )
        db.add(membership)
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_by_user_id = current.user.id
    record_audit(
        db,
        action="member.joined",
        resource_type="membership",
        resource_id=membership.id,
        organization_id=invitation.organization_id,
        actor_user_id=current.user.id,
    )
    db.commit()
    return membership


@router.patch("/current/members/{membership_id}", response_model=MembershipRead)
def change_role(
    membership_id: uuid.UUID, payload: MembershipRoleUpdate, db: Db, context: OrgContext, csrf: Csrf
) -> OrganizationMembership:
    require_capability(context, Capability.MANAGE_MEMBERS)
    target = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == context.organization.id,
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="Membership not found")
    if target.role == OrganizationRole.OWNER or payload.role == OrganizationRole.OWNER:
        raise HTTPException(status_code=409, detail="Use an ownership transfer flow")
    target.role = payload.role
    record_audit(
        db,
        action="member.role_changed",
        resource_type="membership",
        resource_id=target.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
        metadata={"role": payload.role.value},
    )
    db.commit()
    return target


@router.delete("/current/members/{membership_id}", status_code=204)
def revoke_member(membership_id: uuid.UUID, db: Db, context: OrgContext, csrf: Csrf) -> None:
    require_capability(context, Capability.MANAGE_MEMBERS)
    target = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == context.organization.id,
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="Membership not found")
    if target.role == OrganizationRole.OWNER:
        raise HTTPException(status_code=409, detail="The owner cannot be revoked")
    target.status = MembershipStatus.REVOKED
    target.revoked_at = datetime.now(UTC)
    record_audit(
        db,
        action="member.revoked",
        resource_type="membership",
        resource_id=target.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    db.commit()
