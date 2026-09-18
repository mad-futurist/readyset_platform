import hmac
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_audit
from app.config import Settings, get_settings
from app.dependencies import Csrf, CurrentUser, Db
from app.email import EmailSender, get_email_sender
from app.models import (
    AuthIdentity,
    MembershipStatus,
    OAuthLoginState,
    OneTimeToken,
    OrganizationMembership,
    PasswordCredential,
    SessionRecord,
    User,
    UserStatus,
)
from app.rate_limit import check_auth_rate
from app.schemas import (
    AuthResponse,
    DeliveryStatus,
    LoginRequest,
    MembershipRead,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    RegistrationResponse,
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
    verify_and_update_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
OAUTH_CALLBACK_PATH = "/api/v1/auth/google/callback"
logger = logging.getLogger("readyset.email")


def _memberships(db: Db, user_id: uuid.UUID) -> list[OrganizationMembership]:
    return list(
        db.scalars(
            select(OrganizationMembership)
            .where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(OrganizationMembership.joined_at, OrganizationMembership.id)
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


def _delete_oauth_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.oauth_binding_cookie_name, path=OAUTH_CALLBACK_PATH)


def _oauth_error(settings: Settings, message: str, status_code: int) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": "oauth_failed", "message": message}},
    )
    _delete_oauth_cookie(response, settings)
    return response


def _send_email(
    sender: EmailSender, recipient: str, subject: str, body: str
) -> DeliveryStatus:
    try:
        sender.send(recipient, subject, body)
    except Exception:
        # Tokens and message bodies are deliberately absent from the log record.
        logger.exception("Synchronous email delivery failed")
        return DeliveryStatus.FAILED
    return DeliveryStatus.SENT


def exchange_google_code(code: str, pending: OAuthLoginState, settings: Settings) -> str:
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
        return str(token_response.json()["id_token"])


def verify_google_token(raw_id_token: str, settings: Settings) -> dict[str, object]:
    return google_id_token.verify_oauth2_token(  # type: ignore[no-any-return,no-untyped-call]
        raw_id_token, google_requests.Request(), settings.google_client_id
    )


@router.post("/register", response_model=RegistrationResponse, status_code=202)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Db,
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> RegistrationResponse:
    if not settings.password_auth_enabled:
        raise HTTPException(status_code=404, detail="Password authentication is disabled")
    check_auth_rate(request, "register", limit=5, email=str(payload.email))
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
    delivery_status = _send_email(
        sender,
        user.primary_email,
        "Verify your ReadySet email",
        "Verify your ReadySet email: "
        f"{settings.public_web_url.rstrip('/')}/verify-email?"
        f"{urlencode({'token': verification_token})}",
    )
    return RegistrationResponse(
        message=(
            "Check your email to verify your account before signing in."
            if delivery_status == DeliveryStatus.SENT
            else "Your account was created, but verification email delivery failed. Retry delivery."
        ),
        delivery_status=delivery_status,
        development_verification_token=(
            verification_token if settings.expose_development_tokens else None
        ),
    )


@router.post("/verification/resend", response_model=MessageResponse, status_code=202)
def resend_verification(
    payload: PasswordResetRequest,
    request: Request,
    db: Db,
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> MessageResponse:
    if not settings.password_auth_enabled:
        raise HTTPException(status_code=404, detail="Password authentication is disabled")
    check_auth_rate(request, "verification-resend", limit=5, email=str(payload.email))
    normalized = normalize_email(str(payload.email))
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "password",
            AuthIdentity.provider_subject == normalized,
            AuthIdentity.email_verified_at.is_(None),
        )
    )
    raw: str | None = None
    if identity:
        user = db.get(User, identity.user_id)
        if user and user.status == UserStatus.ACTIVE:
            now = datetime.now(UTC)
            db.execute(
                update(OneTimeToken)
                .where(
                    OneTimeToken.user_id == user.id,
                    OneTimeToken.purpose == "verify_email",
                    OneTimeToken.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            )
            raw = random_token()
            db.add(
                OneTimeToken(
                    user_id=user.id,
                    purpose="verify_email",
                    token_hash=hash_token(raw),
                    expires_at=now + timedelta(hours=24),
                )
            )
            db.commit()
            _send_email(
                sender,
                user.primary_email,
                "Verify your ReadySet email",
                "Verify your ReadySet email: "
                f"{settings.public_web_url.rstrip('/')}/verify-email?"
                f"{urlencode({'token': raw})}",
            )
    return MessageResponse(
        message="If an unverified password account exists, verification instructions were sent.",
        delivery_status=DeliveryStatus.UNDISCLOSED,
        development_token=raw if raw and settings.expose_development_tokens else None,
    )


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Db,
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    if not settings.password_auth_enabled:
        raise HTTPException(status_code=404, detail="Password authentication is disabled")
    check_auth_rate(request, "login", limit=10, email=str(payload.email))
    found = find_password_identity(db, normalize_email(str(payload.email)))
    if not found:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user, identity, credential = found
    valid, updated_hash = verify_and_update_password(payload.password, credential.password_hash)
    if not valid or user.status != UserStatus.ACTIVE or identity.email_verified_at is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if updated_hash:
        credential.password_hash = updated_hash
    _, token, csrf = create_session(
        db,
        identity,
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
        metadata={"provider": "password"},
    )
    db.commit()
    _set_auth_cookies(response, token, csrf, settings)
    return AuthResponse(
        user=UserRead.model_validate(user),
        memberships=[MembershipRead.model_validate(m) for m in _memberships(db, user.id)],
        csrf_token=csrf,
    )


@router.get("/me", response_model=AuthResponse)
def me(
    current: CurrentUser,
    db: Db,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    csrf = request.cookies.get(settings.csrf_cookie_name) or ""
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
    now = datetime.now(UTC)
    identity.email_verified_at = now
    db.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == token.user_id,
            OneTimeToken.purpose == "verify_email",
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    record_audit(
        db,
        action="user.email_verified",
        resource_type="auth_identity",
        resource_id=identity.id,
        organization_id=None,
        actor_user_id=identity.user_id,
    )
    db.commit()


@router.post("/password-reset/request", response_model=MessageResponse, status_code=202)
def request_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Db,
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> MessageResponse:
    if not settings.password_auth_enabled:
        raise HTTPException(status_code=404, detail="Password authentication is disabled")
    check_auth_rate(request, "password-reset-request", limit=5, email=str(payload.email))
    found = find_password_identity(db, normalize_email(str(payload.email)))
    raw: str | None = None
    if found and found[1].email_verified_at is not None and found[0].status == UserStatus.ACTIVE:
        user = found[0]
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
        _send_email(
            sender,
            user.primary_email,
            "Reset your ReadySet password",
            "Reset your ReadySet password: "
            f"{settings.public_web_url.rstrip('/')}/reset-password?"
            f"{urlencode({'token': raw})}",
        )
    return MessageResponse(
        message="If the account exists, reset instructions were sent.",
        delivery_status=DeliveryStatus.UNDISCLOSED,
        development_token=raw if raw and settings.expose_development_tokens else None,
    )


@router.post("/password-reset/confirm", status_code=204)
def confirm_reset(payload: PasswordResetConfirm, request: Request, db: Db) -> None:
    check_auth_rate(request, "password-reset-confirm", limit=5)
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
            AuthIdentity.user_id == token.user_id,
            AuthIdentity.provider == "password",
            AuthIdentity.email_verified_at.is_not(None),
        )
    )
    credential = db.get(PasswordCredential, identity.id) if identity else None
    if not credential:
        raise HTTPException(status_code=400, detail="Invalid token")
    assert identity is not None
    now = datetime.now(UTC)
    credential.password_hash = hash_password(payload.password)
    credential.password_changed_at = now
    db.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == token.user_id,
            OneTimeToken.purpose == "password_reset",
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    db.execute(
        update(SessionRecord)
        .where(SessionRecord.user_id == token.user_id, SessionRecord.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    record_audit(
        db,
        action="user.password_reset",
        resource_type="auth_identity",
        resource_id=identity.id,
        organization_id=None,
        actor_user_id=token.user_id,
    )
    db.commit()


@router.get("/google/start")
def google_start(
    request: Request,
    response: Response,
    db: Db,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    check_auth_rate(request, "google-start", limit=20)
    if (
        not settings.google_auth_enabled
        or not settings.google_client_id
        or not settings.google_client_secret
    ):
        raise HTTPException(status_code=503, detail="Google authentication is not configured")
    state, verifier, nonce, binding = (
        random_token(),
        random_token(48),
        random_token(),
        random_token(),
    )
    db.add(
        OAuthLoginState(
            state_hash=hash_token(state),
            binding_hash=hash_token(binding),
            code_verifier=verifier,
            nonce=nonce,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.oauth_state_ttl_minutes),
        )
    )
    db.commit()
    response.set_cookie(
        settings.oauth_binding_cookie_name,
        binding,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.oauth_state_ttl_minutes * 60,
        path=OAUTH_CALLBACK_PATH,
    )
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


@router.get("/google/callback", response_model=None)
def google_callback(
    code: str,
    state: str,
    request: Request,
    db: Db,
    settings: Settings = Depends(get_settings),
) -> Response:
    binding = request.cookies.get(settings.oauth_binding_cookie_name)
    pending = db.scalar(
        select(OAuthLoginState)
        .where(
            OAuthLoginState.state_hash == hash_token(state),
            OAuthLoginState.consumed_at.is_(None),
            OAuthLoginState.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if (
        not pending
        or not binding
        or not hmac.compare_digest(pending.binding_hash, hash_token(binding))
        or not settings.google_auth_enabled
        or not settings.google_client_id
        or not settings.google_client_secret
    ):
        if pending:
            pending.consumed_at = datetime.now(UTC)
            db.commit()
        return _oauth_error(settings, "Invalid or expired OAuth request", 400)
    try:
        raw_id_token = exchange_google_code(code, pending, settings)
        claims = verify_google_token(raw_id_token, settings)
    except (httpx.HTTPError, GoogleAuthError, ValueError, KeyError, TypeError):
        pending.consumed_at = datetime.now(UTC)
        db.commit()
        return _oauth_error(settings, "Google authentication could not be completed", 401)
    if (
        claims.get("nonce") != pending.nonce
        or claims.get("email_verified") is not True
        or not claims.get("sub")
        or not claims.get("email")
    ):
        pending.consumed_at = datetime.now(UTC)
        db.commit()
        return _oauth_error(settings, "Google identity could not be verified", 401)
    subject = str(claims["sub"])
    provider_email = str(claims["email"])
    email = normalize_email(provider_email)
    picture_claim = claims.get("picture")
    picture = str(picture_claim) if picture_claim else None
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google", AuthIdentity.provider_subject == subject
        )
    )
    user: User | None
    if identity:
        user = db.get(User, identity.user_id)
        if not user or user.status != UserStatus.ACTIVE:
            pending.consumed_at = datetime.now(UTC)
            db.commit()
            return _oauth_error(settings, "Google identity could not be verified", 401)
        if (
            user.normalized_email != email
            or normalize_email(identity.provider_email or "") != email
        ):
            pending.consumed_at = datetime.now(UTC)
            db.commit()
            return _oauth_error(settings, "Google identity conflicts with this account", 409)
    else:
        user = db.scalar(select(User).where(User.normalized_email == email).with_for_update())
        if user and user.status != UserStatus.ACTIVE:
            pending.consumed_at = datetime.now(UTC)
            db.commit()
            return _oauth_error(settings, "Google identity could not be verified", 401)
        if user:
            conflicting = db.scalar(
                select(AuthIdentity.id).where(
                    AuthIdentity.user_id == user.id,
                    AuthIdentity.provider == "google",
                    AuthIdentity.provider_subject != subject,
                )
            )
            if conflicting:
                pending.consumed_at = datetime.now(UTC)
                db.commit()
                return _oauth_error(settings, "Google identity conflicts with this account", 409)
            unsafe_password_identity = db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.user_id == user.id,
                    AuthIdentity.provider == "password",
                    AuthIdentity.provider_subject == email,
                    AuthIdentity.email_verified_at.is_(None),
                )
            )
            if unsafe_password_identity:
                now = datetime.now(UTC)
                db.execute(
                    update(OneTimeToken)
                    .where(
                        OneTimeToken.user_id == user.id,
                        OneTimeToken.purpose == "verify_email",
                        OneTimeToken.consumed_at.is_(None),
                    )
                    .values(consumed_at=now)
                )
                # Deleting the identity cascades to its password credential and any
                # impossible pre-verification sessions; the attacker password is not trusted.
                db.delete(unsafe_password_identity)
                db.flush()
            has_verified_identity = db.scalar(
                select(AuthIdentity.id).where(
                    AuthIdentity.user_id == user.id,
                    AuthIdentity.email_verified_at.is_not(None),
                )
            )
            user.primary_email = provider_email
            if not has_verified_identity:
                user.display_name = str(claims.get("name") or email)
                user.avatar_url = picture
        else:
            user = User(
                primary_email=provider_email,
                normalized_email=email,
                display_name=str(claims.get("name") or email),
                avatar_url=picture,
            )
            db.add(user)
            db.flush()
        identity = AuthIdentity(
            id=uuid.uuid4(),
            user_id=user.id,
            provider="google",
            provider_subject=subject,
            provider_email=email,
            email_verified_at=datetime.now(UTC),
        )
        db.add(identity)
    pending.consumed_at = datetime.now(UTC)
    _, token, csrf = create_session(
        db,
        identity,
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
        metadata={"provider": "google"},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _oauth_error(settings, "Google identity linking conflicted; retry sign-in", 409)
    response = RedirectResponse(f"{settings.public_web_url.rstrip('/')}/", status_code=303)
    _set_auth_cookies(response, token, csrf, settings)
    _delete_oauth_cookie(response, settings)
    return response
