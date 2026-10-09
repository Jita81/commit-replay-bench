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
What it does: Fails when a job in any workflow, or the product image's Dockerfile, installs
              the project or a library other than from ``uv.lock`` (``uv sync --locked``,
              or ``uv export --locked`` with ``--require-hashes``, then the project's own
              build with ``--no-deps``) — the image is what ships (P-270); when
              ``uv.lock`` no longer matches the extras
              and dependency groups ``pyproject.toml`` declares (a dependency added or
              re-pinned without relocking) or pins a gate or reporting tool at another
              version than ``pyproject.toml``; when a workflow's ``setup-uv`` step lets the
              installer float (no exact ``version``); and when the
              ``fresh-clone`` check — ``fresh-clone-gates``, the ``fresh-clone-shard`` jobs and
              the ``fresh-clone`` aggregator over them — stops running a gate, stops running
              as root in its own clone, stops proving the docker daemon is gone, stops proving
              the shards' partition, lets an aggregator step be skipped (P-746), or declares a
              tool root is not given (P-745, P-743). Each check
              is also run on a planted regression so it cannot pass vacuously.
How:          PyYAML reads the workflows; the Dockerfile's ``RUN`` instructions are joined
              across continuations; ``tomllib`` reads ``uv.lock`` and ``pyproject.toml``;
              requirement strings are compared as (name, extras, specifier, extra marker).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   .github/workflows/ci.yml (the install steps and the ``fresh-clone`` job),
              .github/workflows/release.yml (the wheel smoke test), deploy/Dockerfile (the
              image's dependency layer),
              uv.lock (the lock), pyproject.toml (the extras it locks), docs/CONTRIBUTING.md
              (the same install for a person), docs/dod/product.md (product.evidence.205)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a job installs Python packages a new way; a gate is added
              to CONTRIBUTING's list (add it to ``GATES`` and to the fresh-clone job in the same
              change).
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
DOCKERFILE = ROOT / "deploy" / "Dockerfile"
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


#: Options of ``pip install`` that take a value; the value is not a package.
_VALUED = ("--python", "-p")
#: Options that name what to install from a file: never "only the local tree".
_FROM_FILE = ("-r", "--requirement", "-c", "--constraint", "-e", "--editable")


def _installs_only_a_local_build(command: str) -> bool:
    """``uv pip install --no-deps <path>…``: the project's own wheel or tree, with nothing
    resolved (its dependencies came from the lock in an earlier step)."""
    words = command.split()
    if "--no-deps" not in words:
        return False
    args: list[str] = []
    skip = False
    for w in words[words.index("install") + 1 :]:
        if skip:
            skip = False
        elif w in _VALUED:
            skip = True
        elif w in _FROM_FILE:
            return False
        elif not w.startswith("-"):
            args.append(w)
    return bool(args) and all(a == "." or "/" in a for a in args)


def run_findings(where: str, run: str) -> list[str]:
    """Each Python install in one shell ``run`` (a workflow step, a Dockerfile ``RUN``) that
    does not come from ``uv.lock``."""
    findings: list[str] = []
    for m in _UV_SYNC.finditer(run):
        if "--locked" not in m.group(0):
            findings.append(f"{where}: {m.group(0)!r} resolves instead of reading uv.lock")
    for command in re.split(r"\n|;|&&", run):
        for m in _PIP_INSTALL.finditer(command):
            line = m.group(0).strip()
            hashed = re.search(r"--require-hashes -r (\S+)", line)
            if hashed:
                exported = [e for e in _UV_EXPORT.findall(run) if f"-o {hashed.group(1)}" in e]
                if not exported or not all("--locked" in e for e in exported):
                    findings.append(f"{where}: {hashed.group(1)} is not exported --locked")
                continue
            if _installs_only_a_local_build(line):
                continue
            # anything else names packages, or a file of them, on the command line: none
            # come from the lock (the reporting tools are in uv.lock's audit and sbom groups)
            findings.append(f"{where}: {line!r} installs from outside uv.lock")
    return findings


def install_findings(ci_text: str) -> list[str]:
    """Each Python install in the workflow that does not come from ``uv.lock``."""
    findings: list[str] = []
    for job, run in _runs(yaml.safe_load(ci_text)):
        findings += run_findings(job, run)
    return findings


def dockerfile_runs(text: str) -> list[tuple[str, str]]:
    """Every ``RUN`` instruction of a Dockerfile as ``(line, its shell text)``, the
    backslash continuations joined and comment lines inside it dropped."""
    out: list[tuple[str, str]] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        start = i
        parts = [lines[i]]
        while parts[-1].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            if not lines[i].lstrip().startswith("#"):
                parts.append(lines[i])
        i += 1
        joined = " ".join(p.rstrip().rstrip("\\").strip() for p in parts)
        if joined.startswith("RUN "):
            out.append((str(start + 1), joined[4:]))
    return out


def image_findings(text: str, name: str = "deploy/Dockerfile") -> list[str]:
    """Each Python install in the product image's Dockerfile that does not come from
    ``uv.lock`` — the image is what ships, so a pin that holds only in CI pins nothing a
    customer runs (P-270)."""
    return [f for line, run in dockerfile_runs(text) for f in run_findings(f"{name}:{line}", run)]


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


#: The UI gates run in one subshell line of the gates script, exactly this.
UI_GATES_LINE = (
    "(cd ui && npm ci --no-audit --no-fund --legacy-peer-deps && npm run typecheck "
    "&& npx vitest run)"
)
#: The one way the gates script may be run: bash with errexit, nounset and pipefail, as a
#: file (P-346).
GATES_INVOCATION = (
    'env "PATH=$PATH" HOME=/root bash -euo pipefail "$RUNNER_TEMP/gates.sh" < /dev/null'
)
_HEREDOC = re.compile(r"<<'GATES'\n(.*?)\n\s*GATES\s*(?:\n|$)", re.S)


def _gates_script(runs: str) -> list[str]:
    """The lines of the heredoc that writes ``gates.sh``, stripped."""
    m = _HEREDOC.search(runs)
    return [line.strip() for line in m.group(1).splitlines()] if m else []


#: The parts of the fresh-clone check: every gate but the suite, and the suite's N shards. The
#: aggregator ``fresh-clone`` carries the one name an administrator requires (DL-101); it was
#: one job until its first run took 65.9 of its 75 minutes (P-743).
FRESH_CLONE_PARTS = ("fresh-clone-gates", "fresh-clone-shard")
#: The aggregator's gate over ``toJSON(needs)``: every part succeeded, and there is one.
ALL_PASSED_JQ = 'to_entries | length > 0 and all(.value.result == "success")'
_ALWAYS = ("always()", "${{ always() }}")


def shard_suite_line(n: int) -> str:
    """The one line of a fresh-clone shard's script that runs the suite: the ``pytest`` gate
    unchanged, plus this shard's options and its report — nothing else selects a test."""
    return (
        f"PYTHONPATH=scripts {GATES[-1]} -p ci_test_shards "
        f'--shard="$SHARD/{n}" --shard-report="$SRC/fresh-clone-report/shard-$SHARD.json"'
    )


def _shard_values(job: dict[str, Any]) -> list[Any]:
    return list(((job.get("strategy") or {}).get("matrix") or {}).get("shard") or [])


def _part_findings(name: str, job: dict[str, Any]) -> tuple[list[str], list[str]]:
    """What one part no longer holds of the fresh-clone conditions, and its gates script."""
    findings: list[str] = []
    if str(job.get("if", "always()")).strip() not in _ALWAYS:
        findings.append(f"{name} runs only if {job['if']!r}")
    if job.get("continue-on-error"):
        findings.append(f"{name} may fail without failing the check")
    for step in job.get("steps", []):
        if step.get("continue-on-error") or str(step.get("if", "always()")).strip() not in _ALWAYS:
            findings.append(f"a {name} step can be skipped or ignored: {step.get('name')!r}")
    runs = "\n".join(str(s.get("run", "")) for s in job.get("steps", []))
    lines = [line.strip() for line in runs.splitlines()]
    if GATES_INVOCATION not in lines:
        findings.append(f"{name}: the gates script is not run as bash -euo pipefail of the file")
    required = {
        "the daemon is stopped": "sudo systemctl stop docker.socket docker.service",
        "the step fails while a daemon answers": "if docker info >/dev/null 2>&1; then",
        "the gates run as root": "sudo --preserve-env=",
        "root is asserted": 'test "$(id -u)" = 0',
        "a clone made by root": "git clone -q --no-local",
        "installed from the lock": "uv sync -q --locked",
    }
    findings += [f"{name} lost: {why}" for why, text in required.items() if text not in runs]
    if runs.find("systemctl stop docker") > runs.find('"$RUNNER_TEMP/gates.sh" <'):
        findings.append(f"{name} runs its gates before it stops the daemon")
    return findings, _gates_script(runs)


def fresh_clone_findings(ci_text: str) -> list[str]:
    """Each condition of product.evidence.205 the ``fresh-clone`` check no longer holds.

    The jobs are parsed, not searched (P-346): a gate counts only as an exact line of a gates
    script (so ``|| true``, ``--co``, ``-k`` or ``--deselect`` on it is a finding), each
    script runs only as ``bash -euo pipefail`` of the file, and no part, aggregator or step of
    either carries an ``if:`` other than ``always()`` or a ``continue-on-error``. The aggregator runs
    ``always()``, needs every part, passes only when every part passed and proves the
    shards' partition; each shard declares the tools it provides as root, and never docker —
    its daemon is stopped (P-745)."""
    jobs = yaml.safe_load(ci_text)["jobs"]
    agg = jobs.get("fresh-clone")
    if agg is None:
        return ["ci.yml has no fresh-clone job"]
    findings: list[str] = []
    if str(agg.get("if", "")).strip() not in _ALWAYS:
        findings.append("the fresh-clone aggregator does not run always(): a failed part skips it")
    needs = agg.get("needs") or []
    if set([needs] if isinstance(needs, str) else needs) != set(FRESH_CLONE_PARTS):
        findings.append(f"the fresh-clone aggregator needs {needs!r}, not every part")
    agg_runs = "\n".join(str(s.get("run", "")) for s in agg.get("steps", []))
    if f"jq -e '{ALL_PASSED_JQ}'" not in agg_runs:
        findings.append("the fresh-clone aggregator does not fail when a part did not pass")
    if agg.get("continue-on-error") or any(s.get("continue-on-error") for s in agg["steps"]):
        findings.append("the fresh-clone aggregator may fail without failing the check")
    for step in agg.get("steps", []):  # an ``if: false`` step is green without running (P-746)
        if str(step.get("if", "always()")).strip() not in _ALWAYS:
            findings.append(f"a fresh-clone aggregator step can be skipped: {step.get('name')!r}")
    scripts: dict[str, list[str]] = {}
    for name in FRESH_CLONE_PARTS:
        job = jobs.get(name)
        if job is None:
            findings.append(f"ci.yml has no {name} job")
            continue
        part, scripts[name] = _part_findings(name, job)
        findings += part
    for g in GATES[:-1]:
        exact = UI_GATES_LINE if g in ("npm run typecheck", "npx vitest run") else g
        if exact not in scripts.get("fresh-clone-gates", []):
            findings.append(f"fresh-clone-gates does not run {g!r} as its own line")
    shard = jobs.get("fresh-clone-shard") or {}
    n = len(_shard_values(shard))
    if _shard_values(shard) != list(range(1, n + 1)) or n == 0:
        findings.append(f"the fresh-clone shards are not 1..N: {_shard_values(shard)!r}")
    if shard_suite_line(n) not in scripts.get("fresh-clone-shard", []):
        findings.append("fresh-clone-shard does not run the suite, sharded, as its own line")
    if f"ci_test_shards.py verify --shards {n} " not in " ".join(agg_runs.split()):
        findings.append(f"the fresh-clone aggregator does not prove the {n} shards' partition")
    provided = str((shard.get("env") or {}).get("CRB_TEST_REQUIRE_TOOLS", "")).split()
    if not provided or "docker" in provided:
        findings.append(f"the fresh-clone shards declare {provided!r} as the tools they provide")
    shard_runs = "\n".join(str(s.get("run", "")) for s in shard.get("steps", []))
    if not re.search(r"--preserve-env=[^ ]*\bCRB_TEST_REQUIRE_TOOLS\b", shard_runs):
        findings.append("the fresh-clone shards do not hand root the tools they provide")
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


def test_every_workflow_install_comes_from_the_lock() -> None:
    """Not only ci.yml: the release's wheel smoke test installs too, and a release built on
    a fresh resolution is a release of versions no gate ran."""
    found = [f for w in WORKFLOWS for f in install_findings(w.read_text("utf-8"))]
    assert found == []
    assert len(WORKFLOWS) >= 4


def test_the_product_image_installs_from_the_lock() -> None:
    """The image CI's ``container`` job builds and the release pushes is what a customer
    runs; its libraries come from uv.lock by version and hash, never from pyproject.toml
    resolved at build time (the SQLAlchemy 2.1.0 class, in production — P-270)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert image_findings(text) == []
    runs = " ".join(run for _line, run in dockerfile_runs(text))
    assert "uv export" in runs and "--locked" in runs and "--require-hashes" in runs
    assert "COPY pyproject.toml uv.lock" in text


def test_the_image_check_refuses_a_fresh_resolution() -> None:
    """The negative controls: the old dependency layer, an unlocked export, a library named
    in a RUN, and a local install that resolves its dependencies are each a finding."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    old = (
        "RUN set -eu; \\\n    uv venv /app/.venv; \\\n    uv pip install --python "
        "/app/.venv/bin/python \\\n        -r /app/pyproject.toml --extra server\n"
    )
    assert any("installs from outside uv.lock" in f for f in image_findings(old))
    unlocked = text.replace("uv export --locked", "uv export", 1)
    assert unlocked != text
    assert any("is not exported --locked" in f for f in image_findings(unlocked))
    assert any(
        "installs from outside uv.lock" in f
        for f in image_findings("RUN uv pip install --python /app/.venv/bin/python sqlalchemy\n")
    )
    resolving = text.replace("--no-deps /app", "/app", 1)
    assert resolving != text
    assert any("installs from outside uv.lock" in f for f in image_findings(resolving))
    # and in a workflow: the wheel smoke test must not resolve the wheel's dependencies
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    loose = release.replace("--no-deps dist/", "dist/", 1)
    assert loose != release
    assert any("installs from outside uv.lock" in f for f in install_findings(loose))


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


def _split_fresh_clone(text: str) -> tuple[str, str, str]:
    """ci.yml as (before, the three fresh-clone jobs, after)."""
    head, jobs = text.split("\n  fresh-clone-gates:\n", 1)
    jobs, tail = jobs.split("\n  ui-unit:\n", 1)
    return head, jobs, tail


def _planted_job(edit: Any) -> str:
    head, jobs, tail = _split_fresh_clone(CI.read_text(encoding="utf-8"))
    return f"{head}\n  fresh-clone-gates:\n{edit(jobs)}\n  ui-unit:\n{tail}"


@pytest.mark.parametrize(
    ("what", "edit"),
    [
        ("an if on the job", lambda j: j.replace("    name:", "    if: false\n    name:", 1)),
        (
            "a gate that cannot fail",
            lambda j: j.replace(".venv/bin/mypy\n", ".venv/bin/mypy || true\n", 1),
        ),
        (
            "the suite only collected",
            lambda j: j.replace(
                "pytest -q -p no:cacheprovider", "pytest --co -q -p no:cacheprovider"
            ),
        ),
        (
            "a deselected suite",
            lambda j: j.replace('-m "not sandbox_images"', '-m "not sandbox_images" -k store'),
        ),
        (
            "the script never run",
            lambda j: j.replace(
                'bash -euo pipefail "$RUNNER_TEMP/gates.sh"', 'bash -c true "$RUNNER_TEMP/gates.sh"'
            ),
        ),
        (
            "a step that may fail",
            lambda j: j.replace(
                "      - name: Every gate but the suite",
                "      - continue-on-error: true\n        name: Every gate but the suite",
            ),
        ),
        (
            "a shard step that may fail",
            lambda j: j.replace(
                "      - name: This shard of the suite",
                "      - continue-on-error: true\n        name: This shard of the suite",
            ),
        ),
        (
            "an aggregator a failed part skips",
            lambda j: j.replace("fresh-clone-shard]\n    if: always()\n", "fresh-clone-shard]\n"),
        ),
        (
            "an aggregator that ignores a failed part",
            lambda j: j.replace("jq -e 'to_entries", "jq 'to_entries", 1),
        ),
        (
            "an aggregator that does not wait for the shards",
            lambda j: j.replace(
                "needs: [fresh-clone-gates, fresh-clone-shard]", "needs: [fresh-clone-gates]"
            ),
        ),
        (
            "an aggregator whose every-part-passed step never runs",
            lambda j: j.replace(
                "      - name: Every part passed (the gates and every shard)\n",
                "      - name: Every part passed (the gates and every shard)\n        if: false\n",
            ),
        ),
        (
            "an aggregator whose partition proof never runs",
            lambda j: j.replace(
                "      - name: Every test ran in exactly one shard (the partition proof)\n",
                "      - name: Every test ran in exactly one shard (the partition proof)\n"
                "        if: false\n",
            ),
        ),
        (
            "an aggregator that does not prove the partition",
            lambda j: j.replace("ci_test_shards.py verify --shards 11", "ci_test_shards.py plan"),
        ),
        (
            "a shard that drops a slice",
            lambda j: j.replace('--shard="$SHARD/11"', '--shard="1/11"'),
        ),
        (
            "a shard that claims the stopped daemon",
            lambda j: j.replace(
                'CRB_TEST_REQUIRE_TOOLS: "go', 'CRB_TEST_REQUIRE_TOOLS: "docker go'
            ),
        ),
        (
            "a shard whose declaration never reaches root",
            lambda j: j.replace("SRC,SHARD,CRB_TEST_REQUIRE_TOOLS,", "SRC,SHARD,"),
        ),
    ],
)
def test_the_fresh_clone_check_refuses_a_neutered_job(what: str, edit: Any) -> None:
    """P-346: the check matched substrings, so a job with ``if: false``, a gate run as
    ``… || true``, the suite collected but not run, or the gates script never executed all
    passed it. Each shape is a finding."""
    planted = _planted_job(edit)
    assert planted != CI.read_text(encoding="utf-8"), what
    assert fresh_clone_findings(planted) != [], what


@pytest.mark.parametrize("dropped", [*GATES, "sudo systemctl stop docker.socket docker.service"])
def test_the_fresh_clone_check_refuses_a_job_that_drops_a_condition(dropped: str) -> None:
    head, jobs, tail = _split_fresh_clone(CI.read_text(encoding="utf-8"))
    assert dropped in jobs
    planted = (
        f"{head}\n  fresh-clone-gates:\n{jobs.replace(dropped, 'true', 1)}\n  ui-unit:\n{tail}"
    )
    assert fresh_clone_findings(planted) != []


@pytest.mark.parametrize("part", FRESH_CLONE_PARTS)
def test_the_fresh_clone_check_refuses_a_part_that_drops_a_condition(part: str) -> None:
    """Every part holds every condition on its own: dropping the daemon stop, the root
    assertion or the lock from the SECOND part is found as surely as from the first."""
    head, jobs, tail = _split_fresh_clone(CI.read_text(encoding="utf-8"))
    body = jobs.split(f"\n  {part}:\n", 1)[-1] if part != FRESH_CLONE_PARTS[0] else jobs
    for condition in ("sudo systemctl stop docker.socket docker.service", 'test "$(id -u)" = 0'):
        assert condition in body
        cut = jobs[: len(jobs) - len(body)] + body.replace(condition, "true", 1)
        planted = f"{head}\n  fresh-clone-gates:\n{cut}\n  ui-unit:\n{tail}"
        assert any(f.startswith(part) for f in fresh_clone_findings(planted)), (part, condition)
