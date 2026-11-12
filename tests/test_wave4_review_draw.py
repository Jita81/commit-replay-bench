"""scripts/wave4_review_draw.py — Wave 4's review draw (Amendment 3 Part B), on made-up rows.

Navigation
----------
What it is:   The suite for the script that draws Wave 4's blinded review sample and Paul's
              audit set. Every commit, run id and row here is invented; no request leaves the
              process.
What it does: Pins the pure draw (hash order and its tie rule, R6, the step order 1-2-3, step
              3 walking both-arms commits first, the stop at ten mid-step, the lower attempt,
              a shortfall, zero clean, one commit order for both arms, the audit order, the
              salted reviewer labels) against hand-built tables and against a naive
              re-implementation of B2 over seeded random tables, and checks that the label
              order cannot be read from the public audit hash; then runs the whole script on
              the read suite's made-up wave: the blinded output holds no arm, attempt, run id
              or audit set, the printed sha256s are the list's, the key file's and the audit
              file's, every file is refused if it exists, and an order-check failure (among
              them a run naming its repository otherwise) reads no row and exits non-zero.
How:          The script and the read suite's ``World`` loaded by path; ``main`` runs with an
              injected file reader, getter, output and key openers and a fixed salt.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/wave4_review_draw.py (under test), scripts/wave4_primary_read.py (the
              order check it reuses), tests/test_wave4_primary_read.py (the made-up wave)
Tested by:    tests/test_wave4_review_draw.py
Touch when:   never for a new repository; the review draw or Amendment 3 Part B changes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import itertools
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# The read suite's fixtures first: it registers the read script as ``wave4_primary_read``,
# and the draw script then imports that same module object (so patched constants agree).
F = _load("_wave4_read_fixtures", ROOT / "tests" / "test_wave4_primary_read.py")
D = _load("wave4_review_draw", ROOT / "scripts" / "wave4_review_draw.py")
W = F.W
assert D.R is W

KEYF = "/fixture/key.txt"
AUDF = "/fixture/audit.txt"
ARGV = [
    "--poster-dir", F.POSTER, "--login", F.LOGIN, "--api", F.API,
    "--campaign", W.CAMPAIGN_ID, "--key-out", KEYF, "--audit-out", AUDF, "--output", F.OUTF,
]  # fmt: skip
SALT = "fixture-salt"


def salts() -> Any:
    """Distinct made-up salts: the key's, the audit file's order salt, then its file id."""
    n = iter(range(1, 100))
    return lambda: f"{SALT}-{next(n)}"


def cm(tag: str) -> str:
    """A made-up 40-hex commit."""
    return hashlib.sha1(tag.encode()).hexdigest()


def rk(repo: str, commit: str) -> str:
    return hashlib.sha256(f"crb.wave4.review|20261112|{repo}|{commit}".encode()).hexdigest()


def ak(repo: str, arm: str, commit: str, attempt: int) -> str:
    s = f"crb.wave4.audit|20261112|{repo}|{arm}|{commit}|{attempt}"
    return hashlib.sha256(s.encode()).hexdigest()


def ordered(repo: str, n: int, tag: str = "c") -> list[str]:
    """``n`` made-up commits in the review order of ``repo``."""
    return sorted((cm(f"{tag}{i}") for i in range(n)), key=lambda c: (rk(repo, c), c))


def rows_for(repo: str, table: dict[str, dict[str, set[int]]]) -> list[Any]:
    """Plain rows from {commit: {arm: clean attempts}}; every other attempt is a not-clean
    row."""
    out = []
    for c, arms in table.items():
        for arm in ("A0", "S1"):
            for a in (1, 2):
                out.append(D.PlainRow(repo, c, arm, a, a in arms.get(arm, set())))
    return out


def picked(d: Any, repo: str, arm: str) -> list[tuple[str, int, int]]:
    return [(p.commit, p.attempt, p.step) for p in d.cells[(repo, arm)].patches]


# ---------------------------------------------------------------------------
# the pure draw
# ---------------------------------------------------------------------------


def test_review_order_is_the_hash_ascending() -> None:
    cs = [cm(f"o{i}") for i in range(30)]
    got = D.review_order("click", cs)
    assert got == sorted(cs, key=lambda c: rk("click", c))
    assert got != D.review_order("cobra", cs)  # the repository is in the string
    assert D.review_key("click", cs[0]) == rk("click", cs[0])


def test_review_order_ties_by_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "review_key", lambda _r, _c: "0" * 64)
    cs = [cm("t3"), cm("t1"), cm("t2")]
    assert D.review_order("click", cs) == sorted(cs)


def test_audit_order_ties_by_commit_then_arm_then_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(D, "audit_key", lambda _p: "f" * 64)
    a, b = sorted([cm("u1"), cm("u2")])
    ps = [D.Patch("click", "S1", b, 1, 1), D.Patch("click", "S1", a, 2, 3),
          D.Patch("click", "A0", a, 2, 1), D.Patch("click", "S1", a, 1, 1)]  # fmt: skip
    got = [(p.commit, p.arm, p.attempt) for p in D.audit_order(ps)]
    assert got == [(a, "A0", 2), (a, "S1", 1), (a, "S1", 2), (b, "S1", 1)]


def test_r6_one_clean_row_under_each_arm_is_both() -> None:
    c = ordered("click", 1)[0]
    d = D.draw(rows_for("click", {c: {"A0": {2}, "S1": {1}}}))
    assert picked(d, "click", "A0") == [(c, 2, 1)]
    assert picked(d, "click", "S1") == [(c, 1, 1)]


def test_step_order_one_then_two_then_three() -> None:
    o = ordered("click", 6)
    # o[0]: S1 only, both attempts; o[1]: both arms; o[2]: S1 only, one attempt;
    # o[3]: both arms, both S1 attempts; o[4]: nothing; o[5]: A0 only
    table = {
        o[0]: {"S1": {1, 2}}, o[1]: {"S1": {2}, "A0": {1}}, o[2]: {"S1": {1}},
        o[3]: {"S1": {1, 2}, "A0": {2}}, o[4]: {}, o[5]: {"A0": {1}},
    }  # fmt: skip
    d = D.draw(rows_for("click", table))
    assert picked(d, "click", "S1") == [
        (o[1], 2, 1),
        (o[3], 1, 1),  # step 1: both arms, in order
        (o[0], 1, 2),
        (o[2], 1, 2),  # step 2: the others, in order
        (o[3], 2, 3),
        (o[0], 2, 3),  # step 3: both-arms commits first
    ]
    assert picked(d, "click", "A0") == [(o[1], 1, 1), (o[3], 2, 1), (o[5], 1, 2)]
    cell = d.cells[("click", "S1")]
    assert [cell.step_count(s) for s in (1, 2, 3)] == [2, 2, 2]
    assert cell.shortfall == 4


def test_step3_walks_both_arms_commits_first_even_when_later_in_order() -> None:
    o = ordered("cobra", 2)
    # o[0] is S1-only with two clean attempts; o[1] is both-arms with two
    table = {o[0]: {"S1": {1, 2}}, o[1]: {"S1": {1, 2}, "A0": {1}}}
    d = D.draw(rows_for("cobra", table))
    step3 = [(c, a) for c, a, s in picked(d, "cobra", "S1") if s == 3]
    assert step3 == [(o[1], 2), (o[0], 2)]


def test_stops_at_ten_in_the_middle_of_step_2() -> None:
    o = ordered("click", 14)
    table = {c: {"S1": {1, 2}, "A0": {1}} for c in o[:6]}
    table |= {c: {"S1": {1}} for c in o[6:]}
    d = D.draw(rows_for("click", table))
    got = picked(d, "click", "S1")
    assert len(got) == 10
    assert got == [(c, 1, 1) for c in o[:6]] + [(c, 1, 2) for c in o[6:10]]
    assert d.cells[("click", "S1")].shortfall == 0


def test_stops_at_ten_in_the_middle_of_step_1_and_step_3() -> None:
    o = ordered("click", 12)
    d = D.draw(rows_for("click", {c: {"S1": {1}, "A0": {1}} for c in o}))
    assert picked(d, "click", "S1") == [(c, 1, 1) for c in o[:10]]
    o = ordered("cobra", 7)
    d = D.draw(rows_for("cobra", {c: {"S1": {1, 2}} for c in o}))
    assert picked(d, "cobra", "S1") == [(c, 1, 2) for c in o] + [(c, 2, 3) for c in o[:3]]


def test_the_lower_clean_attempt_is_taken() -> None:
    o = ordered("click", 2)
    d = D.draw(rows_for("click", {o[0]: {"S1": {1, 2}}, o[1]: {"S1": {2}}}))
    assert picked(d, "click", "S1")[:2] == [(o[0], 1, 2), (o[1], 2, 2)]


def test_fewer_than_ten_gives_all_and_a_shortfall() -> None:
    o = ordered("click", 3)
    d = D.draw(rows_for("click", {o[0]: {"A0": {1}}, o[1]: {"A0": {2}}, o[2]: {}}))
    assert len(d.cells[("click", "A0")].patches) == 2
    assert d.cells[("click", "A0")].shortfall == 8
    assert d.cells[("click", "S1")].shortfall == 10
    assert d.audit_shortfall() == 3  # two of five audit patches


def test_missing_and_error_rows_are_not_clean() -> None:
    o = ordered("click", 2)
    rows = [D.PlainRow("click", o[0], "S1", 1, False)]  # an error row arrives not clean
    d = D.draw(rows, {"click": o})  # o[1] has no row at all
    assert d.cells[("click", "S1")].patches == ()


def test_zero_clean() -> None:
    commits = {"click": ordered("click", 30), "cobra": ordered("cobra", 30)}
    d = D.draw([], commits)
    assert all(not c.patches and c.shortfall == 10 for c in d.cells.values())
    assert d.audit == () and d.audit_shortfall() == 10
    lab = D.label(d, SALT)
    lines = D.blinded_lines(d, lab, "0" * 64, "1" * 64, 0)
    assert "click: 0 patches drawn of 20; shortfall 20" in lines
    key = D.key_text(d, lab, {}, [], {}, audit_salt="a", rows_read=0)
    assert key.endswith("attempt):\n  none\n")
    assert "audit patches: 0 of 10; shortfall 10" in D.audit_text(d, lab, "s", "f")


def test_one_commit_order_serves_both_arms() -> None:
    o = ordered("click", 12)
    table = {c: {"S1": {1}, "A0": {1}} for c in o}
    d = D.draw(rows_for("click", table))
    assert [c for c, _, _ in picked(d, "click", "S1")] == o[:10]
    assert [c for c, _, _ in picked(d, "click", "A0")] == o[:10]


def test_rows_outside_the_rules_are_refused() -> None:
    c = cm("x")
    with pytest.raises(ValueError):
        D.draw([D.PlainRow("click", c, "S3", 1, True)])
    with pytest.raises(ValueError):
        D.draw([D.PlainRow("click", c, "S1", 3, True)])
    with pytest.raises(ValueError):
        D.draw([D.PlainRow("click", c, "S1", 1, True)] * 2)
    with pytest.raises(ValueError):
        D.draw([D.PlainRow("click", c, "S1", 1, True)], {"click": [cm("y")]})


def test_audit_order_labels_and_sequence() -> None:
    oc, ob = ordered("click", 8, "k"), ordered("cobra", 3, "b")
    rows = rows_for("click", {c: {"S1": {1, 2}, "A0": {1}} for c in oc})
    rows += rows_for("cobra", {ob[0]: {"S1": {1}}, ob[1]: {"A0": {2}}, ob[2]: {"S1": {2}}})
    d = D.draw(rows)
    for repo in ("click", "cobra"):
        pats = [p for arm in ("A0", "S1") for p in d.cells[(repo, arm)].patches]
        want = sorted(pats, key=lambda p: (ak(p.repo, p.arm, p.commit, p.attempt), p.commit,
                                           p.arm, p.attempt))  # fmt: skip
        assert list(d.ordered[repo]) == want
    assert d.repo_total("click") == 18 and d.repo_total("cobra") == 3
    oc_, ob_ = d.ordered["click"], d.ordered["cobra"]
    assert d.audit == (oc_[0], ob_[0], oc_[1], ob_[1], oc_[2], ob_[2], oc_[3], oc_[4])
    assert d.audit_shortfall() == 2
    # the reviewer labels: R-01.. in the salted order, the audit sequence mapped onto them
    lab = D.label(d, SALT)
    for repo in ("click", "cobra"):
        sk = [D.sha256_hex(f"crb.wave4.reviewer|{SALT}|{p.repo}|{p.arm}|{p.commit}|{p.attempt}")
              for p in d.ordered[repo]]  # fmt: skip
        want = [p for _, p in sorted(zip(sk, d.ordered[repo], strict=True),
                                     key=lambda t: (t[0], t[1].commit, t[1].arm, t[1].attempt))]  # fmt: skip
        assert [lp.patch for lp in lab.labelled[repo]] == want
        assert [lp.label for lp in lab.labelled[repo]] == [
            f"{repo}-{i:02d}" for i in range(1, len(want) + 1)
        ]
    assert lab.audit_labels(d) == tuple(lab.label_of[p] for p in d.audit)
    assert D.label(d, "another").labelled != lab.labelled  # the salt moves the labels
    with pytest.raises(ValueError):
        D.label(d, "")


def _random_tables(rng: random.Random, n: int = 30) -> tuple[list[Any], dict[str, list[str]]]:
    commits = {repo: [cm(f"{repo}{rng.random()}") for _ in range(n)]
               for repo in ("click", "cobra")}  # fmt: skip
    pa, ps = rng.uniform(0.2, 0.6), rng.uniform(0.2, 0.6)
    rows = [D.PlainRow(repo, c, arm, a, rng.random() < (pa if arm == "A0" else ps))
            for repo, cs in commits.items() for c in cs for arm in ("A0", "S1")
            for a in (1, 2)]  # fmt: skip
    return rows, commits


def _public_inference(listed: list[tuple[str, str]]) -> list[set[str]]:
    """What a reader of the list could infer if labels followed B3's public audit hash: for
    each label (repo, commit), keep the (arm, attempt) candidates whose audit hash can rise
    in label order (a forward and a backward pass); return the arms left per label."""
    cands = [{(arm, a): ak(r, arm, c, a) for arm in ("A0", "S1") for a in (1, 2)}
             for r, c in listed]  # fmt: skip
    lo = ""
    for cd in cands:
        for k in [k for k, h in cd.items() if h <= lo]:
            del cd[k]
        lo = min(cd.values(), default="g")
    hi = "g"
    for cd in reversed(cands):
        for k in [k for k, h in cd.items() if h >= hi]:
            del cd[k]
        hi = max(cd.values(), default="")
    return [{arm for arm, _ in cd} for cd in cands]


def test_reviewer_label_order_cannot_be_read_from_the_public_audit_hash() -> None:
    rng = random.Random(7)
    rising = pairs = fixed_public = fixed_salted = labels = 0
    for t in range(150):
        rows, commits = _random_tables(rng)
        d = D.draw(rows, commits)
        lab = D.label(d, f"secret-{t}")
        for repo in d.repos:
            got = [lp.patch for lp in lab.labelled[repo]]
            keys = [ak(p.repo, p.arm, p.commit, p.attempt) for p in got]
            rising += sum(1 for a, b in itertools.pairwise(keys) if a < b)
            pairs += max(len(keys) - 1, 0)
            labels += len(got)
            for order, counter in ((list(d.ordered[repo]), "public"), (got, "salted")):
                arms = _public_inference([(p.repo, p.commit) for p in order])
                n = sum(1 for s, p in zip(arms, order, strict=True) if s == {p.arm})
                if counter == "public":
                    fixed_public += n
                else:
                    fixed_salted += n
    # the attack works on the public order (the design this replaced) ...
    assert fixed_public / labels > 0.7
    # ... and not on the salted labels: neighbours rise about half the time, and the reader
    # can pin the true arm of few labels
    assert 0.4 < rising / pairs < 0.6
    assert fixed_salted / labels < 0.1


def naive_b2(rows: list[Any], commits: dict[str, list[str]]) -> dict[tuple[str, str], list[Any]]:
    """B2 item 3, re-read from the text and written plainly, independent of the script."""
    out: dict[tuple[str, str], list[Any]] = {}
    for repo, cs in commits.items():
        order = sorted(
            cs,
            key=lambda c: (
                hashlib.sha256(
                    ("crb.wave4.review|20261112|" + repo + "|" + c).encode("utf-8")
                ).hexdigest()
                + c
            ),
        )
        ok = {(r.commit, r.arm, r.attempt) for r in rows if r.repo == repo and r.clean}

        def has(c: str, a: str, ok: set[tuple[str, str, int]] = ok) -> bool:
            return (c, a, 1) in ok or (c, a, 2) in ok

        for arm in ("A0", "S1"):
            other = "S1" if arm == "A0" else "A0"
            got: list[Any] = []
            for c in order:  # step 1
                if len(got) < 10 and has(c, arm) and has(c, other):
                    got.append((c, 1 if (c, arm, 1) in ok else 2, 1))
            for c in order:  # step 2
                if len(got) < 10 and has(c, arm) and not has(c, other):
                    got.append((c, 1 if (c, arm, 1) in ok else 2, 2))
            for first in (True, False):  # step 3
                for c in order:
                    two = (c, arm, 1) in ok and (c, arm, 2) in ok
                    if len(got) < 10 and two and has(c, other) == first:
                        got.append((c, 2, 3))
            out[(repo, arm)] = got
    return out


def test_matches_a_naive_reimplementation_over_random_tables() -> None:
    rng = random.Random(20261112)
    for _ in range(400):
        commits = {repo: [cm(f"{repo}{rng.random()}") for _ in range(30)]
                   for repo in ("click", "cobra")}  # fmt: skip
        p = rng.choice([0.05, 0.2, 0.4, 0.7, 0.95])
        rows = []
        for repo, cs in commits.items():
            for c in cs:
                for arm in ("A0", "S1"):
                    for a in (1, 2):
                        if rng.random() < 0.9:  # some rows missing
                            rows.append(D.PlainRow(repo, c, arm, a, rng.random() < p))
        d = D.draw(rows, commits)
        want = naive_b2(rows, commits)
        for key, cell in d.cells.items():
            assert [(x.commit, x.attempt, x.step) for x in cell.patches] == want[key]


# ---------------------------------------------------------------------------
# the script, on the read suite's made-up wave
# ---------------------------------------------------------------------------


@dataclass
class Res:
    code: int
    out: str
    w: Any
    key: Any
    audit: Any


def run(w: Any, monkeypatch: pytest.MonkeyPatch, *, argv: list[str] | None = None,
        exists: bool = False, key_error: OSError | None = None,
        audit_error: OSError | None = None, key_cls: type[Any] | None = None,
        audit_cls: type[Any] | None = None, check: bool = True, **kw: Any) -> Res:  # fmt: skip
    for log in (w.calls, w.opened, w.reads, w.outputs):
        log.clear()
    rec = w.recorded()
    F.pin_hashes(monkeypatch, rec)
    keys: dict[str, Any] = {}
    exists_paths = {KEYF} if exists is True else set()

    def open_key(path: str) -> Any:
        if key_error is not None:
            raise key_error
        assert not w.calls and not w.opened, "key opened after a request"
        assert all(r == F.LOGIN for r in w.reads), "key opened after a poster file read"
        keys[path] = (key_cls or F.FakeOutput)()
        return keys[path]

    def open_audit(path: str) -> Any:
        if audit_error is not None:
            raise audit_error
        assert not w.calls and not w.opened, "audit file opened after a request"
        keys[path] = (audit_cls or F.FakeOutput)()
        return keys[path]

    args: dict[str, Any] = {
        "read_file": w.read_file, "open_getter": w.open_getter, "open_output": w.open_output,
        "open_key": open_key, "open_audit": open_audit,
        "path_exists": lambda p: p in exists_paths, "make_salt": salts(),
        "sync": lambda _f: None, "stdout": io.StringIO(), "recorded": rec,
        "self_bytes": b"fixture-self", "read_bytes": b"fixture-read",
    }  # fmt: skip
    args |= kw
    code = D.main(argv if argv is not None else list(ARGV), **args)
    text = args["stdout"].getvalue()
    if check:
        F.check_output_file(w, text)
    assert "Traceback" not in text
    return Res(code, text, w, keys.get(KEYF), keys.get(AUDF))


def world() -> Any:
    """The read suite's wave, with some A0 rows made clean and one clean-true error row."""
    w = F.make_world()
    for repo, b in W.BATCH_KEYS:
        first = w.a0_of(repo, b)[0]
        for i, row in enumerate(w.grades[first]):
            row["clean"] = i % 2 == 0
    rid = w.a0_of("cobra", 2)[1]
    w.grades[rid][0] |= {"clean": True, "error": "LEAK-ROW-ERROR"}
    return w


def expected_draw(w: Any) -> Any:
    """The draw computed here from the fixture's own truth (arm by run, attempt by filing)."""
    rows = []
    for repo, b in W.BATCH_KEYS:
        for arm, ids in (("A0", w.a0_of(repo, b)), ("S1", w.s1_of(repo, b))):
            ids = sorted(ids, key=lambda i: w.runs[i]["created"])
            for attempt, rid in enumerate(ids, start=1):
                for g in w.grades[rid]:
                    # ruling Q4: clean field true and no error (null or "" is no error)
                    clean = g["clean"] is True and g["error"] in (None, "")
                    rows.append(D.PlainRow(repo, g["task_id"], arm, attempt, clean))
    return D.draw(rows, D.listed_commits())


def test_draw_passes_and_writes_the_key_then_the_blinded_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world()
    res = run(w, monkeypatch)
    assert res.code == 0, res.out
    d = expected_draw(w)
    lab = D.label(d, f"{SALT}-1")
    key = res.key.closed_text
    assert key is not None and key.splitlines()[1] == f"salt {SALT}-1"
    assert key.splitlines()[2] == f"audit file salt {SALT}-2"
    sha = hashlib.sha256(key.encode("utf-8")).hexdigest()
    assert f"key file sha256 {sha}\n" in res.out
    # the key file holds every patch with its arm, attempt, run, step and audit position
    for repo in d.repos:
        for lp in lab.labelled[repo]:
            p = lp.patch
            pos = d.ordered[repo].index(p) + 1
            assert (f"  {lp.label}  {repo}  {p.arm}  {p.commit}  attempt {p.attempt}  "
                    in key and f"step {p.step}  audit position {pos}\n" in key)  # fmt: skip
    assert "clean rows that carry an error 1" in key
    for repo in d.repos:
        for arm in ("A0", "S1"):
            c = d.cells[(repo, arm)]
            assert (f"  {repo} {arm}: step 1 gave {c.step_count(1)}, step 2 gave "
                    f"{c.step_count(2)}, step 3 gave {c.step_count(3)}; ") in key  # fmt: skip
    # the blinded list: label, repository, commit, in the salted label order
    listed = [f"  {lp.label}  {repo}  {lp.patch.commit}" for repo in d.repos
              for lp in lab.labelled[repo]]  # fmt: skip
    head = "Review list (blinded; label, repository, commit; in label order):"
    block = "".join(ln + "\n" for ln in [head, *listed])
    assert block in res.out
    assert f"review list sha256 {hashlib.sha256(block.encode()).hexdigest()}\n" in res.out
    # Paul's audit file: his ten as reviewer labels in the salted order, its sha256 printed
    audit = res.audit.closed_text
    assert audit is not None
    seq = lab.audit_labels(d)
    assert len(seq) == 10
    salted = sorted(d.audit, key=lambda p: hashlib.sha256(
        f"crb.wave4.auditfile|{SALT}-2|{lab.label_of[p]}".encode()).hexdigest())  # fmt: skip
    block = "".join(f"  {lab.label_of[p]}  {p.repo}  {p.commit}\n" for p in salted)
    assert "Patches (label, repository, commit):\n" + block in audit
    assert f"audit file sha256 {hashlib.sha256(audit.encode()).hexdigest()}\n" in res.out
    # the B3 sequence is in the key file only
    nth: dict[str, int] = {}
    for p in d.audit:
        nth[p.repo] = nth.get(p.repo, 0) + 1
        assert (f"  {p.repo} {nth[p.repo]}  {lab.label_of[p]}  {p.repo}  {p.arm}  {p.commit}  "
                f"attempt {p.attempt}\n") in key  # fmt: skip
    assert ", ".join(seq) not in res.out and "sequence" not in res.out.lower()
    assert D.STEP_COUNTS_NOTE + "\n" in res.out
    assert d.cells[("click", "A0")].patches and d.cells[("click", "S1")].patches
    # only standing runs' rows were read; no event was requested
    assert w.requested("grades") == set(w.ids.values())
    assert w.requested("events") == set()


def test_blinded_output_holds_no_arm_attempt_or_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world()
    res = run(w, monkeypatch)
    assert res.code == 0
    # the one fixed note that says where B2 item 3's counts are is the only line naming
    # "arm" or "step" (no arm value, no count by arm)
    body = res.out.replace(D.STEP_COUNTS_NOTE, "")
    words = set(re.findall(r"[a-z0-9]+", body.lower()))
    for word in ("a0", "s1", "attempt", "attempts", "step", "steps", "arm", "arms", "salt",
                 "audit position", "sequence"):  # fmt: skip
        assert word not in words, word
    assert not re.search(r"\b(a0|s1)\b", res.out.lower())
    assert SALT not in res.out
    for rid in w.all_ids():
        assert rid not in res.out and rid[:8] not in res.out
    F.no_leak(res.out)
    assert "LEAK" not in res.out


def test_key_sha256_matches_the_key_bytes_and_moves_with_the_salt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world()
    a = run(w, monkeypatch)
    sha = hashlib.sha256(a.key.closed_text.encode("utf-8")).hexdigest()
    assert a.out.count(sha) == 1
    d = expected_draw(w)
    text = D.key_text(d, D.label(d, "other"), {}, [], {}, audit_salt="x", rows_read=240)
    assert hashlib.sha256(text.encode()).hexdigest() not in a.out


@pytest.mark.parametrize("which", ["output", "key", "audit"])
def test_existing_output_key_or_audit_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    w = world()
    if which == "output":
        w.output_error = FileExistsError()
        res = run(w, monkeypatch)
        assert "not ready: output file already exists (--output)" in res.out
    elif which == "key":
        res = run(w, monkeypatch, key_error=FileExistsError())
        assert "not ready: key file already exists (--key-out)" in res.out
    else:
        res = run(w, monkeypatch, audit_error=FileExistsError())
        assert "not ready: audit file already exists (--audit-out)" in res.out
    assert res.code == 1
    assert not w.calls and not w.opened


def test_existing_key_path_is_refused_before_anything_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world()
    res = run(w, monkeypatch, exists=True)
    assert res.code == 1 and "key file already exists" in res.out
    assert not w.outputs and res.key is None and not w.calls


@pytest.mark.parametrize("pair", [(KEYF, F.OUTF), (AUDF, F.OUTF), (AUDF, KEYF)])
def test_the_three_files_must_differ(monkeypatch: pytest.MonkeyPatch,
                                     pair: tuple[str, str]) -> None:  # fmt: skip
    w = world()
    argv = [pair[1] if a == pair[0] else a for a in ARGV]
    res = run(w, monkeypatch, argv=argv)
    assert res.code == 1 and "do not name three files" in res.out


def test_the_real_openers_create_0600_and_refuse_an_existing_file(tmp_path: Path) -> None:
    p = tmp_path / "k.txt"
    f = D._open_new(str(p))
    f.write("x\n")
    f.close()
    assert p.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        D._open_new(str(p))


def test_order_check_failure_reads_no_row_and_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world()
    rid = w.key_id("cobra", 1, 1)
    w.campaign_run(rid)["s1"] = not w.campaign_run(rid)["s1"]
    res = run(w, monkeypatch)
    assert res.code == 2, res.out
    assert "ORDER CHECK FAILED: 1 failure(s) in 1 part(s)" in res.out
    assert "part campaign s1: 1 failure(s)" in res.out
    assert w.requested("grades") == set()
    for i in w.all_ids():
        assert i[:8] not in res.out
    assert res.key is not None and res.key.closed_text == ""


def test_t1_failure_stops_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world()
    w.tamper["plan"] = b"{}"
    res = run(w, monkeypatch)
    assert res.code == 2 and "part T1: 1 failure(s)" in res.out
    assert not w.calls and not w.opened


def test_rows_not_as_the_records_state_stop_the_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world()
    rid = w.key_id("click", 2, 1)
    w.grades[rid].append(dict(w.grades[rid][0]))  # one commit twice
    res = run(w, monkeypatch)
    assert res.code == 4
    assert "or one commit twice: 1" in res.out and rid not in res.out
    assert "Review list" not in res.out


def _broken(stage: str) -> type[Any]:
    """A key or audit file whose write, fsync or close fails."""

    class Broken(F.FakeOutput):
        broken = True

        def write(self, text: str) -> int:
            if stage == "write" and text:
                raise OSError("disk full")
            return super().write(text)

        def fileno(self) -> int:
            if stage == "sync":
                raise OSError("fsync failed")
            return -1

        def close(self) -> None:
            if stage == "close":
                raise OSError("close failed")
            super().close()

    return Broken


def _sync_by_fileno(f: Any) -> None:
    """The fsync seam on a fake: the broken file's fileno is where its fsync fails."""
    if getattr(f, "broken", False):
        f.fileno()


SALTED_TAIL = D.DO_NOT_RERUN + "\n"
UNSALTED_TAIL = D.NO_SALT + "\n"


@pytest.mark.parametrize("which", ["key", "audit"])
@pytest.mark.parametrize("stage", ["write", "sync", "close"])
def test_key_or_audit_failure_prints_nothing_of_the_list_and_says_do_not_rerun(
    monkeypatch: pytest.MonkeyPatch, which: str, stage: str
) -> None:
    """Finding 1 and 2: both files are closed before the list; a failure on either (write,
    fsync or close) shows no line of the list and no sha256, and ends DO NOT RERUN."""
    w = world()
    cls = _broken(stage)
    res = run(w, monkeypatch, check=False, sync=_sync_by_fileno,
              **({"key_cls": cls} if which == "key" else {"audit_cls": cls}))  # fmt: skip
    assert res.code == 5, res.out
    msg = D.KEY_NOT_WRITTEN if which == "key" else D.AUDIT_NOT_WRITTEN
    assert res.out.endswith(msg + "\n" + SALTED_TAIL)
    assert "Review list" not in res.out
    for printed in ("review list sha256", "key file sha256", "audit file sha256"):
        assert printed not in res.out, printed
    assert "no draw is filed" not in res.out and "filed output is incomplete" not in res.out
    # the output file holds exactly what stdout held before the two exit-5 lines
    (outf,) = w.outputs.values()
    assert res.out == outf.text + msg + "\n" + SALTED_TAIL


def test_key_and_audit_are_synced_and_closed_before_any_line_of_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 1: at the first line of the list (or any sha256), both files are already
    written, fsynced and closed."""
    w = world()
    events: list[str] = []

    class Watch(io.StringIO):
        def write(self, s: str) -> int:
            if s.startswith(("Review list", "review list sha256", "key file sha256")):
                events.append(f"print {s.split()[0]}")
            return super().write(s)

    class Tracked(F.FakeOutput):
        def close(self) -> None:
            events.append(f"close {'key' if ' key: ' in self.text else 'audit'}")
            super().close()

    def sync(f: Any) -> None:
        events.append(f"sync {'key' if ' key: ' in f.text else 'audit'}")

    res = run(w, monkeypatch, key_cls=Tracked, audit_cls=Tracked, sync=sync, stdout=Watch())
    assert res.code == 0, res.out
    assert events[:4] == ["sync key", "close key", "sync audit", "close audit"]
    assert events[4:] == ["print Review", "print review", "print key"]


def test_the_real_fsync_syncs_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(D.os, "fsync", seen.append)
    f = D._open_new(str(tmp_path / "k.txt"))
    D._fsync(f)
    assert seen == [f.fileno()]
    f.close()


def _output_world(fail_on: str) -> tuple[Any, list[Any]]:
    """The world whose --output file fails at a write starting with ``fail_on`` (or, with
    "close", at close)."""
    w = world()
    made: list[Any] = []

    class Broken(F.FakeOutput):
        def write(self, text: str) -> int:
            if fail_on != "close" and fail_on in text:
                raise OSError("disk full")
            return super().write(text)

        def close(self) -> None:
            if fail_on == "close":
                raise OSError("close failed")
            super().close()

    def open_output(path: str) -> Any:
        made.append(Broken())
        w.outputs[path] = made[-1]
        return made[-1]

    w.open_output = open_output  # type: ignore[method-assign]
    return w, made


@pytest.mark.parametrize(
    ("fail_on", "msg", "tail"),
    [
        ("campaign:", D.OUTPUT_NOT_WRITTEN, UNSALTED_TAIL),
        ("Order check passed", D.OUTPUT_NOT_WRITTEN, UNSALTED_TAIL),
        ("  click-03", D.OUTPUT_PART_OF_LIST, SALTED_TAIL),
        ("close", D.OUTPUT_NOT_CLOSED, SALTED_TAIL),
    ],
)
def test_output_failures_say_what_is_true_and_whether_to_rerun(
    monkeypatch: pytest.MonkeyPatch, fail_on: str, msg: str, tail: str
) -> None:
    """Finding 2: the exit-5 text on --output depends on how far the list got; before any
    salt a later run is the first draw, after one it must not be rerun."""
    w, _made = _output_world(fail_on)
    res = run(w, monkeypatch, check=False)
    assert res.code == 5, res.out
    assert res.out.endswith(msg + "\n" + tail)
    assert "filed output is incomplete" not in res.out
    if fail_on == "close":  # stdout holds the full list
        assert "audit file sha256 " in res.out and "click: " in res.out
    if fail_on == "  click-03":
        assert "  click-02  " in res.out and "  click-03  " not in res.out
        assert "review list sha256" not in res.out
    if tail == UNSALTED_TAIL:
        assert "Review list" not in res.out


def test_a_key_close_failure_before_any_salt_says_the_next_run_is_the_first_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The safety net: an exit 2 leaves the empty key file open; its close failing is exit 5
    with no salt made."""
    w = world()
    w.tamper["plan"] = b"{}"
    res = run(w, monkeypatch, check=False, key_cls=_broken("close"))
    assert res.code == 5, res.out
    assert res.out.endswith(D.KEY_NOT_WRITTEN + "\n" + UNSALTED_TAIL)
    assert "part T1: 1 failure(s)" in res.out


@pytest.mark.parametrize("where", ["draw", "key_text"])
def test_an_unexpected_error_names_its_class_only(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """Finding 5: no traceback, no exit 1, no message text; exit 4 before any salt, exit 5
    and DO NOT RERUN after one."""
    w = world()

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("LEAK-SECRET-MESSAGE")

    monkeypatch.setattr(D, where, boom)
    res = run(w, monkeypatch)  # the output file holds stdout byte for byte
    line = D.UNEXPECTED.format(cls="RuntimeError") + "\n"
    if where == "draw":  # before the salts
        assert res.code == 4 and res.out.endswith(line + UNSALTED_TAIL), res.out
    else:  # after the salts
        assert res.code == 5 and res.out.endswith(line + SALTED_TAIL), res.out
    assert "LEAK" not in res.out and "Review list" not in res.out
    assert res.key.closed_text == "" and res.audit.closed_text == ""


def test_a_run_without_exactly_five_rows_stops_the_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 6: the order check holds the run record's counts.rows, not the rows fetched
    afterwards from /grades; a short run stops the draw, counts only."""
    w = world()
    rid = w.key_id("click", 2, 1)
    gone = w.grades[rid].pop()
    res = run(w, monkeypatch)
    assert res.code == 4, res.out
    assert res.out.endswith(D.ROW_COUNT_BAD.format(per=5, n=1) + "\n")
    assert rid not in res.out and rid[:8] not in res.out and gone["task_id"] not in res.out
    assert "Review list" not in res.out and res.key.closed_text == ""


def test_an_attempt_2_patch_from_step_3_is_in_the_key_and_not_in_the_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 7: one cobra commit is clean under both S1 runs and no other cobra S1 row is
    clean, so step 3 draws attempt 2 of it."""
    w = world()
    s1 = sorted(w.s1_of("cobra", 1), key=lambda i: w.runs[i]["created"])
    commit = w.grades[s1[0]][0]["task_id"]
    for repo, b in W.BATCH_KEYS:
        if repo == "cobra":
            for rid in w.s1_of(repo, b):
                for g in w.grades[rid]:
                    g["clean"] = rid in s1 and g["task_id"] == commit
    d = expected_draw(w)
    got = [(p.commit, p.attempt, p.step) for p in d.cells[("cobra", "S1")].patches]
    assert got[-1] == (commit, 2, 3) and len(got) == 2
    res = run(w, monkeypatch)
    assert res.code == 0, res.out
    lines = [ln for ln in res.key.closed_text.splitlines() if f"  cobra  S1  {commit}  " in ln]
    assert len(lines) == 2
    assert any(f"attempt 2  run {s1[1]}  step 3  " in ln for ln in lines)
    # the output lists the commit once per drawn patch (both S1 attempts, and A0's if drawn),
    # each under its own label, and nothing more of it
    listed = [ln for ln in res.out.splitlines() if commit in ln]
    n = sum(1 for p in d.ordered["cobra"] if p.commit == commit)
    assert n >= 2 and len(listed) == n and all(re.fullmatch(r"  cobra-\d\d  cobra  [0-9a-f]{40}", ln)
                                    for ln in listed)  # fmt: skip
    assert "attempt" not in res.out and "step 3" not in res.out
    assert s1[1] not in res.out and s1[1][:8] not in res.out


def test_no_figure_of_the_primary_read_is_computed() -> None:
    src = (ROOT / "scripts" / "wave4_review_draw.py").read_text()
    for name in ("compute(", "decide(", "build_batches", "primary_units", "usable_attempt",
                 "print_read", "events/log", "interval("):  # fmt: skip
        assert name not in src, name


@pytest.mark.parametrize("where", ["run record", "run body"])
def test_a_run_naming_its_repository_otherwise_fails_the_order_check(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """B2 item 2: R is "click or cobra, as the run body names it". The read's T5 holds every
    standing run record's repo to the batch's repository, and section 4 holds the body's repo
    to the record's, so a body naming "pallets/click" cannot reach the draw."""
    w = world()
    if where == "run record":
        w.runs[w.key_id("click", 1, 1)]["repo"] = "pallets/click"
    else:
        for body in w.bodies("click-1/1"):
            body["repo"] = "pallets/click"
    res = run(w, monkeypatch)
    assert res.code == 2, res.out
    assert "ORDER CHECK FAILED" in res.out and w.requested("grades") == set()


def _error_row_world() -> tuple[Any, str, str]:
    """The world with the one clean-true error row its only clean A0 row for that commit."""
    w = world()
    rid = w.a0_of("cobra", 2)[1]
    commit = w.grades[rid][0]["task_id"]
    for other in w.a0_of("cobra", 2):
        for g in w.grades[other]:
            if g["task_id"] == commit and other != rid:
                g["clean"] = False
    return w, rid, commit


def test_a_clean_row_with_an_error_is_not_drawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling Q4: clean only if the clean field is true AND the row carries no error. The old
    rule (the read's ``clean is True`` alone) drew this row's commit under A0."""
    w, _rid, commit = _error_row_world()
    res = run(w, monkeypatch)
    assert res.code == 0, res.out
    key = res.key.closed_text
    a0 = [line for line in key.splitlines() if f"  cobra  A0  {commit}  " in line]
    assert a0 == [], a0
    assert not any(p.commit == commit for p in expected_draw(w).cells[("cobra", "A0")].patches)
    assert "  cobra A0: " in key and "clean rows that carry an error 1\n" in key
    assert "Clean rows that carry an error, total across the 240 rows: 1\n" in key
    assert "LEAK" not in res.out and "LEAK" not in res.audit.closed_text


@pytest.mark.parametrize(("error", "clean"), [("", True), (None, True), ("x", False),
                                               (0, False), ("LEAK-ROW-ERROR", False)])  # fmt: skip
def test_row_is_clean_needs_the_field_and_no_error(error: Any, clean: bool) -> None:
    """A null or empty-string error is no error (the old rule took null as an error)."""
    assert D.row_is_clean(W.Row("r", cm("e"), True, error)) is clean
    assert D.row_is_clean(W.Row("r", cm("e"), False, error)) is False
    with pytest.raises(ValueError):
        D.row_is_clean(W.Row("r", cm("e"), True))  # no error field


def test_a_null_error_row_is_drawn_and_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    w, rid, commit = _error_row_world()
    w.grades[rid][0]["error"] = None
    res = run(w, monkeypatch)
    assert res.code == 0, res.out
    assert any(f"  cobra  A0  {commit}  " in ln for ln in res.key.closed_text.splitlines())
    assert "total across the 240 rows: 0\n" in res.key.closed_text
    assert D.WITH_ERROR_TOTAL.format(n=0) + "\n" in res.out


def test_the_output_prints_only_the_wave_wide_error_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world()
    w.grades[w.s1_of("click", 1)[0]][1] |= {"clean": True, "error": "LEAK-SECOND"}
    res = run(w, monkeypatch)
    assert res.code == 0, res.out
    lines = [ln for ln in res.out.splitlines() if "carry an error" in ln]
    assert lines == [D.WITH_ERROR_TOTAL.format(n=2)]
    assert "total across the 240 rows: 2\n" in res.key.closed_text
    assert "LEAK" not in res.out


@pytest.mark.parametrize("clean", [True, False])
def test_a_row_without_an_error_field_stops_the_draw(
    monkeypatch: pytest.MonkeyPatch, clean: bool
) -> None:
    """Ruling Q4: an absent error field (not null, not empty) stops the draw, counts only."""
    w = world()
    rid = w.key_id("click", 2, 1)
    row = w.grades[rid][0]
    row["clean"] = clean
    del row["error"]
    res = run(w, monkeypatch)
    assert res.code == 4, res.out
    assert D.NO_ERROR_FIELD.format(n=1) + "\n" in res.out
    assert "Review list" not in res.out
    assert rid not in res.out and rid[:8] not in res.out and row["task_id"] not in res.out
    assert res.key.closed_text == "" and res.audit.closed_text == ""


def test_the_audit_file_holds_no_salt_sequence_position_or_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling Q2: the audit file carries Paul's ten under reviewer labels in a salted order;
    no salt, no B3 order or position, no arm, attempt, run id or step."""
    w = world()
    res = run(w, monkeypatch)
    assert res.code == 0, res.out
    audit, key = res.audit.closed_text, res.key.closed_text
    assert f"{SALT}-1" not in audit and f"{SALT}-2" not in audit
    assert f"audit file salt {SALT}-2\n" in key
    # a random line that orders nothing, so the file's sha256 cannot be matched by guessing
    assert f"file id {SALT}-3\n" in audit and f"{SALT}-3" not in key
    assert f"{SALT}-3" not in res.out
    with pytest.raises(ValueError):
        D.audit_text(expected_draw(w), D.label(expected_draw(w), "k"), "s", "")
    low = audit.replace(f"file id {SALT}-3\n", "").lower()  # the made-up id holds "salt"
    for word in ("sequence", "position", "attempt", "step", "run", "salt", "a0", "s1"):
        assert not re.search(rf"\b{word}\b", low), word
    for rid in w.all_ids():
        assert rid not in audit and rid[:8] not in audit
    assert "Check in this sequence" not in audit
    assert ("All 10 patches below are to be checked. Give a verdict on each before being told "
            "the arm or the reviewer's verdict.\n") in audit  # fmt: skip
    listed = [ln.split()[0] for ln in audit.splitlines() if ln.startswith("  ")]
    assert len(listed) == 10
    d = expected_draw(w)
    lab = D.label(d, f"{SALT}-1")
    b3 = list(lab.audit_labels(d))
    assert sorted(listed) == sorted(b3)
    assert listed == sorted(listed, key=lambda x: hashlib.sha256(
        f"crb.wave4.auditfile|{SALT}-2|{x}".encode()).hexdigest())  # fmt: skip
    # the salt moves the order; without it the B3 order is not what the file shows
    other = [lab.label_of[p] for p in D.audit_file_order(lab, d, "another")]
    assert other != listed and listed != b3
    with pytest.raises(ValueError):
        D.audit_file_order(lab, d, "")


def test_step_counts_note_is_not_a_departure() -> None:
    """Ruling Q3: the wave report prints the step counts after the review."""
    note = D.STEP_COUNTS_NOTE.lower()
    assert "departure" not in note and "ruling" not in note
    assert "wave report" in note and "sha256" in note
    doc = D.__doc__ or ""
    assert "departure" not in doc and "wave report" in doc


def test_docstring_matches_the_labels_and_records_the_rulings() -> None:
    doc = " ".join((D.__doc__ or "").split())
    assert "R-01" not in doc and "``click-01``" in doc
    assert "R-01" not in (D.label.__doc__ or "")
    assert "delivery manager confirms in writing" in doc
    assert '"reviewed patches"' in doc and "recomputed over the reviewed patches" in doc
    assert "signed by the methodologist on 2026-11-12" in doc
    assert "docs/reviews/2026-11-10-wave-4-registration/wave-record-notes.md" in doc
    assert "Check in this sequence" not in (ROOT / "scripts" / "wave4_review_draw.py").read_text()


def test_the_docstrings_state_the_residual_b3_leak_and_no_stronger_claim() -> None:
    """Findings 3 and 4: the script adds no arm information, but B3's public hash (which
    includes the arm) still lets a reader guess arms and the audit set better than chance."""
    src = (ROOT / "scripts" / "wave4_review_draw.py").read_text()
    assert "nobody holding it can recompute anything" not in src
    for text in (D.__doc__ or "", D.audit_text.__doc__ or ""):
        flat = " ".join(text.split())
        assert "adds no arm information" in flat
        assert "public and includes the arm" in flat
        assert "guess arms better than chance" in flat
        assert "recorded in the wave record" in flat and "without changing B3" in flat
    assert "guess the audit set better than chance" in " ".join((D.__doc__ or "").split())


def test_a_read_module_loaded_from_elsewhere_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = ModuleType(D.READ_NAME)
    fake.__file__ = str(tmp_path / "wave4_primary_read.py")
    monkeypatch.setitem(sys.modules, D.READ_NAME, fake)
    with pytest.raises(D.ReadModuleError):
        D._load_read()
    monkeypatch.setitem(sys.modules, D.READ_NAME, W)
    assert D._load_read() is W
