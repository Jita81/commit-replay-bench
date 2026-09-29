"""The host posture's declared test environment: a tool that is merely installed never
changes a verdict (pilot finding D2, ADR-0048).

Navigation
----------
What it is:   The tests for ``crb.core.runners.toolenv`` and the runners' use of it.
What it does: Pins that the declared environment holds exactly the declared tools and the
              allowlisted names, never the worker's ``PATH``; that its digest moves when a
              declared tool's bytes move and never when an undeclared tool appears; that the
              host executor inherits nothing from a declared command; that a Go test which
              fails when an extra tool is on the ``PATH`` reads the same with that tool on the
              worker's ``PATH`` (run and qualification alike); and that the host posture and
              its qualification record and evidence pack name the environment, so a pool
              qualified under one environment is refused under another; and that nothing gets
              round it — a ``PATH`` or loader name in ``runner_opts.env`` is refused, a venv
              ``bin``'s contents move the digest and crb's own never reaches the tests, no
              go env file or git config under ``HOME`` is read, and the farm root is private.
How:          Fake tools in ``tmp_path`` directories prepended to ``PATH``; a real ``go`` for
              the fixture module (skipped without one); ``resolve_posture`` and ``context_for``
              for the identity.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0048-the-host-posture-declares-its-environment.md,
              docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/runners/toolenv.py (under test), src/crb/core/runners/base.py
              (``declare``), src/crb/core/runners/go_runner.py (the Go list),
              src/crb/core/execution.py (``Command.declared_env``), src/crb/core/posture.py
              (``Posture.environment``), tests/fixtures/langs/gorepo.py (the fixture module)
Tested by:    tests/test_runners_toolenv.py
Touch when:   never for a new repository; a runner gains a declaration, or the identity's
              fields change.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from crb.core.deps import HOST_ENV_DEPS, TaskDeps
from crb.core.execution import Command, LocalExecutor
from crb.core.git import GitRepo
from crb.core.grade import Belts
from crb.core.mine import qualify
from crb.core.posture import Posture, PostureMismatch, resolve_posture
from crb.core.qualify import context_for
from crb.core.runners import get_runner
from crb.core.runners.toolenv import (
    IDENTITY_PREFIX,
    ResolvedTool,
    ToolSpec,
    declare_environment,
    ensure_farm,
)
from crb.core.spec import BELT_BARE, Language, RepoConfig, TaskSpec

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

gorepo = langs.fixture_module("gorepo")

needs_go = pytest.mark.toolchain("go")

#: The tool the leak fixture's test refuses to find on its PATH.
LEAK_TOOL = "crbleaktool"

_LEAK_GO = "package leak\n\n// Leak is the unit under test.\nfunc Leak() int { return 1 }\n"
_LEAK_TEST = (
    'package leak\n\nimport (\n\t"os/exec"\n\t"testing"\n)\n\n'
    "func TestNoHostTool(t *testing.T) {\n"
    f'\tif p, err := exec.LookPath("{LEAK_TOOL}"); err == nil {{\n'
    '\t\tt.Fatalf("a host tool reached the test: %s", p)\n'
    "\t}\n}\n"
)


@pytest.fixture(autouse=True)
def _farm_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every farm this module builds lives under its own ``tmp_path``."""
    monkeypatch.setenv("CRB_TOOLENV_DIR", str(tmp_path / "farms"))


def _tool(directory: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


# ---------------------------------------------------------------------------
# The declaration itself (no toolchain needed)
# ---------------------------------------------------------------------------


def test_the_declared_path_holds_only_the_declared_tools(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _tool(host, "crbdeclared")
    _tool(host, LEAK_TOOL)
    env = declare_environment(
        (ToolSpec("crbdeclared"),),
        host_env={
            "PATH": str(host),
            "HOME": "/home/x",
            "SECRET_TOKEN": "s",
            "NODE_OPTIONS": "-r x",
        },
    )
    farm = Path(env.bin_dir)
    assert sorted(p.name for p in farm.iterdir()) == ["crbdeclared"]
    assert env.env["PATH"] == str(farm)
    assert env.env["HOME"] == "/home/x"
    assert "SECRET_TOKEN" not in env.env and "NODE_OPTIONS" not in env.env
    assert env.env["CI"] == "1" and env.env["NO_COLOR"] == "1"
    assert env.identity.startswith(IDENTITY_PREFIX)


def test_an_undeclared_tool_never_moves_the_digest_and_a_declared_one_always_does(
    tmp_path: Path,
) -> None:
    host = tmp_path / "host"
    declared = _tool(host, "crbdeclared")
    specs = (ToolSpec("crbdeclared"), ToolSpec("crbabsent"))
    before = declare_environment(specs, host_env={"PATH": str(host)})
    _tool(host, LEAK_TOOL)  # the shellcheck of the pilot: installed, never declared
    assert declare_environment(specs, host_env={"PATH": str(host)}).digest == before.digest
    declared.write_text("#!/bin/sh\necho changed\nexit 0\n", encoding="utf-8")
    after = declare_environment(specs, host_env={"PATH": str(host)})
    assert after.digest != before.digest
    absent = next(t for t in after.tools if t.name == "crbabsent")
    assert absent.present is False and "crbabsent=absent" in after.summary()


def test_a_locale_or_time_zone_is_part_of_the_identity(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _tool(host, "crbdeclared")
    spec = (ToolSpec("crbdeclared"),)
    utc = declare_environment(spec, host_env={"PATH": str(host), "TZ": "UTC"})
    ldn = declare_environment(spec, host_env={"PATH": str(host), "TZ": "Europe/London"})
    assert utc.digest != ldn.digest
    home_a = declare_environment(spec, host_env={"PATH": str(host), "HOME": "/a"})
    home_b = declare_environment(spec, host_env={"PATH": str(host), "HOME": "/b"})
    assert home_a.digest == home_b.digest  # a path-valued name counts by presence


def test_the_host_executor_inherits_nothing_from_a_declared_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOFLAGS", "-from-the-worker")
    env_tool = "/usr/bin/env"
    declared = LocalExecutor().run(
        Command((env_tool,), tmp_path, env={"ONLY": "1"}, timeout=30, declared_env=True)
    )
    assert declared.ok
    assert declared.stdout.split() == ["ONLY=1"]
    inherited = LocalExecutor().run(Command((env_tool,), tmp_path, env={"ONLY": "1"}, timeout=30))
    assert "GOFLAGS=-from-the-worker" in inherited.stdout.split()


def test_a_docker_command_is_never_declared(tmp_path: Path) -> None:
    from crb.core.execution import DockerExecutor, DockerSettings

    runner = get_runner(gorepo.config())
    ex = DockerExecutor(
        DockerSettings(image="crb-sandbox-go:x", docker_binary="/usr/bin/true"), verify_daemon=False
    )
    cmd = runner.command(tmp_path, ("./calc",), executor=ex, timeout=60)
    assert runner.declared_environment(ex) is None
    assert runner.declare(cmd, ex) == cmd


def _go_config(**opts: object) -> RepoConfig:
    return RepoConfig(
        name="gofix", language=Language.GO, runner="go", belt_scope=BELT_BARE, runner_opts=opts
    )


def test_runner_opts_tools_declare_what_one_repository_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "host"
    _tool(host, "crbneeded")
    _tool(host, LEAK_TOOL)
    monkeypatch.setenv("PATH", f"{host}{os.pathsep}{os.environ.get('PATH', '')}")
    runner = get_runner(_go_config(tools=["crbneeded"]))
    declared = runner.declared_environment(LocalExecutor())
    assert declared is not None
    assert (Path(declared.bin_dir) / "crbneeded").exists()
    assert not (Path(declared.bin_dir) / LEAK_TOOL).exists()
    assert "crbneeded=-@" in declared.summary()


@pytest.mark.parametrize("bad", [{"x": "/bin/x"}, ["/bin/sh"], [""], [1]])
def test_a_tools_option_of_any_other_shape_is_refused_before_a_test_runs(bad: object) -> None:
    with pytest.raises(ValueError, match=r"runner_opts\.tools"):
        get_runner(_go_config(tools=bad)).declared_environment(LocalExecutor())


# ---------------------------------------------------------------------------
# The Go runner on a real toolchain: the pilot's D2, reproduced and closed
# ---------------------------------------------------------------------------


@pytest.fixture
def leak_module(tmp_path: Path) -> Path:
    root = tmp_path / "leakmod"
    (root / "leak").mkdir(parents=True)
    (root / "go.mod").write_text("module example.com/leak\n\ngo 1.22\n", encoding="utf-8")
    (root / "leak" / "leak.go").write_text(_LEAK_GO, encoding="utf-8")
    (root / "leak" / "leak_test.go").write_text(_LEAK_TEST, encoding="utf-8")
    return root


@pytest.fixture
def host_tool_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The pilot's shellcheck: a tool on the worker's PATH that no runner declared."""
    host = tmp_path / "hostbin"
    _tool(host, LEAK_TOOL)
    monkeypatch.setenv("PATH", f"{host}{os.pathsep}{os.environ.get('PATH', '')}")
    return host


@needs_go
def test_a_host_tool_on_the_path_never_changes_the_go_runners_result(
    leak_module: Path, host_tool_on_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = get_runner(gorepo.config())
    ex = LocalExecutor()
    # the fixture is sensitive: the worker's own PATH makes its test fail
    inherited = ex.run(runner.command(leak_module, ("./leak",), executor=ex, timeout=300))
    assert inherited.returncode != 0 and "a host tool reached the test" in inherited.stdout
    with_tool = runner.run(ex, leak_module, ("./leak",))
    monkeypatch.setenv("PATH", os.environ["PATH"].split(os.pathsep, 1)[1])
    without_tool = runner.run(LocalExecutor(), leak_module, ("./leak",))
    assert with_tool.green and without_tool.green
    assert (with_tool.returncode, with_tool.failing) == (
        without_tool.returncode,
        without_tool.failing,
    )


@needs_go
def test_a_host_tool_on_the_path_never_changes_a_qualification(
    tmp_path: Path, host_tool_on_path: Path
) -> None:
    root, feat_sha = gorepo.build(
        tmp_path / "q", extra={"leak/leak.go": _LEAK_GO, "leak/leak_test.go": _LEAK_TEST}
    )
    repo, config = GitRepo(root), gorepo.config(BELT_BARE)
    runner, ex = get_runner(config), LocalExecutor()
    outcome = qualify(
        repo,
        config,
        langs.feat_candidate(repo, config, feat_sha),
        runner=runner,
        executor=ex,
        scratch=tmp_path / "scratch",
    )
    q = outcome.qualification
    assert q is not None and q.is_qualified, outcome.skipped_reason
    # under the inherited PATH the leak test would be red at the parent and subtracted
    assert "example.com/m/leak::TestNoHostTool" not in q.baseline_failing
    assert q.posture["environment"].startswith(IDENTITY_PREFIX)
    assert "go=go version go" in q.posture["environment_tools"]
    assert LEAK_TOOL not in q.posture["environment_tools"]


@needs_go
def test_the_host_posture_names_its_declared_environment(tmp_path: Path) -> None:
    root = tmp_path / "m"
    root.mkdir()
    runner, ex = get_runner(gorepo.config()), LocalExecutor()
    posture = resolve_posture(ex, runner, deps_mode="host-env", root=root)
    assert posture.environment.startswith(IDENTITY_PREFIX)
    assert "git=" in posture.environment_tools and "sh=" in posture.environment_tools
    other = Posture.from_dict({**posture.to_dict(), "environment": IDENTITY_PREFIX + "0" * 64})
    assert other.posture_id != posture.posture_id
    # the tool list names the bytes, as image_ref names the image: never part of the id
    renamed = Posture.from_dict({**posture.to_dict(), "environment_tools": "anything"})
    assert renamed.posture_id == posture.posture_id


@needs_go
def test_a_pool_qualified_under_one_environment_is_refused_under_another(tmp_path: Path) -> None:
    root, feat_sha = gorepo.build(tmp_path / "p")
    repo, config = GitRepo(root), gorepo.config(BELT_BARE)
    runner, ex = get_runner(config), LocalExecutor()
    outcome = qualify(
        repo,
        config,
        langs.feat_candidate(repo, config, feat_sha),
        runner=runner,
        executor=ex,
        scratch=tmp_path / "scratch",
    )
    q, task = outcome.qualification, outcome.task
    assert q is not None and task is not None
    here = Posture.from_dict(q.posture)
    deps = TaskDeps.uniform(HOST_ENV_DEPS)
    assert context_for(task, posture=here, qualification=q, deps=deps, witness=None)
    elsewhere = Posture.from_dict({**q.posture, "environment": IDENTITY_PREFIX + "f" * 64})
    with pytest.raises(PostureMismatch):
        context_for(task, posture=elsewhere, qualification=q, deps=deps, witness=None)


def test_a_posture_without_an_environment_keeps_its_id() -> None:
    """A sandbox posture (the image is the environment) and every runner with no
    declaration hash exactly as before the field existed, so no record goes stale."""
    import hashlib
    import json
    from dataclasses import asdict

    p = Posture(executor="docker", image_id="sha256:ab", toolchain="go version go1.26.8")
    old = asdict(p)
    for k in ("image_ref", "environment", "environment_tools"):
        old.pop(k)
    text = json.dumps(old, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert p.posture_id == "pst_" + hashlib.sha256(text.encode()).hexdigest()[:24]
    assert "environment" not in p.to_dict() and "environment_tools" not in p.to_dict()


# ---------------------------------------------------------------------------
# The same rule for the Python and Node runners
# ---------------------------------------------------------------------------

_PY_LEAK_TEST = (
    f"import shutil\n\n\ndef test_no_host_tool():\n    assert shutil.which({LEAK_TOOL!r}) is None\n"
)


def test_a_host_tool_on_the_path_never_changes_the_python_runners_result(
    tmp_path: Path, host_tool_on_path: Path
) -> None:
    root = tmp_path / "pyleak"
    root.mkdir()
    (root / "test_leak.py").write_text(_PY_LEAK_TEST, encoding="utf-8")
    runner = get_runner(RepoConfig(name="pyfix", language=Language.PYTHON, runner="pytest"))
    ex = LocalExecutor()
    inherited = ex.run(runner.command(root, ("test_leak.py",), executor=ex, timeout=300))
    assert inherited.returncode != 0  # the fixture is sensitive to the worker's PATH
    run = runner.run(ex, root, ("test_leak.py",))
    assert run.green, run.tail
    declared = runner.declared_environment(ex, root)
    assert declared is not None and "python=" in declared.summary()


def test_the_node_runners_declare_node_npm_and_the_basics_never_the_host_path(
    tmp_path: Path, host_tool_on_path: Path
) -> None:
    for name in ("node", "jest", "vitest", "mocha"):
        runner = get_runner(RepoConfig(name="js", language=Language.JAVASCRIPT, runner=name))
        declared = runner.declared_environment(LocalExecutor(), tmp_path)
        assert declared is not None
        names = {t.name for t in declared.tools}
        assert {"node", "npm", "npx", "git", "sh", "env"} <= names
        assert LEAK_TOOL not in names
        assert not (Path(declared.bin_dir) / LEAK_TOOL).exists()
        assert declared.env["PATH"].split(os.pathsep) == [declared.bin_dir]


def test_maven_and_cargo_still_inherit_and_say_so() -> None:
    """G-791: the two runners without a declaration hand the tests the worker's allowlist."""
    for runner_name, lang in (("maven", Language.JVM), ("cargo", Language.RUST)):
        runner = get_runner(RepoConfig(name="x", language=lang, runner=runner_name))
        assert runner.declared_tools(LocalExecutor()) is None
        assert runner.declared_environment(LocalExecutor()) is None


def test_the_declared_environment_reads_the_executors_host_environment(tmp_path: Path) -> None:
    """The source is the executor's own host environment (what a deployment configured on
    it), never the process's: its allowlisted names reach the tests, its other names do not,
    and a module setting such as ``GOPROXY=off`` is part of the digest by value."""
    host = tmp_path / "host"
    _tool(host, "go")
    base = {"PATH": str(host), "HOME": "/h", "GOPROXY": "off", "SECRET_TOKEN": "s"}
    runner = get_runner(_go_config())
    offline = runner.declared_environment(LocalExecutor(base_env=base))
    assert offline is not None
    assert offline.env["GOPROXY"] == "off" and offline.env["HOME"] == "/h"
    assert "SECRET_TOKEN" not in offline.env
    assert (Path(offline.bin_dir) / "go").exists()
    online = runner.declared_environment(
        LocalExecutor(base_env={k: v for k, v in base.items() if k != "GOPROXY"})
    )
    assert online is not None and online.digest != offline.digest


# ---------------------------------------------------------------------------
# Stream Q2's verifiers (2026-09-28): the ways round the declaration, each closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"])
@pytest.mark.parametrize(
    ("runner_name", "lang"),
    [("go", Language.GO), ("pytest", Language.PYTHON), ("node", Language.JAVASCRIPT)],
)
def test_a_path_in_runner_opts_env_is_refused_before_a_test_runs(
    tmp_path: Path, name: str, runner_name: str, lang: Language
) -> None:
    """A ``PATH`` in ``runner_opts.env`` would sit over the tool farm and bring the leak back
    with the digest unchanged; a loader variable would run code no declaration names."""
    runner = get_runner(
        RepoConfig(
            name="x", language=lang, runner=runner_name, runner_opts={"env": {name: "/opt/x"}}
        )
    )
    with pytest.raises(ValueError, match=rf"runner_opts\.env.*{name}"):
        runner.declared_environment(LocalExecutor(), tmp_path)
    with pytest.raises(ValueError, match=r"runner_opts\.env"):
        runner.run(LocalExecutor(), tmp_path, ("x",))


def test_a_pinned_node_leads_the_setup_path_so_npm_runs_under_it(tmp_path: Path) -> None:
    """What the refused ``PATH`` was for: an engine-strict repository's ``npm`` (a node
    script) must run under the pinned ``node``. ``runner_opts.node`` now leads setup's
    ``PATH`` — declared, and part of the test environment's digest."""
    pinned = _tool(tmp_path / "node24" / "bin", "node")
    runner = get_runner(
        RepoConfig(
            name="js",
            language=Language.JAVASCRIPT,
            runner="node",
            runner_opts={"node": str(pinned)},
        )
    )
    ex = LocalExecutor(base_env={"PATH": "/usr/bin:/bin"})
    env = runner.setup_env(ex)
    assert env["PATH"].split(os.pathsep) == [str(pinned.parent), "/usr/bin", "/bin"]
    plain = get_runner(RepoConfig(name="js", language=Language.JAVASCRIPT, runner="node"))
    assert "PATH" not in plain.setup_env(ex)


class _NoBaseEnv:
    """An executor with no ``base_env``: ``honours`` says whether a host pin applies on it
    (a container's ``tool`` never takes one — ``DockerExecutor.tool``)."""

    def __init__(self, *, honours: bool) -> None:
        self.honours = honours

    def tool(self, name: str, host_override: str | None = None) -> str:
        return (host_override or name) if self.honours else name


def test_a_pinned_node_leads_path_only_where_the_executor_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-724: a container's toolchain is on the image's ``PATH`` and a host pin never applies
    there, so setup sets no ``PATH`` at all — before, the pin led ``os.defpath``
    (``/bin:/usr/bin``), which dropped the image's ``/usr/local/bin``, where ``node`` and
    ``npm`` live. An executor that runs the pin but has no ``base_env`` puts the pin before
    the worker's own ``PATH``, as ``declare_environment`` reads ``os.environ`` there."""
    pinned = _tool(tmp_path / "node24" / "bin", "node")
    runner = get_runner(
        RepoConfig(
            name="js",
            language=Language.JAVASCRIPT,
            runner="node",
            runner_opts={"node": str(pinned)},
        )
    )
    monkeypatch.setenv("PATH", "/opt/worker/bin:/usr/local/bin:/usr/bin")
    assert "PATH" not in runner.setup_env(_NoBaseEnv(honours=False))  # type: ignore[arg-type]
    env = runner.setup_env(_NoBaseEnv(honours=True))  # type: ignore[arg-type]
    assert env["PATH"].split(os.pathsep) == [
        str(pinned.parent),
        "/opt/worker/bin",
        "/usr/local/bin",
        "/usr/bin",
    ]
    monkeypatch.delenv("PATH")
    assert runner.setup_env(_NoBaseEnv(honours=True))["PATH"] == os.pathsep.join(  # type: ignore[arg-type]
        [str(pinned.parent), os.defpath]
    )


def test_the_evidence_pack_carries_the_declared_environment(tmp_path: Path) -> None:
    """Packs are stamped with the run's ``Posture.to_dict()``; the pack itself — its dict and
    its hash — must carry the environment's identity and its tool list."""
    from crb.core import evidence as ev
    from fixtures.posture import posture_result

    runner = get_runner(RepoConfig(name="pyfix", language=Language.PYTHON, runner="pytest"))
    posture = resolve_posture(LocalExecutor(), runner, deps_mode="host-env", root=tmp_path)
    assert posture.environment.startswith(IDENTITY_PREFIX)
    task = TaskSpec(
        task_id="a" * 40,
        repo="pyfix",
        subject="s",
        authored="2026-01-01T00:00:00+00:00",
        test_files=["tests/test_a.py"],
        src_files=["a.py"],
        target_tests=["tests/test_a.py"],
        belt_scope=["tests/"],
    )
    graded = posture_result(
        task.task_id, "pyfix", "sighted", clean=True, belts=Belts(True, True, True, True)
    )

    def pack(p: dict[str, object]) -> ev.EvidencePack:
        return ev.EvidencePack(
            task=task,
            grade=graded,
            apparatus=ev.ApparatusStamp(runner="pytest", posture=p),
            builder=ev.BuilderRef(name="b"),
            run_id="r",
            trial="t1",
            created="2026-09-28T00:00:00+00:00",
        )

    here = pack(posture.to_dict())
    stamped = here.to_dict()["apparatus"]["posture"]
    assert stamped["environment"] == posture.environment
    assert stamped["environment_tools"] == posture.environment_tools
    moved = pack({**posture.to_dict(), "environment": IDENTITY_PREFIX + "0" * 64})
    assert moved.pack_hash != here.pack_hash


def _venv(where: Path) -> Path:
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(where)], check=True, timeout=120
    )
    return where / "bin" / "python"


def test_a_tool_in_the_interpreters_venv_bin_moves_the_digest(tmp_path: Path) -> None:
    """The venv's ``bin`` follows the farm on the tests' ``PATH``, so what is in it is part of
    the identity: a console script added there moves the digest."""
    python = _venv(tmp_path / "venv")
    runner = get_runner(
        RepoConfig(
            name="pyfix",
            language=Language.PYTHON,
            runner="pytest",
            runner_opts={"python": str(python)},
        )
    )
    ex = LocalExecutor()
    before = runner.declared_environment(ex, tmp_path)
    assert before is not None and str(python.parent) in before.env["PATH"].split(os.pathsep)
    _tool(python.parent, LEAK_TOOL)
    after = runner.declared_environment(ex, tmp_path)
    assert after is not None and after.digest != before.digest


def test_the_fallback_interpreter_never_puts_crbs_own_venv_bin_on_the_path(
    tmp_path: Path,
) -> None:
    """With no interpreter configured the tests run under crb's own; its ``bin`` (ruff, mypy,
    crb, uvicorn…) is not the repository's and never reaches the tests."""
    import sys

    runner = get_runner(RepoConfig(name="pyfix", language=Language.PYTHON, runner="pytest"))
    declared = runner.declared_environment(LocalExecutor(), tmp_path)
    assert declared is not None
    assert declared.env["PATH"].split(os.pathsep) == [declared.bin_dir]
    assert str(Path(sys.executable).parent) not in declared.env["PATH"]
    assert (Path(declared.bin_dir) / "python").exists()


def test_a_bare_interpreter_name_resolves_on_the_executors_path(tmp_path: Path) -> None:
    host = tmp_path / "host"
    crbpy = _tool(host, "crbpy")
    runner = get_runner(
        RepoConfig(
            name="pyfix", language=Language.PYTHON, runner="pytest", runner_opts={"python": "crbpy"}
        )
    )
    declared = runner.declared_environment(LocalExecutor(base_env={"PATH": str(host)}), tmp_path)
    assert declared is not None
    python = next(t for t in declared.tools if t.name == "python")
    assert python.path == str(crbpy)


def test_every_declared_environment_reads_no_host_git_or_go_config_file() -> None:
    """``$HOME``'s go env file and git's global and system config are host state: the
    declaration switches all three off, by value, so they are part of the digest."""
    for runner_name, lang in (
        ("go", Language.GO),
        ("pytest", Language.PYTHON),
        ("node", Language.JAVASCRIPT),
    ):
        runner = get_runner(RepoConfig(name="x", language=lang, runner=runner_name))
        declared = runner.declared_environment(LocalExecutor())
        assert declared is not None
        assert declared.env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert declared.env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert declared.env["PYTHONNOUSERSITE"] == "1"
    go = get_runner(gorepo.config()).declared_environment(LocalExecutor())
    assert go is not None and go.env["GOENV"] == "off"


def _real_go_env(name: str) -> str:
    import subprocess

    return subprocess.run(
        ["go", "env", name], capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()


_ARCH_TEST = (
    'package leak\n\nimport (\n\t"runtime"\n\t"testing"\n)\n\n'
    "func TestArch(t *testing.T) {\n"
    '\tif runtime.GOARCH != "@ARCH@" {\n'
    '\t\tt.Fatalf("built for %s", runtime.GOARCH)\n'
    "\t}\n}\n"
)


@needs_go
def test_a_go_env_file_under_home_never_changes_a_result(leak_module: Path, tmp_path: Path) -> None:
    """``go env -w GOARCH=…`` writes a file under ``$HOME`` that every later ``go test``
    reads; the declared environment passes ``HOME`` through, so the file must be ignored."""
    import subprocess

    arch = _real_go_env("GOARCH")
    (leak_module / "leak" / "arch_test.go").write_text(
        _ARCH_TEST.replace("@ARCH@", arch),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    base = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "GOCACHE": _real_go_env("GOCACHE"),
        "GOMODCACHE": _real_go_env("GOMODCACHE"),
    }
    runner = get_runner(gorepo.config())
    clean = runner.run(LocalExecutor(base_env=base), leak_module, ("./leak",))
    assert clean.green, clean.tail
    before = runner.declared_environment(LocalExecutor(base_env=base))
    goenv = subprocess.run(
        ["go", "env", "GOENV"],
        capture_output=True,
        text=True,
        check=True,
        env={**base, "GOENV": ""},
        timeout=60,
    ).stdout.strip()
    Path(goenv).parent.mkdir(parents=True, exist_ok=True)
    Path(goenv).write_text(f"GOARCH={'amd64' if arch != 'amd64' else 'arm64'}\n", encoding="utf-8")
    configured = runner.run(LocalExecutor(base_env=base), leak_module, ("./leak",))
    after = runner.declared_environment(LocalExecutor(base_env=base))
    assert (configured.green, configured.failing) == (clean.green, clean.failing)
    assert before is not None and after is not None and before.digest == after.digest


def test_a_git_config_under_home_never_reaches_a_python_test(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[crb]\n\tleak = 1\n", encoding="utf-8")
    root = tmp_path / "py"
    root.mkdir()
    (root / "test_git.py").write_text(
        "import subprocess\n\n\ndef test_no_host_git_config():\n"
        "    r = subprocess.run(['git', 'config', '--get', 'crb.leak'], capture_output=True)\n"
        "    assert r.returncode != 0, r.stdout\n",
        encoding="utf-8",
    )
    runner = get_runner(RepoConfig(name="pyfix", language=Language.PYTHON, runner="pytest"))
    ex = LocalExecutor(base_env={"PATH": os.environ["PATH"], "HOME": str(home)})
    run = runner.run(ex, root, ("test_git.py",))
    assert run.green, run.tail


def test_the_farm_root_is_private_to_its_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The farm root is where a grade's tools are linked: a root another user can write to
    could swap a link between the check and the exec, so it is made ``0700`` and refused when
    it is a link or belongs to another user."""
    from crb.core.runners import toolenv

    host = tmp_path / "host"
    _tool(host, "crbdeclared")
    root = tmp_path / "farms"
    root.mkdir(mode=0o777)
    root.chmod(0o777)
    toolenv.declare_environment((ToolSpec("crbdeclared"),), host_env={"PATH": str(host)}, root=root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    link = tmp_path / "farms-link"
    link.symlink_to(root)
    with pytest.raises(PermissionError, match="farm root"):
        toolenv.declare_environment(
            (ToolSpec("crbdeclared"),), host_env={"PATH": str(host)}, root=link
        )
    other_uid = os.geteuid() + 1
    monkeypatch.setattr(toolenv.os, "geteuid", lambda: other_uid)
    with pytest.raises(PermissionError, match="another user"):
        toolenv.declare_environment(
            (ToolSpec("crbdeclared"),), host_env={"PATH": str(host)}, root=root
        )


def test_a_farm_another_worker_just_renamed_in_is_kept_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-723: two workers resolve one tool set at once; both find no farm, both build one.
    A renames its farm in and its test runs with ``PATH=<farm>/bin``; B must not then set
    A's live farm aside and delete it — the key is content-addressed, so a farm that checks
    out is identical to B's own and stays. B's first check is made to miss, as it would
    have before A's rename."""
    from crb.core.runners import toolenv

    sh = ResolvedTool("sh", path="/bin/sh", sha256="a" * 64)
    root = tmp_path / "farms"
    bin_dir = ensure_farm([sh], root=root)  # worker A's farm, in place
    before = os.stat(bin_dir.parent).st_ino
    real = toolenv._farm_ok
    calls: list[int] = []

    def missed_once(bin_dir: Path, tools: object) -> bool:
        calls.append(1)
        return False if len(calls) == 1 else real(bin_dir, tools)  # type: ignore[arg-type]

    monkeypatch.setattr(toolenv, "_farm_ok", missed_once)
    assert ensure_farm([sh], root=root) == bin_dir  # worker B
    assert os.stat(bin_dir.parent).st_ino == before, "B replaced A's live farm"
    assert sorted(p.name for p in root.iterdir()) == [bin_dir.parent.name]
