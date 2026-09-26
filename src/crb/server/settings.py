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
* **Production refuses the unsealed posture** (ADR-0023). ``CRB_ENV=prod`` with the host
  builder (``CRB_BUILDER__EXECUTOR=host``) or the local test executor
  (``CRB_SANDBOX__EXECUTOR=local``) does not start unless ``CRB_ALLOW_UNSEALED_PROD=1`` says
  so on purpose; the override is shown by :meth:`Settings.posture` (``/health``,
  ``/settings``, the Posture page) and the worker stamps it into every run's apparatus. In
  ``prod`` the builder defaults to ``docker``; in ``dev`` to ``host``.
  :func:`unsealed_prod_refusal` is the one rule; ``crb worker`` applies the same function.
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
              under an OS-managed temporary directory (``dev`` warns), or with the host builder
              or the local executor unless ``CRB_ALLOW_UNSEALED_PROD=1`` (ADR-0023); keeps secret
              values as ``SecretStr`` and exposes only ``redacted_dict`` for display. Defines
              the role ladder and ``MIN_PASSWORD_LENGTH`` the auth module enforces.
How:          ``pydantic-settings`` with ``CRB_`` prefix and ``__`` nesting; CSV-or-JSON
              list fields via ``NoDecode`` + a ``before`` validator; an ``after`` validator
              generates a dev-only ephemeral key, applies the temporary-home guard
              (``temp_dir_reason``), resolves the builder's default executor for the env and
              applies ``unsealed_prod_refusal``.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md,
              docs/adr/0023-production-refuses-the-unsealed-posture.md
Works with:   src/crb/server/worker_main.py (the worker applies ``unsealed_prod_refusal`` to
              its own reading of the same environment), src/crb/server/app.py (reads
              ``resolved_database_url``, cookie security, CORS),
              src/crb/server/auth.py (``ROLE_RANK``, ``session_ttl``, ``secret_key_value``),
              src/crb/server/routes/system.py (serves ``redacted_dict``),
              src/crb/builders/container.py (the worker reads the same ``CRB_BUILDER__*``),
              src/crb/cli/commands/service.py (``crb doctor``'s ``home`` line reuses
              ``temp_dir_reason``), src/crb/provision/config.py (the worker's side of
              ``CRB_PROVISION__*`` and its production refusals), src/crb/factory/author.py (the rung spelling
              ``CRB_FACTORY__TEST_AUTHOR`` carries and the refusal it feeds),
              docs/DEPLOYMENT.md#21-environment-reference (the operator-facing list; §1.1 the
              temporary-directory rule)
Tested by:    tests/test_server_app.py, tests/test_server_system.py, tests/test_server_auth.py,
              tests/test_settings_home_guard.py, tests/test_settings_posture.py
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
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from crb.provision.config import (
    DEFAULT_GO_IMAGE,
    DEFAULT_NODE_IMAGE,
    DEFAULT_PYTHON_IMAGE,
    ProvisionConfig,
)

log = logging.getLogger("crb.server.settings")

Env = Literal["dev", "prod"]
BuilderExecutor = Literal["host", "docker"]
Role = Literal["viewer", "operator", "approver", "admin"]

#: Ascending privilege ladder. ``require_role(r)`` admits any role at or above ``r``.
ROLE_LADDER: tuple[str, ...] = ("viewer", "operator", "approver", "admin")
ROLE_RANK: dict[str, int] = {r: i for i, r in enumerate(ROLE_LADDER)}

#: Minimum length for any locally-stored password (bootstrap admin included).
MIN_PASSWORD_LENGTH = 12

#: The only hosts ``CRB_PUBLIC_URL`` may name over plain http: a developer's own machine and
#: the walkthrough stack, which has no certificate. Matched against the PARSED host name, so
#: a name that merely starts with one of these ("localhost.example.com") is not one of them.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

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


#: The one explicit opt-in to running production unsealed (ADR-0023). Its presence is the
#: operator's statement that this deployment's measurements are a development reading.
ALLOW_UNSEALED_PROD_ENV = "CRB_ALLOW_UNSEALED_PROD"
#: The sealed kind for both executors: tests in the fail-closed sandbox (ADR-0005), the
#: builder in its sealed container (ADR-0012).
SEALED_EXECUTOR = "docker"
#: Where the full rule is explained to the person who meets the refusal.
UNSEALED_PROD_DOC = "docs/SECURITY.md#5-what-this-document-does-not-claim"


def default_builder_executor(env: str) -> BuilderExecutor:
    """The builder's executor when ``CRB_BUILDER__EXECUTOR`` is not set: the sealed
    container in ``prod``, the host in ``dev`` (ADR-0023)."""
    return "docker" if env == "prod" else "host"


def unsealed_prod_refusal(
    env: str, sandbox_executor: str, builder_executor: str, *, allow: bool
) -> str:
    """Why this posture may not run, or ``""`` when it may (ADR-0023).

    ``prod`` with a test executor or a builder executor that is not :data:`SEALED_EXECUTOR`
    is refused unless ``allow`` (``CRB_ALLOW_UNSEALED_PROD=1``) says so on purpose. ``dev``
    and a sealed ``prod`` are never refused. The API's :class:`Settings` and the worker's
    entrypoint (``crb.server.worker_main``) both call this, so the two processes cannot
    disagree about what production may run.
    """
    if env != "prod" or allow:
        return ""
    unsealed: list[str] = []
    if sandbox_executor != SEALED_EXECUTOR:
        unsealed.append(
            f"CRB_SANDBOX__EXECUTOR={sandbox_executor} (repository tests would run on the host, "
            "outside the sealed sandbox)"
        )
    if builder_executor != SEALED_EXECUTOR:
        unsealed.append(
            f"CRB_BUILDER__EXECUTOR={builder_executor} (the builder would run on the host with "
            "Bash, its API key and the gold commit within reach)"
        )
    if not unsealed:
        return ""
    return (
        "production refuses the unsealed posture (ADR-0023): "
        + "; ".join(unsealed)
        + f". Use docker for both, or set {ALLOW_UNSEALED_PROD_ENV}=1 to run unsealed on "
        "purpose: the override is shown on /health and the Posture page and stamped into "
        "every run's apparatus, and what such a run measures is a development reading, not "
        f"evidence ({UNSEALED_PROD_DOC})"
    )


def factory_builds_posture(env: str, *, allow: bool) -> str:
    """Where a factory run's builds happen (ADR-0023): ``refused`` in ``prod`` unless
    ``allow``, else ``host``. A factory build runs the builder on a host worktree and is never
    sealed, so a sealed ``prod`` posture cannot admit one without the override. The API serves
    this on ``/health``; the worker applies the same rule (``Worker._run_factory``)."""
    return "refused" if env == "prod" and not allow else "host"


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
    #: When the claims set an account's role: ``first_login`` (default) — on the account's
    #: first sign-in only, so an admin's later change stands; ``always`` — on every sign-in
    #: (the provider is the source of truth), each change recorded as ``user.role_overridden``.
    role_from_claims: Literal["first_login", "always"] = "first_login"

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
    """Raw-retention defaults (ADR-0006 and its 2026-09-25 amendment)."""

    #: Days to keep builder transcripts referenced from evidence packs. 0 = keep none (default).
    transcripts_days: int = Field(default=0, ge=0)
    #: Keep every graded attempt's patch — redacted, capped at 1 MiB, content-addressed under
    #: ``<home>/evidence/patches`` and anchored by its evidence pack (crb.core.patches) — for
    #: as long as its row. ``false`` for a deployment that must keep no code.
    patches: bool = True


class SandboxSettings(BaseModel):
    """Where repository TESTS run (ADR-0005) — distinct from ``BuilderSettings``, which is
    where the builder's attempt runs."""

    #: ``docker`` (default, fail-closed isolation) or ``local`` (host execution; dev only).
    executor: Literal["local", "docker"] = "docker"
    image: str = ""
    #: ``copy`` (default): tests run in a throwaway copy of the read-only worktree;
    #: ``readonly``: the worktree itself, read-only — a different posture (ADR-0019 §7).
    tree: Literal["copy", "readonly"] = "copy"
    #: The size cap of the throwaway copy (a tmpfs, so it counts against the container's memory).
    work_size: str = "1g"


class ProvisionSettings(BaseModel):
    """Dependency provisioning (ADR-0019, ``CRB_PROVISION__*``): a task's dependencies are
    fetched outside the test container, sealed and mounted read-only. OFF by default —
    switching it on is the operator's consent to a fetch through their egress. In ``prod``
    a public registry is refused unless ``allow_public`` is set (a mirror inside the tenant
    is the documented shape) and every fetch image must be pinned by digest. The worker
    reads the same variables (:meth:`crb.provision.config.ProvisionConfig.from_env`)."""

    enabled: bool = False
    #: Empty ⇒ ``<CRB_HOME>/deps``. Must be a path the docker daemon can bind-mount.
    store: str = ""
    go_proxy: str = "https://proxy.golang.org"
    go_sumdb: str = "sum.golang.org"
    pypi_index: str = "https://pypi.org/simple"
    pypi_files_host: str = "files.pythonhosted.org"
    npm_registry: str = "https://registry.npmjs.org"
    #: Comma-separated or a JSON list in the environment (``NoDecode`` hands us the raw string).
    extra_allow_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allow_public: bool = False
    egress_network: str = "bridge"
    proxy_image: str = ""
    go_image: str = ""
    python_image: str = ""
    node_image: str = ""
    ca_bundle: str = ""
    max_bundle_mb: int = Field(default=2048, ge=1)
    max_total_gb: float = Field(default=20.0, gt=0)
    fetch_timeout_s: int = Field(default=900, ge=1)

    @field_validator("extra_allow_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, v: Any) -> Any:
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                return json.loads(raw)
            return [p.strip() for p in raw.split(",") if p.strip()]
        return v

    def to_config(self, *, env: str, home: Path) -> ProvisionConfig:
        """The worker-side configuration; its own validation (the allowlist parsed by the
        egress proxy's ``parse_allow``, ``GO_PROXY`` never ``direct``) raises ``ValueError``."""
        return ProvisionConfig(
            enabled=self.enabled,
            store=Path(self.store) if self.store else Path(home) / "deps",
            go_proxy=self.go_proxy,
            go_sumdb=self.go_sumdb,
            pypi_index=self.pypi_index,
            pypi_files_host=self.pypi_files_host,
            npm_registry=self.npm_registry,
            extra_allow_hosts=tuple(self.extra_allow_hosts),
            allow_public=self.allow_public,
            egress_network=self.egress_network,
            proxy_image=self.proxy_image,
            go_image=self.go_image or DEFAULT_GO_IMAGE,
            python_image=self.python_image or DEFAULT_PYTHON_IMAGE,
            node_image=self.node_image or DEFAULT_NODE_IMAGE,
            ca_bundle=self.ca_bundle,
            max_bundle_mb=self.max_bundle_mb,
            max_total_gb=self.max_total_gb,
            fetch_timeout_s=self.fetch_timeout_s,
            env=env,
        )


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
    ``host[:port]``; empty ⇒ no network at all). ``host``: the builder runs in the
    worker's process / host worktree — development and evaluation only. Unset (``None``)
    resolves in :class:`Settings` to ``docker`` in ``prod`` and ``host`` in ``dev``
    (ADR-0023). An EXPLICIT ``docker`` needs ``image`` at start-up; the defaulted one does
    not, and the worker fails closed when it builds without one.
    """

    executor: BuilderExecutor | None = None
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

    @field_validator("executor", mode="before")
    @classmethod
    def _blank_is_unset(cls, v: Any) -> Any:
        # an empty CRB_BUILDER__EXECUTOR (a template's placeholder) means "the env's default"
        return None if isinstance(v, str) and not v.strip() else v

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


class IntakeSettings(BaseModel):
    """The tracker this deployment takes work from (``CRB_INTAKE__*``).

    This is the *connection* only — which tracker, where, which project, which column.
    Whether a given repository's listener is ON is not here: it is per repository, it
    defaults to OFF, and an operator throws it on the Intake screen
    (:class:`crb.server.intake.ListenerState`). The credential is not here either: it
    lives in the product's own secret store as ``tracker_token`` and is read back as a
    fingerprint, exactly like the GitHub App key.

    ``tracker: none`` (the default) means no column is watched anywhere, whatever any
    repository's listener says.
    """

    #: ``fake`` is the walkthrough's file-backed board; it is refused unless
    #: ``CRB_ENABLE_FAKE_TRACKER=1`` is set, like the fixture builder.
    tracker: Literal["none", "ado", "jira", "fake"] = "none"
    #: Azure DevOps organisation URL (``https://dev.azure.com/contoso``) or Jira site URL
    #: (``https://contoso.atlassian.net``).
    url: str = ""
    project: str = ""
    #: The state (Azure DevOps) or status (Jira) the listener watches.
    column: str = ""
    #: Azure DevOps only: restrict the query to one area path.
    area_path: str = ""
    #: Jira only: extra JQL ANDed onto the query, the account email the API token belongs
    #: to, and the custom fields holding story points and acceptance criteria on that site.
    jql: str = ""
    email: str = ""
    points_field: str = ""
    acceptance_field: str = ""
    #: Seconds between polls of a switched-on repository's column.
    poll_s: int = Field(default=300, ge=30)
    #: The most tickets ONE pass may read. A pass costs about eleven tracker calls per
    #: ticket, and Azure DevOps will answer a query with up to 20,000 ids, so an
    #: unbounded pass would starve the worker's heartbeat and hold an API thread for as
    #: long as the column is long. A column with more than this in it is not read at all:
    #: the pass stops with ``column_too_large`` and says to narrow the area path or the
    #: JQL, because reading an arbitrary 200 of somebody's board and saying nothing about
    #: the rest would be worse than reading none of it.
    max_per_poll: int = Field(default=200, ge=1, le=2000)
    #: The longest one pass may take before it stops early and serves what it has. It is
    #: checked between tickets AND at the tracker boundary inside one, so an expired pass
    #: starts no further call on somebody's board — which is what bounds the API request the
    #: on-demand poll runs inside, and its database session. It cannot cancel a call already
    #: in flight (an HTTPX timeout measures network inactivity, not total duration), so the
    #: bound is this plus the calls of the verb in progress. The worker's own liveness does
    #: not depend on it: a pass keeps checking in for as long as it lasts.
    poll_budget_s: int = Field(default=60, ge=5, le=900)
    #: ``merged``/``closed`` → the state the ticket moves to. EMPTY BY DEFAULT: a
    #: deployment that configures nothing never moves anybody's ticket.
    outcome_map: dict[str, str] = Field(default_factory=dict)
    #: ADR-0022 — a ready ticket is a DRAFT until an operator registers it on the Intake
    #: screen (an evented act). ON BY DEFAULT: without it, anyone who can edit a ticket in
    #: the watched column puts work into the factory. ``false`` registers ready tickets
    #: unattended (``approved_by: unattended`` on the chain).
    require_approval: bool = True
    #: Tracker authors (the ticket's creator — Azure DevOps sign-in name, Jira email or
    #: account id) whose ready tickets skip the Register act. EMPTY BY DEFAULT. Set as a
    #: JSON list (``CRB_INTAKE__APPROVE_AUTHORS='["ada@contoso.com"]'``); compared
    #: case-insensitively; recorded as ``approved_by: allowlist:<author>``.
    approve_authors: list[str] = Field(default_factory=list)

    @property
    def enabled(self) -> bool:
        """Whether a tracker is configured at all (a listener still has to be switched on)."""
        return self.tracker != "none" and bool(self.url.strip()) and bool(self.column.strip())

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        # The credential travels on this URL. A plain-http tracker would put a personal
        # access token on the wire, so it is refused at start-up rather than at the first
        # poll (the same rule as the OIDC issuer and the GitHub API URL).
        raw = v.strip().rstrip("/")
        if raw and not raw.lower().startswith("https://"):
            raise ValueError(f"the tracker URL must be https://, got {raw!r}")
        return raw

    @field_validator("approve_authors", mode="before")
    @classmethod
    def _authors_list(cls, v: Any) -> Any:
        # an explicit env mapping (the worker's) hands a raw string: a JSON list, or names
        # separated by commas; either way blanks are dropped and names compared casefolded
        if isinstance(v, str):
            raw = v.strip()
            v = json.loads(raw) if raw.startswith("[") else raw.split(",")
        return [str(a).strip().casefold() for a in (v or []) if str(a).strip()]

    @field_validator("outcome_map")
    @classmethod
    def _outcomes_are_known(cls, v: dict[str, str]) -> dict[str, str]:
        bad = sorted(k for k in v if k not in ("merged", "closed"))
        if bad:
            raise ValueError(f"outcome_map keys must be 'merged' or 'closed', got {bad}")
        return v

    def redacted(self) -> dict[str, Any]:
        """What ``/settings`` may show. There is no secret in this model, but the shape
        matches ``BuilderSettings.redacted`` so a reader treats them alike."""
        return {
            "tracker": self.tracker,
            "url": self.url,
            "project": self.project,
            "column": self.column,
            "area_path": self.area_path,
            "jql": self.jql,
            "email": self.email,
            "points_field": self.points_field,
            "acceptance_field": self.acceptance_field,
            "poll_s": self.poll_s,
            "max_per_poll": self.max_per_poll,
            "poll_budget_s": self.poll_budget_s,
            "outcome_map": dict(self.outcome_map),
            "require_approval": self.require_approval,
            "approve_authors": list(self.approve_authors),
            "enabled": self.enabled,
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
    #: ``CRB_ALLOW_UNSEALED_PROD=1`` admits the host builder or the local test executor in
    #: ``prod`` (ADR-0023). Shown by :meth:`posture`; the worker stamps it on every run.
    allow_unsealed_prod: bool = False
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
    #: Dependency provisioning (ADR-0019) — off by default; see ``ProvisionSettings``.
    provision: ProvisionSettings = Field(default_factory=ProvisionSettings)
    builder: BuilderSettings = Field(default_factory=BuilderSettings)
    factory: FactorySettings = Field(default_factory=FactorySettings)
    #: Where work arrives from (ADR-0017). ``tracker: none`` by default: no column is
    #: watched until an admin configures one AND an operator switches a listener on.
    intake: IntakeSettings = Field(default_factory=IntakeSettings)
    metrics_enabled: bool = True
    log_format: Literal["json", "text"] = "json"
    log_level: str = "INFO"
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    #: The address people use to reach THIS deployment (``https://crb.example.com``).
    #: It is needed because the product writes links to its own pages on somebody else's
    #: ticket, and a relative path in a Jira or Azure DevOps comment resolves against
    #: THEIR host, so it goes nowhere. Empty is refused where it matters rather than
    #: papered over: a listener cannot be switched on without it, and a pass that somehow
    #: starts without it stops with ``no_public_url`` before it writes anything.
    public_url: str = ""
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

    @field_validator("public_url")
    @classmethod
    def _public_url_is_absolute(cls, v: str) -> str:
        # An absolute https:// address, because it is written into a third party's ticket
        # and a reader there clicks it from another host. Loopback over http is admitted
        # for a developer and for the walkthrough's own stack, which has no certificate;
        # nothing else may be plain http, since the link is how a person reaches a page
        # that asks them to sign in.
        # The value is PARSED, not prefix-matched: `http://localhost.example.com` and
        # `http://127.0.0.1.attacker.test` both begin with a loopback name and are neither,
        # and `https:///path` has no host at all. Every link the product writes on a ticket
        # is built from this value, so a host that only looks like loopback would put a plain
        # http address somebody else controls into a customer's work item.
        raw = v.strip().rstrip("/")
        if not raw:
            return ""
        parts = urlsplit(raw)
        scheme, host = parts.scheme.lower(), (parts.hostname or "")
        if scheme == "https" and host:
            return raw
        if scheme == "http" and host in LOOPBACK_HOSTS:
            return raw
        raise ValueError(
            f"CRB_PUBLIC_URL must be an https:// address with a host name (or http:// on "
            f"loopback: {', '.join(sorted(LOOPBACK_HOSTS))}), got {raw!r}"
        )

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
        # ADR-0023: the builder's default follows the env, then production refuses the
        # unsealed posture unless the operator said so on purpose
        if self.builder.executor is None:
            self.builder.executor = default_builder_executor(self.env)
        refusal = unsealed_prod_refusal(
            self.env,
            self.sandbox.executor,
            self.builder_executor,
            allow=self.allow_unsealed_prod,
        )
        if refusal:
            raise ValueError(refusal)
        # dependency provisioning: a typo in an allowlist, a public registry in prod without
        # allow_public, or an unpinned fetch image fails at start-up — never at the first fetch
        refusal_p = self.provision_config.production_refusal()
        if refusal_p is not None:
            raise ValueError(f"{refusal_p.code}: {refusal_p.message}; {refusal_p.fix}")
        if self.posture()["unsealed_prod_override"]:
            log.warning(
                "%s=1: production runs UNSEALED (tests %s, builder %s) — every run's apparatus "
                "carries the override; what it measures is a development reading (ADR-0023)",
                ALLOW_UNSEALED_PROD_ENV,
                self.sandbox.executor,
                self.builder_executor,
            )
        return self

    # --- derived ---------------------------------------------------------------
    @property
    def builder_executor(self) -> str:
        """The builder's executor as resolved for this env (``docker`` | ``host``)."""
        return self.builder.executor or default_builder_executor(self.env)

    def posture(self) -> dict[str, Any]:
        """Where tests and the builder run, whether that is sealed, and whether production
        runs unsealed under ``CRB_ALLOW_UNSEALED_PROD`` (ADR-0023). Served on ``/health``
        and ``/settings``; nothing here is secret. ``sealed`` and ``unsealed_prod_override``
        describe replay builds and test runs; the override is reported in force there only
        when it is what lets this deployment start (an unused override is not a posture).

        ``factory_builds`` is the factory's own posture, reported apart because a factory
        build is never sealed (the builder is handed a host worktree, no container):
        ``refused`` in ``prod`` without the override (the worker refuses the run), ``host``
        otherwise — and in ``prod`` every such run's apparatus carries the override."""
        sealed = (
            self.sandbox.executor == SEALED_EXECUTOR and self.builder_executor == SEALED_EXECUTOR
        )
        return {
            "env": self.env,
            "sandbox_executor": self.sandbox.executor,
            "builder_executor": self.builder_executor,
            "sealed": sealed,
            "unsealed_prod_override": self.env == "prod"
            and not sealed
            and self.allow_unsealed_prod,
            "factory_builds": factory_builds_posture(self.env, allow=self.allow_unsealed_prod),
        }

    @property
    def provision_config(self) -> ProvisionConfig:
        """The worker-side provisioning configuration these settings describe."""
        return self.provision.to_config(env=self.env, home=self.home)

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
            "retention": {
                "transcripts_days": self.retention.transcripts_days,
                "patches": self.retention.patches,
            },
            "sandbox": {
                "executor": self.sandbox.executor,
                "image": self.sandbox.image,
                "tree": self.sandbox.tree,
                "work_size": self.sandbox.work_size,
            },
            "provision": self.provision_config.view(),
            "builder": self.builder.redacted(),
            "posture": self.posture(),
            "factory": self.factory.redacted(),
            "intake": self.intake.redacted(),
            "public_url": self.public_url,
            "metrics_enabled": self.metrics_enabled,
            "log_format": self.log_format,
            "worker_heartbeat_stale_s": self.worker_heartbeat_stale_s,
        }


__all__ = [
    "ALLOW_UNSEALED_PROD_ENV",
    "MIN_PASSWORD_LENGTH",
    "ROLE_LADDER",
    "ROLE_RANK",
    "SEALED_EXECUTOR",
    "TEMP_DIR_ROOTS",
    "TEMP_HOME_ADVICE",
    "BootstrapAdmin",
    "BuilderSettings",
    "FactorySettings",
    "IntakeSettings",
    "OidcSettings",
    "ProvisionSettings",
    "RetentionSettings",
    "Role",
    "SandboxSettings",
    "Settings",
    "default_builder_executor",
    "factory_builds_posture",
    "temp_dir_reason",
    "unsealed_prod_refusal",
]
