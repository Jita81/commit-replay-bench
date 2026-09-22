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
* **A deployment never lives in a temporary directory** (DL-045). ``CRB_HOME`` under
  ``/tmp``, ``/private/tmp``, ``/var/folders`` or ``$TMPDIR`` is refused in ``prod`` and
  warned about in ``dev`` (:func:`temp_dir_reason`); ``CRB_ALLOW_TEMP_HOME=true`` is the
  explicit opt-out for a throwaway evaluation. macOS documents those paths as temporary
  and its periodic clean-up removes untouched files there.

Navigation
----------
What it is:   The server's configuration model — every ``CRB_*`` variable the API and its
              ``/settings`` view know about, with the fail-closed rules attached.
What it does: Parses the environment into typed, nested settings (OIDC, bootstrap admin,
              retention, sandbox, builder container, factory); refuses to start in ``prod`` without a
              strong ``CRB_SECRET_KEY``, with a short bootstrap password or with a ``CRB_HOME``
              under an OS-managed temporary directory (``dev`` warns); keeps secret
              values as ``SecretStr`` and exposes only ``redacted_dict`` for display. Defines
              the role ladder and ``MIN_PASSWORD_LENGTH`` the auth module enforces.
How:          ``pydantic-settings`` with ``CRB_`` prefix and ``__`` nesting; CSV-or-JSON
              list fields via ``NoDecode`` + a ``before`` validator; an ``after`` validator
              generates a dev-only ephemeral key, applies the temporary-home guard
              (``temp_dir_reason``) and logs the prod warnings.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/server/app.py (reads ``resolved_database_url``, cookie security, CORS),
              src/crb/server/auth.py (``ROLE_RANK``, ``session_ttl``, ``secret_key_value``),
              src/crb/server/routes/system.py (serves ``redacted_dict``),
              src/crb/builders/container.py (the worker reads the same ``CRB_BUILDER__*``),
              src/crb/cli/commands/service.py (``crb doctor``'s ``home`` line reuses
              ``temp_dir_reason``), src/crb/factory/author.py (the rung spelling
              ``CRB_FACTORY__TEST_AUTHOR`` carries and the refusal it feeds),
              docs/DEPLOYMENT.md#21-environment-reference (the operator-facing list; §1.1 the
              temporary-directory rule)
Tested by:    tests/test_server_app.py, tests/test_server_system.py, tests/test_server_auth.py,
              tests/test_settings_home_guard.py
Touch when:   never for a new repository (repositories are configured in the database, not
              the environment); adding a variable means adding it here, to ``redacted_dict``
              (never a secret value), to docs/DEPLOYMENT.md#21-environment-reference and to
              the Helm/compose templates under deploy/.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from collections.abc import Mapping
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

#: OS-managed temporary roots (``$TMPDIR`` is added at run time). On macOS ``/tmp`` and
#: ``/var`` are symlinks into ``/private``, so both spellings are listed and both sides are
#: resolved before the comparison. ``/var/tmp`` is included because systemd-tmpfiles ages it
#: (30 days on the RHEL family) even though Debian's default does not.
TEMP_DIR_ROOTS: tuple[str, ...] = (
    "/tmp",
    "/private/tmp",
    "/var/tmp",
    "/private/var/tmp",
    "/var/folders",
    "/private/var/folders",
)
#: What the guard tells the person, once, in the refusal and in the warning.
TEMP_HOME_ADVICE = (
    "macOS's periodic clean-up removes untouched files there and a reboot may empty it; "
    "put the deployment under a persistent path such as ~/crb-stack or "
    "/srv/crb (docs/DEPLOYMENT.md#11-single-host-without-containers-evaluation)"
)


def temp_dir_reason(path: Path | str, environ: Mapping[str, str] | None = None) -> str | None:
    """Why ``path`` is under an OS-managed temporary directory, or ``None`` when it is not.

    ``path`` is expanded and resolved (non-strict: it need not exist); each root in
    :data:`TEMP_DIR_ROOTS` plus ``$TMPDIR`` is compared both as written and resolved, so a
    symlinked root (``/tmp`` to ``/private/tmp``) is recognised either way. The sentence
    names the path and the root it fell under.
    """
    env = os.environ if environ is None else environ
    target = Path(path).expanduser()
    try:
        resolved = target.resolve()
    except OSError:  # pragma: no cover - a path the OS refuses to resolve
        resolved = target.absolute()
    shown = target if target.is_absolute() else resolved
    tmpdir = (env.get("TMPDIR") or "").strip()
    roots: list[tuple[str, Path]] = [("", Path(r)) for r in TEMP_DIR_ROOTS]
    if tmpdir:
        roots.append((f"$TMPDIR ({tmpdir})", Path(tmpdir).expanduser()))
    for label, root in roots:
        try:
            candidates = {root, root.resolve()}
        except OSError:  # pragma: no cover
            candidates = {root}
        for candidate in candidates:
            if resolved == candidate or candidate in resolved.parents:
                return (
                    f"{shown} resolves under {label or candidate}, an OS-managed temporary "
                    "directory"
                )
    return None


class GitHubAppSettings(BaseModel):
    """The GitHub App this deployment is registered as (docs/GITHUB-APP.md) — the enterprise
    connection: an org installs the app on *selected* repositories, the product mints
    short-lived installation tokens to clone (and, where the installation grants it, to
    deliver). Enabled when ``app_id`` and a private key are set. ``CRB_GITHUB__*``.

    The private key is the app's RS256 key (PEM): ``private_key`` inline (a secret store
    hands it over as one value) or ``private_key_file`` (a mounted file). ``api_url`` and
    ``web_url`` point at GitHub Enterprise Server when the org runs one.
    """

    app_id: str = ""
    #: The app's URL slug (``https://github.com/apps/<slug>``) — the install link.
    app_slug: str = ""
    private_key: SecretStr | None = None
    private_key_file: str = ""
    webhook_secret: SecretStr | None = None
    api_url: str = "https://api.github.com"
    web_url: str = "https://github.com"

    @property
    def enabled(self) -> bool:
        return bool(self.app_id.strip()) and bool(self.private_key_pem())

    def private_key_pem(self) -> str:
        """The PEM text, from the inline value or the file; ``""`` when neither is set."""
        if self.private_key and self.private_key.get_secret_value().strip():
            return self.private_key.get_secret_value()
        if self.private_key_file:
            try:
                return Path(self.private_key_file).read_text(encoding="utf-8")
            except OSError:
                return ""
        return ""

    @property
    def install_url(self) -> str:
        """Where an org admin installs the app (the ``Setup URL`` brings them back)."""
        return (
            f"{self.web_url.rstrip('/')}/apps/{self.app_slug}/installations/new"
            if self.app_slug
            else ""
        )

    @field_validator("api_url", "web_url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        raw = v.strip().rstrip("/")
        if raw and not raw.lower().startswith("https://"):
            raise ValueError(f"GitHub URLs must be https://, got {raw!r}")
        return raw


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

    @field_validator("issuer")
    @classmethod
    def _issuer_is_https(cls, v: str) -> str:
        # OIDC discovery, token exchange and the JWKS fetch all hang off the issuer;
        # a plain-http issuer would let an on-path attacker mint the ID token that
        # grants a role (CodeRabbit on PR #4, 2026-09-15). Empty = OIDC disabled.
        raw = v.strip()
        if raw and not raw.lower().startswith("https://"):
            raise ValueError(f"oidc issuer must be an https:// URL, got {raw!r}")
        return raw

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
    """Zero-raw-retention defaults (ADR-0006); only transcripts have a knob today."""

    #: Days to keep builder transcripts referenced from evidence packs. 0 = keep none (default).
    transcripts_days: int = Field(default=0, ge=0)


class SandboxSettings(BaseModel):
    """Where repository TESTS run (ADR-0005) — distinct from ``BuilderSettings``, which is
    where the builder's attempt runs."""

    #: ``docker`` (default, fail-closed isolation) or ``local`` (host execution; dev only).
    executor: Literal["local", "docker"] = "docker"
    image: str = ""


class FactorySettings(BaseModel):
    """The served factory's deployment defaults (``CRB_FACTORY__*``).

    ``test_author`` is the rung that writes the failing test for an item nobody authored
    an oracle for — the same ``builder:model[:provider]`` spelling as a build rung,
    because the refusal that keeps an author out of its own build compares rung labels
    (:mod:`crb.factory.author`). Empty (the default) means no author: an item without an
    operator-authored test stops ``no_oracle`` and waits for a person, which is what this
    product did before the setting existed. A run may override it
    (``params.test_author``); ``none`` in either place means no author.
    """

    test_author: str = ""

    @field_validator("test_author")
    @classmethod
    def _rung_shaped(cls, v: str) -> str:
        # a typo fails at start-up, not half-way through a paid run
        raw = v.strip()
        if raw and raw.lower() != "none" and ":" not in raw:
            raise ValueError(
                "CRB_FACTORY__TEST_AUTHOR must be a rung, 'builder:model[:provider]' "
                "(or 'none' / empty for no test author)"
            )
        return raw

    def redacted(self) -> dict[str, Any]:
        """The ``/settings`` view. Nothing here is secret, and an absent author is a state
        an operator needs to see — it is why items stop ``no_oracle``."""
        return {"test_author": self.test_author or "none"}


class BuilderSettings(BaseModel):
    """Where the builder attempt runs (ADR-0012). Read by the worker from the same
    ``CRB_BUILDER__*`` variables (:meth:`crb.builders.container.BuilderContainerSettings.from_env`);
    this model is the API's view of that posture for ``/settings`` and ``crb doctor``.

    ``docker``: a sealed export of the parent tree, built inside ``image`` on an
    internal network whose only egress is the allowlisting proxy (``allow_hosts``,
    ``host[:port]``; empty ⇒ no network at all). ``host`` (default): the builder runs
    in the worker's process / host worktree — development and evaluation only.
    """

    executor: Literal["host", "docker"] = "host"
    image: str = ""
    proxy_image: str = ""
    #: Comma-separated or a JSON list in the environment (``NoDecode`` hands us the raw string).
    allow_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["api.anthropic.com"]
    )
    egress_network: str = "bridge"
    memory: str = "4g"
    cpus: str = "2"
    pids_limit: int = Field(default=1024, ge=1)
    tmp_size: str = "1g"
    #: ``uid:gid`` for the builder container; empty ⇒ the worker's own uid:gid. Root is refused by the worker.
    user: str = ""
    #: The Claude Code CLI the API host runs for the login flow and the verify probe
    #: (``CRB_BUILDER__CLAUDE_BINARY``); empty ⇒ ``claude`` on PATH. The worker resolves its
    #: own binary through the builder config; this is the API's.
    claude_binary: str = ""

    @field_validator("allow_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, v: Any) -> Any:
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [p.strip() for p in raw.split(",") if p.strip()]
        return v

    @model_validator(mode="after")
    def _docker_needs_image(self) -> BuilderSettings:
        if self.executor == "docker" and not self.image.strip():
            raise ValueError("CRB_BUILDER__IMAGE is required when CRB_BUILDER__EXECUTOR=docker")
        return self

    def redacted(self) -> dict[str, Any]:
        """The ``/settings`` view of the builder posture (nothing here is secret, but the
        derived ``egress_network: none`` reading is what an operator needs to see)."""
        return {
            "executor": self.executor,
            "image": self.image,
            "claude_binary": self.claude_binary or "claude (PATH)",
            "proxy_image": self.proxy_image or self.image,
            "allow_hosts": list(self.allow_hosts),
            "egress_network": self.egress_network if self.allow_hosts else "none",
            "memory": self.memory,
            "cpus": self.cpus,
            "pids_limit": self.pids_limit,
            "user": self.user or "worker uid:gid",
        }


class Settings(BaseSettings):
    """The top-level settings object: one instance per app, built from the environment
    (or by a test with keyword arguments). See the module docstring for the invariants."""

    model_config = SettingsConfigDict(
        env_prefix="CRB_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    env: Env = "prod"
    home: Path = Path(".crb")
    #: ``CRB_ALLOW_TEMP_HOME=true`` admits a ``home`` under an OS temporary directory in
    #: ``prod`` — for a throwaway evaluation only; the warning is still logged.
    allow_temp_home: bool = False
    database_url: str | None = None
    secret_key: SecretStr | None = None
    #: Session lifetime in seconds (default 8 hours).
    session_ttl: int = Field(default=8 * 3600, ge=60)
    #: ``None`` resolves to ``env != "dev"``; an explicit value always wins.
    cookie_secure: bool | None = None
    oidc: OidcSettings = Field(default_factory=OidcSettings)
    github: GitHubAppSettings = Field(default_factory=GitHubAppSettings)
    local_auth_enabled: bool = True
    bootstrap_admin: BootstrapAdmin = Field(default_factory=BootstrapAdmin)
    #: Comma-separated or a JSON list in the environment (``NoDecode`` hands us the raw string).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    #: Client addresses whose ``X-Forwarded-For`` / ``X-Forwarded-Proto`` are believed.
    trusted_proxies: Annotated[list[str], NoDecode] = Field(default_factory=list)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    builder: BuilderSettings = Field(default_factory=BuilderSettings)
    factory: FactorySettings = Field(default_factory=FactorySettings)
    metrics_enabled: bool = True
    log_format: Literal["json", "text"] = "json"
    log_level: str = "INFO"
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    #: Seconds after which a running run with a stale heartbeat is reported degraded.
    worker_heartbeat_stale_s: int = Field(default=120, ge=1)
    #: Built UI directory (``ui/dist``). When it exists the API serves it at ``/`` with an
    #: ``index.html`` fallback for deep links; API paths never fall through to it.
    ui_dist: str = ""

    @field_validator("cors_origins", "trusted_proxies", mode="before")
    @classmethod
    def _split_csv(cls, v: Any) -> Any:
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [p.strip() for p in raw.split(",") if p.strip()]
        return v

    @field_validator("cors_origins")
    @classmethod
    def _cors_origins_are_explicit(cls, v: list[str]) -> list[str]:
        # The middleware always sends ``Access-Control-Allow-Credentials``; with ``*``
        # every site could drive the session cookie (CodeRabbit on PR #4, 2026-09-15).
        # Starlette also refuses to echo an origin for ``*`` + credentials, so a wildcard
        # is both unsafe in intent and silently broken — fail at start-up instead.
        bad = [
            o
            for o in v
            if o.strip() in {"*", "null"} or not o.strip().startswith(("http://", "https://"))
        ]
        if bad:
            raise ValueError(
                f"cors_origins must be explicit http(s) origins (no '*' / 'null'), got {bad}"
            )
        return v

    @model_validator(mode="after")
    def _secrets_fail_closed(self) -> Settings:
        # The fail-closed rules of the module docstring live here so that a Settings that
        # constructed at all is one the server may run with.
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
        reason = temp_dir_reason(self.home)
        if reason:
            if self.env == "prod" and not self.allow_temp_home:
                raise ValueError(
                    f"CRB_HOME {reason}; {TEMP_HOME_ADVICE}; set CRB_ALLOW_TEMP_HOME=true only "
                    "for a throwaway evaluation"
                )
            log.warning("CRB_HOME %s; %s", reason, TEMP_HOME_ADVICE)
        if self.env == "prod" and self.sandbox.executor == "local":
            log.warning("CRB_SANDBOX__EXECUTOR=local in prod: test runs are NOT isolated")
        if self.env == "prod" and self.builder.executor == "host":
            log.warning(
                "CRB_BUILDER__EXECUTOR=host in prod: builder attempts run on the host with a "
                "worktree that shares the main clone's objects (ADR-0012 recommends docker)"
            )
        return self

    # --- derived ---------------------------------------------------------------
    @property
    def is_dev(self) -> bool:
        """``CRB_ENV=dev`` — the only mode that relaxes a secret or cookie rule."""
        return self.env == "dev"

    @property
    def resolved_cookie_secure(self) -> bool:
        """``Secure`` on cookies: explicit setting, else ``True`` outside dev."""
        return (not self.is_dev) if self.cookie_secure is None else self.cookie_secure

    @property
    def resolved_database_url(self) -> str:
        """``CRB_DATABASE_URL`` or the SQLite file under ``home`` (same rule as the store)."""
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.home / 'crb.db'}"

    @property
    def secret_key_value(self) -> str:
        """The signing key as text — for the cookie serialisers only, never for display."""
        assert self.secret_key is not None  # guaranteed by the validator
        return self.secret_key.get_secret_value()

    @property
    def database_dialect(self) -> str:
        """``sqlite`` / ``postgresql`` — all of the URL that may be shown or logged."""
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
            "github": {
                "enabled": self.github.enabled,
                "app_id": self.github.app_id,
                "app_slug": self.github.app_slug,
                "api_url": self.github.api_url,
                "install_url": self.github.install_url,
                "private_key_configured": bool(self.github.private_key_pem()),
                "webhook_secret_configured": bool(
                    self.github.webhook_secret and self.github.webhook_secret.get_secret_value()
                ),
            },
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
            "builder": self.builder.redacted(),
            "factory": self.factory.redacted(),
            "metrics_enabled": self.metrics_enabled,
            "log_format": self.log_format,
            "worker_heartbeat_stale_s": self.worker_heartbeat_stale_s,
        }


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "ROLE_LADDER",
    "ROLE_RANK",
    "TEMP_DIR_ROOTS",
    "TEMP_HOME_ADVICE",
    "BootstrapAdmin",
    "BuilderSettings",
    "FactorySettings",
    "OidcSettings",
    "RetentionSettings",
    "Role",
    "SandboxSettings",
    "Settings",
    "temp_dir_reason",
]
