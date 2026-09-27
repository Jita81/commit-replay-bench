"""CI installs from ``uv.lock``, and one job runs every gate on a fresh clone, as root, without docker.

Before the lock, ``mypy`` and ``ruff`` were pinned but every library resolved fresh on every
install, so the same tree could pass on Monday and fail on Tuesday (SQLAlchemy 2.1.0 turned
eight query results into ``mypy`` errors on 24 September with no commit). ``uv.lock`` pins
every package the extras reach, by version and hash; these tests hold CI to installing from
it, hold the lock to ``pyproject.toml``, and hold the ``fresh-clone`` job to the conditions of
product.evidence.205: every gate, a clone made by root, no docker daemon (G-664).

Navigation
----------
What it is:   The gate on how CI installs Python dependencies and on the fresh-clone job.
What it does: Fails when a CI job installs the project or a library other than from
              ``uv.lock`` (``uv sync --locked``, or ``uv export --locked`` with
              ``--require-hashes``); when ``uv.lock`` no longer matches the extras
              ``pyproject.toml`` declares (a dependency added or re-pinned without relocking)
              or pins a gate tool at another version than ``pyproject.toml``; and when the
              ``fresh-clone`` job stops running a gate, stops running as root in its own
              clone, or stops proving the docker daemon is gone. Each check is also run on a
              planted regression so it cannot pass vacuously.
How:          PyYAML reads ``ci.yml``; ``tomllib`` reads ``uv.lock`` and ``pyproject.toml``;
              requirement strings are compared as (name, extras, specifier, extra marker).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   .github/workflows/ci.yml (the install steps and the ``fresh-clone`` job),
              uv.lock (the lock), pyproject.toml (the extras it locks), docs/CONTRIBUTING.md
              (the same install for a person), docs/dod/product.md (product.evidence.205)
Tested by:    (this is a test file)
Touch when:   a job installs Python packages a new way; a gate is added to CONTRIBUTING's
              list (add it to ``GATES`` and to the fresh-clone job in the same change).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
LOCK = ROOT / "uv.lock"
PYPROJECT = ROOT / "pyproject.toml"

#: Every gate a contributor runs before a pull request (docs/CONTRIBUTING.md "The gates"),
#: as the command text the fresh-clone job must contain.
GATES = (
    ".venv/bin/ruff check src tests scripts",
    ".venv/bin/ruff format --check src tests scripts",
    ".venv/bin/mypy",
    ".venv/bin/lint-imports",
    ".venv/bin/python scripts/code_map.py --check",
    ".venv/bin/python scripts/dod_check.py --check",
    ".venv/bin/python scripts/claims_check.py --check",
    "npm run typecheck",
    "npx vitest run",
    '.venv/bin/pytest -q -p no:cacheprovider -m "not sandbox_images"',
)
#: Tools a job adds beside the locked environment to report on it, never imported by crb.
REPORTING_TOOLS = frozenset({"pip", "pip-audit", "cyclonedx-bom"})

_UV_SYNC = re.compile(r"\buv sync\b[^\n]*")
_PIP_INSTALL = re.compile(r"\b(?:uv )?pip install\b[^\n]*")


def _runs(workflow: dict[str, Any]) -> list[tuple[str, str]]:
    """Every ``(job, run text)`` in the workflow."""
    out: list[tuple[str, str]] = []
    for job, body in workflow["jobs"].items():
        for step in body.get("steps", []):
            if "run" in step:
                out.append((job, str(step["run"])))
    return out


def install_findings(ci_text: str) -> list[str]:
    """Each Python install in the workflow that does not come from ``uv.lock``."""
    findings: list[str] = []
    for job, run in _runs(yaml.safe_load(ci_text)):
        for m in _UV_SYNC.finditer(run):
            if "--locked" not in m.group(0):
                findings.append(f"{job}: {m.group(0)!r} resolves instead of reading uv.lock")
        for m in _PIP_INSTALL.finditer(run):
            line = m.group(0)
            if "--require-hashes -r locked-requirements.txt" in line:
                if "uv export" not in run or "--locked" not in run.split("uv export", 1)[1]:
                    findings.append(f"{job}: locked-requirements.txt is not exported --locked")
                continue
            words = [w for w in line.split() if not w.startswith("-")]
            named = words[words.index("install") + 1 :]
            named = [w for w in named if not w.startswith(".venv") and not w.startswith(".audit")]
            if not named or any(n not in REPORTING_TOOLS for n in named):
                findings.append(f"{job}: {line!r} installs from outside uv.lock")
    return findings


def _req_key(req: dict[str, Any]) -> tuple[str, tuple[str, ...], str, str]:
    return (
        req["name"],
        tuple(sorted(req.get("extras", []))),
        req.get("specifier", ""),
        req.get("marker", ""),
    )


_PEP508 = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[([^\]]*)\])?\s*(.*)$")


def pyproject_requirements(pyproject: dict[str, Any]) -> set[tuple[str, tuple[str, ...], str, str]]:
    """``pyproject.toml``'s extras as the lock's ``requires-dist`` records them."""
    out: set[tuple[str, tuple[str, ...], str, str]] = set()
    for extra, reqs in pyproject["project"]["optional-dependencies"].items():
        for req in reqs:
            m = _PEP508.match(req.strip())
            assert m, req
            name = m.group(1).lower().replace("_", "-")
            extras = tuple(sorted(e.strip() for e in (m.group(2) or "").split(",") if e.strip()))
            spec = m.group(3).replace(" ", "")
            if name == pyproject["project"]["name"]:
                # the self-reference (``all``): the lock keeps the extras' order as written
                extras = tuple(sorted(extras))
            out.add((name, extras, spec, f"extra == '{extra}'"))
    return out


def lock_findings(lock: dict[str, Any], pyproject: dict[str, Any]) -> list[str]:
    """Each way ``uv.lock`` disagrees with ``pyproject.toml``."""
    name = pyproject["project"]["name"]
    roots = [p for p in lock["package"] if p["name"] == name]
    if len(roots) != 1:
        return [f"uv.lock has {len(roots)} entries for {name}"]
    locked = {_req_key(r) for r in roots[0]["metadata"]["requires-dist"]}
    declared = pyproject_requirements(pyproject)
    findings = [f"declared but not locked: {k}" for k in sorted(declared - locked)]
    findings += [f"locked but no longer declared: {k}" for k in sorted(locked - declared)]
    versions = {p["name"]: p.get("version") for p in lock["package"]}
    for extra in pyproject["project"]["optional-dependencies"].values():
        for req in extra:
            m = re.match(r"^([A-Za-z0-9_.-]+)==(\S+)$", req.strip())
            if m and versions.get(m.group(1)) != m.group(2):
                findings.append(
                    f"{m.group(1)} is pinned {m.group(2)} in pyproject.toml but locked at "
                    f"{versions.get(m.group(1))}"
                )
    return findings


def fresh_clone_findings(ci_text: str) -> list[str]:
    """Each condition of product.evidence.205 the ``fresh-clone`` job no longer holds."""
    jobs = yaml.safe_load(ci_text)["jobs"]
    job = jobs.get("fresh-clone")
    if job is None:
        return ["ci.yml has no fresh-clone job"]
    runs = "\n".join(str(s.get("run", "")) for s in job.get("steps", []))
    findings = [f"the fresh-clone job does not run {g!r}" for g in GATES if g not in runs]
    required = {
        "the daemon is stopped": "sudo systemctl stop docker.socket docker.service",
        "the step fails while a daemon answers": "if docker info >/dev/null 2>&1; then",
        "the gates run as root": "sudo --preserve-env=",
        "root is asserted": 'test "$(id -u)" = 0',
        "a clone made by root": "git clone -q --no-local",
        "installed from the lock": "uv sync -q --locked",
    }
    findings += [
        f"the fresh-clone job lost: {why}" for why, text in required.items() if text not in runs
    ]
    if runs.find("systemctl stop docker") > runs.find(".venv/bin/pytest"):
        findings.append("the fresh-clone job runs the suite before it stops the daemon")
    return findings


def test_every_ci_install_comes_from_the_lock() -> None:
    assert install_findings(CI.read_text(encoding="utf-8")) == []


def test_the_install_check_refuses_a_fresh_resolution() -> None:
    """A job reverted to the old editable install, an unlocked sync, or a library named on the
    command line is each a finding — the check cannot pass on any of them."""
    planted = CI.read_text(encoding="utf-8").replace(
        "uv sync -q --locked --python 3.12 --extra dev\n",
        "uv pip install -q -e '.[dev]' --python .venv/bin/python\n",
        1,
    )
    assert any("installs from outside uv.lock" in f for f in install_findings(planted))
    unlocked = CI.read_text(encoding="utf-8").replace("uv sync -q --locked", "uv sync -q", 1)
    assert any("resolves instead of reading uv.lock" in f for f in install_findings(unlocked))
    named = CI.read_text(encoding="utf-8").replace(
        "uv pip install -q pip pip-audit", "uv pip install -q pip pip-audit sqlalchemy", 1
    )
    assert any("installs from outside uv.lock" in f for f in install_findings(named))


def test_the_lock_matches_pyproject_and_pins_the_gate_tools() -> None:
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert lock_findings(lock, pyproject) == []
    versions = {p["name"]: p.get("version") for p in lock["package"]}
    for tool in ("ruff", "mypy", "pytest", "import-linter", "markdown-it-py", "sqlalchemy"):
        assert versions.get(tool), f"uv.lock pins no {tool}"


def test_the_lock_check_refuses_a_dependency_added_without_relocking() -> None:
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    pyproject["project"]["optional-dependencies"]["server"].append("rich>=13")
    assert any("declared but not locked" in f for f in lock_findings(lock, pyproject))
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]
    dev[:] = ["ruff==0.0.1" if d.startswith("ruff==") else d for d in dev]
    findings = lock_findings(lock, pyproject)
    assert any("ruff is pinned 0.0.1 in pyproject.toml but locked at" in f for f in findings)


def test_the_fresh_clone_job_runs_every_gate_as_root_without_docker() -> None:
    assert fresh_clone_findings(CI.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("dropped", [*GATES, "sudo systemctl stop docker.socket docker.service"])
def test_the_fresh_clone_check_refuses_a_job_that_drops_a_condition(dropped: str) -> None:
    text = CI.read_text(encoding="utf-8")
    head, job = text.split("\n  fresh-clone:\n", 1)
    job, tail = job.split("\n  ui-unit:\n", 1)
    assert dropped in job
    planted = f"{head}\n  fresh-clone:\n{job.replace(dropped, 'true', 1)}\n  ui-unit:\n{tail}"
    assert fresh_clone_findings(planted) != []
