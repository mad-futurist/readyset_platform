import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import record_audit
from app.config import Settings, get_settings
from app.dependencies import Csrf, CurrentUser, Db, OrgContext
from app.email import EmailSender, get_email_sender
from app.models import (
    InvitationStatus,
    MembershipStatus,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationRole,
    User,
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
    OwnershipTransferRequest,
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
            .order_by(OrganizationMembership.joined_at, OrganizationMembership.id)
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
    try:
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
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Organization slug is already in use") from exc
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
            .order_by(OrganizationMembership.joined_at, OrganizationMembership.id)
        )
    )


@router.post("/current/invitations", response_model=InvitationRead, status_code=201)
def invite_member(
    payload: InvitationCreate,
    db: Db,
    context: OrgContext,
    csrf: Csrf,
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> InvitationRead:
    require_capability(context, Capability.MANAGE_MEMBERS)
    if not settings.invitations_enabled:
        raise HTTPException(status_code=404, detail="Invitations are disabled")
    if payload.role == OrganizationRole.OWNER:
        raise HTTPException(status_code=422, detail="Ownership must be transferred explicitly")
    normalized = normalize_email(str(payload.email))
    if db.scalar(
        select(OrganizationMembership.id)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == context.organization.id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
            User.normalized_email == normalized,
        )
    ):
        raise HTTPException(status_code=409, detail="This person is already a member")
    raw = random_token()
    invitation = db.scalar(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.organization_id == context.organization.id,
            OrganizationInvitation.normalized_email == normalized,
            OrganizationInvitation.status == InvitationStatus.PENDING,
        )
        .with_for_update()
    )
    action = "member.invitation_reissued"
    if invitation:
        invitation.email = str(payload.email)
        invitation.role = payload.role
        invitation.token_hash = hash_token(raw)
        invitation.invited_by_user_id = context.user.id
        invitation.expires_at = datetime.now(UTC) + timedelta(days=7)
    else:
        action = "member.invited"
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
        action=action,
        resource_type="invitation",
        resource_id=invitation.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
        metadata={"email": normalized, "role": payload.role.value},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A pending invitation for this email already exists"
        ) from exc
    try:
        sender.send(
            invitation.email,
            f"You are invited to {context.organization.name} on ReadySet",
            f"Accept your ReadySet invitation: {settings.public_web_url.rstrip('/')}/"
            f"accept-invitation?{urlencode({'token': raw})}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Email delivery is temporarily unavailable"
        ) from exc
    result = InvitationRead.model_validate(invitation)
    result.development_token = raw if settings.expose_development_tokens else None
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
    db.flush()
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


@router.delete("/current/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: uuid.UUID, db: Db, context: OrgContext, csrf: Csrf) -> None:
    require_capability(context, Capability.MANAGE_MEMBERS)
    invitation = db.scalar(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.organization_id == context.organization.id,
            OrganizationInvitation.status == InvitationStatus.PENDING,
        )
        .with_for_update()
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Pending invitation not found")
    invitation.status = InvitationStatus.REVOKED
    record_audit(
        db,
        action="member.invitation_revoked",
        resource_type="invitation",
        resource_id=invitation.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    db.commit()


@router.post("/current/ownership-transfer", response_model=MembershipRead)
def transfer_ownership(
    payload: OwnershipTransferRequest, db: Db, context: OrgContext, csrf: Csrf
) -> OrganizationMembership:
    db.scalar(
        select(Organization.id).where(Organization.id == context.organization.id).with_for_update()
    )
    current_owner = db.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.id == context.membership.id,
            OrganizationMembership.organization_id == context.organization.id,
        )
        .with_for_update()
    )
    if not current_owner or current_owner.role != OrganizationRole.OWNER:
        raise HTTPException(status_code=403, detail="Only the current owner may transfer ownership")
    target = db.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.id == payload.membership_id,
            OrganizationMembership.organization_id == context.organization.id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
        )
        .with_for_update()
    )
    if not target or target.id == current_owner.id:
        raise HTTPException(status_code=422, detail="Target must be another active member")
    current_owner.role = OrganizationRole.ADMIN
    db.flush()
    target.role = OrganizationRole.OWNER
    record_audit(
        db,
        action="organization.ownership_transferred",
        resource_type="organization",
        resource_id=context.organization.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
        metadata={"new_owner_user_id": str(target.user_id)},
    )
    db.commit()
    return target


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
