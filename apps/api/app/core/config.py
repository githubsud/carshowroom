"""Service configuration, read from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Working product name (SPEC §1): change it here only.
PRODUCT_NAME = "SayyaraDMS"
API_PREFIX = "/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "testing", "production"] = "development"

    # Direct Postgres connection as the app_api role (never service_role).
    database_url: str

    supabase_url: str
    # Defaults to {supabase_url}/auth/v1/.well-known/jwks.json
    supabase_jwks_url: str | None = None
    # Legacy HS256 projects only; asymmetric (JWKS) signing is preferred.
    supabase_jwt_secret: SecretStr | None = None
    # Used only for Auth admin calls (invites) and Storage signed URLs.
    supabase_service_role_key: SecretStr | None = None
    jwt_audience: str = "authenticated"

    # AES-256 key (base64, 32 bytes) for national IDs (DECISIONS D-05). Without it,
    # national IDs cannot be stored or revealed; everything else works.
    national_id_key: SecretStr | None = None

    cors_origins: list[str] = ["http://localhost:4200", "http://127.0.0.1:4200"]
    invite_redirect_url: str = "http://localhost:4200/reset-password"

    @property
    def jwks_url(self) -> str:
        return self.supabase_jwks_url or f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    # Required values come from the environment / .env file.
    return Settings()
