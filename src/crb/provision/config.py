"""The provisioning settings the worker runs with (``CRB_PROVISION__*``, ADR-0019).

A plain frozen dataclass, read from the environment by :meth:`ProvisionConfig.from_env`, so
the worker and the CLI need neither pydantic nor the server; the API's
:class:`crb.server.settings.ProvisionSettings` is the same fields with validation and the
``/settings`` view, and converts to this with ``to_config``.

Provisioning is **off** by default: switching it on is the operator's consent to a fetch
through their egress. In production (``CRB_ENV=prod``) a public registry is refused unless
``allow_public`` is set — a mirror inside the tenant is the documented shape — and every
fetch image must be pinned by digest. A ``file://`` mirror runs the fetch with no network
at all (the air-gapped mode, and how CI proves the fetch).

Navigation
----------
What it is:   The worker-side provisioning configuration: registries, fetch images, store,
              limits and the production refusals.
What it does: Reads ``CRB_PROVISION__*``; derives each recipe's registry hosts (the proxy's
              exact allowlist) or its air-gapped mirror; refuses a public registry in
              production without ``allow_public`` and a fetch image without ``@sha256``.
How:          ``from_env`` → typed fields → ``production_refusal`` (``PROVISION_PUBLIC_REGISTRY``
              / ``PROVISION_FETCH_IMAGE_UNPINNED``) → ``hosts_for`` / ``mirror_for`` per language.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/provision/__init__.py (``make_deps_provider`` reads it),
              src/crb/server/settings.py (``ProvisionSettings`` mirrors it for the API),
              src/crb/provision/fetch.py (the allowlist and the mirror),
              docs/DEPLOYMENT.md#21-environment-reference (the operator's list)
Tested by:    tests/test_provision_go.py, tests/test_settings_provision.py
Touch when:   a registry or limit becomes configurable (a field here, in ``ProvisionSettings``,
              in DEPLOYMENT §2.1 and in the Helm/compose templates).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from crb.builders import egress_proxy
from crb.core.deps import ProvisionRefused
from crb.core.provision import LANG_GO, LANG_NODE, LANG_PYTHON

ENV_PREFIX = "CRB_PROVISION__"

#: The toolchain stage of the Go sandbox image (deploy/sandbox/Dockerfile.go): it has CA
#: certificates, which the slim runtime does not (the D3 finding).
DEFAULT_GO_IMAGE = (
    "golang:1.26.8-bookworm@sha256:a688600ca24f8a4d3ca77f95b0dd40704a9fc787c826660eb7ba0b641b8b175d"
)
#: The Python sandbox image's base (deploy/sandbox/Dockerfile.python).
DEFAULT_PYTHON_IMAGE = "python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7"
#: The Node sandbox image's base (deploy/sandbox/Dockerfile.node).
DEFAULT_NODE_IMAGE = "node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90"

#: The public registries: refused in production unless ``allow_public``.
PUBLIC_HOSTS: frozenset[str] = frozenset(
    {
        "proxy.golang.org",
        "sum.golang.org",
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
    }
)


def _host(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        return ""
    return f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname


def _truthy(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProvisionConfig:
    """``CRB_PROVISION__*``. See the module docstring for the defaults' reasons."""

    enabled: bool = False
    store: Path = Path(".crb") / "deps"
    go_proxy: str = "https://proxy.golang.org"
    go_sumdb: str = "sum.golang.org"
    pypi_index: str = "https://pypi.org/simple"
    pypi_files_host: str = "files.pythonhosted.org"
    npm_registry: str = "https://registry.npmjs.org"
    extra_allow_hosts: tuple[str, ...] = ()
    allow_public: bool = False
    egress_network: str = "bridge"
    proxy_image: str = ""
    go_image: str = DEFAULT_GO_IMAGE
    python_image: str = DEFAULT_PYTHON_IMAGE
    node_image: str = DEFAULT_NODE_IMAGE
    ca_bundle: str = ""
    max_bundle_mb: int = 2048
    max_total_gb: float = 20.0
    fetch_timeout_s: int = 900
    env: str = "prod"
    docker_binary: str = ""
    extra: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "store", Path(self.store).expanduser())
        hosts = tuple(h.strip() for h in self.extra_allow_hosts if str(h).strip())
        egress_proxy.parse_allow(list(hosts))  # a typo fails at start-up
        object.__setattr__(self, "extra_allow_hosts", hosts)
        if self.max_bundle_mb <= 0 or self.fetch_timeout_s <= 0 or self.max_total_gb <= 0:
            raise ValueError("provisioning limits must be positive")
        proxies = [p.strip() for p in self.go_proxy.replace("|", ",").split(",")]
        if len(proxies) != 1 or proxies[0] in {"direct", "off", ""}:
            raise ValueError(
                "CRB_PROVISION__GO_PROXY must be one proxy URL (or file:// mirror): never "
                "'direct', 'off' or a list — a fetch never reaches a VCS"
            )

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, *, home: Path | None = None
    ) -> ProvisionConfig:
        e = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return str(e.get(f"{ENV_PREFIX}{name}", default)).strip()

        home = home or Path(str(e.get("CRB_HOME") or ".crb")).expanduser()
        extra = tuple(h.strip() for h in get("EXTRA_ALLOW_HOSTS").split(",") if h.strip())
        return cls(
            enabled=_truthy(get("ENABLED", "false")),
            store=Path(get("STORE") or str(home / "deps")),
            go_proxy=get("GO_PROXY") or cls.go_proxy,
            go_sumdb=get("GO_SUMDB") or cls.go_sumdb,
            pypi_index=get("PYPI_INDEX") or cls.pypi_index,
            pypi_files_host=get("PYPI_FILES_HOST") or cls.pypi_files_host,
            npm_registry=get("NPM_REGISTRY") or cls.npm_registry,
            extra_allow_hosts=extra,
            allow_public=_truthy(get("ALLOW_PUBLIC", "false")),
            egress_network=get("EGRESS_NETWORK") or "bridge",
            proxy_image=get("PROXY_IMAGE") or str(e.get("CRB_BUILDER__PROXY_IMAGE", "")).strip(),
            go_image=get("GO_IMAGE") or DEFAULT_GO_IMAGE,
            python_image=get("PYTHON_IMAGE") or DEFAULT_PYTHON_IMAGE,
            node_image=get("NODE_IMAGE") or DEFAULT_NODE_IMAGE,
            ca_bundle=get("CA_BUNDLE"),
            max_bundle_mb=int(get("MAX_BUNDLE_MB") or 2048),
            max_total_gb=float(get("MAX_TOTAL_GB") or 20),
            fetch_timeout_s=int(get("FETCH_TIMEOUT_S") or 900),
            env=str(e.get("CRB_ENV") or "prod").strip().lower(),
        )

    # --- per language --------------------------------------------------------------
    def image_for(self, lang: str) -> str:
        return {LANG_GO: self.go_image, LANG_PYTHON: self.python_image, LANG_NODE: self.node_image}[
            lang
        ]

    def mirror_for(self, lang: str) -> Path | None:
        """The host path of a ``file://`` registry for ``lang`` (air-gapped), else ``None``."""
        url = {LANG_GO: self.go_proxy, LANG_PYTHON: self.pypi_index, LANG_NODE: self.npm_registry}[
            lang
        ]
        if url.startswith("file://"):
            return Path(urlsplit(url).path)
        return None

    def hosts_for(self, lang: str) -> tuple[str, ...]:
        """The exact allowlist the fetch's proxy serves for ``lang`` (never ``direct``, never
        a VCS host): the registry, the checksum database or files host, and the extras."""
        if self.mirror_for(lang) is not None:
            return ()
        if lang == LANG_GO:
            hosts = [_host(self.go_proxy)]
            if self.go_sumdb and self.go_sumdb != "off":
                hosts.append(self.go_sumdb.split()[0].split("+")[0].split("/")[0])
        elif lang == LANG_PYTHON:
            hosts = [_host(self.pypi_index), self.pypi_files_host]
        else:
            hosts = [_host(self.npm_registry)]
        out: dict[str, None] = {h: None for h in hosts if h}
        for h in self.extra_allow_hosts:
            out[h] = None
        return tuple(out)

    def npm_registry_host(self) -> str:
        return (
            (urlsplit(self.npm_registry).hostname or "")
            if not self.npm_registry.startswith("file://")
            else "registry.npmjs.org"
        )

    # --- production refusals ------------------------------------------------------------
    def production_refusal(self) -> ProvisionRefused | None:
        """In production: a public registry without ``allow_public`` is
        ``PROVISION_PUBLIC_REGISTRY``; a fetch image without ``@sha256:`` is
        ``PROVISION_FETCH_IMAGE_UNPINNED``. ``None`` when neither applies."""
        if not self.enabled or self.env != "prod":
            return None
        if not self.allow_public:
            public = sorted(
                {
                    h.split(":")[0]
                    for lang in (LANG_GO, LANG_PYTHON, LANG_NODE)
                    for h in self.hosts_for(lang)
                }
                & PUBLIC_HOSTS
            )
            if public:
                return ProvisionRefused(
                    "PROVISION_PUBLIC_REGISTRY",
                    f"production provisioning points at public registries: {', '.join(public)}",
                )
        unpinned = [
            i for i in (self.go_image, self.python_image, self.node_image) if "@sha256:" not in i
        ]
        if unpinned:
            return ProvisionRefused(
                "PROVISION_FETCH_IMAGE_UNPINNED",
                f"fetch image(s) not pinned by digest: {', '.join(unpinned)}",
            )
        return None

    def view(self) -> dict[str, object]:
        """Hosts and flags only — what ``GET /settings`` shows (no path to a secret)."""
        return {
            "enabled": self.enabled,
            "store": str(self.store),
            "allow_public": self.allow_public,
            "hosts": {
                lang: list(self.hosts_for(lang)) for lang in (LANG_GO, LANG_PYTHON, LANG_NODE)
            },
            "mirrors": {
                lang: str(self.mirror_for(lang) or "") for lang in (LANG_GO, LANG_PYTHON, LANG_NODE)
            },
            "images": {"go": self.go_image, "python": self.python_image, "node": self.node_image},
            "egress_network": self.egress_network,
            "ca_bundle_configured": bool(self.ca_bundle),
            "max_bundle_mb": self.max_bundle_mb,
            "max_total_gb": self.max_total_gb,
            "fetch_timeout_s": self.fetch_timeout_s,
        }


__all__ = [
    "DEFAULT_GO_IMAGE",
    "DEFAULT_NODE_IMAGE",
    "DEFAULT_PYTHON_IMAGE",
    "ENV_PREFIX",
    "PUBLIC_HOSTS",
    "ProvisionConfig",
]
