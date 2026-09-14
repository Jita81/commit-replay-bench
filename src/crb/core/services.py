"""Services the oracle needs — declared in ``runner_opts.services``, reproducible.

Some test suites are only an oracle when a *service* is running next to them:
NHSDigital/mesh-client's integration tests talk to the MESH sandbox on
``localhost:8701`` over TLS, with the certificates the sandbox presents having
to match the ones the commit's own tests carry. Without a first-class notion of
that dependency the oracle was assembled by hand (2026-09-14) and could not be
reproduced from the repository's configuration. This module is that notion.

A :class:`ServiceSpec` says *what* to run (an ``image``, a ``compose`` service
of the repository's own compose file with an operator ``override``, or a
``build`` of a context at a ref), *how to know it is up* (``health``: a URL or a
command, with a deadline), *what it must be given* (``fixtures`` staged from the
repository — a path in the clone, or ``<ref>:<path>`` from history — and an
optional ``generate`` command that produces them, run once per variant), and
*what the tests are told* (``export``: environment for the test command). A
service may have :class:`Variant`\\ s selected by the task's authored date
(:class:`Era`), so a commit gets the certificates of *its* era.

A :class:`ServiceSession` starts the services through an executor, waits for
health, exposes the merged ``export`` environment, records which image digest
answered (the apparatus stamp), keeps a redacted log tail for the evidence, and
stops what it started on close. Three invariants:

* **Fail closed.** A service that cannot be started, built, staged or probed
  healthy is :class:`ServiceUnavailable` — a :class:`~crb.core.execution.SandboxUnavailable`
  — never a red test run and never a green one. A pinned build that no longer
  builds (bit-rot) is reported with the exact override to set; nothing is
  substituted silently.
* **Staged where the container runtime can see it.** Fixtures are copied under
  the runner's ``env_dir`` (``CRB_HOME/envs/<repo>/services/…``), never under
  ``/private/tmp``: on macOS the VM behind docker (colima, Docker Desktop) shares
  ``/Users`` but not ``/private/var/folders`` or ``/private/tmp``, so a bind
  mount from a temp path is silently empty inside the container.
* **One instance per service.** Sequential worktrees share the running service
  (idempotent ``ensure``; a healthy instance — even one another process left
  running under the same name — is adopted, a different era's variant replaces
  it). Concurrency is therefore **1 per service**; run two eras side by side
  only by giving each variant its own host port.

The core stays standard-library only; docker is driven through the executor's
``Command`` interface so a scripted executor can exercise every branch offline.
"""

from __future__ import annotations

import atexit
import json
import re
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from crb.core.execution import Command, ExecResult, Executor, SandboxUnavailable
from crb.core.redact import redact_and_cap

#: Last N log lines kept per service (redacted, capped) for the evidence.
SERVICE_LOG_LINES = 200

#: Cap on the redacted log tail one service record keeps.
SERVICE_TAIL_CHARS = 4000

#: Health deadline / poll interval when the config gives none.
DEFAULT_HEALTH_TIMEOUT_S = 120
DEFAULT_HEALTH_INTERVAL_S = 2.0

#: Wall clock for one ``docker`` bookkeeping command (inspect, logs, rm, ps).
DOCKER_CMD_TIMEOUT_S = 120

#: Wall clock for a start (``run -d`` / ``compose up -d`` / ``build``): it may pull or build.
DEFAULT_START_TIMEOUT_S = 1800

#: Wall clock for one URL probe.
PROBE_TIMEOUT_S = 5.0

#: Label every container crb starts carries, so leftovers can be found: ``docker ps --filter``.
LABEL = "crb.service"

SERVICES_SANDBOX_REFUSED = (
    "runner_opts.services need the host network (the tests reach the service on localhost) "
    "but the sandbox executor runs tests with --network=none; run this repository under the "
    "local executor, or ship the service inside the sandbox image"
)

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_PORT_RE = re.compile(r"(?:[0-9.]+:)?(?P<host>\d{1,5}):(?P<container>\d{1,5})(?:/(?:tcp|udp))?")
_UNSAFE_RE = re.compile(r"[^a-z0-9_-]+")

ProbeFn = Callable[[str, float, bool], bool]
#: Sees every docker command the session ran, with its result (return value ignored).
CommandHook = Callable[[Command, ExecResult], object]


class ServiceUnavailable(SandboxUnavailable):
    """A declared service cannot be provided. FAIL CLOSED: a harness error, never a verdict."""


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def _parse_when(text: str, *, what: str) -> datetime:
    """ISO-8601 date or datetime → aware UTC datetime (a naive value is UTC)."""
    try:
        dt = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(f"{what}: {text!r} is not an ISO-8601 date") from exc
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Era:
    """A half-open window on the task's authored date: ``after <= authored < before``.

    Either bound may be empty (open). ``before: 2025-08-01`` is *strictly before
    midnight UTC on that day*; ``after: 2025-08-01`` includes it — so two variants
    with the same boundary date partition the timeline with no gap and no overlap.
    """

    after: str = ""
    before: str = ""

    def __post_init__(self) -> None:
        if not self.after and not self.before:
            raise ValueError("era needs 'before' and/or 'after'")
        lo = _parse_when(self.after, what="era.after") if self.after else None
        hi = _parse_when(self.before, what="era.before") if self.before else None
        if lo is not None and hi is not None and lo >= hi:
            raise ValueError(
                f"era.after {self.after!r} must be earlier than era.before {self.before!r}"
            )

    def matches(self, authored: str) -> bool:
        when = _parse_when(authored, what="authored")
        if self.after and when < _parse_when(self.after, what="era.after"):
            return False
        return not (self.before and when >= _parse_when(self.before, what="era.before"))

    def to_dict(self) -> dict[str, Any]:
        return {"after": self.after, "before": self.before}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Era:
        return cls(after=str(d.get("after", "") or ""), before=str(d.get("before", "") or ""))

    def __str__(self) -> str:
        return f"[{self.after or '…'}, {self.before or '…'})"


@dataclass(frozen=True)
class Fixture:
    """One file the service must see.

    ``src`` is either a path in the repository clone (after ``generate`` ran) or
    ``<ref>:<path>`` — the file as committed at ``ref`` (``git show``), which is
    how an era whose fixtures were *committed* stays reproducible after HEAD
    deleted them. ``dst`` is the absolute path inside the container.
    """

    src: str
    dst: str
    ro: bool = True

    def __post_init__(self) -> None:
        if not self.src or not self.dst:
            raise ValueError("fixture needs 'src' and 'dst'")
        if not PurePosixPath(self.dst).is_absolute():
            raise ValueError(f"fixture dst {self.dst!r} must be an absolute container path")
        if self.git_ref is None and (Path(self.src).is_absolute() or ".." in Path(self.src).parts):
            raise ValueError(f"fixture src {self.src!r} must be repository-relative")

    @property
    def git_ref(self) -> tuple[str, str] | None:
        """``(ref, path)`` for the ``<ref>:<path>`` form, else ``None``."""
        if ":" not in self.src:
            return None
        ref, path = self.src.split(":", 1)
        return (ref, path) if ref and path else None

    def to_dict(self) -> dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "ro": self.ro}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Fixture:
        return cls(str(d.get("src", "")), str(d.get("dst", "")), bool(d.get("ro", True)))


@dataclass(frozen=True)
class Health:
    """How the session knows the service is up: a URL that answers 2xx/3xx, or a
    command that exits 0 (run through the executor in the clone). ``insecure_tls``
    accepts the service's own (self-signed) certificate on the URL probe."""

    url: str = ""
    cmd: tuple[str, ...] = ()
    timeout_s: int = DEFAULT_HEALTH_TIMEOUT_S
    interval_s: float = DEFAULT_HEALTH_INTERVAL_S
    insecure_tls: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "cmd", tuple(str(a) for a in self.cmd))
        if bool(self.url) == bool(self.cmd):
            raise ValueError("health needs exactly one of 'url' or 'cmd'")
        if self.url and not self.url.startswith(("http://", "https://")):
            raise ValueError(f"health.url {self.url!r} must be http(s)")
        if self.timeout_s <= 0 or self.interval_s <= 0:
            raise ValueError("health.timeout_s and health.interval_s must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "cmd": list(self.cmd),
            "timeout_s": self.timeout_s,
            "interval_s": self.interval_s,
            "insecure_tls": self.insecure_tls,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Health:
        return cls(
            url=str(d.get("url", "") or ""),
            cmd=tuple(str(a) for a in (d.get("cmd") or [])),
            timeout_s=int(d.get("timeout_s", DEFAULT_HEALTH_TIMEOUT_S)),
            interval_s=float(d.get("interval_s", DEFAULT_HEALTH_INTERVAL_S)),
            insecure_tls=bool(d.get("insecure_tls", False)),
        )


@dataclass(frozen=True)
class ComposeRef:
    """A service of the repository's own compose file. ``override`` is merged in as
    a second compose file (JSON is YAML): the place for the build ref that still
    builds, extra environment, anything the pinned file gets wrong today."""

    file: str
    service: str
    override: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.file or not self.service:
            raise ValueError("compose needs 'file' and 'service'")
        if Path(self.file).is_absolute() or ".." in Path(self.file).parts:
            raise ValueError(f"compose.file {self.file!r} must be repository-relative")
        object.__setattr__(self, "override", json.loads(json.dumps(dict(self.override))))

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "service": self.service, "override": dict(self.override)}


@dataclass(frozen=True)
class BuildRef:
    """``docker build`` of ``context`` (a directory in the clone or a git URL) at ``ref``."""

    context: str
    ref: str = ""

    def __post_init__(self) -> None:
        if not self.context:
            raise ValueError("build needs 'context'")
        if not self.is_url:
            if self.ref:
                raise ValueError(
                    "build.ref selects a git ref of a URL context; a local one has none"
                )
            if Path(self.context).is_absolute() or ".." in Path(self.context).parts:
                raise ValueError(
                    f"build.context {self.context!r} must be a URL or repository-relative"
                )

    @property
    def is_url(self) -> bool:
        return "://" in self.context or self.context.startswith("git@")

    @property
    def source(self) -> str:
        """What ``docker build`` is given (a URL context carries ``#<ref>``)."""
        return f"{self.context}#{self.ref}" if self.ref else self.context

    def to_dict(self) -> dict[str, Any]:
        return {"context": self.context, "ref": self.ref}


@dataclass(frozen=True)
class Variant:
    """One era of a service: the fixtures (and the command that generates them)
    that commits in ``era`` need. A variant without an era is the default and
    must come last."""

    name: str
    era: Era | None = None
    fixtures: tuple[Fixture, ...] = ()
    generate: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _NAME_RE.fullmatch(self.name):
            raise ValueError(f"variant name {self.name!r} must match {_NAME_RE.pattern}")
        object.__setattr__(self, "fixtures", tuple(self.fixtures))
        object.__setattr__(self, "generate", tuple(str(a) for a in self.generate))
        object.__setattr__(self, "env", {str(k): str(v) for k, v in dict(self.env).items()})

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "era": self.era.to_dict() if self.era else None,
            "fixtures": [f.to_dict() for f in self.fixtures],
            "generate": list(self.generate),
            "env": dict(self.env),
        }


DEFAULT_VARIANT = "default"


@dataclass(frozen=True)
class ServiceSpec:
    """One service the oracle needs. Exactly one of ``image`` / ``compose`` / ``build``.

    ``env`` is the container's environment; ``export`` is what the *test command*
    receives (``{fixtures}``, ``{port}``, ``{host}``, ``{name}`` are substituted);
    ``command`` overrides the image's command (an image without an entrypoint of
    its own). Top-level ``fixtures`` / ``generate`` are shared by every variant
    (prepended); without ``variants`` they form the single default variant.
    """

    name: str
    health: Health
    image: str = ""
    compose: ComposeRef | None = None
    build: BuildRef | None = None
    command: tuple[str, ...] = ()
    ports: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    export: Mapping[str, str] = field(default_factory=dict)
    fixtures: tuple[Fixture, ...] = ()
    generate: tuple[str, ...] = ()
    variants: tuple[Variant, ...] = ()
    logs_tail: int = SERVICE_LOG_LINES
    keep: bool = False
    start_timeout_s: int = DEFAULT_START_TIMEOUT_S

    def __post_init__(self) -> None:
        if not _NAME_RE.fullmatch(self.name):
            raise ValueError(f"service name {self.name!r} must match {_NAME_RE.pattern}")
        kinds = [
            k
            for k, v in (("image", self.image), ("compose", self.compose), ("build", self.build))
            if v
        ]
        if len(kinds) != 1:
            raise ValueError(
                f"service {self.name!r} needs exactly one of image | compose | build, got {kinds}"
            )
        object.__setattr__(self, "command", tuple(str(a) for a in self.command))
        object.__setattr__(self, "ports", tuple(str(p) for p in self.ports))
        for p in self.ports:
            if not _PORT_RE.fullmatch(p):
                raise ValueError(f"service {self.name!r}: port {p!r} must be '<host>:<container>'")
        object.__setattr__(self, "env", {str(k): str(v) for k, v in dict(self.env).items()})
        object.__setattr__(self, "export", {str(k): str(v) for k, v in dict(self.export).items()})
        object.__setattr__(self, "fixtures", tuple(self.fixtures))
        object.__setattr__(self, "generate", tuple(str(a) for a in self.generate))
        object.__setattr__(self, "variants", tuple(self.variants))
        names = [v.name for v in self.variants]
        if len(set(names)) != len(names):
            raise ValueError(f"service {self.name!r}: variant names must be unique, got {names}")
        defaults = [v for v in self.variants if v.era is None]
        if len(defaults) > 1:
            raise ValueError(f"service {self.name!r}: at most one variant may have no era")
        if defaults and self.variants[-1].era is not None:
            raise ValueError(f"service {self.name!r}: the variant without an era must come last")
        if self.logs_tail < 0 or self.start_timeout_s <= 0:
            raise ValueError("logs_tail must be >= 0 and start_timeout_s > 0")

    @property
    def kind(self) -> str:
        return "image" if self.image else "compose" if self.compose else "build"

    @property
    def ref(self) -> str:
        """What the record cites: the image, the build source, or the compose service."""
        if self.image:
            return self.image
        if self.build is not None:
            return self.build.source
        assert self.compose is not None
        return f"compose:{self.compose.file}:{self.compose.service}"

    @property
    def needs_era(self) -> bool:
        return any(v.era is not None for v in self.variants)

    @property
    def host_port(self) -> str:
        for p in self.ports:
            m = _PORT_RE.fullmatch(p)
            if m:
                return m.group("host")
        return ""

    def variant_for(self, authored: str | None) -> Variant:
        """The variant whose era holds ``authored`` (first match, declared order);
        the era-less default when nothing else does; the single implicit default
        without variants. Raises :class:`ServiceUnavailable` when a date is needed
        and unknown, or no era matches — never a silent guess."""
        if not self.variants:
            return Variant(DEFAULT_VARIANT, None, self.fixtures, self.generate)
        for v in self.variants:
            if v.era is None:
                return self._merged(v)
            if authored is None:
                continue
            if v.era.matches(authored):
                return self._merged(v)
        eras = ", ".join(f"{v.name}={v.era}" for v in self.variants if v.era is not None)
        if authored is None:
            raise ServiceUnavailable(
                f"service {self.name!r} has era variants ({eras}) but the task's authored date is "
                "unknown; pass authored= to run() or add an era-less default variant"
            )
        raise ServiceUnavailable(
            f"service {self.name!r}: no variant covers authored {authored!r} ({eras}); "
            "add an era or an era-less default variant"
        )

    def all_variants(self) -> tuple[Variant, ...]:
        """Every variant, shared fixtures merged in (the implicit default alone
        when none is declared) — what setup stages up front."""
        if not self.variants:
            return (Variant(DEFAULT_VARIANT, None, self.fixtures, self.generate),)
        return tuple(self._merged(v) for v in self.variants)

    def latest_variant(self) -> Variant:
        """The variant setup starts when no task has chosen one: the era-less
        default if declared, else the LAST declared (eras are declared oldest
        first, so that is the newest era)."""
        variants = self.all_variants()
        for v in variants:
            if v.era is None:
                return v
        return variants[-1]

    def _merged(self, v: Variant) -> Variant:
        if not self.fixtures and not self.generate:
            return v
        return Variant(
            v.name, v.era, (*self.fixtures, *v.fixtures), v.generate or self.generate, v.env
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "image": self.image,
            "compose": self.compose.to_dict() if self.compose else None,
            "build": self.build.to_dict() if self.build else None,
            "command": list(self.command),
            "ports": list(self.ports),
            "env": dict(self.env),
            "export": dict(self.export),
            "health": self.health.to_dict(),
            "fixtures": [f.to_dict() for f in self.fixtures],
            "generate": list(self.generate),
            "variants": [v.to_dict() for v in self.variants],
            "logs_tail": self.logs_tail,
            "keep": self.keep,
            "start_timeout_s": self.start_timeout_s,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ServiceSpec:
        name = str(d.get("name", "") or "")
        where = f"services[{name or '?'}]"
        try:
            health_d = d.get("health")
            if not isinstance(health_d, Mapping):
                raise ValueError("health is required ({url|cmd, timeout_s, interval_s})")
            compose_d = d.get("compose")
            build_d = d.get("build")
            compose = (
                ComposeRef(
                    str(compose_d.get("file", "")),
                    str(compose_d.get("service", "")),
                    dict(compose_d.get("override") or {}),
                )
                if isinstance(compose_d, Mapping)
                else None
            )
            build = (
                BuildRef(str(build_d.get("context", "")), str(build_d.get("ref", "") or ""))
                if isinstance(build_d, Mapping)
                else None
            )
            variants = tuple(_variant_from_dict(v) for v in (d.get("variants") or []))
            return cls(
                name=name,
                health=Health.from_dict(health_d),
                image=str(d.get("image", "") or ""),
                compose=compose,
                build=build,
                command=tuple(str(a) for a in (d.get("command") or [])),
                ports=tuple(str(p) for p in (d.get("ports") or [])),
                env=dict(d.get("env") or {}),
                export=dict(d.get("export") or {}),
                fixtures=tuple(Fixture.from_dict(f) for f in (d.get("fixtures") or [])),
                generate=tuple(str(a) for a in (d.get("generate") or [])),
                variants=variants,
                logs_tail=int(d.get("logs_tail", SERVICE_LOG_LINES)),
                keep=bool(d.get("keep", False)),
                start_timeout_s=int(d.get("start_timeout_s", DEFAULT_START_TIMEOUT_S)),
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"{where}: {exc}") from exc


def _variant_from_dict(d: Mapping[str, Any]) -> Variant:
    if not isinstance(d, Mapping):
        raise ValueError("each variant must be a mapping")
    era_d = d.get("era")
    return Variant(
        name=str(d.get("name", "") or ""),
        era=Era.from_dict(era_d) if isinstance(era_d, Mapping) and era_d else None,
        fixtures=tuple(Fixture.from_dict(f) for f in (d.get("fixtures") or [])),
        generate=tuple(str(a) for a in (d.get("generate") or [])),
        env=dict(d.get("env") or {}),
    )


def parse_services(runner_opts: Mapping[str, Any]) -> tuple[ServiceSpec, ...]:
    """``runner_opts["services"]`` → specs. Absent / empty → ``()``. A malformed
    entry raises ``ValueError`` naming the service — configuration is validated
    before anything is started, never while a test is waiting."""
    raw = runner_opts.get("services")
    if not raw:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError("runner_opts.services must be a list of service mappings")
    specs: list[ServiceSpec] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"services[{i}] must be a mapping")
        specs.append(ServiceSpec.from_dict(item))
    names = [s.name for s in specs]
    if len(set(names)) != len(names):
        raise ValueError(f"service names must be unique, got {names}")
    return tuple(specs)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceRecord:
    """Which service instance the oracle ran against — carried by every test run
    and by the setup result, so the apparatus stamp names the service version."""

    name: str
    variant: str
    ref: str
    image_digest: str = ""
    healthy_at: str = ""
    adopted: bool = False
    container: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "variant": self.variant,
            "ref": self.ref,
            "image_digest": self.image_digest,
            "healthy_at": self.healthy_at,
            "adopted": self.adopted,
            "container": self.container,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ServiceRecord:
        return cls(
            name=str(d.get("name", "")),
            variant=str(d.get("variant", "")),
            ref=str(d.get("ref", "")),
            image_digest=str(d.get("image_digest", "")),
            healthy_at=str(d.get("healthy_at", "")),
            adopted=bool(d.get("adopted", False)),
            container=str(d.get("container", "")),
        )


@dataclass
class _Active:
    spec: ServiceSpec
    variant: Variant
    record: ServiceRecord
    container: str
    compose_argv: tuple[str, ...]  # ``docker compose -p … -f … [-f …]`` prefix, or ()
    fixtures_dir: Path | None
    started_here: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def safe_name(*parts: str) -> str:
    """A docker container / compose project name: lowercase ``[a-z0-9_-]``, joined by ``-``."""
    out = "-".join(_UNSAFE_RE.sub("-", p.lower()).strip("-") for p in parts if p)
    return out[:120] or "crb"


def clone_root_of(root: Path) -> Path:
    """The main clone behind ``root``: itself, or — for a linked worktree — the
    repository whose ``.git`` directory it shares. Services stage from the clone,
    so every worktree of a repo sees the same fixtures."""
    root = Path(root)
    try:
        p = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return root
    common = Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None
    if common is None:
        return root
    return common.parent if common.name == ".git" else root


def authored_of(root: Path) -> str | None:
    """The author date of ``root``'s HEAD, or ``None``. A trial worktree's HEAD is
    the commit's *parent*, so this is the fallback for era selection when the
    caller did not pass the task's own date — exact except at an era boundary."""
    try:
        p = subprocess.run(
            ["git", "-C", str(root), "show", "-s", "--format=%aI", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.strip() or None


def read_fixture(clone: Path, fx: Fixture) -> bytes:
    """The fixture's bytes: ``git show ref:path`` from the clone, or the file in it."""
    ref = fx.git_ref
    if ref is not None:
        rev, rel = ref
        try:
            p = subprocess.run(
                ["git", "-C", str(clone), "show", f"{rev}:{rel}"],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ServiceUnavailable(f"fixture {fx.src!r}: git show failed: {exc}") from exc
        if p.returncode != 0:
            err = p.stderr.decode("utf-8", "replace").strip()[:300]
            raise ServiceUnavailable(f"fixture {fx.src!r}: not in the repository's history ({err})")
        return bytes(p.stdout)
    path = Path(clone) / fx.src
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ServiceUnavailable(
            f"fixture {fx.src!r}: {exc.strerror or exc} — not in the clone; does 'generate' produce it?"
        ) from exc


def probe_url(url: str, timeout: float = PROBE_TIMEOUT_S, insecure_tls: bool = False) -> bool:
    """``True`` iff ``url`` answers with a 2xx/3xx status within ``timeout``."""
    ctx: ssl.SSLContext | None = None
    if insecure_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    # S310: the scheme is validated to http(s) by Health; the URL is the operator's own.
    req = urllib.request.Request(url, headers={"User-Agent": "crb-service-probe"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310
            return 200 <= int(resp.status) < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def bit_rot_hint(spec: ServiceSpec) -> str:
    if spec.kind == "build":
        assert spec.build is not None
        return (
            f"if the pinned ref no longer builds (bit-rot), find the latest release tag of "
            f"{spec.build.context} and set runner_opts.services[{spec.name}].build.ref to it; "
            "crb never substitutes a version silently"
        )
    if spec.kind == "compose":
        assert spec.compose is not None
        return (
            "if the compose file's pinned build no longer builds (bit-rot), find the latest release "
            f"tag and set runner_opts.services[{spec.name}].compose.override.services."
            f"{spec.compose.service}.build.context to it (e.g. …#refs/tags/<latest>); crb never "
            "substitutes a version silently"
        )
    return "check the image reference and the registry; crb never substitutes a version silently"


def _substitute(value: str, **subs: str) -> str:
    for k, v in subs.items():
        value = value.replace("{" + k + "}", v)
    return value


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class ServiceSession:
    """Starts, adopts, probes, records and stops the services of one repository.

    ``executor`` runs every docker command (``run -d``, ``compose up -d``, ``build``,
    ``inspect``, ``logs``, ``rm``) as a :class:`~crb.core.execution.Command` in the
    clone; ``on_command`` sees each one with its result (the runner turns them
    into setup steps). ``state_dir`` is where fixtures and compose overrides are
    staged (``<env_dir>/services``); ``probe``, ``clock`` and ``sleep`` are
    injectable for hermetic tests.
    """

    def __init__(
        self,
        specs: Sequence[ServiceSpec],
        executor: Executor,
        *,
        clone: Path,
        repo: str,
        state_dir: Path | None,
        on_command: CommandHook | None = None,
        probe: ProbeFn | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        docker: str = "",
        register_atexit: bool = True,
    ) -> None:
        self.specs = tuple(specs)
        self.executor = executor
        self.clone = Path(clone)
        self.repo = repo
        self.state_dir = Path(state_dir) if state_dir is not None else None
        self.on_command = on_command
        self._probe: ProbeFn = probe or probe_url
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self.docker = docker or executor.tool("docker", shutil.which("docker"))
        self._active: dict[str, _Active] = {}
        self.logs: dict[str, str] = {}
        self._register_atexit = register_atexit
        self._finalizer_registered = False

    # --- public --------------------------------------------------------------------
    @property
    def records(self) -> tuple[ServiceRecord, ...]:
        return tuple(a.record for a in self._active.values())

    @property
    def env(self) -> dict[str, str]:
        """The merged ``export`` environment of every active service, for the test command."""
        out: dict[str, str] = {}
        for a in self._active.values():
            subs = {
                "fixtures": str(a.fixtures_dir) if a.fixtures_dir else "",
                "port": a.spec.host_port,
                "host": "127.0.0.1",
                "name": a.spec.name,
            }
            for k, v in a.spec.export.items():
                out[k] = _substitute(v, **subs)
        return out

    def prepare(self) -> None:
        """Stage every variant of every service (run each ``generate`` once, copy
        the fixtures, write the compose overrides) without starting anything —
        the setup phase does this so a missing fixture or a broken generator is
        found before any task waits on it."""
        for spec in self.specs:
            for variant in spec.all_variants():
                self._stage(spec, variant)

    def ensure(
        self, authored: str | None = None, *, latest: bool = False
    ) -> tuple[ServiceRecord, ...]:
        """Every declared service healthy for the variant ``authored`` selects
        (``latest=True`` and no date: the newest era — the setup phase, where no
        task has chosen one yet). Idempotent: a running healthy instance of the
        right variant is reused; a different variant replaces it. Raises
        :class:`ServiceUnavailable`."""
        for spec in self.specs:
            variant = (
                spec.latest_variant() if latest and authored is None else spec.variant_for(authored)
            )
            active = self._active.get(spec.name)
            if active is not None:
                if active.variant.name == variant.name and self._healthy_once(spec):
                    continue
                self._stop(active)
            self._ensure_one(spec, variant)
        self._register_finalizer()
        return self.records

    def close(self) -> None:
        """Stop what this session started (``keep: true`` services stay up), keeping
        each one's redacted log tail in :attr:`logs`."""
        for name in list(self._active):
            active = self._active[name]
            if active.started_here and not active.spec.keep:
                self._stop(active)
            else:
                self._capture_logs(active)
                del self._active[name]

    # --- one service -----------------------------------------------------------------
    def _ensure_one(self, spec: ServiceSpec, variant: Variant) -> None:
        fixtures_dir = self._stage(spec, variant)
        container_name = safe_name("crb", self.repo, spec.name, variant.name)
        compose_argv = self._compose_argv(spec, variant, fixtures_dir)
        # adopt a healthy instance already running under our name (another process)
        existing = self._find_container(spec, container_name, compose_argv)
        if existing:
            if self._healthy_once(spec):
                self._activate(spec, variant, existing, compose_argv, fixtures_dir, adopted=True)
                return
            self._remove(spec, existing, compose_argv)
        container = self._start(spec, variant, container_name, compose_argv, fixtures_dir)
        self._wait_healthy(spec, container, compose_argv)
        self._activate(spec, variant, container, compose_argv, fixtures_dir, adopted=False)

    def _activate(
        self,
        spec: ServiceSpec,
        variant: Variant,
        container: str,
        compose_argv: tuple[str, ...],
        fixtures_dir: Path | None,
        *,
        adopted: bool,
    ) -> None:
        digest, image = self._inspect_image(container)
        record = ServiceRecord(
            name=spec.name,
            variant=variant.name,
            ref=spec.ref if spec.kind != "compose" else (image or spec.ref),
            image_digest=digest,
            healthy_at=datetime.now(UTC).isoformat(timespec="seconds"),
            adopted=adopted,
            container=container,
        )
        self._active[spec.name] = _Active(
            spec, variant, record, container, compose_argv, fixtures_dir, not adopted
        )

    # --- staging -----------------------------------------------------------------------
    def _stage(self, spec: ServiceSpec, variant: Variant) -> Path | None:
        needs = bool(variant.fixtures or variant.generate or spec.kind == "compose")
        if not needs:
            return None
        if self.state_dir is None:
            raise ServiceUnavailable(
                f"service {spec.name!r} needs a staging directory the container runtime can see "
                "(fixtures / compose override) but the runner has no env_dir; bind one under "
                "CRB_HOME (never /private/tmp — the docker VM does not mount it)"
            )
        stage = self.state_dir / spec.name / variant.name
        fixtures_dir = stage / "fixtures"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        if variant.generate:
            marker = stage / ".generated.json"
            if not marker.exists():
                cmd = Command(
                    variant.generate,
                    self.clone,
                    env={},
                    timeout=spec.start_timeout_s,
                    network=False,
                )
                res = self._run(cmd)
                if not res.ok:
                    raise ServiceUnavailable(
                        f"service {spec.name!r} variant {variant.name!r}: generate failed "
                        f"(rc={res.returncode}): {' '.join(variant.generate)}\n"
                        + redact_and_cap(res.combined, max_chars=SERVICE_TAIL_CHARS)
                    )
                marker.write_text(
                    json.dumps(
                        {
                            "argv": list(variant.generate),
                            "at": datetime.now(UTC).isoformat(timespec="seconds"),
                        }
                    ),
                    encoding="utf-8",
                )
        for fx in variant.fixtures:
            data = read_fixture(self.clone, fx)
            dest = fixtures_dir / PurePosixPath(fx.dst).relative_to("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            dest.chmod(0o644)
        return fixtures_dir

    def _mounts(self, variant: Variant, fixtures_dir: Path | None) -> list[tuple[str, str, bool]]:
        if fixtures_dir is None:
            return []
        return [
            (str(fixtures_dir / PurePosixPath(fx.dst).relative_to("/")), fx.dst, fx.ro)
            for fx in variant.fixtures
        ]

    # --- docker plumbing -----------------------------------------------------------------
    def _run(self, cmd: Command) -> ExecResult:
        try:
            res = self.executor.run(cmd)
        except OSError as exc:
            res = ExecResult(127, "", f"{type(exc).__name__}: {exc}", False, 0.0)
        if self.on_command is not None:
            self.on_command(cmd, res)
        return res

    def _docker(
        self, *args: str, timeout: int = DOCKER_CMD_TIMEOUT_S, network: bool = False
    ) -> ExecResult:
        return self._run(
            Command((self.docker, *args), self.clone, timeout=timeout, network=network)
        )

    def _compose_argv(
        self, spec: ServiceSpec, variant: Variant, fixtures_dir: Path | None
    ) -> tuple[str, ...]:
        if spec.compose is None:
            return ()
        assert fixtures_dir is not None  # compose always stages (the override file)
        project = safe_name("crb", self.repo, spec.name, variant.name)
        override_path = fixtures_dir.parent / "compose.override.json"
        override = json.loads(json.dumps(dict(spec.compose.override)))
        services = override.setdefault("services", {})
        svc = services.setdefault(spec.compose.service, {})
        mounts = self._mounts(variant, fixtures_dir)
        if mounts:
            svc.setdefault("volumes", [])
            svc["volumes"] = [
                *svc["volumes"],
                *(f"{src}:{dst}{':ro' if ro else ''}" for src, dst, ro in mounts),
            ]
        env = {**spec.env, **variant.env}
        if env:
            svc["environment"] = {**dict(svc.get("environment") or {}), **env}
        if spec.ports:
            svc["ports"] = list(spec.ports)
        if spec.command:
            svc["command"] = list(spec.command)
        svc.setdefault("labels", {})
        svc["labels"] = {**dict(svc["labels"]), LABEL: "1", f"{LABEL}.repo": self.repo}
        override_path.write_text(json.dumps(override, indent=1), encoding="utf-8")
        return (
            self.docker,
            "compose",
            "-p",
            project,
            "-f",
            str(self.clone / spec.compose.file),
            "-f",
            str(override_path),
        )

    def _find_container(self, spec: ServiceSpec, name: str, compose_argv: tuple[str, ...]) -> str:
        """The id/name of a RUNNING instance under our name, or ``""``."""
        if compose_argv:
            assert spec.compose is not None
            res = self._run(
                Command(
                    (*compose_argv, "ps", "-q", "--status", "running", spec.compose.service),
                    self.clone,
                    timeout=DOCKER_CMD_TIMEOUT_S,
                )
            )
            ids = res.stdout.split()
            return ids[0] if res.ok and ids else ""
        res = self._docker("inspect", "--format", "{{.State.Running}}", name)
        return name if res.ok and res.stdout.strip() == "true" else ""

    def _start(
        self,
        spec: ServiceSpec,
        variant: Variant,
        name: str,
        compose_argv: tuple[str, ...],
        fixtures_dir: Path | None,
    ) -> str:
        t = spec.start_timeout_s
        if spec.kind == "compose":
            assert spec.compose is not None
            res = self._run(
                Command(
                    (*compose_argv, "up", "-d", "--remove-orphans", spec.compose.service),
                    self.clone,
                    timeout=t,
                    network=True,
                )
            )
            if not res.ok:
                raise ServiceUnavailable(self._start_failure(spec, res, "docker compose up"))
            container = self._find_container(spec, name, compose_argv)
            if not container:
                raise ServiceUnavailable(
                    f"service {spec.name!r}: 'docker compose up' exited 0 but "
                    f"{spec.compose.service!r} is not running\n"
                    + redact_and_cap(res.combined, max_chars=SERVICE_TAIL_CHARS)
                )
            return container
        image = spec.image
        if spec.kind == "build":
            assert spec.build is not None
            image = (
                safe_name("crb-svc", self.repo, spec.name)
                + ":"
                + (safe_name(spec.build.ref) if spec.build.ref else "latest")
            )
            context = (
                spec.build.source if spec.build.is_url else str(self.clone / spec.build.context)
            )
            res = self._docker("build", "-t", image, context, timeout=t, network=True)
            if not res.ok:
                raise ServiceUnavailable(self._start_failure(spec, res, "docker build"))
        argv: list[str] = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{LABEL}=1",
            "--label",
            f"{LABEL}.repo={self.repo}",
            "--security-opt",
            "no-new-privileges",
        ]
        for p in spec.ports:
            argv += ["-p", p]
        for k, v in {**spec.env, **variant.env}.items():
            argv += ["--env", f"{k}={v}"]
        for src, dst, ro in self._mounts(variant, fixtures_dir):
            argv += ["--mount", f"type=bind,src={src},dst={dst}" + (",readonly" if ro else "")]
        argv.append(image)
        argv.extend(spec.command)
        res = self._docker(*argv, timeout=t, network=True)
        if not res.ok:
            raise ServiceUnavailable(self._start_failure(spec, res, "docker run"))
        return name

    def _start_failure(self, spec: ServiceSpec, res: ExecResult, what: str) -> str:
        how = "timed out" if res.timed_out else f"rc={res.returncode}"
        return (
            f"service {spec.name!r} ({spec.ref}): {what} failed ({how}); {bit_rot_hint(spec)}\n"
            + redact_and_cap(res.combined, max_chars=SERVICE_TAIL_CHARS)
        )

    def _healthy_once(self, spec: ServiceSpec) -> bool:
        h = spec.health
        if h.url:
            return self._probe(h.url, PROBE_TIMEOUT_S, h.insecure_tls)
        res = self._run(Command(h.cmd, self.clone, timeout=max(1, int(h.interval_s * 5))))
        return res.ok

    def _wait_healthy(
        self, spec: ServiceSpec, container: str, compose_argv: tuple[str, ...]
    ) -> None:
        deadline = self._clock() + spec.health.timeout_s
        while True:
            if self._healthy_once(spec):
                return
            if self._clock() >= deadline:
                break
            self._sleep(spec.health.interval_s)
        tail = self._logs_of(spec, container, compose_argv)
        self.logs[spec.name] = tail
        self._remove(spec, container, compose_argv)
        what = spec.health.url or " ".join(spec.health.cmd)
        raise ServiceUnavailable(
            f"service {spec.name!r} ({spec.ref}) did not become healthy within "
            f"{spec.health.timeout_s}s ({what})\n--- last {spec.logs_tail} log lines ---\n{tail}"
        )

    def _logs_of(self, spec: ServiceSpec, container: str, compose_argv: tuple[str, ...]) -> str:
        if spec.logs_tail == 0:
            return ""
        if compose_argv:
            assert spec.compose is not None
            res = self._run(
                Command(
                    (
                        *compose_argv,
                        "logs",
                        "--no-color",
                        "--tail",
                        str(spec.logs_tail),
                        spec.compose.service,
                    ),
                    self.clone,
                    timeout=DOCKER_CMD_TIMEOUT_S,
                )
            )
        else:
            res = self._docker("logs", "--tail", str(spec.logs_tail), container)
        return redact_and_cap(res.combined, max_chars=SERVICE_TAIL_CHARS)

    def _inspect_image(self, container: str) -> tuple[str, str]:
        res = self._docker("inspect", "--format", "{{.Image}}|{{.Config.Image}}", container)
        if not res.ok:
            return "", ""
        digest, _, image = res.stdout.strip().partition("|")
        return digest, image

    def _capture_logs(self, active: _Active) -> None:
        self.logs[active.spec.name] = self._logs_of(
            active.spec, active.container, active.compose_argv
        )

    def _remove(self, spec: ServiceSpec, container: str, compose_argv: tuple[str, ...]) -> None:
        if compose_argv:
            self._run(
                Command(
                    (*compose_argv, "down", "--remove-orphans"),
                    self.clone,
                    timeout=DOCKER_CMD_TIMEOUT_S,
                )
            )
        else:
            self._docker("rm", "-f", container)

    def _stop(self, active: _Active) -> None:
        self._capture_logs(active)
        self._remove(active.spec, active.container, active.compose_argv)
        self._active.pop(active.spec.name, None)

    def _register_finalizer(self) -> None:
        """Stop what we started when the process ends — a leaked service container
        would be adopted by the next process as 'already healthy' for the wrong era."""
        if self._register_atexit and not self._finalizer_registered:
            atexit.register(self.close)
            self._finalizer_registered = True


__all__: Sequence[str] = (
    "BuildRef",
    "ComposeRef",
    "Era",
    "Fixture",
    "Health",
    "ServiceRecord",
    "ServiceSession",
    "ServiceSpec",
    "ServiceUnavailable",
    "Variant",
    "authored_of",
    "bit_rot_hint",
    "clone_root_of",
    "parse_services",
    "probe_url",
    "read_fixture",
    "safe_name",
)
