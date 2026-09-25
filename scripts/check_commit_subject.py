#!/usr/bin/env python3
"""The commit-subject gate — Conventional Commits, an imperative subject, at most 72 characters.

``docs/CONTRIBUTING.md`` ("Commit convention") has long required ``type(scope): subject`` with
the subject in the imperative and at most 72 characters. Until this script that was prose, and
the pull request titles that a squash merge writes as the subject on ``main`` ran past 100
characters and read as descriptions ("the work arrives from the board …"). This is the gate.

    python scripts/check_commit_subject.py --range BASE..HEAD           # report
    python scripts/check_commit_subject.py --range BASE..HEAD --check   # CI: exit 1 on a finding
    python scripts/check_commit_subject.py --title "docs: add x" --check

``--range`` reads every non-merge commit in the range (a merge commit made by "Update branch"
is not the author's subject); ``--title`` checks a pull request title, because a squash merge
turns it into the commit subject on ``main``.

**The imperative heuristic, honestly.** English has no reliable marker for the imperative, so
the gate refuses the four shapes that are reliably *not* imperative: a first word that is an
article or a determiner ("the", "a", "every"), a past tense ending in ``-ed`` ("fixed"), a
gerund ending in ``-ing`` ("fixing") and a third-person verb ending in ``-s`` ("fixes"), with
short allowlists for real imperatives that happen to end that way ("embed", "bring",
"address", "focus"). It will pass a subject whose first word is a noun ("readme updates") —
a reviewer still has to read.

Navigation
----------
What it is:   The commit-subject gate (stdlib only; CI's ``commit-subjects`` job).
What it does: Checks each subject against Conventional Commits (a known type, an optional
              scope, an optional ``!``, a description), a 72-character limit on the whole
              line, and the imperative heuristic; reports each defect with its reason;
              ``--check`` exits non-zero on any finding.
How:          ``git log --no-merges --format=%H%x00%s`` over ``--range`` (in ``--repo``) plus
              the optional ``--title`` → ``check_subject`` on each → one line per finding.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/CONTRIBUTING.md (the commit convention it enforces),
              .github/workflows/ci.yml (the commit-subjects job that runs --check on a pull
              request's commits and its title), scripts/claims_check.py (the same gate idiom)
Tested by:    tests/test_check_commit_subject.py
Touch when:   a Conventional Commits type is added to the convention (update TYPES and
              docs/CONTRIBUTING.md together); a real imperative is refused (add it to the
              matching allowlist with a test case).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The types docs/CONTRIBUTING.md names, plus the standard ones Dependabot and reverts use.
TYPES: tuple[str, ...] = (
    "feat",
    "fix",
    "docs",
    "ci",
    "test",
    "refactor",
    "chore",
    "perf",
    "build",
    "style",
    "revert",
)
MAX_LEN = 72

_SHAPE_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^()\s]+)\))?(?P<bang>!)?: (?P<desc>\S.*)$"
)

#: First words that start a description, never an instruction.
NOT_A_VERB: frozenset[str] = frozenset(
    {"a", "an", "the", "this", "these", "that", "those", "its", "our", "every", "each", "all"}
)
#: Imperatives that end in the suffixes the heuristic reads as another tense.
ENDS_ED_OK: frozenset[str] = frozenset({"embed", "shed", "shred"})
ENDS_ING_OK: frozenset[str] = frozenset({"bring", "ring", "sing", "spring", "string", "swing"})
ENDS_S_OK: frozenset[str] = frozenset({"alias", "bias"})


def _not_imperative(word: str) -> bool:
    w = word.lower().strip("`'\"")
    if w in NOT_A_VERB:
        return True
    if w.endswith("ed") and not w.endswith("eed") and w not in ENDS_ED_OK and len(w) > 3:
        return True
    if w.endswith("ing") and w not in ENDS_ING_OK and len(w) > 4:
        return True
    return (
        w.endswith("s")
        and not w.endswith(("ss", "us"))
        and w not in ENDS_S_OK
        and len(w) > 3
        and w.isalpha()
    )


def check_subject(subject: str) -> list[str]:
    """Every defect in one subject line; ``[]`` when it passes."""
    line = subject.splitlines()[0] if subject else ""
    problems: list[str] = []
    if len(line) > MAX_LEN:
        problems.append(f"longer than {MAX_LEN} characters ({len(line)})")
    m = _SHAPE_RE.match(line)
    if m is None:
        problems.append("not a Conventional Commits subject: expected `type(scope): subject`")
        return problems
    if m.group("type") not in TYPES:
        problems.append(f"unknown type {m.group('type')!r}: use one of {', '.join(TYPES)}")
    first = m.group("desc").split()[0]
    if _not_imperative(first):
        problems.append(
            f"not imperative: the subject starts with {first!r}; write it as an instruction "
            "(“add”, “fix”, “refuse”)"
        )
    return problems


def subjects_in_range(repo: Path, rev_range: str) -> list[tuple[str, str]]:
    """``(short sha, subject)`` for every non-merge commit in ``rev_range``, oldest first."""
    out = subprocess.run(
        ["git", "-C", str(repo), "log", "--no-merges", "--reverse", "--format=%H%x00%s", rev_range],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pairs: list[tuple[str, str]] = []
    for row in out.splitlines():
        sha, _, subject = row.partition("\x00")
        if sha:
            pairs.append((sha[:10], subject))
    return pairs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--range", dest="rev_range", default=None, help="a git range, BASE..HEAD")
    ap.add_argument("--title", default=None, help="a pull request title (the squash subject)")
    ap.add_argument("--repo", default=str(ROOT), help="the repository --range is read from")
    ap.add_argument("--check", action="store_true", help="exit non-zero on any finding (CI)")
    args = ap.parse_args(argv)
    items: list[tuple[str, str]] = []
    if args.rev_range:
        items.extend(subjects_in_range(Path(args.repo), args.rev_range))
    if args.title is not None:
        items.append(("title", args.title))
    stream = sys.stderr if args.check else sys.stdout
    findings = 0
    for where, subject in items:
        for problem in check_subject(subject):
            findings += 1
            print(f"{where}: {problem} — {subject}", file=stream)
    print(f"{findings} finding(s) across {len(items)} subject(s)", file=stream)
    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
