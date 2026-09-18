import enum
from functools import lru_cache
from ipaddress import ip_network
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, enum.Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class EmailBackend(str, enum.Enum):
    CAPTURE = "capture"
    SMTP = "smtp"


class RateLimitBackend(str, enum.Enum):
    MEMORY = "memory"
    REDIS = "redis"


class ScannerBackend(str, enum.Enum):
    NOOP = "noop"
    CLAMAV = "clamav"


class StorageEncryption(str, enum.Enum):
    NONE = "none"
    AES256 = "AES256"
    KMS = "aws:kms"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    database_url: str = "postgresql+psycopg://readyset:readyset@localhost:5432/readyset"
    public_web_url: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    cookie_secure: bool = False
    session_cookie_name: str = "rs_session"
    csrf_cookie_name: str = "rs_csrf"
    oauth_binding_cookie_name: str = "rs_oauth_binding"
    session_ttl_hours: int = 168
    oauth_state_ttl_minutes: int = 10

    password_auth_enabled: bool = True
    google_auth_enabled: bool = False
    invitations_enabled: bool = True
    development_token_exposure: bool = True
    uploads_enabled: bool = True
    rate_limit_backend: RateLimitBackend = RateLimitBackend.MEMORY
    redis_url: str | None = None
    rate_limit_key_prefix: str = "readyset:rate-limit"
    trust_proxy_headers: bool = False
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    scanner_backend: ScannerBackend = ScannerBackend.NOOP
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 10.0

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:3000/api/v1/auth/google/callback"

    email_backend: EmailBackend = EmailBackend.CAPTURE
    email_from: str = "ReadySet <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True

    storage_endpoint_url: str | None = "http://localhost:9000"
    storage_access_key: str | None = "readyset"
    storage_secret_key: str | None = "readyset-local-only"
    storage_bucket: str = "readyset-documents"
    storage_region: str = "us-east-1"
    storage_auto_create_bucket: bool = True
    storage_encryption: StorageEncryption = StorageEncryption.NONE
    storage_kms_key_id: str | None = None
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_content_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ]
    )

    @field_validator("cors_origins", "allowed_content_types", "trusted_proxy_cidrs", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: list[str]) -> list[str]:
        for cidr in value:
            ip_network(cidr, strict=False)
        return value

    @model_validator(mode="after")
    def validate_deployment(self) -> "Settings":
        hardened = self.environment in {Environment.STAGING, Environment.PRODUCTION}
        if not hardened:
            return self
        errors: list[str] = []
        web = urlparse(self.public_web_url)
        callback = urlparse(self.google_redirect_uri)
        if web.scheme != "https" or not web.netloc or web.path not in {"", "/"}:
            errors.append("PUBLIC_WEB_URL must be an absolute HTTPS origin without a path")
        expected_callback = f"{self.public_web_url.rstrip('/')}/api/v1/auth/google/callback"
        if self.google_redirect_uri != expected_callback or callback.scheme != "https":
            errors.append("GOOGLE_REDIRECT_URI must use the public web origin callback path")
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true")
        if "*" in self.cors_origins or any(
            urlparse(origin).scheme != "https" for origin in self.cors_origins
        ):
            errors.append("CORS_ORIGINS must contain explicit HTTPS origins")
        if self.public_web_url not in self.cors_origins:
            errors.append("CORS_ORIGINS must include PUBLIC_WEB_URL")
        if self.development_token_exposure:
            errors.append("DEVELOPMENT_TOKEN_EXPOSURE must be false")
        if self.rate_limit_backend != RateLimitBackend.REDIS or not self.redis_url:
            errors.append("RATE_LIMIT_BACKEND=redis and REDIS_URL are required")
        elif urlparse(self.redis_url).scheme != "rediss":
            errors.append("REDIS_URL must use rediss:// in hardened environments")
        if self.trust_proxy_headers and not self.trusted_proxy_cidrs:
            errors.append("TRUSTED_PROXY_CIDRS is required when TRUST_PROXY_HEADERS=true")
        if self.uploads_enabled and (
            self.scanner_backend != ScannerBackend.CLAMAV or not self.clamav_host
        ):
            errors.append("SCANNER_BACKEND=clamav and CLAMAV_HOST are required when uploads are enabled")
        if self.google_auth_enabled and (
            not self.google_client_id or not self.google_client_secret
        ):
            errors.append("Google credentials are required when GOOGLE_AUTH_ENABLED=true")
        if (
            self.password_auth_enabled or self.invitations_enabled
        ) and self.email_backend != EmailBackend.SMTP:
            errors.append("SMTP email delivery is required for password auth or invitations")
        if self.email_backend == EmailBackend.SMTP and (
            not self.smtp_host or not self.smtp_username or not self.smtp_password
        ):
            errors.append("SMTP_HOST, SMTP_USERNAME, and SMTP_PASSWORD are required")
        if self.email_backend == EmailBackend.SMTP and not self.smtp_starttls:
            errors.append("SMTP_STARTTLS must be true")
        forbidden_secrets = {"readyset-local-only", "replace-for-non-local-use", "readyset"}
        database = urlparse(self.database_url.replace("postgresql+psycopg", "postgresql", 1))
        if database.username in {"readyset", "postgres", "user"} or database.password in {
            "readyset",
            "password",
            "secret",
        }:
            errors.append("development/default database credentials are forbidden")
        if (
            self.storage_access_key in forbidden_secrets
            or self.storage_secret_key in forbidden_secrets
        ):
            errors.append("local/default storage credentials are forbidden")
        if bool(self.storage_access_key) != bool(self.storage_secret_key):
            errors.append("storage access and secret keys must be configured together")
        if self.storage_auto_create_bucket:
            errors.append("STORAGE_AUTO_CREATE_BUCKET must be false")
        if self.storage_encryption == StorageEncryption.NONE:
            errors.append("STORAGE_ENCRYPTION must be AES256 or aws:kms")
        if self.storage_encryption == StorageEncryption.KMS and not self.storage_kms_key_id:
            errors.append("STORAGE_KMS_KEY_ID is required for aws:kms")
        storage = urlparse(self.storage_endpoint_url or "")
        if self.storage_endpoint_url and storage.scheme != "https":
            errors.append("STORAGE_ENDPOINT_URL must use HTTPS when explicitly configured")
        if "@localhost" in self.email_from.casefold():
            errors.append("EMAIL_FROM must use a routable address")
        for name, value in (
            ("DATABASE_URL", self.database_url),
            ("STORAGE_ENDPOINT_URL", self.storage_endpoint_url or ""),
        ):
            if "localhost" in value or "127.0.0.1" in value:
                errors.append(f"{name} must not use localhost")
        if errors:
            raise ValueError("Invalid hardened-environment configuration: " + "; ".join(errors))
        return self

    @property
    def is_hardened(self) -> bool:
        return self.environment in {Environment.STAGING, Environment.PRODUCTION}

    @property
    def expose_development_tokens(self) -> bool:
        return (
            self.environment in {Environment.DEVELOPMENT, Environment.TEST}
            and self.development_token_exposure
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
