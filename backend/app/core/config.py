from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


OIDCAlgorithm = Literal["RS256", "ES256", "EdDSA"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTDOCK_",
        env_ignore_empty=True,
        extra="ignore",
    )

    service_name: str = "AgentDock API"
    app_version: str = "0.2.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: SecretStr | None = None

    # Configure all three values together. The audience must identify this API,
    # not merely the Android OAuth client ID.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_authorized_party: str | None = None
    oidc_allowed_client_ids: list[str] = Field(default_factory=list)
    oidc_allowed_algorithms: list[OIDCAlgorithm] = Field(default_factory=lambda: ["RS256"])
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=120)
    oidc_jwks_timeout_seconds: int = Field(default=5, ge=1, le=10)
    session_access_token_minutes: int = Field(default=15, ge=5, le=60)
    session_max_lifetime_days: int = Field(default=30, ge=1, le=90)

    # Worker process (python -m app.worker). The worker uses its own least-privilege
    # database role and credentials; it never reuses the API runtime or migrator role.
    worker_database_url: SecretStr | None = None
    worker_handler: str | None = None
    worker_lease_seconds: int = Field(default=30, ge=5, le=600)
    worker_heartbeat_seconds: int = Field(default=10, ge=1, le=300)
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    worker_task_timeout_seconds: int = Field(default=300, ge=5, le=3600)
    worker_retry_base_seconds: float = Field(default=5.0, ge=0.1, le=600)
    worker_retry_max_seconds: float = Field(default=300.0, ge=0.1, le=3600)
    worker_shutdown_grace_seconds: float = Field(default=20.0, ge=0, le=300)
    worker_health_port: int | None = Field(default=None, ge=1, le=65535)

    # Server-sent events for task timelines.
    sse_heartbeat_seconds: float = Field(default=15.0, ge=0.1, le=60)
    sse_poll_seconds: float = Field(default=2.0, ge=0.05, le=30)
    sse_max_lifetime_seconds: float = Field(default=300.0, ge=0.5, le=3600)
    sse_revalidate_seconds: float = Field(default=20.0, ge=0.05, le=300)

    @property
    def oidc_enabled(self) -> bool:
        return all((self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url))

    @model_validator(mode="after")
    def validate_oidc_configuration(self) -> "Settings":
        if self.worker_heartbeat_seconds * 2 >= self.worker_lease_seconds:
            raise ValueError("WORKER_HEARTBEAT_SECONDS must be less than half of WORKER_LEASE_SECONDS.")
        configured = (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        if any(configured) and not all(configured):
            raise ValueError("OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL must be configured together.")
        if self.oidc_authorized_party and not self.oidc_enabled:
            raise ValueError("OIDC_AUTHORIZED_PARTY requires complete OIDC configuration.")
        if self.oidc_enabled:
            for label, value in (("issuer", self.oidc_issuer), ("JWKS URL", self.oidc_jwks_url)):
                parsed = urlsplit(value or "")
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError(f"OIDC {label} must be an absolute HTTPS URL without credentials, query strings or fragments.")
            if not (self.oidc_audience or "").strip():
                raise ValueError("OIDC_AUDIENCE must not be empty.")
            if not self.oidc_allowed_algorithms:
                raise ValueError("At least one supported OIDC signing algorithm must be configured.")
            if not self.oidc_allowed_client_ids or any(
                not client_id.strip() or len(client_id) > 255
                for client_id in self.oidc_allowed_client_ids
            ):
                raise ValueError("OIDC_ALLOWED_CLIENT_IDS must contain at least one valid client ID.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
