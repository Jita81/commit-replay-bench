"""Grade one build worktree under the five belts, then score its oracle by mutation.

Usage: python grade.py <worktree> <module.py> <tests/test_x.py> <base-ref>
Belts mirror crb's (README "The belts"): tests_unmodified, target_green, no_new_failures,
source_changed, repo_lint_clean. Mutants come from crb.core.oracle.mutation.generate_mutants
over every line of the built module; each is run against the target test file only.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from crb.core.oracle.mutation import generate_mutants

VENV = "/home/user/commit-replay-bench/.venv/bin"


ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def run(cmd, cwd):
    # no bytecode: a mutant written within the same second as the original can otherwise
    # be served from a stale .pyc (crb's scorer guards this with _next_tick)
    for d in Path(cwd).rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300, env=ENV)


def failing(cwd, target=None):
    args = [f"{VENV}/python", "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider"]
    r = run([*args, target] if target else args, cwd)
    fails = {ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("FAILED")}
    return r.returncode, fails


def main(wt, module, target, base):
    wt = Path(wt)
    changed = run(["git", "diff", "--name-only", base], wt).stdout.split()
    untracked = run(["git", "ls-files", "--others", "--exclude-standard"], wt).stdout.split()
    # compiled files are build output, not edits (the skeleton had no .gitignore)
    touched = sorted(t for t in set(changed + untracked) if "__pycache__" not in t)
    test_shas_now = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wt / "tests").glob("*.py")
    }
    test_shas_base = {}
    for name in test_shas_now:
        blob = run(["git", "show", f"{base}:tests/{name}"], wt).stdout.encode()
        test_shas_base[name] = hashlib.sha256(blob).hexdigest()
    rc_t, _ = failing(wt, target)
    _, fails_all = failing(wt)
    other_red_at_base = {"test_identity", "test_phrase", "test_coverage", "test_gaps", "test_planner"}
    target_stem = Path(target).stem
    new_fail = {f for f in fails_all if f.split("::")[0].split("/")[-1][:-3] not in other_red_at_base - {target_stem} }
    lint_files = [t for t in touched if t.endswith(".py")]
    lint = run([f"{VENV}/ruff", "check", *lint_files], wt).returncode == 0 and run(
        [f"{VENV}/ruff", "format", "--check", *lint_files], wt
    ).returncode == 0
    belts = {
        "tests_unmodified": test_shas_now == test_shas_base and not any(t.startswith("tests/") for t in touched),
        "target_green": rc_t == 0,
        "no_new_failures": not new_fail,
        "source_changed": any(t.startswith("mandate/") for t in touched),
        "repo_lint_clean": bool(lint_files) and lint,
    }
    src_path = wt / module
    src = src_path.read_text()
    mutants = generate_mutants(src, set(range(1, src.count("\n") + 2)), max_mutants=40, path=module)
    killed = 0
    for m in mutants:
        src_path.write_text(m.mutated_source)
        rc, _ = failing(wt, target)
        killed += rc != 0
    src_path.write_text(src)
    print(json.dumps({
        "worktree": wt.name, "touched": touched, "belts": belts, "clean": all(belts.values()),
        "mutants": len(mutants), "killed": killed,
        "strength": round(killed / len(mutants), 3) if mutants else None,
    }))


if __name__ == "__main__":
    main(*sys.argv[1:])
