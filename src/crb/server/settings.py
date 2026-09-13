"""Server settings, read from the environment with the ``CRB_`` prefix.

Invariants
----------
* **Fail closed on secrets.** ``CRB_ENV`` defaults to ``prod``; in prod a
  ``CRB_SECRET_KEY`` is mandatory and cookies are ``Secure``. Only ``CRB_ENV=dev``
  relaxes either (auto-generated key with a warning; ``Secure`` off).
* **Secret values never leave the process as text.** They are ``SecretStr`` fields;
  :meth:`Settings.redacted_dict` is the only serialisation and it reports
  ``configured: yes/no`` instead of the value. The database URL is reduced to its
  dialect because a PostgreSQL URL can embed a password.
* Nested groups use ``__`` as the delimiter: ``CRB_OIDC__ISSUER``,
  ``CRB_OIDC__ROLE_MAP='{"crb-admins": "admin"}'``, ``CRB_SANDBOX__EXECUTOR=docker``.
"""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger("crb.server.settings")

Env = Literal["dev", "prod"]
Role = Literal["viewer", "operator", "approver", "admin"]

#: Ascending privilege ladder. ``require_role(r)`` admits any role at or above ``r``.
ROLE_LADDER: tuple[str, ...] = ("viewer", "operator", "approver", "admin")
ROLE_RANK: dict[str, int] = {r: i for i, r in enumerate(ROLE_LADDER)}

#: Minimum length for any locally-stored password (bootstrap admin included).
MIN_PASSWORD_LENGTH = 12


class OidcSettings(BaseModel):
    """OpenID Connect (Entra ID or any compliant issuer). Enabled when issuer + client id are set."""

    issuer: str = ""
    client_id: str = ""
    client_secret: SecretStr | None = None
    scopes: str = "openid profile email"
    redirect_url: str = ""
    #: Claim carrying role/group values (a string or a list of strings).
    role_claim: str = "roles"
    #: Claim value → crb role. Values not present map to the default role ``viewer``.
    role_map: dict[str, str] = Field(default_factory=dict)
    #: Any of these values in ``role_claim`` or ``groups`` grants ``admin``.
    admin_groups: list[str] = Field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return bool(self.issuer and self.client_id)

    @field_validator("role_map")
    @classmethod
    def _roles_are_known(cls, v: dict[str, str]) -> dict[str, str]:
        bad = sorted(r for r in v.values() if r not in ROLE_RANK)
        if bad:
            raise ValueError(f"role_map targets unknown roles: {bad}; allowed {ROLE_LADDER}")
        return v


class BootstrapAdmin(BaseModel):
    """Seed admin for a fresh deployment. Honoured ONLY while the ``users`` table is empty."""

    username: str = ""
    password: SecretStr | None = None

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password and self.password.get_secret_value())


class RetentionSettings(BaseModel):
    #: Days to keep builder transcripts referenced from evidence packs. 0 = keep none (default).
    transcripts_days: int = Field(default=0, ge=0)


class SandboxSettings(BaseModel):
    #: ``docker`` (default, fail-closed isolation) or ``local`` (host execution; dev only).
    executor: Literal["local", "docker"] = "docker"
    image: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRB_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    env: Env = "prod"
    home: Path = Path(".crb")
    database_url: str | None = None
    secret_key: SecretStr | None = None
    #: Session lifetime in seconds (default 8 hours).
    session_ttl: int = Field(default=8 * 3600, ge=60)
    #: ``None`` resolves to ``env != "dev"``; an explicit value always wins.
    cookie_secure: bool | None = None
    oidc: OidcSettings = Field(default_factory=OidcSettings)
    local_auth_enabled: bool = True
    bootstrap_admin: BootstrapAdmin = Field(default_factory=BootstrapAdmin)
    #: Comma-separated or a JSON list in the environment (``NoDecode`` hands us the raw string).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    #: Client addresses whose ``X-Forwarded-For`` / ``X-Forwarded-Proto`` are believed.
    trusted_proxies: Annotated[list[str], NoDecode] = Field(default_factory=list)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    metrics_enabled: bool = True
    log_format: Literal["json", "text"] = "json"
    log_level: str = "INFO"
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    #: Seconds after which a running run with a stale heartbeat is reported degraded.
    worker_heartbeat_stale_s: int = Field(default=120, ge=1)

    @field_validator("cors_origins", "trusted_proxies", mode="before")
    @classmethod
    def _split_csv(cls, v: Any) -> Any:
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [p.strip() for p in raw.split(",") if p.strip()]
        return v

    @model_validator(mode="after")
    def _secrets_fail_closed(self) -> Settings:
        if self.secret_key is None or not self.secret_key.get_secret_value():
            if self.env == "prod":
                raise ValueError(
                    "CRB_SECRET_KEY is required when CRB_ENV=prod (set CRB_ENV=dev to auto-generate)"
                )
            self.secret_key = SecretStr(secrets.token_urlsafe(48))
            log.warning(
                "CRB_SECRET_KEY not set; generated an ephemeral key (dev only) — "
                "sessions will not survive a restart"
            )
        elif len(self.secret_key.get_secret_value()) < 32:
            raise ValueError("CRB_SECRET_KEY must be at least 32 characters")
        if self.bootstrap_admin.password is not None and (
            len(self.bootstrap_admin.password.get_secret_value()) < MIN_PASSWORD_LENGTH
        ):
            raise ValueError(
                f"CRB_BOOTSTRAP_ADMIN__PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        if self.env == "prod" and self.sandbox.executor == "local":
            log.warning("CRB_SANDBOX__EXECUTOR=local in prod: test runs are NOT isolated")
        return self

    # --- derived ---------------------------------------------------------------
    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def resolved_cookie_secure(self) -> bool:
        return (not self.is_dev) if self.cookie_secure is None else self.cookie_secure

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.home / 'crb.db'}"

    @property
    def secret_key_value(self) -> str:
        assert self.secret_key is not None  # guaranteed by the validator
        return self.secret_key.get_secret_value()

    @property
    def database_dialect(self) -> str:
        return self.resolved_database_url.split(":", 1)[0].split("+", 1)[0]

    def redacted_dict(self) -> dict[str, Any]:
        """Everything an admin may see on ``/settings``. No secret VALUE is ever included."""
        return {
            "env": self.env,
            "home": str(self.home),
            "database": {"dialect": self.database_dialect},
            "secret_key_configured": True,
            "session_ttl": self.session_ttl,
            "cookie_secure": self.resolved_cookie_secure,
            "local_auth_enabled": self.local_auth_enabled,
            "oidc": {
                "enabled": self.oidc.enabled,
                "issuer": self.oidc.issuer,
                "client_id": self.oidc.client_id,
                "client_secret_configured": bool(
                    self.oidc.client_secret and self.oidc.client_secret.get_secret_value()
                ),
                "scopes": self.oidc.scopes,
                "redirect_url": self.oidc.redirect_url,
                "role_claim": self.oidc.role_claim,
                "role_map": dict(self.oidc.role_map),
                "admin_groups": list(self.oidc.admin_groups),
            },
            "bootstrap_admin": {
                "username": self.bootstrap_admin.username,
                "password_configured": self.bootstrap_admin.configured,
            },
            "cors_origins": list(self.cors_origins),
            "trusted_proxies": list(self.trusted_proxies),
            "retention": {"transcripts_days": self.retention.transcripts_days},
            "sandbox": {"executor": self.sandbox.executor, "image": self.sandbox.image},
            "metrics_enabled": self.metrics_enabled,
            "log_format": self.log_format,
            "worker_heartbeat_stale_s": self.worker_heartbeat_stale_s,
        }


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "ROLE_LADDER",
    "ROLE_RANK",
    "BootstrapAdmin",
    "OidcSettings",
    "RetentionSettings",
    "Role",
    "SandboxSettings",
    "Settings",
]
