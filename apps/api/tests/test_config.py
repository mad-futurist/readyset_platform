import pytest
from pydantic import ValidationError

from app.config import Settings


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod")


def test_list_settings_accept_compose_style_csv_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8,192.0.2.10/32")
    monkeypatch.setenv("ALLOWED_CONTENT_TYPES", "text/plain,text/markdown")

    settings = Settings(environment="test")

    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert settings.trusted_proxy_cidrs == ["10.0.0.0/8", "192.0.2.10/32"]
    assert settings.allowed_content_types == ["text/plain", "text/markdown"]


def test_hardened_environment_rejects_development_defaults() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(environment="production")
    message = str(error.value)
    assert "COOKIE_SECURE" in message
    assert "SMTP" in message
    assert "RATE_LIMIT_BACKEND" in message
    assert "SCANNER_BACKEND" in message
    assert "storage credentials" in message
    assert "STORAGE_AUTO_CREATE_BUCKET" in message
    assert "STORAGE_ENCRYPTION" in message


def test_valid_hardened_environment_is_accepted() -> None:
    settings = Settings(
        environment="staging",
        database_url="postgresql+psycopg://app:staging-db-password@db.internal/readyset",
        public_web_url="https://app.staging.readyset.example",
        cors_origins=["https://app.staging.readyset.example"],
        cookie_secure=True,
        google_redirect_uri=("https://app.staging.readyset.example/api/v1/auth/google/callback"),
        development_token_exposure=False,
        rate_limit_backend="redis",
        redis_url="rediss://redis.internal:6379/0",
        scanner_backend="clamav",
        clamav_host="clamav.internal",
        email_backend="smtp",
        email_from="ReadySet <no-reply@staging.readyset.example>",
        smtp_host="smtp.internal",
        smtp_username="readyset",
        smtp_password="secret",
        storage_endpoint_url="https://objects.internal",
        storage_access_key="staging-access",
        storage_secret_key="staging-secret",
        storage_auto_create_bucket=False,
        storage_encryption="AES256",
    )
    assert settings.is_hardened
    assert not settings.expose_development_tokens


def test_hardened_environment_requires_tls_redis() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            database_url="postgresql+psycopg://app:strong-db-password@db.internal/readyset",
            public_web_url="https://app.example",
            cors_origins=["https://app.example"],
            cookie_secure=True,
            google_redirect_uri="https://app.example/api/v1/auth/google/callback",
            development_token_exposure=False,
            rate_limit_backend="redis",
            redis_url="redis://redis.internal:6379/0",
            uploads_enabled=False,
            password_auth_enabled=False,
            invitations_enabled=False,
            storage_endpoint_url="https://objects.internal",
            storage_access_key=None,
            storage_secret_key=None,
            storage_auto_create_bucket=False,
            storage_encryption="AES256",
            email_from="ReadySet <no-reply@example.com>",
        )
    assert "rediss://" in str(error.value)


def test_trusted_proxy_headers_require_explicit_networks() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            database_url="postgresql+psycopg://app:strong-db-password@db.internal/readyset",
            public_web_url="https://app.example",
            cors_origins=["https://app.example"],
            cookie_secure=True,
            google_redirect_uri="https://app.example/api/v1/auth/google/callback",
            development_token_exposure=False,
            rate_limit_backend="redis",
            redis_url="rediss://redis.internal:6379/0",
            trust_proxy_headers=True,
            uploads_enabled=False,
            password_auth_enabled=False,
            invitations_enabled=False,
            storage_endpoint_url="https://objects.internal",
            storage_access_key=None,
            storage_secret_key=None,
            storage_auto_create_bucket=False,
            storage_encryption="AES256",
            email_from="ReadySet <no-reply@example.com>",
        )
    assert "TRUSTED_PROXY_CIDRS" in str(error.value)


def test_hardened_environment_rejects_default_database_and_insecure_storage() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            database_url="postgresql+psycopg://readyset:readyset@db.internal/readyset",
            public_web_url="https://app.readyset.example",
            cors_origins=["https://app.readyset.example"],
            cookie_secure=True,
            google_redirect_uri="https://app.readyset.example/api/v1/auth/google/callback",
            development_token_exposure=False,
            rate_limit_backend="redis",
            redis_url="rediss://redis.internal:6379/0",
            uploads_enabled=False,
            password_auth_enabled=False,
            invitations_enabled=False,
            storage_endpoint_url="http://objects.internal",
            storage_access_key="production-access",
            storage_secret_key="production-secret",
            storage_auto_create_bucket=False,
            storage_encryption="AES256",
            email_from="ReadySet <no-reply@readyset.example>",
        )
    message = str(error.value)
    assert "database credentials" in message
    assert "STORAGE_ENDPOINT_URL" in message


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"public_web_url": "http://app.example"}, "PUBLIC_WEB_URL"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"development_token_exposure": True}, "DEVELOPMENT_TOKEN_EXPOSURE"),
        ({"email_backend": "capture"}, "SMTP"),
        ({"rate_limit_backend": "memory"}, "RATE_LIMIT_BACKEND"),
        ({"scanner_backend": "noop"}, "SCANNER_BACKEND"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"google_redirect_uri": "https://wrong.example/callback"}, "GOOGLE_REDIRECT_URI"),
    ],
)
def test_hardened_configuration_fails_closed(override: dict[str, object], expected: str) -> None:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+psycopg://app:strong-db-password@db.internal/readyset",
        "public_web_url": "https://app.example",
        "cors_origins": ["https://app.example"],
        "cookie_secure": True,
        "google_redirect_uri": "https://app.example/api/v1/auth/google/callback",
        "development_token_exposure": False,
        "rate_limit_backend": "redis",
        "redis_url": "rediss://redis.internal:6379/0",
        "scanner_backend": "clamav",
        "clamav_host": "clamav.internal",
        "email_backend": "smtp",
        "email_from": "ReadySet <no-reply@example.com>",
        "smtp_host": "smtp.internal",
        "smtp_username": "app",
        "smtp_password": "strong-secret",
        "storage_endpoint_url": "https://objects.internal",
        "storage_access_key": None,
        "storage_secret_key": None,
        "storage_auto_create_bucket": False,
        "storage_encryption": "AES256",
    }
    values.update(override)
    with pytest.raises(ValidationError) as error:
        Settings(**values)
    assert expected in str(error.value)
