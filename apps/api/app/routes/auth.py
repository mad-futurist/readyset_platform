import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_audit
from app.config import Settings, get_settings
from app.dependencies import Csrf, CurrentUser, Db
from app.models import (
    AuthIdentity,
    MembershipStatus,
    OAuthLoginState,
    OneTimeToken,
    OrganizationMembership,
    PasswordCredential,
    SessionRecord,
    User,
)
from app.rate_limit import check_auth_rate
from app.schemas import (
    AuthResponse,
    LoginRequest,
    MembershipRead,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    TokenRequest,
    UserRead,
)
from app.security import (
    create_session,
    find_password_identity,
    hash_password,
    hash_token,
    normalize_email,
    pkce_challenge,
    random_token,
    validate_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _memberships(db: Db, user_id: uuid.UUID) -> list[OrganizationMembership]:
    return list(
        db.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        )
    )


def _set_auth_cookies(response: Response, token: str, csrf: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Db,
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    check_auth_rate(request, "register", limit=5)
    try:
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized = normalize_email(str(payload.email))
    if db.scalar(select(User.id).where(User.normalized_email == normalized)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        primary_email=str(payload.email).strip(),
        normalized_email=normalized,
        display_name=payload.display_name.strip(),
    )
    identity = AuthIdentity(
        provider="password", provider_subject=normalized, provider_email=normalized
    )
    identity.user = user
    db.add_all([user, identity])
    db.flush()
    db.add(
        PasswordCredential(
            auth_identity_id=identity.id, password_hash=hash_password(payload.password)
        )
    )
    verification_token = random_token()
    db.add(
        OneTimeToken(
            user_id=user.id,
            purpose="verify_email",
            token_hash=hash_token(verification_token),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    _, token, csrf = create_session(
        db,
        user,
        settings,
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )
    record_audit(
        db,
        action="user.registered",
        resource_type="user",
        resource_id=user.id,
        organization_id=None,
        actor_user_id=user.id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        ) from exc
    _set_auth_cookies(response, token, csrf, settings)
    return AuthResponse(
        user=UserRead.model_validate(user),
        memberships=[],
        csrf_token=csrf,
        development_verification_token=verification_token if not settings.is_production else None,
    )


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Db,
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    check_auth_rate(request, "login", limit=10)
    found = find_password_identity(db, normalize_email(str(payload.email)))
    if not found or not verify_password(payload.password, found[1].password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user, _ = found
    _, token, csrf = create_session(
        db,
        user,
        settings,
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )
    record_audit(
        db,
        action="user.logged_in",
        resource_type="user",
        resource_id=user.id,
        organization_id=None,
        actor_user_id=user.id,
    )
    db.commit()
    _set_auth_cookies(response, token, csrf, settings)
    return AuthResponse(
        user=UserRead.model_validate(user),
        memberships=[MembershipRead.model_validate(m) for m in _memberships(db, user.id)],
        csrf_token=csrf,
    )


@router.get("/me", response_model=AuthResponse)
def me(current: CurrentUser, db: Db, request: Request) -> AuthResponse:
    csrf = request.cookies.get(get_settings().csrf_cookie_name) or ""
    return AuthResponse(
        user=UserRead.model_validate(current.user),
        memberships=[MembershipRead.model_validate(m) for m in _memberships(db, current.user.id)],
        csrf_token=csrf,
    )


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    db: Db,
    current: CurrentUser,
    csrf: Csrf,
    settings: Settings = Depends(get_settings),
) -> None:
    session = db.get(SessionRecord, current.session_id)
    if session:
        session.revoked_at = datetime.now(UTC)
    db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.post("/verify-email", status_code=204)
def verify_email(payload: TokenRequest, db: Db) -> None:
    token = db.scalar(
        select(OneTimeToken)
        .where(
            OneTimeToken.token_hash == hash_token(payload.token),
            OneTimeToken.purpose == "verify_email",
            OneTimeToken.consumed_at.is_(None),
            OneTimeToken.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == token.user_id, AuthIdentity.provider == "password"
        )
    )
    if not identity:
        raise HTTPException(status_code=400, detail="Invalid token")
    identity.email_verified_at = datetime.now(UTC)
    token.consumed_at = datetime.now(UTC)
    db.commit()


@router.post("/password-reset/request", status_code=202)
def request_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Db,
    settings: Settings = Depends(get_settings),
) -> dict[str, str | None]:
    check_auth_rate(request, "password-reset", limit=5)
    user = db.scalar(
        select(User).where(User.normalized_email == normalize_email(str(payload.email)))
    )
    raw: str | None = None
    if user:
        raw = random_token()
        db.add(
            OneTimeToken(
                user_id=user.id,
                purpose="password_reset",
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
    return {
        "message": "If the account exists, reset instructions were created.",
        "development_token": raw if raw and not settings.is_production else None,
    }


@router.post("/password-reset/confirm", status_code=204)
def confirm_reset(payload: PasswordResetConfirm, db: Db) -> None:
    try:
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token = db.scalar(
        select(OneTimeToken)
        .where(
            OneTimeToken.token_hash == hash_token(payload.token),
            OneTimeToken.purpose == "password_reset",
            OneTimeToken.consumed_at.is_(None),
            OneTimeToken.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == token.user_id, AuthIdentity.provider == "password"
        )
    )
    credential = db.get(PasswordCredential, identity.id) if identity else None
    if not credential:
        raise HTTPException(status_code=400, detail="Invalid token")
    credential.password_hash = hash_password(payload.password)
    credential.password_changed_at = datetime.now(UTC)
    token.consumed_at = datetime.now(UTC)
    db.execute(
        update(SessionRecord)
        .where(SessionRecord.user_id == token.user_id)
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()


@router.get("/google/start")
def google_start(
    request: Request, db: Db, settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    check_auth_rate(request, "google-start", limit=20)
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google authentication is not configured")
    state, verifier, nonce = random_token(), random_token(48), random_token()
    db.add(
        OAuthLoginState(
            state_hash=hash_token(state),
            code_verifier=verifier,
            nonce=nonce,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    db.commit()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return {
        "authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    }


@router.get("/google/callback")
def google_callback(
    code: str, state: str, request: Request, db: Db, settings: Settings = Depends(get_settings)
) -> RedirectResponse:
    pending = db.scalar(
        select(OAuthLoginState)
        .where(
            OAuthLoginState.state_hash == hash_token(state),
            OAuthLoginState.consumed_at.is_(None),
            OAuthLoginState.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if not pending or not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    with httpx.Client(timeout=10) as client:
        token_response = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": pending.code_verifier,
            },
        )
        token_response.raise_for_status()
        raw_id_token = token_response.json()["id_token"]
    claims = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
        raw_id_token, google_requests.Request(), settings.google_client_id
    )
    if claims.get("nonce") != pending.nonce or not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google identity could not be verified")
    subject, email = str(claims["sub"]), normalize_email(str(claims["email"]))
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google", AuthIdentity.provider_subject == subject
        )
    )
    if identity:
        user = db.get(User, identity.user_id)
    else:
        user = db.scalar(select(User).where(User.normalized_email == email))
        if not user:
            user = User(
                primary_email=str(claims["email"]),
                normalized_email=email,
                display_name=str(claims.get("name") or email),
                avatar_url=claims.get("picture"),
            )
            db.add(user)
            db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider="google",
                provider_subject=subject,
                provider_email=email,
                email_verified_at=datetime.now(UTC),
            )
        )
    if not user:
        raise HTTPException(status_code=401, detail="Google identity could not be verified")
    pending.consumed_at = datetime.now(UTC)
    _, token, csrf = create_session(
        db,
        user,
        settings,
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )
    record_audit(
        db,
        action="user.google_logged_in",
        resource_type="user",
        resource_id=user.id,
        organization_id=None,
        actor_user_id=user.id,
    )
    db.commit()
    response = RedirectResponse(f"{settings.web_url}/", status_code=303)
    _set_auth_cookies(response, token, csrf, settings)
    return response
