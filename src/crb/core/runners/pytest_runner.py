"""pytest runner (Python).

Interpreter resolution (:meth:`PytestRunner.python_for`), most explicit first:

1. ``runner_opts.python`` — the operator's interpreter, used as given;
2. ``<env_dir>/venv/bin/python`` — the virtualenv :meth:`PytestRunner.setup` built;
3. the interpreter running crb (hermetic tests and dev boxes; never *ready*).

Setup mirrors the census recipe: a venv under ``env_dir`` (``uv venv`` when uv is
on PATH, else ``python -m venv``), one install of ``runner_opts.pip`` (a list of
pip arguments; ``pip_fallback`` on failure), then ``pip uninstall`` of
``runner_opts.uninstall`` — the repository's *own* distribution — so the
worktree's source on ``PYTHONPATH`` is what the tests import, not a stale wheel.
Without ``pip`` the default is an editable install of the repository with its
test extra (the first of :data:`TEST_EXTRAS` that ``pyproject.toml`` actually
declares; installers exit 0 on an unknown extra, so nothing is guessed), falling
back to a plain ``-e .``, followed by ``pytest``.

``environment_ready`` is strict on purpose: only ``runner_opts.python`` or the
setup venv can be ready. The interpreter running crb is the last resort for
``command()`` (hermetic tests, dev boxes) but never *counts* as the repository's
environment — it does not carry the repository's dependencies.

Navigation
----------
What it is:   The Python runner — ``PytestRunner`` — and the reference implementation every
              other language runner mirrors.
What it does: Builds a deterministic ``python -m pytest -rfE`` command for a scope, parses the
              short summary into failing ids, checks a target file really defines tests
              (malformed-oracle guard), installs the repository's test dependencies into a venv
              under ``env_dir`` (the network phase), and detects ruff for belt 5.
How:          ``command``: resolve the interpreter (opts → venv → crb's own) → pin ``PYTHONPATH``
              to the worktree (``/work`` under docker) → pytest argv. ``setup``: venv → install
              (``runner_opts.pip`` / fallback, else ``-e .[test]``) → uninstall the repo's own
              distribution → dist-info stubs → ``finish_setup``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/runners/base.py (the contract and the setup records),
              src/crb/core/lint.py (``python_plan``, ``pinned_ruff_spec``),
              src/crb/core/execution.py (``Executor.tool`` picks the sandbox interpreter),
              src/crb/core/runners/__init__.py (registered as ``"pytest"``),
              tests/fixtures/pyrepo.py (the fixture repository the tests drive it on)
Tested by:    tests/test_runners_parsers.py, tests/test_runners_setup.py, tests/test_lint.py
Touch when:   a Python repository needs a different install recipe — prefer ``runner_opts``
              (``pip``, ``pip_fallback``, ``uninstall``, ``python``, ``env``,
              ``dist_info_stubs``; docs/OPERATOR.md) over editing this file; a new pytest
              reporter shape or a new interpreter source changes ``parse``/``python_for`` and
              needs a parser test.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.lint import LintPlan, pinned_ruff_spec, python_plan
from crb.core.runners.base import (
    BaseRunner,
    SetupResult,
    SetupSession,
    SetupStep,
    TestRun,
    host_check,
    parse_pytest_failures,
    tail_of,
)

#: (interpreter, spec) pairs already satisfied this process — one install per commit pin.
_PINNED_RUFF_DONE: set[tuple[str, str]] = set()

# A real pytest oracle defines test functions/classes. A source module that merely
# happens to be named test_*.py does NOT — using it as an oracle lets source edits
# read as tamper and runs a non-test file as the target (malformed-oracle class).
_PYTEST_DEF_RE = re.compile(r"(?m)^\s*(?:async\s+)?def\s+test|^\s*class\s+Test")

#: Extras tried, in order, for the default editable install.
TEST_EXTRAS: tuple[str, ...] = ("test", "tests", "dev", "testing")

#: Files whose presence means ``pip install -e .`` has something to build.
_PROJECT_FILES: tuple[str, ...] = ("pyproject.toml", "setup.py", "setup.cfg")

_SETUP_ENV: dict[str, str] = {
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "UV_NO_PROGRESS": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def venv_python(env_dir: Path) -> Path:
    """The interpreter of the virtualenv :meth:`PytestRunner.setup` builds under ``env_dir``."""
    venv = Path(env_dir) / "venv"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def split_pip_args(items: Sequence[object] | str) -> list[str]:
    """``["-e .[test]", "pytest"]``, ``["-e", ".", "pytest"]`` and the plain string
    ``"-e . pytest"`` all → argv tokens. A bare string used to be iterated character by
    character (``"pytest"`` → ``pip install p y t e s t``); OPERATOR.md always said a
    string splits on whitespace (A12 finding, 2026-09-14)."""
    seq: Sequence[object] = [items] if isinstance(items, str) else items
    out: list[str] = []
    for item in seq:
        out.extend(shlex.split(str(item)))
    return out


def declared_extras(root: Path) -> frozenset[str]:
    """The ``[project.optional-dependencies]`` names ``pyproject.toml`` declares."""
    p = Path(root) / "pyproject.toml"
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    project = data.get("project")
    extras = project.get("optional-dependencies") if isinstance(project, dict) else None
    return frozenset(str(k) for k in extras) if isinstance(extras, dict) else frozenset()


class PytestRunner(BaseRunner):
    """``RepoConfig.runner == "pytest"``. Scopes are file paths (pytest addresses files
    directly, so the base ``target_scope`` is exact); belt 5 is ruff when the repository
    configures it."""

    name = "pytest"
    default_timeout = 900

    # --- interpreter -------------------------------------------------------------
    def configured_python(self, root: Path, env_dir: Path | None) -> str | None:
        """The interpreter that carries the repository's dependencies, or ``None``:
        ``runner_opts.python`` if set, else the setup venv if it exists. A relative
        ``runner_opts.python`` with a directory part is resolved against ``root``."""
        explicit = self.opts.get("python")
        if explicit:
            p = Path(str(explicit))
            if not p.is_absolute() and len(p.parts) > 1:
                return str(Path(root) / p)
            return str(explicit)
        if env_dir is not None:
            vp = venv_python(env_dir)
            if vp.exists():
                return str(vp)
        return None

    def python_for(self, root: Path, env_dir: Path | None) -> str:
        """The interpreter the tests run with (see the module docstring for the order)."""
        return self.configured_python(root, env_dir) or sys.executable

    # --- execution ---------------------------------------------------------------
    def toolchain_argv(self, executor: Executor) -> tuple[str, ...]:
        """``<python> -V`` — the interpreter the tests run under, part of the posture."""
        host_default = (
            self.python_for(self.env_dir or Path("."), self.env_dir)
            if executor.name != "docker"
            else None
        )
        return (executor.tool("python", host_default), "-V")

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """``python -m pytest -q -rfE … <scope>`` with the repository's ``addopts`` and
        random-ordering plugins neutralised, so two runs of the same tree produce the
        same summary and the parser sees exactly the ``-rfE`` shape it expects."""
        # Under docker the image's interpreter must be used; the host venv is not mounted.
        host_default = self.python_for(root, self.env_dir) if executor.name != "docker" else None
        python = executor.tool("python", host_default)
        argv = [
            python,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-rfE",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-o",
            "addopts=",  # the repo's own addopts could change the reporter or add -x / coverage
            "--continue-on-collection-errors",  # one broken file must not hide the others' ids
            *scope,
        ]
        env = {
            # The worktree first on the path: the trial's edits, not an installed wheel, run.
            "PYTHONPATH": str(root) + str(self.opts.get("pythonpath_suffix", "")),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",  # set-ordering-dependent tests behave the same every run
        }
        if executor.name == "docker":
            # The sandbox mounts the worktree at /work; a host-absolute suffix is remapped too.
            env["PYTHONPATH"] = "/work" + str(self.opts.get("pythonpath_suffix", "")).replace(
                str(root), "/work"
            )
        for k, v in dict(self.opts.get("env", {})).items():
            env[str(k)] = str(v)
        return Command(
            tuple(argv), root, env=env, timeout=timeout, writable_paths=(".pytest_scratch",)
        )

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        """Failing ids from the ``-rfE`` short summary; the base ``run`` adds the
        fail-closed ``parse_error`` when rc≠0 and nothing was parsed."""
        failing = parse_pytest_failures(result.combined)
        return TestRun(
            result.returncode, failing, tail_of(result.combined), duration_s=result.duration_s
        )

    def is_valid_oracle(self, root: Path, test_file: str) -> bool:
        """Tighter than the base rule: the file must define at least one ``def test``
        or ``class Test`` (see ``_PYTEST_DEF_RE``), else it is a malformed oracle."""
        p = root / test_file
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return _PYTEST_DEF_RE.search(text) is not None

    # --- belt 5 -------------------------------------------------------------------
    def ruff_for(self, root: Path, executor: Executor) -> str:
        """The ``ruff`` binary belt 5 runs: the one next to the configured interpreter
        (``runner_opts.python`` or the setup venv — click's ``dev`` extra installs
        it there), else the host's, else the bare name (fails closed at run time as a
        visible harness error, never a silent skip). Under a sandbox the image's PATH
        resolves it."""
        if executor.name == "docker":
            return executor.tool("ruff")
        python = self.configured_python(root, self.env_dir)
        if python:
            self._ensure_pinned_ruff(root, Path(python))
            sibling = Path(python).parent / ("ruff.exe" if os.name == "nt" else "ruff")
            if sibling.exists():
                return str(sibling)
        return shutil.which("ruff") or "ruff"

    def _ensure_pinned_ruff(self, root: Path, python: Path) -> None:
        """Install the ruff version the repository (at THIS commit) pins into the
        environment, so belt 5 applies the maintainers' definition of acceptable — the
        host's ruff 0.16 rejected mesh-client's own patches under a ``^0.2`` pin
        (2026-09-14). Idempotent and offline-tolerant: a failed install leaves the
        sibling as it is and the plan records the version that actually ran."""
        spec = pinned_ruff_spec(root)
        if not spec:
            return
        cache_key = (str(python), spec)
        if cache_key in _PINNED_RUFF_DONE:
            return
        uv = shutil.which("uv")
        argv = (
            [uv, "pip", "install", "-q", "--python", str(python), f"ruff{spec}"]
            if uv
            else [str(python), "-m", "pip", "install", "-q", f"ruff{spec}"]
        )
        try:
            subprocess.run(argv, capture_output=True, text=True, timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return
        _PINNED_RUFF_DONE.add(cache_key)

    def detect_lint(self, root: Path, executor: Executor) -> LintPlan | None:
        """``ruff check`` (+ ``ruff format --check``) when the repository configures
        ruff — click: ``pyproject.toml [tool.ruff]`` and the ``ruff-check`` /
        ``ruff-format`` pre-commit hooks its CI runs on every PR."""
        return python_plan(root, self.ruff_for(root, executor))

    # --- environment -------------------------------------------------------------
    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        """The configured interpreter exists and imports pytest. The crb interpreter
        itself never counts: it does not carry the repository's dependencies."""
        python = self.configured_python(root, env_dir)
        if python is None:
            return False
        return host_check([python, "-c", "import pytest"], root)

    def setup(
        self,
        executor: Executor,
        root: Path,
        *,
        env_dir: Path,
        timeout: int,
        on_step: Callable[[SetupStep], None] | None = None,
    ) -> SetupResult:
        """Build the venv and install the test dependencies (the module docstring has the
        recipe). Stops at the first unrecovered failure; every command is on record."""
        refusal = self.sandbox_refusal(executor)
        if refusal is not None:
            return refusal
        root, env_dir = Path(root), Path(env_dir)
        t = self.setup_timeout(timeout)
        session = SetupSession(executor, on_step=on_step)
        explicit = self.opts.get("python")
        if explicit:
            # The operator chose the interpreter: verify it, never install into it.
            if self.environment_ready(root, env_dir):
                return session.result(True, f"using runner_opts.python={explicit}")
            return session.result(
                False,
                f"runner_opts.python={explicit} cannot import pytest; install the repository's "
                "test dependencies there, or unset it so setup can build a venv",
            )
        python = venv_python(env_dir)
        # uv only when running natively; any other executor gets the portable pip path.
        uv = shutil.which("uv") if executor.name == "local" else None

        def pip(*args: str) -> Command:
            argv = (
                [uv, "pip", "install", "-q", "--python", str(python), *args]
                if uv
                else [str(python), "-m", "pip", "install", "-q", *args]
            )
            return Command(tuple(argv), root, env=_SETUP_ENV, timeout=t, network=True)

        # 1. the virtualenv (idempotent: an existing one is kept)
        if not python.exists():
            env_dir.mkdir(parents=True, exist_ok=True)
            base = sys.executable
            argv = (
                [uv, "venv", "-q", str(python.parents[1]), "--python", base]
                if uv
                else [base, "-m", "venv", str(python.parents[1])]
            )
            if not session.run(Command(tuple(argv), root, env=_SETUP_ENV, timeout=t)).ok:
                return session.result(False, "virtualenv creation failed")
            if not python.exists():
                return session.result(False, f"virtualenv created but {python} is missing")
        # 2. the install: runner_opts.pip (+ pip_fallback), else the editable default
        primary = split_pip_args(self.opts.get("pip") or [])
        if primary:
            step = session.run(pip(*primary))
            fallback = split_pip_args(self.opts.get("pip_fallback") or [])
            if not step.ok and fallback:
                step = session.run(pip(*fallback))
            if not step.ok:
                return self.finish_setup(session, root, env_dir)
        else:
            if any((root / f).exists() for f in _PROJECT_FILES):
                extra = next((e for e in TEST_EXTRAS if e in declared_extras(root)), "")
                step = session.run(pip("-e", f".[{extra}]" if extra else "."))
                if not step.ok and extra:
                    step = session.run(pip("-e", "."))
                if not step.ok:
                    return self.finish_setup(session, root, env_dir)
            if not session.run(pip("pytest")).ok:
                return self.finish_setup(session, root, env_dir)
        # 3. the census pattern: the repo's own distribution must not shadow the worktree
        uninstall = [str(p) for p in (self.opts.get("uninstall") or [])]
        if uninstall:
            argv = (
                [uv, "pip", "uninstall", "-q", "--python", str(python), *uninstall]
                if uv
                else [str(python), "-m", "pip", "uninstall", "-y", "-q", *uninstall]
            )
            session.run(Command(tuple(argv), root, env=_SETUP_ENV, timeout=t))
        # 4. metadata-only distributions: a test that asserts the package reports a real
        #    version (`importlib.metadata.version("mesh-client") != "unknown"`) cannot pass
        #    once the distribution is uninstalled and the code comes from the worktree on
        #    PYTHONPATH — so the operator declares the identity and the harness writes a
        #    dist-info with METADATA only (no RECORD of files, so nothing is shadowed).
        #    NHSDigital/mesh-client `test_get_version`, 2026-09-14.
        for stub in self.opts.get("dist_info_stubs") or []:
            # a malformed entry is a configuration error the setup RECORDS, never a
            # KeyError that loses the setup result (CodeRabbit on PR #3, 2026-09-15)
            name = str((stub.get("name") if isinstance(stub, Mapping) else "") or "").strip()
            if not name:
                return session.result(
                    False, f"runner_opts.dist_info_stubs: every entry needs a name (got {stub!r})"
                )
            version = str(stub.get("version") or "0.0.0+crb")
            written = write_dist_info_stub(python, name, version)
            session.record(
                Command(("crb", "dist-info-stub", name, version), root),
                ExecResult(0, f"wrote {written} (METADATA only; no files shadowed)", ""),
            )
        return self.finish_setup(session, root, env_dir)


def write_dist_info_stub(python: Path, name: str, version: str) -> Path:
    """Write ``<site-packages>/<name>-<version>.dist-info/{METADATA,RECORD,INSTALLER}``
    for the interpreter ``python`` so ``importlib.metadata.version(name)`` resolves,
    without any file entries that could shadow the worktree's package."""
    site = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()
    norm = re.sub(r"[-_.]+", "_", name).lower()
    d = Path(site) / f"{norm}-{version}.dist-info"
    d.mkdir(parents=True, exist_ok=True)
    (d / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        "Summary: metadata-only stub written by crb (code is imported from the worktree)\n",
        encoding="utf-8",
    )
    (d / "RECORD").write_text(
        f"{d.name}/METADATA,,\n{d.name}/RECORD,,\n{d.name}/INSTALLER,,\n", encoding="utf-8"
    )
    (d / "INSTALLER").write_text("crb-harness\n", encoding="utf-8")
    return d
