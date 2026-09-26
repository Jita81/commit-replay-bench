"""Dependency-provisioning settings: off by default, mirror-first in production (D7, ADR-0019).

Navigation
----------
What it is:   The suite for ``ProvisionSettings`` (the API's ``CRB_PROVISION__*``) and the
              worker's ``ProvisionConfig``.
What it does: Pins that provisioning is off by default; that production refuses a public
              registry unless ``allow_public`` is set and a fetch image not pinned by digest, at
              start-up with the code and the fix; that a malformed allowlist entry fails at
              start-up; that ``GET /settings`` shows hosts and flags only; and that the worker
              reads the same variables from its environment.
How:          ``Settings(...)`` with keyword overrides in ``prod`` and ``dev``;
              ``ProvisionConfig.from_env`` on a dict.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/settings.py (``ProvisionSettings``), src/crb/provision/config.py (the
              worker's side), docs/DEPLOYMENT.md#21-environment-reference (the variables)
Tested by:    tests/test_settings_provision.py
Touch when:   a provisioning variable or production rule changes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from crb.provision.config import DEFAULT_GO_IMAGE, ProvisionConfig, parse_host_list
from crb.server.settings import Settings

MIRROR = {
    "go_proxy": "https://goproxy.corp.example",
    "go_sumdb": "off",
    "pypi_index": "https://pypi.corp.example/simple",
    "pypi_files_host": "pypi.corp.example",
    "npm_registry": "https://npm.corp.example",
}


def _prod(tmp_path: Path, **provision: Any) -> Settings:
    return Settings(
        env="prod",
        home=tmp_path,
        allow_temp_home=True,
        secret_key=SecretStr("k" * 40),
        sandbox={"executor": "docker", "image": "crb-sandbox-go:local"},
        provision=provision,
    )


def test_provisioning_is_off_by_default(tmp_path: Path) -> None:
    s = _prod(tmp_path)
    assert s.provision.enabled is False and s.provision_config.enabled is False
    assert s.provision_config.store == tmp_path / "deps"
    assert ProvisionConfig.from_env({}).enabled is False


def test_prod_refuses_a_public_registry_unless_allowed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as ei:
        _prod(tmp_path, enabled=True)
    msg = str(ei.value)
    assert "PROVISION_PUBLIC_REGISTRY" in msg and "proxy.golang.org" in msg
    assert "CRB_PROVISION__ALLOW_PUBLIC" in msg
    # the documented shape: the organisation's mirror
    ok = _prod(tmp_path, enabled=True, **MIRROR)
    assert ok.provision_config.hosts_for("go") == ("goproxy.corp.example",)
    # or an explicit, recorded choice to allow the public registries
    assert _prod(tmp_path, enabled=True, allow_public=True).provision.allow_public is True
    # dev never refuses (an evaluation reaches the public registries through the proxy)
    dev = Settings(
        env="dev", home=tmp_path, secret_key=SecretStr("k" * 40), provision={"enabled": True}
    )
    assert dev.provision_config.production_refusal() is None


def test_prod_refuses_an_unpinned_fetch_image(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as ei:
        _prod(tmp_path, enabled=True, go_image="golang:1.26.8-bookworm", **MIRROR)
    msg = str(ei.value)
    assert "PROVISION_FETCH_IMAGE_UNPINNED" in msg and "golang:1.26.8-bookworm" in msg
    assert _prod(tmp_path, enabled=True, go_image=DEFAULT_GO_IMAGE, **MIRROR).provision.enabled


def test_a_malformed_allowlist_or_a_direct_proxy_fails_at_start_up(tmp_path: Path) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _prod(tmp_path, enabled=True, extra_allow_hosts="good.example,bad host", **MIRROR)
    with pytest.raises((ValidationError, ValueError), match="never 'direct'"):
        _prod(
            tmp_path, enabled=True, **{**MIRROR, "go_proxy": "https://goproxy.corp.example,direct"}
        )


def test_settings_view_shows_hosts_and_flags_only(tmp_path: Path) -> None:
    s = _prod(tmp_path, enabled=True, ca_bundle="/etc/ssl/corp.pem", **MIRROR)
    view = s.redacted_dict()["provision"]
    assert view["enabled"] is True and view["allow_public"] is False
    assert view["hosts"]["python"] == ["pypi.corp.example"]
    assert view["ca_bundle_configured"] is True and "/etc/ssl/corp.pem" not in str(view)
    assert s.redacted_dict()["sandbox"]["tree"] == "copy"


def test_the_worker_reads_the_same_variables() -> None:
    cfg = ProvisionConfig.from_env(
        {
            "CRB_HOME": "/srv/crb",
            "CRB_ENV": "prod",
            "CRB_PROVISION__ENABLED": "true",
            "CRB_PROVISION__GO_PROXY": "file:///srv/mirror/go",
            "CRB_PROVISION__EXTRA_ALLOW_HOSTS": "cdn.corp.example:8443",
            "CRB_PROVISION__MAX_BUNDLE_MB": "512",
        }
    )
    assert cfg.enabled and cfg.store == Path("/srv/crb/deps") and cfg.max_bundle_mb == 512
    assert cfg.mirror_for("go") == Path("/srv/mirror/go") and cfg.hosts_for("go") == ()
    assert "cdn.corp.example:8443" in cfg.hosts_for("python")


#: The same raw environment read by both processes. Each case is a value an operator could
#: write in the compose file or the Helm values: the API and the worker must agree on it.
_PARITY_CASES: dict[str, dict[str, str]] = {
    "comma list": {"CRB_PROVISION__EXTRA_ALLOW_HOSTS": "a.corp.example, b.corp.example:8443"},
    "json list": {"CRB_PROVISION__EXTRA_ALLOW_HOSTS": '["mirror.corp.example:443"]'},
    "blank": {"CRB_PROVISION__EXTRA_ALLOW_HOSTS": "  "},
    "builder proxy image only": {"CRB_BUILDER__PROXY_IMAGE": "proxy@sha256:" + "1" * 64},
    "own proxy image wins": {
        "CRB_BUILDER__PROXY_IMAGE": "proxy@sha256:" + "1" * 64,
        "CRB_PROVISION__PROXY_IMAGE": "fetch-proxy@sha256:" + "2" * 64,
    },
}


@pytest.mark.parametrize("case", sorted(_PARITY_CASES))
def test_the_api_and_the_worker_read_one_environment_the_same_way(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CodeRabbit on PR #56: the API accepted a JSON host list the worker split on commas
    (the worker then refused to start), and the two fell back to different proxy images.
    One environment, both parsers, the same configuration — every field."""
    env = {
        "CRB_ENV": "dev",
        "CRB_HOME": str(tmp_path),
        "CRB_SECRET_KEY": "k" * 40,
        "CRB_PROVISION__ENABLED": "true",
        **_PARITY_CASES[case],
    }
    for name in list(os.environ):
        if name.startswith("CRB_"):
            monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    api = Settings().provision_config  # the API's path: pydantic-settings over os.environ
    worker = ProvisionConfig.from_env(env, home=tmp_path)  # the worker's path
    assert api == worker


def test_a_json_host_list_reaches_the_worker_as_hosts() -> None:
    cfg = ProvisionConfig.from_env(
        {"CRB_PROVISION__EXTRA_ALLOW_HOSTS": '["mirror.corp.example:443", "b.corp.example"]'}
    )
    assert cfg.extra_allow_hosts == ("mirror.corp.example:443", "b.corp.example")


def test_one_parser_reads_the_host_list_for_both_processes() -> None:
    """The structural half: the API's validator IS the worker's parser, so a format added
    to one cannot be missing from the other."""
    assert parse_host_list('["x.example"]') == ("x.example",)
    assert parse_host_list(" x.example , y.example:8443 ,") == ("x.example", "y.example:8443")
    assert parse_host_list("") == ()
    with pytest.raises(ValueError, match="EXTRA_ALLOW_HOSTS"):
        parse_host_list('["x.example"')  # a broken JSON list is refused, never split
    with pytest.raises(ValueError, match="list of host names"):
        parse_host_list('{"x": 1}')
    src = Path(__file__).resolve().parents[1] / "src" / "crb"
    settings_src = (src / "server" / "settings.py").read_text(encoding="utf-8")
    config_src = (src / "provision" / "config.py").read_text(encoding="utf-8")
    assert 'get("EXTRA_ALLOW_HOSTS").split(' not in config_src
    assert "parse_host_list(" in config_src and "parse_host_list(" in settings_src
