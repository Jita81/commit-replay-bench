"""A private mirror's credential reaches the fetch container, and nothing else (G-950).

Navigation
----------
What it is:   The suite for the mirror credential of dependency provisioning: the setting that
              names it, the argv that carries its name, the prelude that turns it into the
              toolchain's own file, and the one process whose environment holds its value.
What it does: Pins that the setting is a variable NAME (a value-shaped setting is refused at
              start-up) and that ``view`` shows the name, never a value; that only a networked
              ``fetch`` step to a registry that is not public carries it — never an install or
              rebuild step, a ``file://`` mirror or a public registry; that the argv holds
              ``--env CRB_MIRROR_CREDENTIAL`` with no value and the prelude, and the value
              appears in no argv token; that ``run_fetch`` gives the value to the docker client
              of the fetch alone, scrubs it from any output it keeps, and refuses (a deployment
              fault) when the named variable is not set; and that the prelude, run by a real
              POSIX shell, writes the ``.netrc`` pip and Go read and the ``.npmrc`` npm reads,
              owner-only, and removes the variable before the toolchain starts.
How:          ``fetch_argv`` on fixed plans; ``run_fetch`` against a fake ``docker`` script
              that records its argv and environment, with the egress sidecar stubbed; the
              prelude run with ``/bin/sh`` on the host.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/provision/fetch.py (under test), src/crb/provision/config.py
              (``mirror_credential_for``), src/crb/server/settings.py (``ProvisionSettings``)
Tested by:    tests/test_provision_mirror_credential.py
Touch when:   never for a new repository; the way a fetch carries a credential changes (a
              security decision: docs/SECURITY.md §3.1.1).
"""

from __future__ import annotations

import base64
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from crb.core.deps import ProvisionRefused
from crb.core.execution import SandboxUnavailable
from crb.provision import fetch as fetch_mod
from crb.provision.config import ProvisionConfig
from crb.provision.fetch import (
    CREDENTIAL_PRELUDE,
    MIRROR_CREDENTIAL,
    FetchPlan,
    MirrorCredential,
    fetch_argv,
    run_fetch,
)

SECRET = "svc-crb:s3cr3t-Mirr0r-p4ss"
KEY = "dep_" + "c" * 64
MIRROR = "https://artifacts.corp.example/api/pypi/simple"
NPM_MIRROR = "https://artifacts.corp.example:8443/api/npm/npm-remote"


def _cfg(**kw: Any) -> ProvisionConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "pypi_index": MIRROR,
        "pypi_files_host": "artifacts.corp.example",
        "npm_registry": NPM_MIRROR,
        "mirror_credential_env": "CORP_MIRROR_AUTH",
        "proxy_image": "crb-proxy:t",
    }
    base.update(kw)
    return ProvisionConfig(**base)


def _plan(lang: str = "python", **kw: Any) -> FetchPlan:
    base: dict[str, Any] = {
        "recipe": "py.site.v1",
        "lang": lang,
        "key": KEY,
        "image": "python:3.12@sha256:" + "a" * 64,
        "argv": ("python", "-m", "pip", "download", "-r", "/in/lock.txt", "-d", "/out/wheels"),
        "env": {"PIP_CONFIG_FILE": "/dev/null"},
        "registry_hosts": ("artifacts.corp.example",),
    }
    base.update(kw)
    return FetchPlan(**base)


# --- the setting ------------------------------------------------------------------------


def test_the_setting_is_a_variable_name_and_the_view_never_holds_a_value() -> None:
    with pytest.raises(ValueError, match="name of an environment variable"):
        ProvisionConfig(mirror_credential_env="user:password")
    cfg = ProvisionConfig.from_env(
        {
            "CRB_PROVISION__MIRROR_CREDENTIAL_ENV": "CORP_MIRROR_AUTH",
            "CRB_PROVISION__PYPI_INDEX": MIRROR,
            "CORP_MIRROR_AUTH": SECRET,
        }
    )
    view = cfg.view()
    assert view["mirror_credential_env"] == "CORP_MIRROR_AUTH"
    assert view["mirror_credential_langs"] == [
        "python"
    ]  # go and npm still point at public registries
    assert SECRET not in repr(view) and SECRET not in repr(cfg)


def test_the_server_settings_carry_the_name_to_the_worker_config(tmp_path: Path) -> None:
    from crb.server.settings import ProvisionSettings

    cfg = ProvisionSettings(mirror_credential_env="CORP_MIRROR_AUTH").to_config(
        env="dev", home=tmp_path
    )
    assert cfg.mirror_credential_env == "CORP_MIRROR_AUTH"


def test_only_a_networked_fetch_to_a_private_registry_carries_it() -> None:
    cfg = _cfg()
    assert MirrorCredential.for_plan(_plan(), cfg) == MirrorCredential(
        "CORP_MIRROR_AUTH", "netrc", "artifacts.corp.example"
    )
    node = MirrorCredential.for_plan(_plan("node"), cfg)
    assert node == MirrorCredential(
        "CORP_MIRROR_AUTH",
        "npmrc",
        "artifacts.corp.example",
        "//artifacts.corp.example:8443/api/npm/npm-remote/",
    )
    # an install or rebuild step runs with no network: nothing to authenticate to
    assert MirrorCredential.for_plan(_plan(step="install", offline=True), cfg) is None
    # a public registry never receives the credential for your mirror
    assert MirrorCredential.for_plan(_plan("go"), cfg) is None
    assert MirrorCredential.for_plan(_plan(), _cfg(pypi_index="https://pypi.org/simple")) is None
    # an air-gapped file:// mirror is read from disk
    assert MirrorCredential.for_plan(_plan(), _cfg(pypi_index="file:///srv/mirror")) is None
    assert MirrorCredential.for_plan(_plan(), _cfg(mirror_credential_env="")) is None


# --- the argv ---------------------------------------------------------------------------


def test_the_argv_names_the_credential_and_never_carries_it(tmp_path: Path) -> None:
    cred = MirrorCredential.for_plan(_plan(), _cfg())
    argv = fetch_argv(
        _plan(),
        network="crb-f-1",
        stage=tmp_path,
        image="python:3.12@sha256:" + "a" * 64,
        user="501:20",
        name="crb-fetch-1",
        proxy_url="http://proxy:3128",
        credential=cred,
    )
    i = argv.index(MIRROR_CREDENTIAL)
    assert argv[i - 1] == "--env" and "=" not in argv[i]
    assert argv[i + 1 : i + 5] == [
        "--env",
        "CRB_MIRROR_KIND=netrc",
        "--env",
        "CRB_MIRROR_HOST=artifacts.corp.example",
    ]
    tail = argv[argv.index("python:3.12@sha256:" + "a" * 64) + 1 :]
    assert tail[:4] == ["sh", "-c", CREDENTIAL_PRELUDE, "crb-fetch"]
    assert tail[4:] == list(_plan().argv)
    assert all(SECRET not in tok for tok in argv)
    # without a credential the argv is exactly what it was
    plain = fetch_argv(
        _plan(),
        network="crb-f-1",
        stage=tmp_path,
        image="python:3.12@sha256:" + "a" * 64,
        user="501:20",
        name="crb-fetch-1",
        proxy_url="http://proxy:3128",
    )
    assert MIRROR_CREDENTIAL not in plain and "sh" not in plain


def test_npm_reads_the_prelude_file_instead_of_no_user_config(tmp_path: Path) -> None:
    plan = _plan("node", env={"npm_config_userconfig": "/dev/null"})
    argv = fetch_argv(
        plan,
        network="n",
        stage=tmp_path,
        image="node@sha256:" + "b" * 64,
        user="501:20",
        credential=MirrorCredential.for_plan(plan, _cfg()),
    )
    assert (
        "npm_config_userconfig=/tmp/.npmrc" in argv
        and "npm_config_userconfig=/dev/null" not in argv
    )
    assert "CRB_MIRROR_SCOPE=//artifacts.corp.example:8443/api/npm/npm-remote/" in argv


# --- run_fetch: the one process whose environment holds the value -------------------------


class _Sidecar:
    network = "crb-f-stub"
    url = "http://proxy:3128"

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    def start(self, **k: Any) -> None:
        pass

    def close(self) -> None:
        pass

    def denied_hosts(self) -> list[str]:
        return []


def _fake_docker(tmp_path: Path, exit_code: int) -> tuple[Path, Path]:
    log = tmp_path / "calls.log"
    script = tmp_path / "docker"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "ARGV %s\\n" "$*" >> "{log}"\n'
        f'printf "ENV %s\\n" "${{CRB_MIRROR_CREDENTIAL-<unset>}}" >> "{log}"\n'
        'if [ "$1" = run ]; then echo "fetching with $CRB_MIRROR_CREDENTIAL" >&2; '
        f"exit {exit_code}; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, log


def test_run_fetch_hands_the_value_to_the_fetch_alone_and_scrubs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch_mod, "EgressSidecar", _Sidecar)
    monkeypatch.setenv("CORP_MIRROR_AUTH", SECRET)
    monkeypatch.delenv(MIRROR_CREDENTIAL, raising=False)
    docker, log = _fake_docker(tmp_path, exit_code=1)
    with pytest.raises(ProvisionRefused) as ei:
        run_fetch(_plan(), tmp_path / "stage", config=_cfg(), docker=str(docker), user="501:20")
    assert SECRET not in ei.value.message and "[mirror credential]" in ei.value.message
    lines = log.read_text(encoding="utf-8").splitlines()
    runs = [i for i, ln in enumerate(lines) if ln.startswith("ARGV run ")]
    assert len(runs) == 1
    envs = [ln for ln in lines if ln.startswith("ENV ")]
    after_run = next(ln for ln in lines[runs[0] :] if ln.startswith("ENV "))
    assert after_run == f"ENV {SECRET}"  # the fetch's docker client holds it …
    assert [e for e in envs if SECRET in e] == [after_run]  # … and no other docker call does
    argv_text = log.read_text(encoding="utf-8").replace(f"ENV {SECRET}", "")
    assert SECRET not in argv_text  # … and it is on no argv


def test_an_install_step_never_receives_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORP_MIRROR_AUTH", SECRET)
    docker, log = _fake_docker(tmp_path, exit_code=0)
    run_fetch(
        _plan(step="install", offline=True),
        tmp_path / "stage",
        config=_cfg(),
        docker=str(docker),
        user="501:20",
    )
    lines = log.read_text(encoding="utf-8").splitlines()
    assert [ln for ln in lines if ln.startswith("ENV ")] == ["ENV <unset>"]
    assert not any(MIRROR_CREDENTIAL in ln for ln in lines if ln.startswith("ARGV"))


def test_a_named_variable_that_is_not_set_is_a_deployment_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CORP_MIRROR_AUTH", raising=False)
    docker, _ = _fake_docker(tmp_path, exit_code=0)
    with pytest.raises(SandboxUnavailable, match="CORP_MIRROR_AUTH"):
        run_fetch(_plan(), tmp_path / "stage", config=_cfg(), docker=str(docker), user="501:20")


# --- the prelude, run by a real POSIX shell ---------------------------------------------------


def _prelude(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return subprocess.run(
        [
            "/bin/sh",
            "-c",
            CREDENTIAL_PRELUDE,
            "crb-fetch",
            "/bin/sh",
            "-c",
            'printf "LEFT=%s\\n" "${CRB_MIRROR_CREDENTIAL-<unset>}"',
        ],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_prelude_writes_the_netrc_pip_and_go_read_and_unsets_the_variable(
    tmp_path: Path,
) -> None:
    r = _prelude(
        tmp_path,
        CRB_MIRROR_CREDENTIAL=SECRET,
        CRB_MIRROR_KIND="netrc",
        CRB_MIRROR_HOST="artifacts.corp.example",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "LEFT=<unset>"  # the toolchain never sees the variable
    netrc = tmp_path / "home" / ".netrc"
    assert (
        netrc.read_text(encoding="utf-8")
        == "machine artifacts.corp.example\nlogin svc-crb\npassword s3cr3t-Mirr0r-p4ss\n"
    )
    assert stat.S_IMODE(netrc.stat().st_mode) == 0o600
    assert SECRET not in r.stdout + r.stderr


def test_the_prelude_writes_the_npmrc_npm_reads(tmp_path: Path) -> None:
    scope = "//artifacts.corp.example:8443/api/npm/npm-remote/"
    r = _prelude(
        tmp_path,
        CRB_MIRROR_CREDENTIAL=SECRET,
        CRB_MIRROR_KIND="npmrc",
        CRB_MIRROR_HOST="artifacts.corp.example",
        CRB_MIRROR_SCOPE=scope,
    )
    assert r.returncode == 0, r.stderr
    line = (tmp_path / "home" / ".npmrc").read_text(encoding="utf-8").strip()
    key, _, value = line.partition(":_auth=")
    assert key == scope and base64.b64decode(value).decode() == SECRET


@pytest.mark.parametrize("value", ["", "no-colon-token"])
def test_the_prelude_refuses_an_empty_or_malformed_credential(tmp_path: Path, value: str) -> None:
    r = _prelude(
        tmp_path, CRB_MIRROR_CREDENTIAL=value, CRB_MIRROR_KIND="netrc", CRB_MIRROR_HOST="h"
    )
    assert r.returncode == 64 and not (tmp_path / "home" / ".netrc").exists()
    assert (value or "x") not in r.stderr or value == ""


# --- nothing else on the worker receives it ----------------------------------------------------


def test_no_test_container_host_command_or_builder_environment_carries_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker holds the variable in its own environment, so every other child it starts
    must build its environment from an allowlist that cannot name it: the local executor's
    test commands, the builder's child process, the sealed builder's docker client and git."""
    from crb.builders import claude_code, container
    from crb.core.execution import LocalExecutor

    monkeypatch.setenv("CORP_MIRROR_AUTH", SECRET)
    envs = {
        "local test command": LocalExecutor._host_base_env(),
        "builder child": claude_code._base_env(),
        "sealed builder's docker client": container.client_env({}),
        "sealed builder's git": container._git_env(),
    }
    for where, env in envs.items():
        assert "CORP_MIRROR_AUTH" not in env and MIRROR_CREDENTIAL not in env, where
        assert SECRET not in env.values(), where
