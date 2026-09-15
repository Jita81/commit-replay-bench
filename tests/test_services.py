"""Services the oracle needs (``runner_opts.services`` → :mod:`crb.core.services`).

Hermetic parts drive :class:`ServiceSession` and the runner hooks through a small
in-memory docker simulator (``FakeDocker``): parsing and its error messages, era
selection, fixture staging from the clone and from history, the compose override
file, adoption of a running instance, variant switching, log capture with
redaction, and every fail-closed branch (unhealthy, failed start, failed build
with the bit-rot hint, missing fixture, sandbox executor, malformed config).

The docker-gated part (``@pytest.mark.docker``) starts ``python:3.12-slim`` as a
real service for the Python fixture repository — its test reads the service URL
from the environment and fetches a fixture the session staged and mounted — and
proves the evidence records the image digest and that an unhealthy service is a
harness error, never a verdict.

Navigation
----------
What it is:   The oracle-services suite (``runner_opts.services`` → ``crb.core.services``).
What it does: Pins, through an in-memory docker simulator, parsing and its error messages, era
              selection by authored date, fixture staging from the clone and from history, the
              compose override, adoption of a running instance, variant switching (a worker
              restart between eras left the other variant bound to the port), log capture with
              redaction, and every fail-closed branch (unhealthy, failed start, failed build with
              the bit-rot hint, missing fixture, sandbox executor, malformed config); the
              docker-marked cases start ``python:3.12-slim`` as a real service for the fixture and
              prove the evidence records the image digest.
How:          ``FakeDocker`` answers the docker commands the session issues and runs everything
              else for real; the runner hooks are exercised through ``PytestRunner`` on ``pyrepo``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/services.py (under test), src/crb/core/runners/base.py
              (``SetupSession`` and the run hooks), src/crb/core/runners/pytest_runner.py (the
              runner that merges the service env), tests/test_builders_adapter.py (the builder
              gets the same services, DL-024), docs/OPERATOR.md (services the oracle needs, §2.2)
Tested by:    tests/test_services.py
Touch when:   onboarding a repository whose tests need a service the spec cannot express (a
              parse case, a session case through ``FakeDocker`` and a docs/OPERATOR.md entry);
              the health or era rules change.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.core.execution import Command, ExecResult, LocalExecutor, SandboxUnavailable
from crb.core.runners.base import SetupSession
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.services import (
    SERVICES_SANDBOX_REFUSED,
    BuildRef,
    ComposeRef,
    Era,
    Fixture,
    Health,
    ServiceRecord,
    ServiceSession,
    ServiceSpec,
    ServiceUnavailable,
    authored_of,
    bit_rot_hint,
    clone_root_of,
    parse_services,
    safe_name,
)
from fixtures import pyrepo as pr

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

# ---------------------------------------------------------------------------
# An in-memory docker: enough of ``run/inspect/logs/rm/build/compose`` to drive the session
# ---------------------------------------------------------------------------


class FakeDocker:
    """Answers the docker commands the session issues; runs everything else for real.

    ``healthy`` is what the injected URL probe answers; ``fail`` names commands that
    must fail (``"run"``, ``"build"``, ``"up"``); ``logs`` is what ``docker logs``
    prints. Containers are tracked by name (``docker run``) or by compose project +
    service (``compose up``).
    """

    name = "local"

    def __init__(
        self, *, healthy: bool = True, fail: set[str] | None = None, logs: str = ""
    ) -> None:
        self.healthy = healthy
        self.fail = set(fail or ())
        self.logs = logs
        self.running: dict[str, str] = {}  # container name/id → image
        self.commands: list[Command] = []
        self.local = LocalExecutor()

    # -- executor protocol --
    def tool(self, name: str, host_override: str | None = None) -> str:
        return "/fake/docker" if name == "docker" else (host_override or name)

    def describe(self) -> dict[str, Any]:
        return {"executor": self.name}

    def run(self, cmd: Command) -> ExecResult:
        self.commands.append(cmd)
        if cmd.argv[0] != "/fake/docker":
            return self.local.run(cmd)
        return self._docker(list(cmd.argv[1:]))

    # -- the probe the session gets --
    def probe(self, url: str, timeout: float, insecure: bool) -> bool:
        return self.healthy

    # -- docker CLI --
    def _docker(self, argv: list[str]) -> ExecResult:
        ok = ExecResult(0, "", "", False, 0.01)
        if argv[0] == "inspect":
            target = argv[-1]
            fmt = argv[argv.index("--format") + 1]
            if target not in self.running:
                return ExecResult(1, "", f"Error: No such object: {target}", False, 0.01)
            if "State.Running" in fmt:
                return ExecResult(0, "true\n", "", False, 0.01)
            return ExecResult(0, f"sha256:{'ab' * 32}|{self.running[target]}\n", "", False, 0.01)
        if argv[0] == "run":
            if "run" in self.fail:
                return ExecResult(
                    125,
                    "",
                    "docker: Error response from daemon: port is already allocated",
                    False,
                    0.01,
                )
            name = argv[argv.index("--name") + 1]
            self.running[name] = self._image_of_run(argv)
            return ExecResult(0, "0123456789ab\n", "", False, 0.01)
        if argv[0] == "rm":
            self.running.pop(argv[-1], None)
            return ok
        if argv[0] == "ps":
            # `docker ps --filter name=<prefix> --format {{.Names}}` — running names only
            flt = (
                argv[argv.index("--filter") + 1].removeprefix("name=") if "--filter" in argv else ""
            )
            names = [n for n in self.running if n.startswith(flt)]
            return ExecResult(0, "".join(n + "\n" for n in names), "", False, 0.01)
        if argv[0] == "logs":
            return ExecResult(0, self.logs, "", False, 0.01)
        if argv[0] == "build":
            if "build" in self.fail:
                return ExecResult(
                    1,
                    "",
                    "ERROR: failed to solve: debian bullseye security archive 404 Not Found",
                    False,
                    0.01,
                )
            return ok
        if argv[0] == "compose":
            project = argv[argv.index("-p") + 1]
            rest = argv[[i for i, a in enumerate(argv) if a == "-f"][-1] + 2 :]
            service = rest[-1]
            key = f"{project}-{service}-1"
            if rest[0] == "ps":
                return ExecResult(0, f"{key}\n" if key in self.running else "", "", False, 0.01)
            if rest[0] == "up":
                if "up" in self.fail:
                    return ExecResult(1, "", "failed to solve: bullseye-security 404", False, 0.01)
                self.running[key] = f"{project}-{service}"
                return ok
            if rest[0] == "down":
                for k in [k for k in self.running if k.startswith(project + "-")]:
                    del self.running[k]
                return ok
            if rest[0] == "logs":
                return ExecResult(0, self.logs, "", False, 0.01)
        raise AssertionError(f"FakeDocker: unexpected docker {argv}")

    @staticmethod
    def _image_of_run(argv: list[str]) -> str:
        # the image is the first positional after the flags (every flag here takes a value)
        i = 1
        while i < len(argv):
            if argv[i] in {"-d"}:
                i += 1
            elif argv[i].startswith("-"):
                i += 2
            else:
                return argv[i]
        raise AssertionError("no image in docker run argv")

    def argvs(self) -> list[str]:
        """Every command issued so far, one string each, for asserting the docker call sequence."""
        return [" ".join(c.argv) for c in self.commands]


def _health(**kw: Any) -> dict[str, Any]:
    return {"url": "http://127.0.0.1:18701/health", "timeout_s": 5, "interval_s": 0.01, **kw}


def _spec(**kw: Any) -> ServiceSpec:
    d: dict[str, Any] = {"name": "svc", "image": "example/svc:1", "health": _health()}
    d.update(kw)
    return ServiceSpec.from_dict(d)


def _session(
    specs: list[ServiceSpec], docker: FakeDocker, clone: Path, state: Path | None
) -> ServiceSession:
    clock = {"t": 0.0}

    def tick() -> float:
        return clock["t"]

    def sleep(s: float) -> None:
        clock["t"] += s

    return ServiceSession(
        specs,
        docker,
        clone=clone,
        repo="pyrepo",
        state_dir=state,
        probe=docker.probe,
        clock=tick,
        sleep=sleep,
        docker="/fake/docker",
        register_atexit=False,
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


MESH_CLIENT_SERVICES: list[dict[str, Any]] = [
    {
        "name": "mesh_sandbox",
        "compose": {
            "file": "docker-compose.yml",
            "service": "mesh_sandbox",
            "override": {
                "services": {
                    "mesh_sandbox": {
                        "build": {
                            "context": "https://github.com/NHSDigital/mesh-sandbox.git#refs/tags/v1.0.110"
                        }
                    }
                }
            },
        },
        "ports": ["8701:443"],
        "health": {
            "url": "https://localhost:8701/health",
            "insecure_tls": True,
            "timeout_s": 180,
            "interval_s": 3,
        },
        "fixtures": [
            {"src": "tests/mailboxes.jsonl", "dst": "/app/mesh_sandbox/store/data/mailboxes.jsonl"},
            {"src": "tests/workflows.jsonl", "dst": "/app/mesh_sandbox/store/data/workflows.jsonl"},
        ],
        "variants": [
            {
                "name": "committed-certs",
                "era": {"before": "2025-08-01"},
                "fixtures": [
                    {"src": "5d0047a77c^:tests/server.cert.pem", "dst": "/tmp/server-cert.pem"},
                    {"src": "5d0047a77c^:tests/server.key.pem", "dst": "/tmp/server-cert.key"},
                ],
            },
            {
                "name": "generated-certs",
                "era": {"after": "2025-08-01"},
                "generate": ["bash", "scripts/create-test-certs-keys.sh"],
                "fixtures": [
                    {"src": "tests/server.cert.pem", "dst": "/tmp/server-cert.pem"},
                    {"src": "tests/server.key.pem", "dst": "/tmp/server-cert.key"},
                ],
            },
        ],
    }
]


def test_parse_absent_or_empty_is_no_services() -> None:
    assert parse_services({}) == ()
    assert parse_services({"services": []}) == ()
    assert parse_services({"services": None}) == ()


def test_parse_mesh_client_shape_round_trips() -> None:
    (spec,) = parse_services({"services": MESH_CLIENT_SERVICES})
    assert spec.kind == "compose" and spec.ref == "compose:docker-compose.yml:mesh_sandbox"
    assert spec.compose is not None and spec.compose.override["services"]["mesh_sandbox"]["build"][
        "context"
    ].endswith("v1.0.110")
    assert spec.host_port == "8701" and spec.health.insecure_tls and spec.needs_era
    assert [v.name for v in spec.variants] == ["committed-certs", "generated-certs"]
    # shared fixtures are prepended to every variant; generate stays per variant
    committed, generated = spec.all_variants()
    assert [f.dst for f in committed.fixtures][:2] == [
        "/app/mesh_sandbox/store/data/mailboxes.jsonl",
        "/app/mesh_sandbox/store/data/workflows.jsonl",
    ]
    assert committed.fixtures[2].git_ref == ("5d0047a77c^", "tests/server.cert.pem")
    assert not committed.generate and generated.generate == (
        "bash",
        "scripts/create-test-certs-keys.sh",
    )
    assert generated.fixtures[2].git_ref is None
    again = ServiceSpec.from_dict(spec.to_dict())
    assert again == spec


@pytest.mark.parametrize(
    ("patch", "needle"),
    [
        ({"health": None}, "health is required"),
        (
            {"compose": {"file": "docker-compose.yml", "service": "x"}},
            "exactly one of image | compose | build",
        ),
        ({"image": ""}, "exactly one of image | compose | build"),
        ({"ports": ["8701"]}, "must be '<host>:<container>'"),
        ({"name": "Bad Name"}, "service name"),
        ({"fixtures": [{"src": "a", "dst": "relative"}]}, "absolute container path"),
        ({"fixtures": [{"src": "/etc/passwd", "dst": "/x"}]}, "repository-relative"),
        ({"fixtures": [{"src": "../x", "dst": "/x"}]}, "repository-relative"),
        (
            {"variants": [{"name": "a", "era": {}}, {"name": "b"}]},
            "at most one variant may have no era",
        ),
        (
            {"variants": [{"name": "a"}, {"name": "b", "era": {"after": "2020-01-01"}}]},
            "must come last",
        ),
        (
            {
                "variants": [
                    {"name": "a", "era": {"after": "2020-01-01"}},
                    {"name": "a", "era": {"before": "2020-01-01"}},
                ]
            },
            "unique",
        ),
        (
            {"variants": [{"name": "a", "era": {"after": "2021-01-01", "before": "2020-01-01"}}]},
            "earlier than",
        ),
        ({"variants": [{"name": "a", "era": {"after": "yesterday"}}]}, "not an ISO-8601 date"),
        ({"health": {"url": "ftp://x", "cmd": []}}, "must be http(s)"),
        ({"health": {"url": "http://x", "cmd": ["true"]}}, "exactly one of 'url' or 'cmd'"),
        ({"health": {"url": "http://x", "timeout_s": 0}}, "must be positive"),
        ({"image": "", "build": {"context": "docker/", "ref": "v1"}}, "local one has none"),
        ({"image": "", "build": {"context": "/abs"}}, "URL or repository-relative"),
        ({"image": "", "compose": {"file": "../x.yml", "service": "s"}}, "repository-relative"),
        ({"logs_tail": -1}, "logs_tail"),
    ],
)
def test_parse_rejects_malformed_entries_naming_the_service(
    patch: dict[str, Any], needle: str
) -> None:
    d: dict[str, Any] = {"name": "svc", "image": "example/svc:1", "health": _health()}
    d.update(patch)
    with pytest.raises(ValueError, match=r"services\[") as ei:
        parse_services({"services": [d]})
    assert needle in str(ei.value)


def test_parse_rejects_non_list_and_duplicate_names() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        parse_services({"services": "svc"})
    with pytest.raises(ValueError, match=r"services\[0\] must be a mapping"):
        parse_services({"services": ["svc"]})
    one = {"name": "svc", "image": "x", "health": _health()}
    with pytest.raises(ValueError, match="unique"):
        parse_services({"services": [one, dict(one)]})


# ---------------------------------------------------------------------------
# Eras and variants
# ---------------------------------------------------------------------------


def test_era_is_half_open_and_date_boundaries_are_midnight_utc() -> None:
    before = Era(before="2025-08-01")
    after = Era(after="2025-08-01")
    boundary = "2025-08-01T00:00:00+00:00"
    assert not before.matches(boundary) and after.matches(boundary)
    assert before.matches("2025-07-31T23:59:59+00:00") and not after.matches("2025-07-31T23:59:59Z")
    # an aware date east of UTC that is still 2025-07-31 in UTC
    assert before.matches("2025-08-01T01:00:00+02:00")
    assert before.matches("2025-07-31")  # naive == UTC
    window = Era(after="2024-01-01", before="2025-01-01")
    assert (
        window.matches("2024-06-01")
        and not window.matches("2025-01-01")
        and not window.matches("2023-12-31")
    )
    assert str(window) == "[2024-01-01, 2025-01-01)"
    with pytest.raises(ValueError, match="needs 'before' and/or 'after'"):
        Era()


def test_variant_for_selects_by_era_or_fails_closed() -> None:
    (spec,) = parse_services({"services": MESH_CLIENT_SERVICES})
    assert spec.variant_for("2023-07-01T23:13:39Z").name == "committed-certs"
    assert spec.variant_for("2025-08-01T14:49:38Z").name == "generated-certs"
    assert spec.latest_variant().name == "generated-certs"
    with pytest.raises(ServiceUnavailable, match="authored date is unknown"):
        spec.variant_for(None)
    gap = _spec(variants=[{"name": "old", "era": {"before": "2020-01-01"}}])
    with pytest.raises(ServiceUnavailable, match="no variant covers authored"):
        gap.variant_for("2024-01-01")
    # an era-less default takes what no era covers, and is the 'latest'
    dflt = _spec(variants=[{"name": "old", "era": {"before": "2020-01-01"}}, {"name": "cur"}])
    assert dflt.variant_for("2024-01-01").name == "cur" and dflt.variant_for(None).name == "cur"
    assert dflt.latest_variant().name == "cur"
    # no variants: the implicit default carries the shared fixtures
    plain = _spec(fixtures=[{"src": "README.md", "dst": "/srv/README.md"}])
    v = plain.variant_for(None)
    assert (
        v.name == "default" and v.era is None and [f.dst for f in v.fixtures] == ["/srv/README.md"]
    )
    assert plain.all_variants() == (v,) and not plain.needs_era


def test_small_helpers() -> None:
    assert (
        safe_name("crb", "Mesh Client", "mesh_sandbox", "v1.0")
        == "crb-mesh-client-mesh_sandbox-v1-0"
    )
    assert safe_name() == "crb"
    assert Fixture("5d0047a77c^:tests/a.pem", "/tmp/a").git_ref == ("5d0047a77c^", "tests/a.pem")
    assert Fixture("tests/a.pem", "/tmp/a").git_ref is None
    assert BuildRef("https://x/y.git", "v1").source == "https://x/y.git#v1"
    assert BuildRef("docker/squid").source == "docker/squid" and not BuildRef("docker/squid").is_url
    assert Health(cmd=["curl", "-sf", "http://x"]).cmd == ("curl", "-sf", "http://x")
    hint = bit_rot_hint(_spec(image="", build={"context": "https://x/y.git", "ref": "v1.0.27"}))
    assert "build.ref" in hint and "never substitutes" in hint
    (mesh,) = parse_services({"services": MESH_CLIENT_SERVICES})
    assert "compose.override.services.mesh_sandbox.build.context" in bit_rot_hint(mesh)
    rec = ServiceRecord(
        "svc", "default", "img:1", "sha256:ab", "2026-09-14T00:00:00+00:00", True, "c"
    )
    assert ServiceRecord.from_dict(rec.to_dict()) == rec
    assert ComposeRef("docker-compose.yml", "svc").override == {}


# ---------------------------------------------------------------------------
# The session, offline
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> pr.PyRepo:
    """A fresh ``pyrepo`` standing in for the clone the services are staged from."""
    return pr.build(tmp_path / "clone")


def test_image_service_starts_once_reuses_exports_env_and_stops(
    repo: pr.PyRepo, tmp_path: Path
) -> None:
    docker = FakeDocker(logs="hello from svc\nAuthorization: Bearer abcdefghijklmnop123456\n")
    spec = _spec(
        ports=["18701:80"],
        env={"MODE": "test"},
        command=["python", "-m", "http.server", "80"],
        export={"SVC_URL": "http://{host}:{port}/", "SVC_NAME": "{name}"},
    )
    s = _session([spec], docker, repo.path, tmp_path / "state")
    records = s.ensure(None)
    assert len(records) == 1 and records[0] == s.records[0]
    rec = records[0]
    assert rec.name == "svc" and rec.variant == "default" and rec.ref == "example/svc:1"
    assert rec.image_digest == "sha256:" + "ab" * 32 and rec.healthy_at and not rec.adopted
    assert rec.container == "crb-pyrepo-svc-default"
    run_argv = next(a for a in docker.argvs() if " run -d " in a)
    assert "--name crb-pyrepo-svc-default" in run_argv and "-p 18701:80" in run_argv
    assert "--env MODE=test" in run_argv and run_argv.endswith(
        "example/svc:1 python -m http.server 80"
    )
    assert "--label crb.service=1" in run_argv and "--security-opt no-new-privileges" in run_argv
    assert "--mount" not in run_argv  # no fixtures → nothing staged, nothing mounted
    assert s.env == {"SVC_URL": "http://127.0.0.1:18701/", "SVC_NAME": "svc"}
    # the start commands are the network phase; bookkeeping is not
    starts = [c for c in docker.commands if " run -d " in " ".join(c.argv)]
    assert all(c.network for c in starts)
    # idempotent: a second ensure re-probes and starts nothing
    n = len(docker.commands)
    assert s.ensure(None) == records
    assert not any(" run -d " in a for a in docker.argvs()[n:])
    # close: logs captured (redacted) and the container removed
    s.close()
    assert docker.argvs()[-2:][0].endswith("logs --tail 200 crb-pyrepo-svc-default")
    assert docker.argvs()[-1].endswith("rm -f crb-pyrepo-svc-default")
    assert "hello from svc" in s.logs["svc"] and "[REDACTED]" in s.logs["svc"]
    assert "abcdefghijklmnop123456" not in s.logs["svc"]
    assert s.records == () and docker.running == {}


def test_unhealthy_service_fails_closed_with_redacted_logs_and_is_removed(
    repo: pr.PyRepo, tmp_path: Path
) -> None:
    docker = FakeDocker(healthy=False, logs="boot\nAKIAABCDEFGHIJKLMNOP\n")
    s = _session([_spec()], docker, repo.path, tmp_path / "state")
    with pytest.raises(ServiceUnavailable, match="did not become healthy within 5s") as ei:
        s.ensure(None)
    assert isinstance(ei.value, SandboxUnavailable)
    msg = str(ei.value)
    assert "http://127.0.0.1:18701/health" in msg and "boot" in msg
    assert "[REDACTED-AWS]" in msg and "AKIAABCDEFGHIJKLMNOP" not in msg
    assert docker.running == {} and any(
        a.endswith("rm -f crb-pyrepo-svc-default") for a in docker.argvs()
    )
    assert s.records == () and s.logs["svc"] == msg.split("log lines ---\n", 1)[1]


def test_failed_start_and_failed_build_fail_closed_with_the_bit_rot_hint(
    repo: pr.PyRepo, tmp_path: Path
) -> None:
    docker = FakeDocker(fail={"run"})
    s = _session([_spec()], docker, repo.path, tmp_path / "state")
    with pytest.raises(ServiceUnavailable, match=r"docker run failed \(rc=125\)") as ei:
        s.ensure(None)
    assert "port is already allocated" in str(ei.value) and s.records == ()

    docker = FakeDocker(fail={"build"})
    built = _spec(
        image="",
        build={
            "context": "https://github.com/NHSDigital/mesh-sandbox.git",
            "ref": "refs/tags/v1.0.27",
        },
    )
    s = _session([built], docker, repo.path, tmp_path / "state")
    with pytest.raises(ServiceUnavailable, match="docker build failed") as ei:
        s.ensure(None)
    msg = str(ei.value)
    assert "bullseye" in msg and "bit-rot" in msg and "services[svc].build.ref" in msg
    assert "never substitutes a version silently" in msg
    assert not any(" run -d " in a for a in docker.argvs())  # nothing ran on a failed build

    docker = FakeDocker()
    s = _session([built], docker, repo.path, tmp_path / "state")
    (rec,) = s.ensure(None)
    build_argv = next(a for a in docker.argvs() if " build " in a)
    assert build_argv.endswith("mesh-sandbox.git#refs/tags/v1.0.27")
    assert "-t crb-svc-pyrepo-svc:refs-tags-v1-0-27" in build_argv
    assert rec.ref == "https://github.com/NHSDigital/mesh-sandbox.git#refs/tags/v1.0.27"


def test_fixtures_stage_from_clone_and_history_under_state_dir(
    repo: pr.PyRepo, tmp_path: Path
) -> None:
    docker = FakeDocker()
    state = tmp_path / "state"
    gen_src = "open('generated.txt', 'w').write('made once\\n')"
    spec = _spec(
        generate=[sys.executable, "-c", gen_src],
        fixtures=[
            {"src": "README.md", "dst": "/srv/README.md"},
            {"src": f"{repo.initial_sha}:{pr.SRC}", "dst": "/srv/initial_calc.py", "ro": False},
            {"src": "generated.txt", "dst": "/srv/generated.txt"},
        ],
        export={"FIXTURES": "{fixtures}"},
    )
    s = _session([spec], docker, repo.path, state)
    s.ensure(None)
    fx = state / "svc" / "default" / "fixtures"
    assert (fx / "srv/README.md").read_text() == pr.README_SRC
    assert (fx / "srv/initial_calc.py").read_text() == pr.SRC_INITIAL  # from history, not HEAD
    assert (fx / "srv/generated.txt").read_text() == "made once\n"
    assert (
        json.loads((state / "svc" / "default" / ".generated.json").read_text())["argv"][0]
        == sys.executable
    )
    run_argv = next(a for a in docker.argvs() if " run -d " in a)
    assert f"--mount type=bind,src={fx}/srv/README.md,dst=/srv/README.md,readonly" in run_argv
    assert (
        f"--mount type=bind,src={fx}/srv/initial_calc.py,dst=/srv/initial_calc.py "
        in run_argv + " "
    )
    assert s.env == {"FIXTURES": str(fx)}
    # generate ran in the clone, once: prepare() again does not re-run it
    gen_runs = [c for c in docker.commands if c.argv[0] == sys.executable]
    assert len(gen_runs) == 1 and gen_runs[0].root == repo.path.resolve()
    s.prepare()
    assert len([c for c in docker.commands if c.argv[0] == sys.executable]) == 1


def test_missing_fixture_and_missing_state_dir_fail_closed(repo: pr.PyRepo, tmp_path: Path) -> None:
    docker = FakeDocker()
    spec = _spec(fixtures=[{"src": "tests/server.cert.pem", "dst": "/tmp/server-cert.pem"}])
    with pytest.raises(ServiceUnavailable, match="does 'generate' produce it"):
        _session([spec], docker, repo.path, tmp_path / "state").ensure(None)
    with pytest.raises(ServiceUnavailable, match="never /private/tmp"):
        _session([spec], docker, repo.path, None).ensure(None)
    gone = _spec(fixtures=[{"src": f"{repo.initial_sha}:tests/nope.pem", "dst": "/tmp/x"}])
    with pytest.raises(ServiceUnavailable, match="not in the repository's history"):
        _session([gone], docker, repo.path, tmp_path / "state").ensure(None)
    bad_gen = _spec(generate=[sys.executable, "-c", "raise SystemExit(3)"])
    with pytest.raises(ServiceUnavailable, match=r"generate failed \(rc=3\)"):
        _session([bad_gen], docker, repo.path, tmp_path / "state").ensure(None)
    assert not any(" run -d " in a for a in docker.argvs())


def test_compose_service_writes_the_override_and_adopts_a_running_instance(
    repo: pr.PyRepo, tmp_path: Path
) -> None:
    (repo.path / "tests" / "mailboxes.jsonl").write_text("{}\n")
    (repo.path / "tests" / "workflows.jsonl").write_text("{}\n")
    (repo.path / "docker-compose.yml").write_text("services:\n  mesh_sandbox:\n    build: .\n")
    committed = pr.git(repo.path, "rev-parse", "HEAD")
    services = json.loads(json.dumps(MESH_CLIENT_SERVICES))
    # the 'committed' era reads its certs from history: point it at this repo's HEAD files
    services[0]["variants"][0]["fixtures"] = [
        {"src": f"{committed}:{pr.TEST_CALC}", "dst": "/tmp/server-cert.pem"},
    ]
    services[0]["variants"][1]["generate"] = [
        sys.executable,
        "-c",
        "open('tests/server.cert.pem','w').write('CERT')",
    ]
    services[0]["variants"][1]["fixtures"] = [
        {"src": "tests/server.cert.pem", "dst": "/tmp/server-cert.pem"}
    ]
    services[0]["health"]["url"] = "https://localhost:18701/health"
    (spec,) = parse_services({"services": services})
    docker = FakeDocker()
    state = tmp_path / "state"
    s = _session([spec], docker, repo.path, state)
    (rec,) = s.ensure("2023-07-01T00:00:00Z")
    assert (
        rec.variant == "committed-certs"
        and rec.container == "crb-pyrepo-mesh_sandbox-committed-certs-mesh_sandbox-1"
    )
    assert (
        rec.ref == "crb-pyrepo-mesh_sandbox-committed-certs-mesh_sandbox"
    )  # what compose reports as the image
    override_path = state / "mesh_sandbox" / "committed-certs" / "compose.override.json"
    override = json.loads(override_path.read_text())
    svc = override["services"]["mesh_sandbox"]
    assert svc["build"]["context"].endswith("#refs/tags/v1.0.110")  # the operator's override kept
    fx = state / "mesh_sandbox" / "committed-certs" / "fixtures"
    assert svc["volumes"] == [
        f"{fx}/app/mesh_sandbox/store/data/mailboxes.jsonl:/app/mesh_sandbox/store/data/mailboxes.jsonl:ro",
        f"{fx}/app/mesh_sandbox/store/data/workflows.jsonl:/app/mesh_sandbox/store/data/workflows.jsonl:ro",
        f"{fx}/tmp/server-cert.pem:/tmp/server-cert.pem:ro",
    ]
    assert svc["ports"] == ["8701:443"] and svc["labels"] == {
        "crb.service": "1",
        "crb.service.repo": "pyrepo",
    }
    assert (fx / "tmp/server-cert.pem").read_text() == pr.TEST_CALC_SRC
    up = next(a for a in docker.argvs() if " up -d " in a)
    assert up.startswith(
        f"/fake/docker compose -p crb-pyrepo-mesh_sandbox-committed-certs -f {repo.path / 'docker-compose.yml'} -f {override_path} up -d --remove-orphans mesh_sandbox"
    )
    # a different era replaces the running variant: down, then up of the other project
    (rec2,) = s.ensure("2025-09-01T00:00:00Z")
    assert rec2.variant == "generated-certs" and not rec2.adopted
    tail = docker.argvs()
    assert any("committed-certs" in a and a.endswith("down --remove-orphans") for a in tail)
    assert (
        state / "mesh_sandbox" / "generated-certs" / "fixtures" / "tmp/server-cert.pem"
    ).read_text() == "CERT"
    assert list(docker.running) == ["crb-pyrepo-mesh_sandbox-generated-certs-mesh_sandbox-1"]
    # a fresh session (another process) adopts the running healthy instance instead of restarting it
    s2 = _session([spec], docker, repo.path, state)
    n = len(docker.commands)
    (rec3,) = s2.ensure("2025-09-01T00:00:00Z")
    assert rec3.adopted and rec3.variant == "generated-certs"
    assert not any(" up -d " in a for a in docker.argvs()[n:])
    s2.close()  # adopted → not stopped by us
    assert list(docker.running) == ["crb-pyrepo-mesh_sandbox-generated-certs-mesh_sandbox-1"]
    s.close()
    assert docker.running == {}


def test_keep_true_leaves_the_service_running_on_close(repo: pr.PyRepo, tmp_path: Path) -> None:
    docker = FakeDocker()
    s = _session([_spec(keep=True)], docker, repo.path, tmp_path / "state")
    s.ensure(None)
    s.close()
    assert list(docker.running) == ["crb-pyrepo-svc-default"] and "svc" in s.logs


def test_health_cmd_runs_through_the_executor(repo: pr.PyRepo, tmp_path: Path) -> None:
    docker = FakeDocker(healthy=False)  # the URL probe is never consulted
    probe = tmp_path / "probe.txt"
    cmd = [
        sys.executable,
        "-c",
        f"import sys,os; sys.exit(0 if os.path.exists({str(probe)!r}) else 1)",
    ]
    s = _session(
        [_spec(health={"cmd": cmd, "timeout_s": 5, "interval_s": 0.01})],
        docker,
        repo.path,
        tmp_path / "s",
    )
    with pytest.raises(ServiceUnavailable, match="did not become healthy"):
        s.ensure(None)
    probe.write_text("up")
    (rec,) = s.ensure(None)
    assert rec.healthy_at


# ---------------------------------------------------------------------------
# The runner hooks
# ---------------------------------------------------------------------------


def _runner(repo: pr.PyRepo, services: list[dict[str, Any]], env_dir: Path | None) -> PytestRunner:
    cfg = pr.default_config(runner_opts={**repo.config.runner_opts, "services": services})
    return PytestRunner(cfg, env_dir=env_dir)


def test_run_merges_the_service_env_and_stamps_the_test_run(
    repo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker()
    monkeypatch.setattr("crb.core.services.probe_url", docker.probe)
    monkeypatch.setattr("crb.core.services.shutil.which", lambda name: "/fake/docker")
    services = [
        {**_spec(export={"SVC_URL": "http://{host}:{port}/"}, ports=["18701:80"]).to_dict()}
    ]
    runner = _runner(repo, services, tmp_path / "env")
    seen: list[Command] = []
    real_run = docker.run

    def spy(cmd: Command) -> ExecResult:
        seen.append(cmd)
        return real_run(cmd)

    docker.run = spy  # type: ignore[method-assign]
    run = runner.run(docker, repo.path, (pr.TEST_CALC,))
    assert (
        run.green
        and len(run.services) == 1
        and run.services[0].container == "crb-pyrepo-svc-default"
    )
    test_cmd = next(c for c in seen if "-m" in c.argv and "pytest" in c.argv)
    assert test_cmd.env["SVC_URL"] == "http://127.0.0.1:18701/" and "PYTHONPATH" in test_cmd.env
    d = run.to_dict()
    assert d["services"][0]["ref"] == "example/svc:1" and d["services"][0][
        "image_digest"
    ].startswith("sha256:")
    assert runner.describe() == {"runner": "pytest", "services": [run.services[0].to_dict()]}
    # the runner's explicit env wins over an export of the same name
    runner.opts["env"] = {"SVC_URL": "http://operator/"}
    seen.clear()
    runner.run(docker, repo.path, (pr.TEST_CALC,))
    assert next(c for c in seen if "pytest" in c.argv).env["SVC_URL"] == "http://operator/"
    runner.close_services()
    assert (
        docker.running == {} and runner.service_records() == () and "svc" in runner.service_logs()
    )


def test_run_without_services_is_unchanged() -> None:
    from crb.core.runners.base import TestRun

    d = TestRun(0, frozenset()).to_dict()
    assert "services" not in d
    r = PytestRunner(pr.default_config())
    assert not r.has_services() and r.service_specs() == () and r.service_env() == {}
    assert r.describe() == {"runner": "pytest"}
    r.close_services()  # nothing to do, never raises


def test_run_fails_closed_under_a_sandbox_executor_and_on_malformed_config(
    repo: pr.PyRepo, tmp_path: Path
) -> None:
    docker = FakeDocker()
    docker.name = "docker"
    runner = _runner(repo, [_spec().to_dict()], tmp_path / "env")
    with pytest.raises(ServiceUnavailable, match="network=none"):
        runner.run(docker, repo.path, (pr.TEST_CALC,))
    assert str(ServiceUnavailable(SERVICES_SANDBOX_REFUSED)).startswith("runner_opts.services need")
    bad = _runner(repo, [{"name": "svc", "image": "x"}], tmp_path / "env")
    with pytest.raises(
        ServiceUnavailable, match=r"runner_opts.services: services\[svc\]: health is required"
    ):
        bad.run(FakeDocker(), repo.path, (pr.TEST_CALC,))


def test_run_for_binds_the_authored_date_and_the_worktree_head_is_the_fallback(
    repo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker()
    monkeypatch.setattr("crb.core.services.probe_url", docker.probe)
    monkeypatch.setattr("crb.core.services.shutil.which", lambda name: "/fake/docker")
    services = [
        _spec(
            variants=[
                {"name": "old", "era": {"before": "2000-01-01"}},
                {"name": "new", "era": {"after": "2000-01-01"}},
            ]
        ).to_dict()
    ]
    runner = _runner(repo, services, tmp_path / "env")
    # explicit binding
    run = runner.run_for(docker, repo.path, (pr.TEST_CALC,), authored="1999-06-01T00:00:00Z")
    assert run.services[0].variant == "old" and runner.authored is None
    # nothing bound: a worktree's HEAD (the fixture commits were authored now) → 'new'
    ws = repo.trial(tmp_path / "trial")
    run = runner.run(docker, ws.root, (pr.TEST_CALC,))
    assert run.services[0].variant == "new"
    assert clone_root_of(ws.root) == repo.path.resolve() and authored_of(
        ws.root
    ) == repo.repo.author_date(repo.repo.parent(repo.feat_sha))
    # the session stayed keyed to the clone: fixtures/generate come from there, not the worktree
    assert runner._services is not None and runner._services.clone == repo.path.resolve()
    ws.remove()
    runner.close_services()


def test_finish_setup_stages_every_variant_starts_the_latest_and_records_it(
    repo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker()
    monkeypatch.setattr("crb.core.services.probe_url", docker.probe)
    (repo.path / "tests" / "shared.txt").write_text("shared")
    services = [
        _spec(
            fixtures=[{"src": "tests/shared.txt", "dst": "/srv/shared.txt"}],
            variants=[
                {
                    "name": "old",
                    "era": {"before": "2000-01-01"},
                    "generate": [sys.executable, "-c", "open('old.txt','w').write('o')"],
                    "fixtures": [{"src": "old.txt", "dst": "/srv/era.txt"}],
                },
                {
                    "name": "new",
                    "era": {"after": "2000-01-01"},
                    "generate": [sys.executable, "-c", "open('new.txt','w').write('n')"],
                    "fixtures": [{"src": "new.txt", "dst": "/srv/era.txt"}],
                },
            ],
        ).to_dict()
    ]
    runner = _runner(repo, services, tmp_path / "env")
    steps: list[str] = []
    session = SetupSession(docker, on_step=lambda s: steps.append(" ".join(s.argv)))
    # a pytest runner is 'ready' on runner_opts.python; the base finish_setup then turns to the services
    monkey = tmp_path / "env"
    result = runner.finish_setup(session, repo.path, monkey)
    assert result.ok and result.note.startswith("ready; services: svc@new"), result.note
    assert [r.variant for r in result.services] == ["new"] and result.to_dict()["services"][0][
        "variant"
    ] == "new"
    # both eras were staged (generate ran once each), only the latest started
    state = monkey / "services" / "svc"
    assert (state / "old" / "fixtures" / "srv/era.txt").read_text() == "o"
    assert (state / "new" / "fixtures" / "srv/era.txt").read_text() == "n"
    assert (state / "new" / "fixtures" / "srv/shared.txt").read_text() == "shared"
    assert list(docker.running) == ["crb-pyrepo-svc-new"]
    # every service command became a recorded, streamed setup step
    assert any(" run -d " in s for s in steps) and [s.argv for s in result.steps] == [
        tuple(s.split(" ")) for s in steps
    ]
    runner.close_services()


def test_finish_setup_fails_the_phase_when_a_service_cannot_be_provided(
    repo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker(healthy=False, logs="crashed\n")
    monkeypatch.setattr("crb.core.services.probe_url", docker.probe)
    runner = _runner(repo, [_spec().to_dict()], tmp_path / "env")
    session = SetupSession(docker)
    result = runner.finish_setup(session, repo.path, tmp_path / "env")
    assert (
        not result.ok
        and result.note.startswith("services: service 'svc'")
        and "crashed" in result.note
    )
    assert result.services == () and "services" not in result.to_dict()
    assert docker.running == {}


# ---------------------------------------------------------------------------
# Docker-gated: a real service for the Python fixture repository
# ---------------------------------------------------------------------------

IMAGE = "python:3.12-slim"

TEST_SERVICE_SRC = """import os
import urllib.request


def test_service_serves_the_staged_fixture():
    url = os.environ["SVC_URL"] + "README.md"
    with urllib.request.urlopen(url, timeout=10) as resp:
        assert resp.status == 200
        body = resp.read().decode()
    assert body.startswith("# calc")
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def docker_root() -> Iterator[Path]:
    """A bind-mountable scratch root under the tests cache for the docker-marked cases; skipped
    with the probe's reason when no daemon answers.
    """
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    if not shutil.which("docker"):  # pragma: no cover — covered by the probe above
        pytest.skip("docker binary not on PATH")
    # under tests/.cache (below /Users on macOS): the VM behind colima / Docker Desktop
    # mounts it; pytest's tmp_path under /private/var/folders would be empty inside
    root = langs.CACHE_DIR / "services" / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.mark.docker
@pytest.mark.slow
def test_e2e_service_started_for_the_fixture_repo_and_recorded(docker_root: Path) -> None:
    repo = pr.build(docker_root / "clone")
    (repo.path / "tests" / "test_service.py").write_text(TEST_SERVICE_SRC)
    port = _free_port()
    services = [
        {
            "name": "web",
            "image": IMAGE,
            "command": ["python", "-m", "http.server", "8000", "--directory", "/srv"],
            "ports": [f"{port}:8000"],
            "fixtures": [{"src": "README.md", "dst": "/srv/README.md"}],
            "health": {"url": f"http://127.0.0.1:{port}/", "timeout_s": 120, "interval_s": 1},
            "export": {"SVC_URL": "http://{host}:{port}/"},
            "start_timeout_s": 600,
        }
    ]
    runner = _runner(repo, services, docker_root / "env")
    try:
        run = runner.run(LocalExecutor(), repo.path, ("tests/test_service.py",))
        assert run.green, run.tail
        (rec,) = run.services
        assert rec.ref == IMAGE and rec.image_digest.startswith("sha256:") and rec.healthy_at
        assert not rec.adopted and rec.container == "crb-pyrepo-web-default"
        assert run.to_dict()["services"][0]["image_digest"] == rec.image_digest
        # the fixture was staged under env_dir (mountable), not under a temp path
        staged = (
            docker_root / "env" / "services" / "web" / "default" / "fixtures" / "srv" / "README.md"
        )
        assert staged.read_text() == pr.README_SRC
        # sequential runs share the instance
        again = runner.run(LocalExecutor(), repo.path, ("tests/test_service.py",))
        assert again.green and again.services[0].container == rec.container
    finally:
        runner.close_services()
    probe = LocalExecutor().run(
        Command(
            ("docker", "inspect", "--format", "{{.State.Running}}", "crb-pyrepo-web-default"),
            repo.path,
            timeout=60,
        )
    )
    assert probe.returncode != 0  # gone after close


@pytest.mark.docker
@pytest.mark.slow
def test_e2e_unhealthy_service_is_a_harness_error_never_a_verdict(docker_root: Path) -> None:
    repo = pr.build(docker_root / "clone-unhealthy")
    port = _free_port()
    services = [
        {
            "name": "dead",
            "image": IMAGE,
            "command": ["sleep", "300"],
            "ports": [f"{port}:8000"],
            "health": {"url": f"http://127.0.0.1:{port}/", "timeout_s": 4, "interval_s": 1},
            "start_timeout_s": 600,
        }
    ]
    runner = _runner(repo, services, docker_root / "env-unhealthy")
    try:
        with pytest.raises(ServiceUnavailable, match="did not become healthy within 4s") as ei:
            runner.run(LocalExecutor(), repo.path, (pr.TEST_CALC,))
        assert isinstance(ei.value, SandboxUnavailable)
        assert runner.service_records() == ()
    finally:
        runner.close_services()
    probe = LocalExecutor().run(
        Command(
            ("docker", "inspect", "--format", "{{.State.Running}}", "crb-pyrepo-dead-default"),
            repo.path,
            timeout=60,
        )
    )
    assert probe.returncode != 0  # removed on the failed health wait, not left behind


def test_services_state_dir_honours_services_dir_override(monkeypatch, tmp_path) -> None:
    """The dev stack's CRB_HOME lives under /private/tmp, which colima cannot bind-mount;
    CRB_SERVICES_DIR moves the staged fixtures to a mountable path (2026-09-14)."""
    from crb.core.runners import get_runner
    from crb.core.spec import RepoConfig

    cfg = RepoConfig.from_dict(
        "r", {"language": "python", "runner": "pytest", "path": str(tmp_path)}
    )
    runner = get_runner(cfg)
    runner.env_dir = tmp_path / "env"
    monkeypatch.delenv("CRB_SERVICES_DIR", raising=False)
    assert runner._services_state_dir() == tmp_path / "env" / "services"
    monkeypatch.setenv("CRB_SERVICES_DIR", str(tmp_path / "shared"))
    assert runner._services_state_dir() == tmp_path / "shared" / "r"


def test_switching_era_evicts_the_other_variant_left_by_a_previous_process(tmp_path: Path) -> None:
    """A worker restart between eras left the committed-certs container bound to :8701;
    starting generated-certs failed with 'port is already allocated' (mesh-client,
    2026-09-14). Another era's container is evicted before ours starts."""
    docker = FakeDocker()
    spec = parse_services(
        {
            "services": [
                {
                    "name": "svc",
                    "image": "img:1",
                    "ports": ["8701:443"],
                    "health": {"url": "http://localhost:8701/health", "timeout_s": 5},
                    "variants": [
                        {"name": "old", "era": {"before": "2025-01-01"}},
                        {"name": "new", "era": {"after": "2025-01-01"}},
                    ],
                }
            ]
        }
    )[0]
    stale = safe_name("crb", "r", "svc", "old")
    docker.running[stale] = "img:1"  # left behind by an earlier process, not in our session
    session = ServiceSession(
        (spec,),
        docker,
        clone=tmp_path,
        repo="r",
        state_dir=tmp_path / "s",
        probe=docker.probe,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
    )
    session.ensure("2026-02-01T00:00:00Z")
    assert stale not in docker.running
    assert safe_name("crb", "r", "svc", "new") in docker.running
