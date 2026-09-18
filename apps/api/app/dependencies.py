import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    AuthIdentity,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    SessionRecord,
    User,
    UserStatus,
)
from app.policy import AuthenticatedUser, OrganizationContext
from app.security import hash_token

Db = Annotated[Session, Depends(get_db)]


def get_current_user(
    request: Request,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    row = db.execute(
        select(SessionRecord, User, AuthIdentity)
        .join(User, User.id == SessionRecord.user_id)
        .join(
            AuthIdentity,
            (AuthIdentity.id == SessionRecord.auth_identity_id)
            & (AuthIdentity.user_id == SessionRecord.user_id),
        )
        .where(
            SessionRecord.token_hash == hash_token(session_token),
            SessionRecord.revoked_at.is_(None),
            SessionRecord.expires_at > datetime.now(UTC),
            User.status == UserStatus.ACTIVE,
            AuthIdentity.email_verified_at.is_not(None),
            AuthIdentity.provider.in_(("password", "google")),
        )
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    session, user, identity = row
    request.state.user_id = user.id
    return AuthenticatedUser(user=user, session_id=session.id, auth_identity_id=identity.id)


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def require_csrf(
    request: Request,
    db: Db,
    current: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    session = db.get(SessionRecord, current.session_id)
    if not session or not hmac.compare_digest(session.csrf_hash, hash_token(csrf_header)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")


Csrf = Annotated[None, Depends(require_csrf)]


def get_organization_context(
    request: Request,
    db: Db,
    current: CurrentUser,
    organization_header: Annotated[str | None, Header(alias="X-ReadySet-Organization")] = None,
) -> OrganizationContext:
    query = (
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.user_id == current.user.id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
        )
    )
    if organization_header:
        try:
            organization_id = uuid.UUID(organization_header)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Organization not found") from exc
        query = query.where(OrganizationMembership.organization_id == organization_id)
    rows = db.execute(query.limit(2)).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not organization_header and len(rows) != 1:
        raise HTTPException(status_code=400, detail="X-ReadySet-Organization is required")
    membership, organization = rows[0]
    request.state.organization_id = organization.id
    return OrganizationContext(user=current.user, organization=organization, membership=membership)


OrgContext = Annotated[OrganizationContext, Depends(get_organization_context)]
