#!/usr/bin/env python3
"""One command for the checks a pull request meets in CI, run before the push.

PR #136 met CI with two failures its author had not seen: the `commit-subjects` job refused
the pull request's title (a squash merge writes it on ``main`` as the commit subject), and
``tests/test_works_with.py`` failed in a test shard. Both checks run on a laptop in seconds;
the author ran a list of checks picked by hand, and neither was on it (docs/PREVENTION.md
P-818). This script is that list, read from CI, so nobody has to pick:

    python scripts/pre_push.py --title "fix(api): refuse an empty name"     # every gate + suite
    python scripts/pre_push.py --fast --title "…"   # gates + changed files' tests + ratchets
    python scripts/pre_push.py --list               # what runs here, and what only CI runs
    python scripts/pre_push.py --install-hook       # once per clone: run it on every git push

Run it with the virtual environment's interpreter (``.venv/bin/python``): it finds ``ruff``,
``mypy`` and ``lint-imports`` beside that interpreter. Every gate runs from this checkout's
``src`` (it is put first on ``PYTHONPATH``), so an editable install of another checkout cannot
pass in its place.

**What it does not run.** A job that needs docker, a database service, a browser or the
network is listed in ``UNCOVERED_JOBS`` or ``UNCOVERED_STEPS`` with its reason and printed at
the end of every run, so a skipped gate is never a silent one. ``tests/test_pre_push.py``
splits every ``run:`` line of the pull-request workflows into its commands (at ``&&``,
``||``, ``;`` and ``|``) and fails on a command that is neither a gate here
(``Gate.mirrors``), nor listed as not run, nor plumbing (``SETUP``): a gate added to CI, even
one chained after ``cd`` or an install, cannot be missing from this list without the suite
saying so. A gate here that cannot run (``ui/node_modules`` absent, no ``--title``) is
NOT RUN and the exit is 3, unless ``--allow-skip`` accepts it.

**The git hook.** ``--install-hook`` points this clone's ``core.hooksPath`` at
``scripts/hooks``, whose ``pre-push`` runs ``--hook`` before a push leaves: the ``--fast`` set,
with the title read from ``CRB_PR_TITLE`` when it is set. In the hook a gate NOT RUN stops the
push, with two exceptions: the title gate when no title is known (a pull request may not
exist yet), and a gate whose own folder and the folders it reads (``ui`` and ``docs`` for the
UI gates) hold no changed file. The gates check what is checked out, so a push that sends
anything but this checkout's ``HEAD`` (another branch, several refs, a tag on an older
commit) is stopped with exit 3, and so is a push from a checkout with uncommitted or
untracked files, which the gates would read in place of what the commit holds. Once the hook has found an interpreter, a push that only
deletes refs runs no gate. A worktree whose branch does not carry ``scripts/hooks`` has no
hook to run. ``git push --no-verify`` skips every git hook, this one included, and nothing
local can stop that: CI remains the gate. A run outside the hook says so when the hook is not
installed.

Nothing here fetches: ``--base`` (``origin/main``) is read as it is in this clone, so a stale
one widens the range the subjects and ``--fast`` read. CI sees only commits; a dirty tree is
checked as it is on disk, and the run starts with a warning naming each such path.

Navigation
----------
What it is:   The local pre-push runner: every static gate the pull-request workflows run that
              works without docker, a service or the network, then the suite as CI runs it.
What it does: Runs each gate in ``GATES`` (ruff, mypy, import-linter, the code-map, dod,
              claims and UI-type gates, the UI's own gates when ``ui/node_modules`` exists,
              the commit subjects since ``--base`` and ``--title`` as the squash subject),
              then pytest over the hermetic suite at CI's coverage floor (or, with ``--fast``,
              over the changed files' tests and the repository-wide ratchets); prints one line
              per gate, every CI check it did not run and ``N passed, N failed, N not run``;
              exits 1 when a gate failed, 3 when one was not run (unless ``--allow-skip``),
              2 when ``--base`` is not a commit here. ``--install-hook`` sets
              ``core.hooksPath`` to ``scripts/hooks``; ``--hook`` is the run that hook makes.
How:          Each gate is an argv run from the repository root (its output shown only when
              it fails; pytest streams) or, for the subjects, a call into
              scripts/check_commit_subject.py; ``--fast`` maps each changed file to its tests
              through its header's ``Tested by`` (scripts/code_map.py).
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the jobs it mirrors, and the coverage floor it reads),
              .github/workflows/commit-subjects.yml (the title gate it runs before the pull
              request exists), scripts/hooks/pre-push (the git hook that runs ``--hook``),
              scripts/check_commit_subject.py (the subject rule it imports,
              never copies), scripts/code_map.py (the header reader that maps a changed file to
              its tests), docs/CONTRIBUTING.md (where a contributor is told to run it),
              docs/PREVENTION.md (P-818, the class it stops)
Tested by:    tests/test_pre_push.py
Touch when:   never for a new repository; a step is added to a pull-request workflow (add a
              ``Gate`` that mirrors it, an ``UNCOVERED_STEPS`` entry with the reason it
              cannot run here, or, in a job not run here, its program in
              ``UNCOVERED_JOB_TOOLS`` — tests/test_pre_push.py fails until one of them names
              it).
"""

from __future__ import annotations

import argparse
import functools
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# The commit-subject rule is imported, never copied; code_map reads the file headers.
import check_commit_subject as ccs  # noqa: E402
import code_map  # noqa: E402

CI_YML = ROOT / ".github" / "workflows" / "ci.yml"

#: The workflows a pull request triggers; tests/test_pre_push.py holds this to every workflow
#: whose ``on:`` names ``pull_request``.
WORKFLOWS: tuple[str, ...] = (".github/workflows/ci.yml", ".github/workflows/commit-subjects.yml")

#: Repository-wide ratchets: tests that read the whole tree, so any change can break them
#: whatever file it touches. ``--fast`` always runs them.
RATCHET_TESTS: tuple[str, ...] = (
    "tests/test_works_with.py",
    "tests/test_header_width.py",
    "tests/test_public_docs.py",
    "tests/test_prevention_register.py",
    "tests/test_version_consistency.py",
    "tests/test_ci_lock.py",
    "tests/test_ci_job_names.py",
    "tests/test_check_branch_protection.py",
    "tests/test_suite_imports_resolve_in_ci.py",
    "tests/test_toolchain_gates.py",
    "tests/test_pre_push.py",
    "tests/test_ci_job_budget.py",
    "tests/test_ci_test_shards.py",
    "tests/test_prevention_ci_evidence.py",
    "tests/test_measured_claims.py",
    "tests/test_code_map.py",
    "tests/test_dod_check.py",
    "tests/test_claims_check.py",
    "tests/test_check_commit_subject.py",
)

#: CI's ``-m`` for the hermetic suite: the sandbox images are built and tested in their own job.
SUITE_MARKER = "not sandbox_images"


@dataclass(frozen=True)
class Gate:
    """One local check and the CI ``run:`` lines it stands for.

    ``argv`` starts with a tool name: ``python`` is this interpreter; ``ruff``, ``mypy`` and
    ``lint-imports`` are found beside it. ``mirrors`` are regular expressions, each matched in
    full against one command (``commands``) of a whitespace-collapsed ``run:`` line of a
    pull-request workflow, prefixed by its job id and a colon
    (``lint: .venv/bin/ruff check src tests``)."""

    name: str
    argv: tuple[str, ...]
    mirrors: tuple[str, ...]
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)
    #: a path (from the root) the gate needs; when it is missing the gate is NOT RUN, and said
    requires: str | None = None
    #: folders outside ``cwd`` whose files the gate also reads (the UI tests read ``docs``);
    #: the hook lets the gate go NOT RUN only when the push changes nothing it reads
    reads: tuple[str, ...] = ()
    #: stream the output (the suite) instead of showing it only on failure
    stream: bool = False


def _floor() -> str:
    """CI's coverage floor, read from the ``test`` job's ``coverage report --fail-under=N``."""
    m = re.search(r"coverage report --fail-under=(\d+)", CI_YML.read_text(encoding="utf-8"))
    if m is None:
        raise SystemExit("pre_push: ci.yml has no `coverage report --fail-under=N` to read")
    return m.group(1)


_PY = r"(?:python3?|\.venv/bin/python)"

GATES: tuple[Gate, ...] = (
    Gate(
        "ruff check (lint; fresh-clone gates)",
        ("ruff", "check", "src", "tests", "scripts"),
        (
            r"lint: \.venv/bin/ruff check src tests",
            r"fresh-clone-gates: \.venv/bin/ruff check src tests scripts",
        ),
    ),
    Gate(
        "ruff format --check (lint; fresh-clone gates)",
        ("ruff", "format", "--check", "src", "tests", "scripts"),
        (
            r"lint: \.venv/bin/ruff format --check src tests",
            r"fresh-clone-gates: \.venv/bin/ruff format --check src tests scripts",
        ),
    ),
    Gate("mypy --strict (types)", ("mypy",), (r"(types|fresh-clone-gates): \.venv/bin/mypy",)),
    Gate(
        "lint-imports (layers)",
        ("lint-imports",),
        (r"(layers|fresh-clone-gates): \.venv/bin/lint-imports",),
    ),
    Gate(
        "code_map --check (code-map)",
        ("python", "scripts/code_map.py", "--check"),
        (rf"(code-map|fresh-clone-gates): {_PY} scripts/code_map\.py --check",),
    ),
    Gate(
        "code_map --changed-since (code-map, pull request)",
        ("python", "scripts/code_map.py", "--check", "--changed-since", "{base}"),
        (r'code-map: python scripts/code_map\.py --check --changed-since "origin/\$BASE_REF"',),
    ),
    Gate(
        "dod_check --check (dod)",
        ("python", "scripts/dod_check.py", "--check"),
        (rf"(dod|fresh-clone-gates): {_PY} scripts/dod_check\.py --check",),
        env={"DOD_BASE": "{base}"},
    ),
    Gate(
        "claims_check --check (claims)",
        ("python", "scripts/claims_check.py", "--check"),
        (rf"(claims|fresh-clone-gates): {_PY} scripts/claims_check\.py --check",),
    ),
    Gate(
        "check_ui_types_drift --check (fresh-clone gates)",
        ("python", "scripts/check_ui_types_drift.py", "--check"),
        (rf"fresh-clone-gates: {_PY} scripts/check_ui_types_drift\.py --check",),
    ),
    Gate(
        "npm run typecheck (ui-unit)",
        ("npm", "run", "typecheck"),
        (r"(ui-unit|fresh-clone-gates): npm run typecheck",),
        cwd="ui",
        requires="ui/node_modules",
        reads=("docs",),
    ),
    Gate(
        "vitest run (ui-unit)",
        ("npx", "vitest", "run"),
        (r"(ui-unit|fresh-clone-gates): npx vitest run",),
        cwd="ui",
        requires="ui/node_modules",
        reads=("docs",),
    ),
    Gate(
        "commit subjects since --base (commit-subjects)",
        ("<subjects>",),
        (
            r'commit-subjects: python scripts/check_commit_subject\.py --range "\$BASE_SHA\.\.'
            r'\$HEAD_SHA" --title "\$PR_TITLE" --pr-number "\$PR_NUMBER" --check',
            r'commit-subjects: python scripts/check_commit_subject\.py --range "\$BEFORE_SHA\.\.'
            r'\$AFTER_SHA" --check',
        ),
    ),
    Gate(
        "pull request title as the squash subject (commit-subjects)",
        ("<title>",),
        (),  # the title half of the commit-subjects line above
    ),
    Gate(
        "pytest, the hermetic suite at CI's coverage floor (test-shard + test)",
        (
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-m",
            SUITE_MARKER,
            "--cov=crb",
            "--cov-branch",
            "--cov-report=",
            "--cov-fail-under={floor}",
        ),
        (
            r'test-shard: \.venv/bin/pytest -q -m "not sandbox_images" -p ci_test_shards '
            r"--shard=.+?/\d+ --shard-report=.+?\.json --cov=crb --cov-branch --cov-report= "
            r"--cov-fail-under=0",
            r"test: \.venv/bin/coverage report --fail-under=\d+",
            r"fresh-clone-shard: PYTHONPATH=scripts \.venv/bin/pytest -q -p no:cacheprovider -m "
            r'"not sandbox_images" -p ci_test_shards .*',
        ),
        stream=True,
    ),
)

#: Whole jobs this script does not run, with the reason. Their lines are still read by
#: tests/test_pre_push.py: each command must be named by a gate, ``UNCOVERED_STEPS`` or
#: ``SETUP``, or run a program the job lists in ``UNCOVERED_JOB_TOOLS`` with no word naming
#: a gate program — the comment on that list says what can still pass.
UNCOVERED_JOBS: dict[str, str] = {
    "security": "gitleaks is downloaded and pip-audit asks the advisory database (network)",
    "sbom": "the CycloneDX SBOM is an artifact, not a verdict on the change",
    "test-postgres": "the store suite against a PostgreSQL 16 service",
    "container": "hadolint, docker build and image smoke, helm lint (docker, helm)",
    "sandbox-images": "builds every reference sandbox image and tests on it (docker)",
    "ui-smoke": "Playwright Chromium over the built bundle (a browser install)",
    "walkthrough-story": "the browser walkthrough against a live stack",
    "walkthrough-screens": "the browser walkthrough's screens shards against a live stack",
    "walkthrough": "an aggregator over the walkthrough jobs' results",
    "fresh-clone-shard": "the suite as root on a fresh clone with no docker daemon",
    "fresh-clone": "an aggregator over the fresh-clone jobs, with the partition proof",
}

#: The fresh-clone jobs' own commands, each held whole: ``test``, ``git`` and ``sudo`` can carry
#: another command, so none of them is accepted by its program alone.
_FRESH_CLONE: tuple[str, ...] = (
    'test "$(id -u)" = 0',
    'git clone -q --no-local "$SRC" /root/fresh',
    "git fetch -q \"$SRC\" '+refs/remotes/origin/*:refs/remotes/origin/*'",
    'git fetch -q "$SRC" HEAD',
    'git checkout -q --detach "$(git -C "$SRC" rev-parse HEAD)"',
)
_AS_ROOT = (
    'sudo --preserve-env={env} env "PATH=$PATH" HOME=/root bash -euo pipefail '
    '"$RUNNER_TEMP/gates.sh" < /dev/null'
)

#: Single commands no gate here runs: ``(job id or "*", regex, reason)``, matched like
#: ``Gate.mirrors`` against one command (``commands``) without its job prefix.
UNCOVERED_STEPS: tuple[tuple[str, str, str], ...] = (
    ("*", r"python3 scripts/ci_job_budget\.py .*", "the job-budget guard times CI's own jobs"),
    ("test", r"jq .*", "the aggregator's every-shard-passed check reads CI's job results"),
    ("fresh-clone", r"jq .*", "the aggregator's every-part-passed check reads CI's job results"),
    (
        "*",
        r"python3 scripts/ci_test_shards\.py verify .*",
        "the shard partition proof and the weights' staleness need the shards' reports",
    ),
    ("test", r"\.venv/bin/coverage (combine|xml) .*", "combines the shards' coverage files"),
    *(
        (
            "fresh-clone-gates",
            re.escape(line),
            "the gates as root on a fresh clone made from the lock (this runs in your checkout)",
        )
        for line in (*_FRESH_CLONE, _AS_ROOT.format(env="DOD_BASE,SRC,PYTHONDONTWRITEBYTECODE"))
    ),
    *(
        (
            "fresh-clone-shard",
            re.escape(line),
            "the suite as root on a fresh clone made from the lock (this runs in your checkout)",
        )
        for line in (
            *_FRESH_CLONE,
            _AS_ROOT.format(
                env="SRC,SHARD,CRB_TEST_REQUIRE_TOOLS,JAVA_HOME,PYTHONDONTWRITEBYTECODE"
            ),
        )
    ),
    (
        "*",
        r"(sudo systemctl stop docker\.socket docker\.service|docker info .*)",
        "stops the runner's docker daemon",
    ),
    ("*", r"npm ci .*", "installs the UI's packages from the registry (network)"),
    ("ui-smoke", r"npx playwright test", "Playwright Chromium over the built bundle (a browser)"),
    ("*", r"npm run build", "builds the UI bundle the browser jobs serve"),
    ("security", r"python3 scripts/ci_gitleaks\.py", "needs the gitleaks binary CI downloads"),
    ("test-postgres", r"\.venv/bin/pytest .*", "needs the PostgreSQL service"),
    ("sbom", r"\.venv/bin/cyclonedx-py .*", "writes the SBOM artifact"),
    ("sandbox-images", r"\.venv/bin/pytest .*", "needs docker and the built sandbox images"),
    *(
        ("sandbox-images", re.escape(line), "checks the built sandbox images (docker)")
        for line in (
            # ``test`` runs the command it substitutes: each line is held whole
            'test -n "$want"',
            'test "$(docker run --rm --network=none --read-only --tmpfs /tmp crb-builder-go:ci '
            'id -u)" = "65534"',
            'test "$(docker run --rm --network=none --read-only --tmpfs /tmp "$img" id -u)" '
            '= "65534"',
            # names python as a sandbox language, and runs pytest inside that image
            "for lang in python node go",
            "docker run --rm --network=none --read-only --tmpfs /tmp crb-sandbox-python:ci "
            "python -m pytest --version",
        )
    ),
    *(
        ("container", re.escape(line), "runs python inside the built image (docker)")
        for line in (
            'docker run --rm crb:ci python -c "import os; assert os.getuid() == 10001, '
            "os.getuid(); print('uid ok')\"",
            "docker run --rm crb:ci python -c \"import os; assert os.path.isfile('/app/ui/dist/"
            "index.html'), 'UI missing from image'; print('ui ok')\"",
            'docker run --rm crb:ci python -c "import crb.store.migrate, crb.core, '
            "crb.builders; print('imports ok')\"",
        )
    ),
    (
        "security",
        re.escape('tar -xzf "$RUNNER_TEMP/gitleaks.tar.gz" -C "$RUNNER_TEMP" gitleaks'),
        "unpacks the gitleaks binary CI downloads",
    ),
    ("*", r"python3 \.\./scripts/ci_install_browser\.py .*", "installs Chromium (network)"),
    ("*", r"scripts/walkthrough\.sh .*", "boots a live stack and drives a browser"),
)

#: Plumbing, in any job: installs, git identity, the clock, file moves, shell syntax. Each is
#: matched against one command (``commands``), so a gate chained after it is still read.
SETUP: tuple[str, ...] = (
    r"uv (sync|export|venv|pip) .*",
    r"git config --global .*",
    r'echo "CRB_JOB_STARTED_AT=.*',
    r'echo "\$NEEDS"',
    r"echo [\"']::error::.*",
    r"(mkdir -p|ls -la|wc -l) .*",
    r"cd \S+",
    r"\[ -f \.coverage \]",
    r"mv \.coverage .*",
    r"(fi|exit \d+)",
    r"cat > \"\$RUNNER_TEMP/gates\.sh\" <<'GATES'",
    r"GATES",
    r"set -euo pipefail",
)

#: The programs each job in ``UNCOVERED_JOBS`` may run without a gate or an entry naming the
#: whole command: the tools its reason needs (docker, helm, the network) and the shell around
#: them, for a job with too many such lines to name each. A program that runs the command
#: after it (``sudo``, ``git``, ``test``, ``tar``) is not listed where the job has few such
#: lines: each line is an exact ``UNCOVERED_STEPS`` entry instead. A command accepted only by
#: its program here (or by ``SHELL_SYNTAX``) is still refused when any of its words, split at
#: whitespace and ``$ ( ) ` " ' ; | & < > = , { }``, names a gate program (``gate_programs``): so
#: ``docker run img pytest -q`` and ``echo $(ruff check src)`` are reported. What this does
#: not catch: a tool no gate here runs (``docker run img shellcheck x``), a gate reached
#: through a variable, a script file or an image's entrypoint (``docker run img`` whose image
#: runs ruff), a gate program under another name (``python3.12``), a name broken up by shell
#: quoting or escaping (``r''uff``, ``py\test``), and ``SETUP`` and ``UNCOVERED_STEPS``
#: patterns that end in ``.*`` (they match whatever follows).
UNCOVERED_JOB_TOOLS: dict[str, tuple[str, ...]] = {
    "security": ("curl", "echo", "sha256sum", ".audit/bin/pip-audit"),
    "test-postgres": ("grep",),
    "container": ("docker", "helm", "echo", "printf", "rm", "["),
    "sandbox-images": ("docker", "grep", "printf"),
    "walkthrough": ("jq",),
}

#: Shell words that run nothing on their own, accepted in any job listed as not run; a bare
#: ``VAR=value`` assignment is read as one of them (its program is ``=``).
SHELL_SYNTAX: tuple[str, ...] = ("for", "do", "done", "then", "else", "fi", "=")

#: Where a command is cut into words for ``gate_words``: whitespace and shell punctuation.
_WORDS = re.compile(r"""[\s$()`"';|&<>=,{}]+""")


def gate_programs(ci_commands: Iterable[tuple[str, str]]) -> frozenset[str]:
    """The programs the gates here run, read from ``GATES`` itself: each gate's tool
    (``argv[0]``), the program (``program``) of every ``(job, command)`` of ``ci_commands``
    a gate mirrors, the basename of each (``.venv/bin/pytest`` is also ``pytest``), and
    ``python`` / ``python3``."""
    found = {gate.argv[0] for gate in GATES if not gate.argv[0].startswith("<")}
    for job, cmd in ci_commands:
        if any(matches(gate.mirrors, f"{job}: {cmd}") for gate in GATES):
            found.add(program(cmd))
    found |= {name.rsplit("/", 1)[-1] for name in found}
    return frozenset(found | {"python", "python3"})


def gate_words(cmd: str, programs: Iterable[str]) -> list[str]:
    """The words of ``cmd`` that name one of ``programs``, by name or basename."""
    names = set(programs)
    words = (w for w in _WORDS.split(cmd) if w)
    return sorted({w for w in words if w in names or w.rsplit("/", 1)[-1] in names})


def program(cmd: str) -> str:
    """The program one command runs: its first word after any ``VAR=value`` assignments
    (``PYTHONPATH=scripts .venv/bin/pytest -q`` runs ``.venv/bin/pytest``), ``=`` for a
    command that only assigns."""
    try:
        words = shlex.split(cmd)
    except ValueError:  # an unbalanced quote: read the words as they are
        words = cmd.split()
    for word in words:
        if not re.match(r"[A-Za-z_][A-Za-z0-9_]*=", word):
            return word
    return "="


def workflow_triggers(workflow: Mapping[object, object]) -> set[str]:
    """The events a workflow's ``on:`` names. PyYAML reads an unquoted ``on:`` key as
    ``True`` and a quoted ``'on':`` as the string ``"on"``; both are read here, and the value
    may be one event, a list of them or a mapping keyed by them."""
    on = workflow.get(True, workflow.get("on"))
    if isinstance(on, str):
        return {on}
    if isinstance(on, Mapping | list | tuple):
        return {str(event) for event in on}
    return set()


#: Shell words that open a command without being one: ``if grep …; then mv …``.
_LEADING = re.compile(r"^(?:(?:if|then|else|elif|do|while|until|!)\s+|\()+")


def commands(line: str) -> list[str]:
    """The commands of one ``run:`` line: split at ``&&``, ``||``, ``;`` and ``|`` outside
    quotes, each stripped of a leading ``if`` / ``then`` / ``(`` and a closing ``)``, so a
    gate chained after a plumbing word (``cd ui && npx eslint .``) is read on its own."""
    parts: list[str] = []
    word: list[str] = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif line.startswith(("&&", "||"), i) or ch in ";|":
            parts.append("".join(word))
            word = []
            i += 2 if line.startswith(("&&", "||"), i) else 1
            continue
        word.append(ch)
        i += 1
    parts.append("".join(word))
    out = []
    for part in parts:
        cmd = _LEADING.sub("", part.strip())
        if cmd.endswith(")") and cmd.count(")") > cmd.count("("):
            cmd = cmd[:-1].rstrip()
        if cmd:
            out.append(cmd)
    return out


def matches(patterns: Iterable[str], text: str) -> bool:
    return any(re.fullmatch(p, text) for p in patterns)


@dataclass
class Result:
    name: str
    status: str  # PASS, FAIL or NOT RUN
    seconds: float
    detail: str = ""


def _tool(name: str) -> str | None:
    """``python`` is this interpreter; a venv tool is the one beside it, else the PATH's.
    ``None`` when the tool is in neither place: the gate is then NOT RUN, not a crash."""
    if name == "python":
        return sys.executable
    beside = Path(sys.executable).parent / name
    if beside.exists():
        return str(beside)
    return shutil.which(name)


def _env(extra: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    paths = [str(ROOT / "src"), str(SCRIPTS)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.update(extra)
    return env


def _git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def base_is_commit(base: str) -> bool:
    """``base`` names a commit in this clone (nothing here fetches it)."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def dirty_paths(root: Path = ROOT) -> list[str]:
    """Uncommitted and untracked paths: CI sees only commits, so these are checked here as
    they are on disk and may not be what CI checks."""
    out = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def check_subjects(base: str) -> tuple[bool, str]:
    """Every non-merge commit subject in ``base..HEAD``, by the commit-subjects rule."""
    findings = [
        f"{sha}: {problem} — {subject}"
        for sha, subject in ccs.subjects_in_range(ROOT, f"{base}..HEAD")
        for problem in ccs.check_subject(subject)
    ]
    return not findings, "\n".join(findings)


def check_title(title: str, pr_number: int | None) -> tuple[bool, str]:
    """``title`` as the squash merge writes it on ``main``, by the commit-subjects rule."""
    subject = ccs.squash_subject(title, pr_number)
    problems = ccs.check_subject(subject)
    return not problems, "\n".join(f"{p} — {subject}" for p in problems)


def changed_files(base: str) -> list[str]:
    """Files this branch changes against ``base``: committed, staged, unstaged, untracked.

    Deleted paths are kept (``tests_for`` maps a deleted source to its tests), and a rename
    is read as its old and its new path (``--no-renames``), so the old name's tests run."""
    names: set[str] = set()
    names.update(_git("diff", "--name-only", "--no-renames", f"{base}...HEAD"))
    names.update(_git("diff", "--name-only", "--no-renames", "HEAD"))
    names.update(_git("ls-files", "--others", "--exclude-standard"))
    return sorted(names)


#: Where the tracked git hooks live, from the root; ``--install-hook`` points git at it.
HOOKS_DIR = "scripts/hooks"
#: The title the hook checks, when the author has one before the pull request exists.
TITLE_ENV = "CRB_PR_TITLE"


def tests_for(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    """The test files that cover ``paths``, and a note for each path no test file maps from.

    A test file is its own test; any other file is covered by the ``tests/*.py`` its header's
    ``Tested by`` names (scripts/code_map.py reads the header) and by ``tests/test_<stem>.py``
    when that exists; a git hook under ``scripts/hooks`` has no header and is covered by
    ``tests/test_pre_push.py``. A deleted path has no header to read: a deleted test file is not run,
    and a deleted source maps to ``tests/test_<stem>.py`` alone."""
    found: set[str] = set()
    notes: list[str] = []
    for rel in paths:
        path = ROOT / rel
        exists = path.is_file()
        if rel.startswith("tests/") and Path(rel).name.startswith("test_") and rel.endswith(".py"):
            if exists:
                found.add(rel)
            else:
                notes.append(f"{rel} is deleted: there is nothing of it to run")
            continue
        if rel.startswith("tests/") and rel.endswith(".py"):
            notes.append(f"{rel} is shared test code: only the full run covers what uses it")
            continue
        named: set[str] = set()
        if exists and path.suffix in (".py", ".ts", ".tsx", ".sh"):
            tested_by = code_map.read_header(path).fields.get("Tested by", "")
            named.update(re.findall(r"tests/[\w/.-]+?\.py", tested_by))
        guess = f"tests/test_{path.stem}.py"
        if (ROOT / guess).is_file():
            named.add(guess)
        if rel.startswith(f"{HOOKS_DIR}/"):
            named.add("tests/test_pre_push.py")
        mapped = {n for n in named if (ROOT / n).is_file()}
        if not mapped:
            notes.append(f"{rel} maps to no test: only the ratchets and the full run read it")
        found.update(mapped)
    return sorted(found), notes


def _substitute(text: str, base: str, floor: str) -> str:
    return text.replace("{base}", base).replace("{floor}", floor)


def run_gate(gate: Gate, base: str, floor: str, argv: Sequence[str] | None = None) -> Result:
    if gate.requires and not (ROOT / gate.requires).exists():
        return Result(gate.name, "NOT RUN", 0.0, f"{gate.requires} is missing (npm ci)")
    words = [_substitute(w, base, floor) for w in (argv or gate.argv)]
    tool = _tool(words[0])
    if tool is None:
        return Result(gate.name, "NOT RUN", 0.0, f"{words[0]} is not installed here")
    words[0] = tool
    env = _env({k: _substitute(v, base, floor) for k, v in gate.env.items()})
    started = time.monotonic()
    proc = subprocess.run(
        words,
        cwd=ROOT / gate.cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=not gate.stream,
        text=True,
        check=False,
    )
    seconds = time.monotonic() - started
    if proc.returncode == 0:
        return Result(gate.name, "PASS", seconds)
    tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-60:])
    return Result(gate.name, "FAIL", seconds, f"exit {proc.returncode}\n{tail}".rstrip())


def _in_process(name: str, check: Callable[[], tuple[bool, str]]) -> Result:
    started = time.monotonic()
    ok, detail = check()
    return Result(name, "PASS" if ok else "FAIL", time.monotonic() - started, detail)


def not_run_here() -> list[str]:
    """Every CI check this script does not run, one line each."""
    lines = [f"job {job}: {why}" for job, why in UNCOVERED_JOBS.items()]
    steps = dict.fromkeys((job, why) for job, _, why in UNCOVERED_STEPS)  # one line per reason
    lines += [f"step in {job}: {why}" for job, why in steps]
    lines.append(
        "tests marked docker / toolchain / network skip here when the tool is absent; CI "
        "(CRB_TEST_REQUIRE_TOOLS, CRB_TEST_STRICT_WARMUP) fails them instead — read pytest's "
        "skipped count"
    )
    here = f"{sys.version_info.major}.{sys.version_info.minor}"
    lines.append(
        f"CI runs the suite on Python 3.12 and 3.13; this run used one interpreter, Python {here}"
    )
    lines.append(
        "CI runs each shard's files in its own process, so a test that depends on the order "
        "of the tests before it can pass here and fail there, or the reverse"
    )
    return lines


def _git_out(root: Path, *args: str) -> str:
    """One git answer from ``root``, stripped; empty when git says no (an unset key)."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def hooks_path(root: Path = ROOT) -> str:
    """``core.hooksPath`` as git resolves it for ``root``, from any scope; empty when unset."""
    return _git_out(root, "config", "--type=path", "--get", "core.hooksPath")


def hook_installed(root: Path = ROOT) -> bool:
    """git runs this checkout's ``scripts/hooks`` on a push from ``root``."""
    configured = hooks_path(root)
    return bool(configured) and (root / configured).resolve() == (root / HOOKS_DIR).resolve()


def install_hook(root: Path = ROOT) -> tuple[bool, str]:
    """Point ``root``'s clone at ``scripts/hooks``. Refuses, changing nothing, when that would
    switch off hooks the clone already runs: a ``core.hooksPath`` set elsewhere, or a live
    hook in the clone's own hooks folder (git reads one folder only)."""
    hook = root / HOOKS_DIR / "pre-push"
    if not os.access(hook, os.X_OK):
        return False, f"{HOOKS_DIR}/pre-push is missing or not executable in {root}"
    if hook_installed(root):
        return True, f"already installed: core.hooksPath is {HOOKS_DIR}"
    configured = hooks_path(root)
    if configured:
        return False, (
            f"core.hooksPath is already {configured}; git reads one hooks folder, so add a "
            f"pre-push there that runs {HOOKS_DIR}/pre-push, or unset it and run this again"
        )
    common = _git_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return False, f"{root} is not a git checkout"
    folder = Path(common) / "hooks"
    live = (
        sorted(f.name for f in folder.iterdir() if f.is_file() and f.suffix != ".sample")
        if folder.is_dir()
        else []
    )
    if live:
        return False, (
            f"{folder} holds live hooks ({', '.join(live)}) that core.hooksPath would switch "
            f"off; move them into {HOOKS_DIR} or remove them, then run this again"
        )
    subprocess.run(
        ["git", "-C", str(root), "config", "--local", "core.hooksPath", HOOKS_DIR], check=True
    )
    return True, f"installed: core.hooksPath is {HOOKS_DIR}; every git push now runs --hook"


def pushed_shas(stdin_text: str) -> list[str]:
    """The commits a push sends, from the lines git hands a pre-push hook
    (``<local ref> <local sha> <remote ref> <remote sha>``). A deleted ref has an all-zero
    local sha and sends nothing."""
    shas = []
    for line in stdin_text.splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[1].strip("0"):
            shas.append(fields[1])
    return shas


def hook_tolerates(gate: Gate, changed: Sequence[str]) -> bool:
    """In the hook a gate NOT RUN stops the push unless the push changes nothing the gate
    reads: the title gate with no title known, or a gate that needs a path missing here when
    no changed file is under its own folder or a folder it ``reads``."""
    if gate.argv == ("<title>",):
        return True
    if gate.requires and gate.cwd != "." and not (ROOT / gate.requires).exists():
        folders = (gate.cwd, *gate.reads)
        return not any(path.startswith(f"{folder}/") for path in changed for folder in folders)
    return False


def not_checked_out(shas: Sequence[str], root: Path = ROOT) -> list[str]:
    """The pushed objects that are not ``root``'s ``HEAD`` commit. An annotated tag is read
    as the commit it names; one git cannot resolve is kept, since nothing here checked it."""
    head = _git_out(root, "rev-parse", "HEAD")
    return [s for s in shas if _git_out(root, "rev-parse", f"{s}^{{commit}}") != head or not head]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--title", default=None, help="the pull request's title, checked as CI will")
    ap.add_argument("--pr-number", type=int, default=None, help="its number, once it has one")
    ap.add_argument(
        "--base",
        default="origin/main",
        help="the branch the pull request targets; nothing here fetches it, so a stale base "
        "widens the range checked (run `git fetch origin main` first)",
    )
    ap.add_argument(
        "--fast",
        action="store_true",
        help="every static gate, then only the changed files' tests and the ratchets",
    )
    ap.add_argument("--list", action="store_true", help="print the gates and what is not run")
    ap.add_argument(
        "--allow-skip",
        action="store_true",
        help="exit 0 when a gate was NOT RUN here (by default that exits 3)",
    )
    ap.add_argument(
        "--install-hook",
        action="store_true",
        help=f"once per clone: point core.hooksPath at {HOOKS_DIR} so every git push runs --hook",
    )
    ap.add_argument(
        "--hook",
        action="store_true",
        help=f"the run {HOOKS_DIR}/pre-push makes: --fast on what git says the push sends "
        f"(stdin), the title from {TITLE_ENV}; a gate not run stops the push",
    )
    args = ap.parse_args(argv)
    if args.install_hook:
        ok, message = install_hook()
        print(f"pre_push: {message}", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.hook:
        shas = pushed_shas(sys.stdin.read())
        if not shas:
            print("pre_push: this push sends no commit (no ref, or deletions only); no gate runs")
            return 0
        other = not_checked_out(shas)
        if other:
            print(
                "pre_push: exit 3 — the push is stopped: it sends "
                f"{', '.join(sha[:12] for sha in other)}, which is not this checkout's HEAD, "
                "and the gates can only check what is checked out. Check that ref out (a "
                "worktree will do) and push it from there, one ref at a time.",
                file=sys.stderr,
            )
            return 3
        unpushed = dirty_paths()
        if unpushed:
            print(
                "pre_push: exit 3 — the push is stopped: the gates read the files on disk, and "
                f"{len(unpushed)} uncommitted or untracked path(s) here are not in the commit "
                "the push sends, so a pass would not be a pass of that commit. Commit them, or "
                "`git stash --include-untracked`, then push again:",
                file=sys.stderr,
            )
            for path in unpushed:
                print(f"  {path}", file=sys.stderr)
            return 3
        args.fast = True
        args.title = args.title or os.environ.get(TITLE_ENV) or None
    if not args.list and not base_is_commit(args.base):
        print(
            f"pre_push: --base {args.base} is not a commit in this clone; run "
            "`git fetch origin main` (nothing here fetches)",
            file=sys.stderr,
        )
        return 2
    floor = _floor()

    if not args.list and not args.hook and not hook_installed():
        print(
            "pre_push: the git hook is not installed in this clone, so a push can leave "
            "without this run; `python scripts/pre_push.py --install-hook` installs it",
            flush=True,
        )

    if args.list:
        for gate in GATES:
            print(f"gate     {gate.name}")
        for line in not_run_here():
            print(f"not run  {line}")
        return 0

    dirty = dirty_paths()
    if dirty:
        print("pre_push: WARNING — CI sees only commits; these uncommitted or untracked paths are")
        print("pre_push: checked here as they are on disk:", flush=True)
        for path in dirty:
            print(f"  {path}", flush=True)

    results: list[Result] = []
    for gate in GATES:
        if gate.argv == ("<subjects>",):
            result = _in_process(gate.name, lambda: check_subjects(args.base))
        elif gate.argv == ("<title>",):
            if args.title is None:
                result = Result(gate.name, "NOT RUN", 0.0, "pass --title to check it")
            else:
                check = functools.partial(check_title, args.title, args.pr_number)
                result = _in_process(gate.name, check)
        elif gate.stream and args.fast:
            tests, notes = tests_for(changed_files(args.base))
            for note in notes:
                print(f"pre_push: {note}", flush=True)
            chosen = sorted(set(tests) | {t for t in RATCHET_TESTS if (ROOT / t).is_file()})
            print(f"pre_push: --fast runs {len(chosen)} test files: {' '.join(chosen)}", flush=True)
            fast = ("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", SUITE_MARKER)
            result = run_gate(gate, args.base, floor, argv=(*fast, *chosen))
            result.name = "pytest --fast: changed files' tests + ratchets (test-shard)"
        else:
            print(f"pre_push: {gate.name} …", flush=True)
            result = run_gate(gate, args.base, floor)
        results.append(result)
        if result.status == "FAIL" and result.detail:
            print(f"--- {result.name}\n{result.detail}\n---", flush=True)

    print("\npre_push summary")
    for r in results:
        why = f" — {r.detail.splitlines()[0]}" if r.status != "PASS" and r.detail else ""
        print(f"  {r.status:<7} {r.name} ({r.seconds:.1f}s){why}")
    print("\nCI runs these too; this script did not:")
    for line in not_run_here():
        print(f"  - {line}")
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "FAIL", "NOT RUN")}
    passed, failed, skipped = counts["PASS"], counts["FAIL"], counts["NOT RUN"]
    mode = " (--fast)" if args.fast else ""
    print(f"\n{passed} passed, {failed} failed, {skipped} not run{mode}")
    if failed:
        return 1
    if args.hook:
        changed = changed_files(args.base)
        stops = [
            r.name
            for gate, r in zip(GATES, results, strict=True)
            if r.status == "NOT RUN" and not hook_tolerates(gate, changed)
        ]
        if stops:
            print(f"pre_push: exit 3 — the push is stopped; not run here: {'; '.join(stops)}")
            return 3
        return 0
    if skipped and not args.allow_skip:
        print(f"pre_push: exit 3 — {skipped} gate(s) not run here; --allow-skip accepts that")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
