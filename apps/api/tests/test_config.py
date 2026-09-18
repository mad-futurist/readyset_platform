import pytest
from pydantic import ValidationError

from app.config import Settings


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod")


def test_hardened_environment_rejects_development_defaults() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(environment="production")
    message = str(error.value)
    assert "COOKIE_SECURE" in message
    assert "SMTP" in message
    assert "SHARED_RATE_LIMIT_ENABLED" in message


def test_valid_hardened_environment_is_accepted() -> None:
    settings = Settings(
        environment="staging",
        database_url="postgresql+psycopg://app:staging-db-password@db.internal/readyset",
        public_web_url="https://app.staging.readyset.example",
        cors_origins=["https://app.staging.readyset.example"],
        cookie_secure=True,
        google_redirect_uri=("https://app.staging.readyset.example/api/v1/auth/google/callback"),
        development_token_exposure=False,
        shared_rate_limit_enabled=True,
        email_backend="smtp",
        email_from="ReadySet <no-reply@staging.readyset.example>",
        smtp_host="smtp.internal",
        smtp_username="readyset",
        smtp_password="secret",
        storage_endpoint_url="https://objects.internal",
        storage_access_key="staging-access",
        storage_secret_key="staging-secret",
    )
    assert settings.is_hardened
    assert not settings.expose_development_tokens


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
            shared_rate_limit_enabled=True,
            password_auth_enabled=False,
            invitations_enabled=False,
            storage_endpoint_url="http://objects.internal",
            storage_access_key="production-access",
            storage_secret_key="production-secret",
            email_from="ReadySet <no-reply@readyset.example>",
        )
    message = str(error.value)
    assert "database credentials" in message
    assert "STORAGE_ENDPOINT_URL" in message
