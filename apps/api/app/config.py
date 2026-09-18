from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://readyset:readyset@localhost:5432/readyset"
    web_url: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    cookie_secure: bool = False
    session_cookie_name: str = "rs_session"
    csrf_cookie_name: str = "rs_csrf"
    session_ttl_hours: int = 168

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"

    storage_endpoint_url: str = "http://localhost:9000"
    storage_access_key: str = "readyset"
    storage_secret_key: str = "readyset-local-only"
    storage_bucket: str = "readyset-documents"
    storage_region: str = "us-east-1"
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_content_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ]
    )

    @field_validator("cors_origins", "allowed_content_types", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
