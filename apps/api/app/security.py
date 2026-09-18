import base64
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuthIdentity, PasswordCredential, SessionRecord, User

password_hash = PasswordHash.recommended()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def random_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_and_update_password(password: str, encoded: str) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(password, encoded)


def validate_password(password: str) -> None:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be between 12 and 256 characters")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    return slug[:80] or "organization"


def create_session(
    db: Session,
    identity: AuthIdentity,
    settings: Settings,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[SessionRecord, str, str]:
    token = random_token()
    csrf = random_token()
    session = SessionRecord(
        user_id=identity.user_id,
        auth_identity_id=identity.id,
        token_hash=hash_token(token),
        csrf_hash=hash_token(csrf),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
        user_agent=(user_agent or "")[:512] or None,
        ip_address=ip_address,
    )
    db.add(session)
    return session, token, csrf


def find_password_identity(
    db: Session, normalized_email: str
) -> tuple[User, AuthIdentity, PasswordCredential] | None:
    row = db.execute(
        select(User, AuthIdentity, PasswordCredential)
        .join(AuthIdentity, AuthIdentity.user_id == User.id)
        .join(PasswordCredential, PasswordCredential.auth_identity_id == AuthIdentity.id)
        .where(
            User.normalized_email == normalized_email,
            AuthIdentity.provider == "password",
        )
    ).first()
    return (row[0], row[1], row[2]) if row else None


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
