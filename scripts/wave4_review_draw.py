#!/usr/bin/env python3
"""Wave 4's review draw: Amendment 3 Part B (B1-B3, readings R6-R10), after the read's order check.

    python scripts/wave4_review_draw.py --poster-dir DIR --login FILE --api URL \\
        --campaign cmp_88cf9e875edba15371e6d3f7 --key-out FILE --audit-out FILE --output FILE

The registration is ``docs/reviews/2026-11-10-wave-4-registration.md``, Amendment 3 Part B: the
ten patches per repository and arm (B2 items 1-4, R6, R7), Paul's audit (B3 items 1-3, R8,
R9) and the hash strings (R10). "The rows of A2" are the rows of the 48 standing runs
(Amendment 3 A2); attempt 1 of an arm in a batch is the row from the first-filed of that arm's
two runs, by the read's place (test (d): rank by filing time), attempt 2 the other (B2 item 1).

B1: the draw is run only after the primary is read and signed. B1 cannot be checked by this
script: the delivery manager confirms in writing that the read was signed before running it.
The script computes no figure of the primary read (no difference, no test, no interval, no
decision word, no usable-test count) and reads no event.

The readings this script applies (ruling Q2: Paul's audit file; Q3: B2 item 3's step counts;
Q4: clean for the draw) were signed by the methodologist on 2026-11-12, after the primary read
and before any draw existed, and are recorded in
``docs/reviews/2026-11-10-wave-4-registration/wave-record-notes.md``.

Everything that decides which rows exist and which arm a run is comes from the read script
``scripts/wave4_primary_read.py``, imported as a module and not changed: the recorded constants
(``RECORDED``), the hashing and parsing of the four poster files (T1-T3), the campaign record,
the run records, the full order check (``run_order_check``: T2-T5, (a)-(h), section 4, the
campaign's ``s1`` flags), the arm of each run (test (e), from the run body), the place of each
run (test (d)), the rows (``keep_row``), strict JSON, the getter and the login handling. The
order check must pass again before any row is read; on a failure this script prints counts only
(no run id, no time) and exits 2.

Clean for the draw (ruling Q4): a row is clean only when its ``clean`` field is ``true`` (A3:
"Clean is read from the row's own field ... Nobody re-grades a row") AND it carries no error. A
null or empty-string ``error`` means no error; any other value is an error. A row whose
``error`` field is absent altogether stops the draw (exit 4, counts only). A run that did not
return exactly its five rows (``ROWS_PER_RUN``, test (a)'s ``counts.rows``) stops the draw
(exit 4, counts only): the order check holds the run record's count, not the rows fetched
after it. Rows whose ``clean`` is true but which carry an error are not drawn; the key file counts
them per repository and arm and in total, and the blinded output prints only the wave-wide
total.

Reviewer labels. The labels ``click-01``, ``click-02``, ..., ``cobra-01``, ... and the order of
the reviewer's list come from a secret salt (``sha256("crb.wave4.reviewer|" + salt + "|" + R +
"|" + A + "|" + commit + "|" + attempt)``, ascending), never from the public audit hash of B3: a
list in B3 order would let anyone hash the four (arm, attempt) candidates of each listed commit
and read most arms off the label order. B3's audit order is kept exactly, in the key file only.

What the outputs still let a reader guess. The script itself adds no arm information: the
labels and the audit file's order are salted. A residual leak remains from the registered B3
hash, which is public and includes the arm: membership of Paul's set, read with the commits,
lets a reader guess arms better than chance, and the filed list lets a reader guess the audit
set better than chance. This is recorded in the wave record and cannot be removed without
changing B3.

Paul's ten (B3 item 1, R8): the first five of each repository in the audit order, computed
exactly as registered. B3 item 1 orders "reviewed patches"; this script orders the drawn
patches, before the review. That is the same list only if every drawn patch is reviewed; if one
is not, the audit order is recomputed over the reviewed patches and the change is recorded.

Three outputs, all new files (0600, refused if they exist, created before any request):
``--key-out`` (the keyed list, NOT for the reviewer, NOT for Paul before his verdicts, R9):
the reviewer salt and the audit-file salt; one line per patch with its label, repository, arm,
commit, attempt, run id, step and B3 audit position; per repository and arm, the step counts
and shortfall of B2 item 3 and the clean rows that carry an error, then their total; the B3
sequence (click 1, cobra 1, click 2, ...) with reviewer label, repository, arm, commit and
attempt. ``--audit-out`` (Paul's file, NOT for the reviewer, ruling Q2): his ten patches as
reviewer label, repository and commit, in a salted order (ascending ``sha256(
"crb.wave4.auditfile|" + audit-file salt + "|" + label)``; that salt is in the key file only),
with no B3 order, position, arm, attempt, run id or step; all ten are to be checked, each given
a verdict before he is told the arm or the reviewer's verdict. ``--output`` (the blinded list,
for the reviewer and for filing): one line per patch with its label, repository and commit
only, in label order; the sha256 of that list's own lines (B2 item 4: "The drawn list and its
sha256 are filed"); the sha256 of the key file and of the audit file; the wave-wide total of
clean rows that carry an error; the totals per repository. stdout is ``--output`` byte for byte
(the read's ``Out``: each line is written and flushed to the file before it is printed);
once the ``--output`` file itself fails, the lines after it go to stdout alone. The key and
audit files are written, flushed, fsynced and closed, and their sha256 taken, before the first
line of the list is printed, so a failure on either shows the reviewer nothing. Nothing that
names an arm, an attempt, a run id or the audit set is ever printed.

B2 item 3's per-(repository, arm) step counts ("The report prints, for each repository and arm,
how many patches each of the three steps gave") are held in the key file (ruling Q3). "The
report" is the wave report: it prints them after the review, from the key file bound by its
sha256 on the filed list. They are not printed here, because by arm they would tell a reader of
the filed list how many patches each arm gave.

Exit codes: 0 the draw was made; 1 not ready (a recorded constant, an argument or the login
file is not as expected, an output file exists, or a module other than ``READ_PATH`` is loaded
as the read), no request made; 2 the order check failed (counts only); 4 the draw was not
made (a row request failed, or the rows are not as the run records state: the read's added
integrity stop, a run without exactly five rows, or a row with no ``error`` field (ruling
Q4); counts only; or an unexpected error before any salt was made, named by its class only,
when the ``--output`` file then takes the exit lines); 5 the
``--output``, ``--key-out`` or ``--audit-out`` file could not be written or closed after it
was opened (on the way out of an unexpected error too), or an unexpected error came after a
salt was made. Every exit 5, and the exit 4 on an unexpected error, ends with one fixed line,
said once: before any salt, ``NO_SALT`` (a later run is the first draw); after one,
``DO_NOT_RERUN`` (a key file may exist that no filed output binds; a second run would make
different labels; escalate to the delivery manager). A broken stdout does not change the code.

Navigation
----------
What it is:   The one script that draws Wave 4's blinded review sample and Paul's audit set:
              Amendment 3 Part B, B2 items 1-4 and B3 items 1-3, with readings R6-R10.
What it does: Runs the read's order check again (T1-T5, (a)-(h), section 4); on a pass reads
              the 48 standing runs' ledger rows, draws up to ten clean patches per repository
              and arm in the three steps of B2 item 3, orders each repository's patches by the
              audit hash of B3, labels them for the reviewer from a secret salt, writes the
              keyed list to ``--key-out`` and Paul's ten, in a salted order, to ``--audit-out``,
              and prints the blinded list with its own sha256 and the sha256 of both files.
How:          Standard library only. The rule itself is the pure ``draw`` over plain rows
              (repository, commit, arm, attempt, clean). All I/O goes through injected
              callables (``read_file``, ``open_getter``, ``open_output``, ``open_key``,
              ``open_audit``, ``path_exists``, ``make_salt``, ``sync``); the getter is the
              read's (urllib, no redirect, no retry).
Layer:        tooling — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/wave4_primary_read.py (the order check, arms, rows and constants it
              reuses), docs/reviews/2026-11-10-wave-4-registration.md (Amendment 3 Part B),
              docs/reviews/2026-11-10-wave-4-registration/wave-record-notes.md (the signed
              readings Q2-Q4 it applies)
Tested by:    tests/test_wave4_review_draw.py
Touch when:   never for a new repository; Wave 4's registration changes the review draw or
              the audit rule of Amendment 3 Part B (a new commit, before the draw is run).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import os
import secrets
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

# ---------------------------------------------------------------------------
# the read script, imported (never edited)
# ---------------------------------------------------------------------------

READ_NAME = "wave4_primary_read"
READ_PATH = Path(__file__).resolve().parent / f"{READ_NAME}.py"


class ReadModuleError(ImportError):
    """A module named ``wave4_primary_read`` is loaded, but not from ``READ_PATH``."""


def _load_read() -> ModuleType:
    """The read script as a module. A copy already loaded under its own name (by a test or
    by an earlier import) is reused, so constants patched on it are the ones used here, but
    only when it was loaded from ``READ_PATH``: the sha256 printed as "(imported)" is of that
    file, so it must be the code that makes the order check and gives the arms."""
    loaded = sys.modules.get(READ_NAME)
    if loaded is not None:
        origin = getattr(loaded, "__file__", None)
        if not (isinstance(origin, str) and Path(origin).resolve() == READ_PATH):
            raise ReadModuleError(f"{READ_NAME} is loaded from another file, not {READ_PATH}")
        return loaded
    spec = importlib.util.spec_from_file_location(READ_NAME, READ_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[READ_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


R: Any = _load_read()

# ---------------------------------------------------------------------------
# registered constants (Amendment 3 Part B)
# ---------------------------------------------------------------------------

SCRIPT_NAME = "wave4_review_draw"
#: B2 item 2 and R10: the review order's hash string prefix.
REVIEW_PREFIX = "crb.wave4.review|20261112|"
#: B3 item 1 and R10: the audit order's hash string prefix.
AUDIT_PREFIX = "crb.wave4.audit|20261112|"
#: The reviewer labels' hash string prefix; the salt that follows it is secret (key file).
REVIEWER_PREFIX = "crb.wave4.reviewer|"
ARMS: tuple[str, ...] = ("A0", "S1")
ATTEMPTS: tuple[int, ...] = (1, 2)
PER_ARM = 10  # "Ten clean patches per arm per repository" (part 6 item 8)
AUDIT_PER_REPO = 5  # R8: five per repository, ten in all
STEPS: tuple[int, ...] = (1, 2, 3)

ORDER_FAIL_FOOTER = (
    "No row was read and no draw is made. The read prints the order check's failures in "
    "full; this script prints counts only."
)
#: The last line of every exit 5 (and of an unexpected exit 4) before any salt was made.
NO_SALT = "no salt was made; a later run is the first draw"
#: The last line of every exit after a salt was made.
DO_NOT_RERUN = (
    "salts were made; a key file may exist at --key-out that no filed output binds; "
    "DO NOT RERUN; escalate to the delivery manager; a second run would make different labels"
)
#: Exit 5 on the ``--output`` file, by how far the list had got.
OUTPUT_NOT_WRITTEN = "output file could not be written or closed (--output); no list was printed"
OUTPUT_PART_OF_LIST = (
    "output file could not be written (--output); the output file and stdout hold only part "
    "of the list"
)
OUTPUT_NOT_CLOSED = (
    "output file could not be closed (--output); the output file may be incomplete; stdout "
    "holds the full list"
)
#: Exit 5 on the key or audit file; both are closed before any line of the list is printed.
KEY_NOT_WRITTEN = (
    "key file could not be written, synced or closed (--key-out); no line of the list was printed"
)
AUDIT_NOT_WRITTEN = (
    "audit file could not be written, synced or closed (--audit-out); no line of the list was "
    "printed"
)
#: An exception nobody expected: its class only, no message text, no row data.
UNEXPECTED = "draw stopped: unexpected error ({cls})"
ROW_COUNT_BAD = "draw not made: runs that did not return exactly {per} rows: {n}"
#: Test (a) of the read holds each standing run record's ``counts.rows`` to 5 (a literal
#: there, no named constant); the rows fetched afterwards are held to the same number here.
ROWS_PER_RUN = 5
STEP_COUNTS_NOTE = (
    "B2 item 3 counts by repository and arm: in the key file; the wave report prints them after "
    "the review, from the key file bound by its sha256 on this list."
)
#: The blinded output's one line on clean rows that carry an error (ruling Q4): the wave-wide
#: total only, no split by repository or arm.
WITH_ERROR_TOTAL = "clean rows that carry an error (not drawn), wave-wide total: {n}"
NO_ERROR_FIELD = "draw not made: rows with no error field (ruling Q4): {n}"
#: Ruling Q2: the salted order of Paul's audit file; the salt is in the key file only.
AUDIT_FILE_PREFIX = "crb.wave4.auditfile|"

# ---------------------------------------------------------------------------
# the rule (pure): B2 items 2-3, R6, R7; B3 items 1-3, R8
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlainRow:
    """One row of A2 as the draw sees it. ``clean`` is already the draw's verdict (ruling
    Q4): True only when the row's ``clean`` field is true and it carries no error (``error``
    null or empty). A missing row is simply not given; a row with ``clean`` true and an error,
    or with ``clean`` false, is given with ``clean`` False."""

    repo: str
    commit: str
    arm: str
    attempt: int
    clean: bool


@dataclass(frozen=True)
class Patch:
    repo: str
    arm: str
    commit: str
    attempt: int
    step: int


@dataclass(frozen=True)
class Cell:
    """The draw for one repository and arm."""

    repo: str
    arm: str
    patches: tuple[Patch, ...]

    def step_count(self, step: int) -> int:
        return sum(1 for p in self.patches if p.step == step)

    @property
    def shortfall(self) -> int:
        return PER_ARM - len(self.patches)


@dataclass(frozen=True)
class Labelled:
    label: str
    patch: Patch


@dataclass(frozen=True)
class Draw:
    repos: tuple[str, ...]
    cells: Mapping[tuple[str, str], Cell]
    #: Each repository's patches in the audit order of B3 item 1 (public; never the
    #: reviewer's order).
    ordered: Mapping[str, tuple[Patch, ...]]
    #: B3 item 3: click 1, cobra 1, click 2, ... up to five per repository.
    audit: tuple[Patch, ...]

    def repo_total(self, repo: str) -> int:
        return len(self.ordered[repo])

    def audit_shortfall(self) -> int:
        return AUDIT_PER_REPO * len(self.repos) - len(self.audit)


def sha256_hex(text: str) -> str:
    """R10: the sha256 of the string's UTF-8 bytes, as lower-case hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def review_key(repo: str, commit: str) -> str:
    return sha256_hex(REVIEW_PREFIX + repo + "|" + commit)


def review_order(repo: str, commits: Iterable[str]) -> list[str]:
    """B2 item 2: ascending ``sha256("crb.wave4.review|20261112|" + R + "|" + commit)``,
    ties by commit. One order serves both arms (R7)."""
    return sorted(set(commits), key=lambda c: (review_key(repo, c), c))


def audit_key(p: Patch) -> str:
    return sha256_hex(f"{AUDIT_PREFIX}{p.repo}|{p.arm}|{p.commit}|{p.attempt}")


def audit_order(patches: Iterable[Patch]) -> list[Patch]:
    """B3 item 1: ascending audit hash, ties by commit, then arm, then attempt."""
    return sorted(patches, key=lambda p: (audit_key(p), p.commit, p.arm, p.attempt))


def _validate(rows: Sequence[PlainRow], commits: Mapping[str, Sequence[str]] | None) -> None:
    seen: set[tuple[str, str, str, int]] = set()
    for r in rows:
        if r.arm not in ARMS:
            raise ValueError("a row's arm is not A0 or S1")
        if r.attempt not in ATTEMPTS or isinstance(r.attempt, bool):
            raise ValueError("a row's attempt is not 1 or 2")
        if not isinstance(r.clean, bool):
            raise ValueError("a row's clean is not a boolean")
        if commits is not None and (r.repo not in commits or r.commit not in commits[r.repo]):
            raise ValueError("a row names a repository or commit outside the given commits")
        k = (r.repo, r.commit, r.arm, r.attempt)
        if k in seen:
            raise ValueError("two rows for one repository, commit, arm and attempt")
        seen.add(k)


def draw_cell(
    repo: str, arm: str, order: Sequence[str], clean: Mapping[tuple[str, str], frozenset[int]]
) -> Cell:
    """B2 item 3 for one repository ``repo`` and arm ``arm`` over the review ``order``.

    ``clean[(commit, arm)]`` is the set of clean attempts. Step 1: commits clean under both
    arms (R6: at least one clean row under each), the lower clean attempt of ``arm``. Step 2:
    the other commits with a clean row under ``arm``, the lower clean attempt. Step 3: attempt 2
    of each commit with two clean rows under ``arm``, walking the order for commits clean under
    both arms first, then again for the others. Every step stops as soon as there are ten."""
    other = ARMS[1] if arm == ARMS[0] else ARMS[0]

    def mine(c: str) -> frozenset[int]:
        return clean.get((c, arm), frozenset())

    def both(c: str) -> bool:
        return bool(mine(c)) and bool(clean.get((c, other), frozenset()))

    taken: list[Patch] = []
    walks: list[tuple[int, list[tuple[str, int]]]] = [
        (1, [(c, min(mine(c))) for c in order if both(c)]),
        (2, [(c, min(mine(c))) for c in order if not both(c) and mine(c)]),
        (
            3,
            [(c, 2) for c in order if both(c) and mine(c) == frozenset(ATTEMPTS)]
            + [(c, 2) for c in order if not both(c) and mine(c) == frozenset(ATTEMPTS)],
        ),
    ]
    for step, candidates in walks:
        for commit, attempt in candidates:
            if len(taken) >= PER_ARM:
                break
            taken.append(Patch(repo, arm, commit, attempt, step))
    return Cell(repo, arm, tuple(taken))


def draw(rows: Iterable[PlainRow], commits: Mapping[str, Sequence[str]] | None = None) -> Draw:
    """The whole of B2 and B3 over plain rows.

    ``commits`` names each repository's commits (the 30 listed commits in the script); when
    it is None the repositories and commits are those the rows name. A commit with no clean
    row gives no patch, so the two give the same draw."""
    rows = list(rows)
    _validate(rows, commits)
    if commits is None:
        universe: dict[str, set[str]] = {}
        for r in rows:
            universe.setdefault(r.repo, set()).add(r.commit)
        repos = tuple(sorted(universe))
        per_repo: dict[str, Sequence[str]] = {k: sorted(v) for k, v in universe.items()}
    else:
        repos = tuple(commits)
        per_repo = dict(commits)
    clean_sets: dict[str, dict[tuple[str, str], set[int]]] = {r: {} for r in repos}
    for r in rows:
        if r.clean:
            clean_sets[r.repo].setdefault((r.commit, r.arm), set()).add(r.attempt)
    cells: dict[tuple[str, str], Cell] = {}
    ordered: dict[str, tuple[Patch, ...]] = {}
    for repo in repos:
        order = review_order(repo, per_repo[repo])
        frozen = {k: frozenset(v) for k, v in clean_sets[repo].items()}
        for arm in ARMS:
            cells[(repo, arm)] = draw_cell(repo, arm, order, frozen)
        pooled = [p for arm in ARMS for p in cells[(repo, arm)].patches]
        ordered[repo] = tuple(audit_order(pooled))
    audit = tuple(
        ordered[repo][i] for i in range(AUDIT_PER_REPO) for repo in repos if i < len(ordered[repo])
    )
    return Draw(repos, cells, ordered, audit)


def reviewer_key(salt: str, p: Patch) -> str:
    return sha256_hex(f"{REVIEWER_PREFIX}{salt}|{p.repo}|{p.arm}|{p.commit}|{p.attempt}")


@dataclass(frozen=True)
class Labels:
    """The reviewer's labels: each repository's patches in the secret salted order."""

    salt: str
    labelled: Mapping[str, tuple[Labelled, ...]]
    label_of: Mapping[Patch, str]

    def audit_labels(self, d: Draw) -> tuple[str, ...]:
        return tuple(self.label_of[p] for p in d.audit)


def label(d: Draw, salt: str) -> Labels:
    """Labels ``click-01``, ``click-02``, ... (per repository) in ascending ``reviewer_key(salt, patch)``, ties by
    commit, then arm, then attempt. Without the salt the order cannot be recomputed, so the
    label order says nothing about the arm (unlike B3's public audit order)."""
    if not salt:
        raise ValueError("the reviewer salt is empty")
    labelled: dict[str, tuple[Labelled, ...]] = {}
    label_of: dict[Patch, str] = {}
    for repo in d.repos:
        pats = sorted(d.ordered[repo],
                      key=lambda p: (reviewer_key(salt, p), p.commit, p.arm, p.attempt))  # fmt: skip
        labelled[repo] = tuple(Labelled(f"{repo}-{i:02d}", p) for i, p in enumerate(pats, 1))
        label_of.update({lp.patch: lp.label for lp in labelled[repo]})
    return Labels(salt, labelled, label_of)


# ---------------------------------------------------------------------------
# the two texts
# ---------------------------------------------------------------------------


def audit_file_key(salt: str, label_: str) -> str:
    return sha256_hex(f"{AUDIT_FILE_PREFIX}{salt}|{label_}")


def audit_file_order(lab: Labels, d: Draw, salt: str) -> list[Patch]:
    """Ruling Q2: Paul's ten in ascending ``sha256("crb.wave4.auditfile|" + salt + "|" +
    label)``. The labels are distinct, so there are no ties. Without the salt (key file only)
    the order cannot be recomputed, so it says nothing of B3's order."""
    if not salt:
        raise ValueError("the audit-file salt is empty")
    return sorted(d.audit, key=lambda p: audit_file_key(salt, lab.label_of[p]))


def key_text(d: Draw, lab: Labels, run_of: Mapping[tuple[str, str, str, int], str],
             header: Sequence[str], with_error: Mapping[tuple[str, str], int], *,
             audit_salt: str, rows_read: int) -> str:  # fmt: skip
    """The keyed list (NOT for the reviewer). ``run_of`` maps (repo, commit, arm, attempt) to
    the run id of that row; ``with_error`` counts rows whose clean is true but which carry an
    error (not drawn, ruling Q4), per (repo, arm); ``rows_read`` is how many rows were read.
    ``audit_salt`` orders Paul's audit file and is written here only."""
    lines = [
        f"{SCRIPT_NAME} key: the keyed review list. NOT for the reviewer; not for Paul before "
        "his own verdicts (R9).",
        f"salt {lab.salt}",
        f"audit file salt {audit_salt}",
        *header,
        "Patches (label, repository, arm, commit, attempt, run, step, B3 audit position):",
    ]
    for repo in d.repos:
        pos = {p: i for i, p in enumerate(d.ordered[repo], start=1)}
        for lp in lab.labelled[repo]:
            p = lp.patch
            rid = run_of.get((p.repo, p.commit, p.arm, p.attempt), "UNKNOWN")
            lines.append(
                f"  {lp.label}  {p.repo}  {p.arm}  {p.commit}  attempt {p.attempt}  "
                f"run {rid}  step {p.step}  audit position {pos[p]}"
            )
    lines.append("Per repository and arm (B2 item 3; clean rows that carry an error: not drawn):")
    for repo in d.repos:
        for arm in ARMS:
            c = d.cells[(repo, arm)]
            steps = ", ".join(f"step {s} gave {c.step_count(s)}" for s in STEPS)
            lines.append(
                f"  {repo} {arm}: {steps}; {len(c.patches)} of {PER_ARM}; "
                f"shortfall {c.shortfall}; clean rows that carry an error "
                f"{with_error.get((repo, arm), 0)}"
            )
    lines.append(f"Clean rows that carry an error, total across the {rows_read} rows: "
                 f"{sum(with_error.values())}")  # fmt: skip
    lines.append("B3 sequence (B3 item 3: click 1, cobra 1, click 2, ...; reviewer label, "
                 "repository, arm, commit, attempt):")  # fmt: skip
    nth: dict[str, int] = {}
    for p in d.audit:
        nth[p.repo] = nth.get(p.repo, 0) + 1
        lines.append(f"  {p.repo} {nth[p.repo]}  {lab.label_of[p]}  {p.repo}  {p.arm}  "
                     f"{p.commit}  attempt {p.attempt}")  # fmt: skip
    if not d.audit:
        lines.append("  none")
    return "".join(ln + "\n" for ln in lines)


def audit_text(d: Draw, lab: Labels, salt: str, file_id: str) -> str:
    """Paul's audit file (NOT for the reviewer; ruling Q2): his ten patches as reviewer label,
    repository and commit, in the salted order of ``audit_file_order``. It holds no B3 order or
    position, no arm, attempt, run id or step, and not the salt (key file only), so the file
    itself adds no arm information (R9). A residual leak remains from the registered B3 hash,
    which is public and includes the arm: membership of this set, read with the commits, lets
    a reader guess arms better than chance; this is recorded in the wave record and cannot be
    removed without changing B3. ``file_id`` is a fresh random line that orders nothing:
    without it the file would hold no secret, and its sha256 on the filed list could be
    matched by trying every audit set and order, which would show which patches Paul checks
    outright."""
    if not file_id:
        raise ValueError("the audit-file id is empty")
    lines = [
        f"{SCRIPT_NAME} audit: Paul's audit file (B3 items 1-3, R8, R9). NOT for the reviewer.",
        f"All {len(d.audit)} patches below are to be checked. Give a verdict on each before "
        "being told the arm or the reviewer's verdict.",
        f"file id {file_id}",
        "Patches (label, repository, commit):",
    ]
    lines += [f"  {lab.label_of[p]}  {p.repo}  {p.commit}" for p in audit_file_order(lab, d, salt)]
    lines.append(f"audit patches: {len(d.audit)} of {AUDIT_PER_REPO * len(d.repos)}; "
                 f"shortfall {d.audit_shortfall()}")  # fmt: skip
    return "".join(ln + "\n" for ln in lines)


def review_list_lines(d: Draw, lab: Labels) -> list[str]:
    """B2 item 4's drawn list as the reviewer sees it: label, repository, commit, in label
    order. Its sha256 is the sha256 of exactly these lines, each ending in a newline."""
    lines = ["Review list (blinded; label, repository, commit; in label order):"]
    for repo in d.repos:
        for lp in lab.labelled[repo]:
            lines.append(f"  {lp.label}  {lp.patch.repo}  {lp.patch.commit}")
    return lines


def blinded_lines(d: Draw, lab: Labels, key_sha256: str, audit_sha256: str,
                  with_error_total: int) -> list[str]:  # fmt: skip
    """The blinded list; its own sha256; the key's and the audit file's sha256; the wave-wide
    total of clean rows that carry an error (ruling Q4: no split by repository or arm); the
    totals per repository. Nothing here names an arm value, an attempt, a run, a step or the
    audit set."""
    lines = review_list_lines(d, lab)
    listed = "".join(ln + "\n" for ln in lines).encode("utf-8")
    lines.append(f"review list sha256 {hashlib.sha256(listed).hexdigest()}")
    lines.append(f"key file sha256 {key_sha256}")
    lines.append(f"audit file sha256 {audit_sha256}")
    lines.append(STEP_COUNTS_NOTE)
    lines.append(WITH_ERROR_TOTAL.format(n=with_error_total))
    for repo in d.repos:
        n = d.repo_total(repo)
        want = PER_ARM * len(ARMS)
        lines.append(f"{repo}: {n} patches drawn of {want}; shortfall {want - n}")
    return lines


# ---------------------------------------------------------------------------
# the rows of A2, from the checked read
# ---------------------------------------------------------------------------


def attempt_of(c: Any) -> dict[str, int]:
    """B2 item 1: in each batch, the arm's first-filed run (lower place, test (d)) gives
    attempt 1 and the other attempt 2. Only the 48 standing runs have a batch and a place."""
    out: dict[str, int] = {}
    for key in R.BATCH_KEYS:
        for arm in ARMS:
            ids = sorted(
                (i for i, k in c.batch_of.items() if k == key and c.arm_of[i] == arm),
                key=lambda i: c.place_of[i],
            )
            if len(ids) != len(ATTEMPTS):  # the order check makes this impossible
                raise AssertionError("a batch does not hold two runs of an arm")
            for attempt, rid in zip(ATTEMPTS, ids, strict=True):
                out[rid] = attempt
    return out


def has_error_field(row: Any) -> bool:
    """Ruling Q4: a row must carry an ``error`` field (null and empty both count as present);
    a row without one stops the draw."""
    return row.error is not R.ABSENT


def carries_error(row: Any) -> bool:
    """Ruling Q4: a null or empty-string ``error`` means no error; any other value is one. An
    absent field is not an answer here (``has_error_field`` stops the draw first)."""
    if not has_error_field(row):
        raise ValueError("a row has no error field")
    return not (row.error is None or (isinstance(row.error, str) and row.error == ""))


def row_is_clean(row: Any) -> bool:
    """Clean for the draw (ruling Q4): the row's own ``clean`` field is true (A3, the read's
    ``r.clean is True``) AND the row carries no error."""
    return row.clean is True and not carries_error(row)


def rows_bad(c: Any, rows: Mapping[str, list[Any]]) -> tuple[int, int]:
    """The read's added integrity stop, unchanged: runs with a row for another run, an
    unlisted commit or one commit twice; rows with a non-boolean clean."""

    def row_set_bad(r: str) -> bool:
        listed = R.batch_commits(*c.batch_of[r])
        tasks = [x.task_id for x in rows[r]]
        return (
            any(not (isinstance(x.run_id, str) and x.run_id == r) for x in rows[r])
            or any(not (isinstance(t, str) and t in listed) for t in tasks)
            or len(set(tasks)) != len(tasks)
        )

    bad_set = sum(1 for r in sorted(c.standing) if row_set_bad(r))
    bad_clean = sum(1 for r in c.standing for x in rows[r] if not isinstance(x.clean, bool))
    return bad_set, bad_clean


def plain_rows(
    c: Any, rows: Mapping[str, list[Any]]
) -> tuple[list[PlainRow], dict[tuple[str, str, str, int], str], dict[tuple[str, str], int]]:
    attempts = attempt_of(c)
    out: list[PlainRow] = []
    run_of: dict[tuple[str, str, str, int], str] = {}
    with_error: dict[tuple[str, str], int] = {}
    for rid in sorted(c.standing):
        repo, _b = c.batch_of[rid]
        arm, attempt = c.arm_of[rid], attempts[rid]
        for x in rows[rid]:
            if x.clean is True and carries_error(x):  # not drawn (ruling Q4); counted
                with_error[(repo, arm)] = with_error.get((repo, arm), 0) + 1
            out.append(PlainRow(repo, x.task_id, arm, attempt, row_is_clean(x)))
            run_of[(repo, x.task_id, arm, attempt)] = rid
    return out, run_of, with_error


def listed_commits() -> dict[str, tuple[str, ...]]:
    """B2 item 2: the 30 commits of each repository (both cut lists, A2 item 1)."""
    return {repo: R.LISTS[(repo, "XS")] + R.LISTS[(repo, "S")] for repo in R.REPOS}


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


class OutputFileError(Exception):
    """Exit 5: the key or audit file could not be written or closed. The message is one of
    the fixed texts above; no path, no value."""


@dataclass
class _State:
    """How far the run got, so every exit 4 or 5 says what is true of it."""

    salted: bool = False  # a salt was made: a later run would make different labels
    listing: bool = False  # the first line of the blinded list is being printed
    listed: bool = False  # every line of the blinded list was printed
    output_failed: bool = False  # an exit line could not be written to the --output file

    def last_line(self) -> str:
        return DO_NOT_RERUN if self.salted else NO_SALT

    def output_message(self) -> str:
        if self.listed:
            return OUTPUT_NOT_CLOSED
        return OUTPUT_PART_OF_LIST if self.listing else OUTPUT_NOT_WRITTEN


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = R._Parser(prog=SCRIPT_NAME, description="Wave 4 review draw (Amendment 3 Part B).")
    ap.add_argument("--poster-dir", required=True, help="folder holding the poster's files")
    ap.add_argument("--login", required=True, help="JSON file {username, password}")
    ap.add_argument("--api", required=True, help="base URL of the served product")
    ap.add_argument("--campaign", required=True, help="the Wave 4 campaign id")
    ap.add_argument("--key-out", required=True,
                    help="new file (0600) for the keyed list; NOT for the reviewer")  # fmt: skip
    ap.add_argument("--audit-out", required=True,
                    help="new file (0600) for Paul's audit list; NOT for the reviewer")  # fmt: skip
    ap.add_argument("--output", required=True,
                    help="new file (0600) that receives every stdout line")  # fmt: skip
    ns: argparse.Namespace = ap.parse_args(argv)
    return ns


def _open_new(path: str) -> Any:
    """A new file, 0600, refused if it exists (``FileExistsError``); text, no newline
    translation."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="")


def _make_salt() -> str:
    return secrets.token_hex(32)


def _fsync(f: Any) -> None:
    """The key or audit file's bytes to disk before it is closed."""
    os.fsync(f.fileno())


#: Whatever a failing file or stream raises, the exit path goes on (an interrupt included).
_ANY = (Exception, KeyboardInterrupt)


def _close_left(files: dict[str, Any]) -> None:
    """Close a key or audit file still open (an exit before the draw wrote it); a failure is
    exit 5 with that file's fixed text. After the list is printed none is left open."""
    for name, msg in (("key", KEY_NOT_WRITTEN), ("audit", AUDIT_NOT_WRITTEN)):
        f = files.pop(name, None)
        if f is not None:
            try:
                f.close()
            except _ANY:
                raise OutputFileError(msg) from None


def _abandon(out: Any, files: dict[str, Any]) -> None:
    """The safety net: close whatever is still open, silently (it never prints or raises)."""
    with contextlib.suppress(*_ANY):
        out.close()
    _close_files(files)


def _close_files(files: dict[str, Any]) -> None:
    """Close the key and audit files still open, silently."""
    for f in files.values():
        with contextlib.suppress(*_ANY):
            f.close()
    files.clear()


def _drop_output(out: Any, state: _State) -> None:
    """The ``--output`` file failed: write no more to it, close it silently, record it."""
    state.output_failed = True
    f, out.file = out.file, None
    if f is not None:
        with contextlib.suppress(*_ANY):
            f.close()


def _say(out: Any, state: _State, *lines: str, stream: bool = True) -> None:
    """The last lines of an exit 4 or 5; never raises. Each goes to the ``--output`` file
    (while it still takes lines; one that fails is dropped and recorded) and then, unless
    ``stream`` is false, to stdout, so the last line is in every place a line can still be
    written."""
    for ln in lines:
        if out.file is not None:
            try:
                out.file.write(ln + "\n")
                out.file.flush()
            except _ANY:
                _drop_output(out, state)
        if stream:
            with contextlib.suppress(*_ANY):
                out.stream_only(ln)


def print_order_failure(out: Any, failures: Sequence[Any],
                        not_evaluated: Sequence[tuple[str, str]]) -> None:  # fmt: skip
    """Counts only: the parts that failed and how many failures each, the parts not
    evaluated. No run id, no time, no reason text."""
    order = {p: i for i, p in enumerate(R.PART_ORDER)}
    parts = sorted({f.part for f in failures}, key=lambda p: (order.get(p, len(order)), p))
    out.line(f"ORDER CHECK FAILED: {len(failures)} failure(s) in {len(parts)} part(s); "
             f"{len(not_evaluated)} part(s) not evaluated")  # fmt: skip
    for p in parts:
        out.line(f"  part {p}: {sum(1 for f in failures if f.part == p)} failure(s)")
    for p, _dep in not_evaluated:
        out.line(f"  part {p}: not evaluated")
    out.line(ORDER_FAIL_FOOTER)


def main(
    argv: Sequence[str] | None = None,
    *,
    read_file: Callable[[str], bytes] = R._read_file,
    open_getter: Any = R.make_urllib_getter,
    open_output: Callable[[str], Any] = _open_new,
    open_key: Callable[[str], Any] = _open_new,
    open_audit: Callable[[str], Any] = _open_new,
    path_exists: Callable[[str], bool] = os.path.lexists,
    make_salt: Callable[[], str] = _make_salt,
    sync: Callable[[Any], None] = _fsync,
    stdout: Any = None,
    recorded: Any = None,
    self_bytes: bytes | None = None,
    read_bytes: bytes | None = None,
) -> int:
    out = R.Out(stdout if stdout is not None else sys.stdout)
    files: dict[str, Any] = {}
    state = _State()

    def salt() -> str:
        state.salted = True  # before the call: from here a rerun would draw other labels
        return make_salt()

    try:
        unexpected: str | None = None
        try:
            code = _main(argv, out, files, state, read_file=read_file,
                         open_getter=open_getter, open_output=open_output, open_key=open_key,
                         open_audit=open_audit, path_exists=path_exists, make_salt=salt,
                         sync=sync, recorded=recorded, self_bytes=self_bytes,
                         read_bytes=read_bytes)  # fmt: skip
        except (R.OutputFileError, OutputFileError):
            raise
        except (Exception, KeyboardInterrupt) as exc:
            # No traceback, no message text, no row data: the class only. An interrupt is
            # held here too, so a salted run still ends with the DO NOT RERUN line.
            unexpected = type(exc).__name__
            code = 5 if state.salted else 4
        _close_left(files)
        if unexpected is not None:
            _say(out, state, UNEXPECTED.format(cls=unexpected))
            # The last line to the file now; to stdout only after the close, so a failure of
            # the file still ends stdout with one last line, after the output file's line.
            _say(out, state, state.last_line(), stream=False)
        try:
            out.close()
        except _ANY:  # an interrupt in close too: the file may not hold every line
            raise R.OutputFileError from None
        if state.output_failed:  # an exit line above could not be written to the file
            raise R.OutputFileError
        if unexpected is not None:
            _say(out, state, state.last_line())  # the file is closed: stdout alone
    except R.OutputFileError:
        _abandon(out, files)  # the output file failed: the lines go to stdout alone
        _say(out, state, state.output_message(), state.last_line())
        return 5
    except OutputFileError as exc:
        _close_files(files)
        _say(out, state, str(exc), state.last_line())  # the output file did not fail: it gets them
        return 5
    finally:
        _abandon(out, files)
    return code


def _main(
    argv: Sequence[str] | None,
    out: Any,
    files: dict[str, Any],
    state: _State,
    *,
    read_file: Callable[[str], bytes],
    open_getter: Any,
    open_output: Callable[[str], Any],
    open_key: Callable[[str], Any],
    open_audit: Callable[[str], Any],
    path_exists: Callable[[str], bool],
    make_salt: Callable[[], str],
    sync: Callable[[Any], None],
    recorded: Any,
    self_bytes: bytes | None,
    read_bytes: bytes | None,
) -> int:
    rec = recorded if recorded is not None else R.RECORDED
    args = parse_args(argv)
    own = self_bytes if self_bytes is not None else Path(__file__).read_bytes()
    read_src = read_bytes if read_bytes is not None else READ_PATH.read_bytes()
    out.line(f"{SCRIPT_NAME} sha256 {hashlib.sha256(own).hexdigest()}")
    out.line(f"{READ_NAME} sha256 {hashlib.sha256(read_src).hexdigest()} (imported)")
    out.line(f"campaign: {R.CAMPAIGN_ID}")
    try:
        R.check_ready(rec)
        if args.campaign != R.CAMPAIGN_ID:
            raise R.NotReadyError("campaign is not the registered Wave 4 campaign id")
        named = [os.path.abspath(p) for p in (args.output, args.key_out, args.audit_out)]
        if len(set(named)) != len(named):
            raise R.NotReadyError("output, key-out and audit-out do not name three files")
        if path_exists(args.key_out):
            raise R.NotReadyError("key file already exists (--key-out)")
        if path_exists(args.audit_out):
            raise R.NotReadyError("audit file already exists (--audit-out)")
        if not R.API_URL.match(args.api):
            raise R.NotReadyError("api is not an http(s) URL")
        username, password = R._read_login(read_file, args.login)
        # All three files are created before any poster file is read or any request is made.
        try:
            out.attach(open_output(args.output))
        except FileExistsError:
            raise R.NotReadyError("output file already exists (--output)") from None
        except OSError:
            raise R.NotReadyError("output file cannot be created (--output)") from None
        for name, opener, flag in (("key", open_key, "--key-out"),
                                   ("audit", open_audit, "--audit-out")):  # fmt: skip
            path = args.key_out if name == "key" else args.audit_out
            try:
                files[name] = opener(path)
            except FileExistsError:
                raise R.NotReadyError(f"{name} file already exists ({flag})") from None
            except OSError:
                raise R.NotReadyError(f"{name} file cannot be created ({flag})") from None
    except R.NotReadyError as exc:
        out.line(f"not ready: {exc}")
        return 1
    # A key or audit file left open (any exit before the draw wrote it) is closed by ``main``.
    return _draw(args, out, files, state, rec, read_file=read_file, open_getter=open_getter,
                 make_salt=make_salt, sync=sync, username=username, password=password,
                 self_sha=hashlib.sha256(own).hexdigest(),
                 read_sha=hashlib.sha256(read_src).hexdigest())  # fmt: skip


def _draw(
    args: argparse.Namespace, out: Any, files: dict[str, Any], state: _State, rec: Any, *,
    read_file: Callable[[str], bytes], open_getter: Any, make_salt: Callable[[], str],
    sync: Callable[[Any], None], username: str, password: str, self_sha: str, read_sha: str,
) -> int:  # fmt: skip
    # --- T1: the four files, fixed by hash (as the read) ---
    paths = {r: os.path.join(args.poster_dir, str(rec.file_names[r])) for r in R.FILE_ROLES}
    data: dict[str, bytes] = {}
    t1: list[Any] = []
    for role in R.FILE_ROLES:
        try:
            data[role] = read_file(paths[role])
        except OSError:
            t1.append(R.Failure("T1", "file not readable"))
            continue
        digest = hashlib.sha256(data[role]).hexdigest()
        out.line(f"input {role}: {paths[role]} sha256 {digest}")
        if digest != rec.file_sha256[role]:
            t1.append(R.Failure("T1", "file hash differs from the recorded one"))
    if t1:
        print_order_failure(out, t1, [])
        return 2

    # --- parse (T3 on shape), T2 ---
    try:
        plan = R.extract_plan(R.strict_json(data["plan"]))
        pre = R.extract_plan(R.strict_json(data["pre_s3"]), batch_may_be_absent=True)
        out_click = R.extract_out(R.strict_json(data["click_out"]))
        out_cobra = R.extract_out(R.strict_json(data["cobra_out"]))
    except R.ShapeError:
        print_order_failure(out, [R.Failure("T3", "file shape not as recorded")], [])
        return 2
    del data
    pre_fail: list[Any] = []
    R.check_t2(plan, pre, lambda part, reason, lines=(): pre_fail.append(
        R.Failure(part, reason, [], list(lines))))  # fmt: skip
    del pre
    if pre_fail:
        print_order_failure(out, pre_fail, [])
        return 2

    # --- the campaign's runs and their records (as the read) ---
    get = open_getter(args.api, username, password)
    runs: dict[str, Any] = {}
    try:
        campaign = R.extract_campaign(R.get_json(get, f"/api/v1/campaigns/{R.CAMPAIGN_ID}"))
        hits = {i for i, _ in campaign if i.startswith(R.SHORT_FIRST_FILING)}
        full_ids = set(rec.standing_ids or ()) | (hits if len(hits) == 1 else set())
        for rid, _ in campaign:
            if rid in runs:
                continue
            if not R.HEX32.match(rid):
                raise R.TransportError("a campaign run id is not a full run id")
            runs[rid] = R.extract_run(R.get_json(get, f"/api/v1/runs/{rid}"),
                                      full=rid in full_ids)  # fmt: skip
            if runs[rid].id != rid:
                raise R.TransportError("a run record names another id")
    except (R.TransportError, R.ShapeError):
        print_order_failure(out, [R.Failure("request", "order-check request")], [])
        return 2

    chk = R.Check(rec=rec, plan=plan, out_click=out_click, out_cobra=out_cobra,
                  campaign=campaign, runs=runs, failures=[])  # fmt: skip
    R.run_order_check(chk)
    if chk.failures or chk.not_evaluated:
        print_order_failure(out, chk.failures, chk.not_evaluated)
        return 2
    out.line("Order check passed (the read's order check, made again before any row was read).")

    # --- the 48 standing runs' rows (A2); no event is read ---
    rows: dict[str, list[Any]] = {}
    try:
        for rid in sorted(chk.standing):
            items = R.get_pages(get, "/api/v1/grades", [("run_id", rid)])
            rows[rid] = [R.keep_row(i, keep_error=True) for i in items]
    except (R.TransportError, R.ShapeError):
        out.line("draw not made: a row request failed")
        return 4
    bad_set, bad_clean = rows_bad(chk, rows)
    if bad_set or bad_clean:
        out.line("draw not made: rows not as the run records state (the read's integrity stop)")
        out.line(f"runs with a row for another run, an unlisted commit or one commit twice: "
                 f"{bad_set}")  # fmt: skip
        out.line(f"rows with a non-boolean clean: {bad_clean}")
        return 4
    # Test (a) held each run record's counts.rows to 5; these rows came from another request.
    off_count = sum(1 for r in chk.standing if len(rows[r]) != ROWS_PER_RUN)
    if off_count:
        out.line(ROW_COUNT_BAD.format(per=ROWS_PER_RUN, n=off_count))
        return 4
    no_error_field = sum(1 for r in chk.standing for x in rows[r] if not has_error_field(x))
    if no_error_field:
        out.line(NO_ERROR_FIELD.format(n=no_error_field))
        return 4

    plain, run_of, with_error = plain_rows(chk, rows)
    del rows
    d = draw(plain, listed_commits())
    lab = label(d, make_salt())
    audit_salt = make_salt()
    audit_file_id = make_salt()

    # --- the key, then Paul's audit list (each written, flushed, fsynced, closed and hashed);
    # only then the list, so a failure on either shows nothing of the list ---
    header = [
        f"{SCRIPT_NAME} sha256 {self_sha}",
        f"{READ_NAME} sha256 {read_sha}",
        f"campaign: {R.CAMPAIGN_ID}",
    ]
    key = key_text(d, lab, run_of, header, with_error, audit_salt=audit_salt,
                   rows_read=len(plain))  # fmt: skip
    texts = (("key", key, KEY_NOT_WRITTEN),
             ("audit", audit_text(d, lab, audit_salt, audit_file_id), AUDIT_NOT_WRITTEN))  # fmt: skip
    sha: dict[str, str] = {}
    for name, text, msg in texts:
        f = files.pop(name)  # closed here, never again by ``main``
        try:
            f.write(text)
            f.flush()
            sync(f)
            f.close()
        except OSError:
            with contextlib.suppress(OSError):
                f.close()
            raise OutputFileError(msg) from None
        sha[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    lines = blinded_lines(d, lab, sha["key"], sha["audit"], sum(with_error.values()))
    state.listing = True
    for ln in lines:
        out.line(ln)
    state.listed = True
    return 0


def _exit_with(rc: int) -> NoReturn:
    """Exit ``rc`` even when stdout is a broken pipe: Python flushes stdout again at shutdown,
    and a failure there would print "Exception ignored" and exit 120. Lines it still holds go
    to the null device instead."""
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        with contextlib.suppress(OSError, ValueError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(rc)


if __name__ == "__main__":
    _exit_with(main())
