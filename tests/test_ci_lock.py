"""CI installs from ``uv.lock``; one job runs every gate on a fresh clone as root, with no docker.

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
              and dependency groups ``pyproject.toml`` declares (a dependency added or
              re-pinned without relocking) or pins a gate or reporting tool at another
              version than ``pyproject.toml``; when a workflow's ``setup-uv`` step lets the
              installer float (no exact ``version``); and when the
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

_UV_SYNC = re.compile(r"\buv sync\b[^\n]*")
_PIP_INSTALL = re.compile(r"\b(?:uv )?pip install\b[^\n]*")
_UV_EXPORT = re.compile(r"\buv export\b[^\n]*")


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
            hashed = re.search(r"--require-hashes -r (\S+)", line)
            if hashed:
                exported = [e for e in _UV_EXPORT.findall(run) if f"-o {hashed.group(1)}" in e]
                if not exported or not all("--locked" in e for e in exported):
                    findings.append(f"{job}: {hashed.group(1)} is not exported --locked")
                continue
            # anything else names packages on the command line: none come from the lock
            # (the reporting tools are in uv.lock's audit and sbom dependency groups)
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


def group_requirements(pyproject: dict[str, Any]) -> set[tuple[str, tuple[str, ...], str, str]]:
    """``pyproject.toml``'s dependency groups as the lock's ``requires-dev`` records them."""
    out: set[tuple[str, tuple[str, ...], str, str]] = set()
    for group, reqs in (pyproject.get("dependency-groups") or {}).items():
        for req in reqs:
            m = _PEP508.match(str(req).strip())
            assert m, req
            name = m.group(1).lower().replace("_", "-")
            extras = tuple(sorted(e.strip() for e in (m.group(2) or "").split(",") if e.strip()))
            out.add((name, extras, m.group(3).replace(" ", ""), f"group {group}"))
    return out


def lock_findings(lock: dict[str, Any], pyproject: dict[str, Any]) -> list[str]:
    """Each way ``uv.lock`` disagrees with ``pyproject.toml``."""
    name = pyproject["project"]["name"]
    roots = [p for p in lock["package"] if p["name"] == name]
    if len(roots) != 1:
        return [f"uv.lock has {len(roots)} entries for {name}"]
    locked = {_req_key(r) for r in roots[0]["metadata"]["requires-dist"]}
    declared = pyproject_requirements(pyproject)
    for group, reqs in (roots[0]["metadata"].get("requires-dev") or {}).items():
        locked |= {(*_req_key(r)[:3], f"group {group}") for r in reqs}
    declared |= group_requirements(pyproject)
    findings = [f"declared but not locked: {k}" for k in sorted(declared - locked)]
    findings += [f"locked but no longer declared: {k}" for k in sorted(locked - declared)]
    versions = {p["name"]: p.get("version") for p in lock["package"]}
    pinned = [
        *pyproject["project"]["optional-dependencies"].values(),
        *(pyproject.get("dependency-groups") or {}).values(),
    ]
    for extra in pinned:
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
        "--only-group audit --no-emit-project -o audit-tools.txt\n",
        "--only-group audit --no-emit-project -o audit-tools.txt\n"
        "          uv pip install -q sqlalchemy --python .audit/bin/python\n",
        1,
    )
    assert any("installs from outside uv.lock" in f for f in install_findings(named))
    # the reporting tools too: pip-audit's verdict is a gate, so it comes from the lock
    for tool in ("pip pip-audit", "cyclonedx-bom"):
        loose = CI.read_text(encoding="utf-8").replace(
            "run: |\n", f"run: |\n          uv pip install -q {tool} --python .venv/bin/python\n", 1
        )
        assert any("installs from outside uv.lock" in f for f in install_findings(loose)), tool
    unexported = CI.read_text(encoding="utf-8").replace(
        "uv export -q --locked --only-group audit", "uv export -q --only-group audit", 1
    )
    assert any("is not exported --locked" in f for f in install_findings(unexported))


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
_EXACT = re.compile(r"^\d+\.\d+\.\d+$")


def installer_findings(name: str, text: str) -> list[str]:
    """Each ``astral-sh/setup-uv`` step that does not pin the installer's own version: a uv
    release that changes how a lock is read would otherwise turn every ``--locked`` job red
    on an unchanged tree."""
    out: list[str] = []
    for job, body in (yaml.safe_load(text).get("jobs") or {}).items():
        for step in body.get("steps", []):
            if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
                version = str((step.get("with") or {}).get("version", ""))
                if not _EXACT.match(version):
                    out.append(f"{name}: {job}: setup-uv floats (version {version or 'unset'!r})")
    return out


def test_every_workflow_pins_the_installer() -> None:
    found = [f for w in WORKFLOWS for f in installer_findings(w.name, w.read_text("utf-8"))]
    assert found == []
    assert WORKFLOWS and any("setup-uv" in w.read_text("utf-8") for w in WORKFLOWS)


def test_the_installer_check_refuses_a_floating_uv() -> None:
    text = CI.read_text(encoding="utf-8")
    pinned = re.search(r'\n( +)version: "\d+\.\d+\.\d+"\n', text)
    assert pinned, "ci.yml pins no setup-uv version"
    assert installer_findings("ci.yml", text.replace(pinned.group(0), "\n", 1)) != []
    assert (
        installer_findings(
            "ci.yml", text.replace(pinned.group(0), f'\n{pinned.group(1)}version: "latest"\n', 1)
        )
        != []
    )


def test_the_lock_matches_pyproject_and_pins_the_gate_tools() -> None:
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert lock_findings(lock, pyproject) == []
    versions = {p["name"]: p.get("version") for p in lock["package"]}
    for tool in ("ruff", "mypy", "pytest", "import-linter", "markdown-it-py", "sqlalchemy"):
        assert versions.get(tool), f"uv.lock pins no {tool}"
    for tool in ("pip", "pip-audit", "cyclonedx-bom"):  # the reporting tools, by group
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
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    pyproject["dependency-groups"]["audit"] = ["pip==26.2.1", "pip-audit==0.0.1"]
    findings = lock_findings(lock, pyproject)
    assert any("pip-audit is pinned 0.0.1 in pyproject.toml but locked at" in f for f in findings)
    pyproject["dependency-groups"]["sbom"].append("rich>=13")
    assert any("declared but not locked" in f for f in lock_findings(lock, pyproject))


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
