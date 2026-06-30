"""Hermetic tests for the commit-replay benchmark — encodes the real bugs hit
during its bring-up as regressions (brittle parser, response field, fuzzy apply)."""

from __future__ import annotations

from commit_replay_bench import core as cr

_CLEAN = """<<<<<<< SEARCH
    return n or ""
=======
    return n if n is not None else ""
>>>>>>> REPLACE"""


# --- the tolerant parser must survive the variants the model actually emits ----
def test_parser_handles_clean_block():
    assert cr.parse_edit_blocks(_CLEAN) == [('    return n or ""', '    return n if n is not None else ""')]


def test_parser_tolerates_marker_variations():
    # these all broke a strict regex and silently dropped the edit
    assert len(cr.parse_edit_blocks(_CLEAN.replace("=======", "======= "))) == 1   # trailing space
    assert len(cr.parse_edit_blocks(_CLEAN.replace("=======", "========"))) == 1   # 8 equals
    assert len(cr.parse_edit_blocks(_CLEAN.replace("\n", "\r\n"))) == 1            # CRLF
    assert len(cr.parse_edit_blocks("  " + _CLEAN)) == 1                           # leading space
    assert cr.parse_edit_blocks("no markers here") == []


# --- fuzzy apply ----------------------------------------------------------------
def test_apply_exact_and_fuzzy():
    src = "def f(n):\n    return n or ''\n"
    new, applied = cr.apply_edit_blocks(src, [("    return n or ''", "    return n if n is not None else ''")])
    assert applied == 1 and "is not None" in new
    # fuzzy: model got the indentation wrong but the content right → still applies
    new2, applied2 = cr.apply_edit_blocks(src, [("return n or ''", "    return 42")])
    assert applied2 == 1 and "return 42" in new2
    # genuinely absent search → does not apply
    _, applied3 = cr.apply_edit_blocks(src, [("nonexistent line", "x")])
    assert applied3 == 0


# --- grading --------------------------------------------------------------------
def test_grade_three_ways():
    assert cr.grade(target_passed=True, regressed=False, succeeded_attempt=1) == cr.AI_CAN
    assert cr.grade(target_passed=True, regressed=False, succeeded_attempt=2) == cr.NEEDS_HUMAN  # retry
    assert cr.grade(target_passed=True, regressed=True, succeeded_attempt=1) == cr.NEEDS_HUMAN   # broke others
    assert cr.grade(target_passed=False, regressed=False, succeeded_attempt=None) == cr.FAILS


# --- orchestration via a fake harness ------------------------------------------
class FakeHarness:
    """Scripts test outcomes; records what the model is asked to fix."""

    def __init__(self, *, target_seq, full_failed=None):
        # target_seq: rc per run_tests(target) call, consumed in order
        self.target_seq = list(target_seq)
        self.full_failed = full_failed or [set()]  # failed-id set per full run, in order
        self._full_i = 0
        self.prior_failures = []

    def reset(self): ...
    def checkout_parent(self, c): ...
    def overlay_tests(self, c, t): ...
    def read(self, p): return "SRC"
    def write(self, p, c): ...
    def restore_parent(self, c, p): ...
    def run_tests(self, paths):
        if paths == ["tests"]:
            f = self.full_failed[min(self._full_i, len(self.full_failed) - 1)]
            self._full_i += 1
            return cr.TestRun(1 if f else 0, set(f), "full")
        rc = self.target_seq.pop(0)
        return cr.TestRun(rc, set(), "RED tail" if rc else "")


def _spec():
    return cr.CommitSpec("abc", "fix it", "m.py", ["tests/test_m.py"], "S")


def _gen_ok(**k):
    return [("SRC", "FIXED")]  # applies (SRC is in the fake read)


def test_valid_python_gate():
    assert cr.valid_python("def f():\n    return 1\n", "x.py") == (True, "")
    ok, err = cr.valid_python("def f(:\n", "x.py")
    assert ok is False and "line" in err
    assert cr.valid_python("this is not { python", "x.js")[0] is True  # non-py skipped


def test_replay_retries_on_syntax_breaking_edit():
    # attempt 1's edit breaks Python syntax → gate catches it (no test run, no
    # whole-suite crash) → retry; attempt 2 is valid + GREEN.
    seq = {"n": 0}
    def gen(**k):
        seq["n"] += 1
        return [("SRC", "def broken(:" if seq["n"] == 1 else "FIXED")]
    h = FakeHarness(target_seq=[1, 0], full_failed=[set(), set()])  # oracle RED, then GREEN on the valid attempt
    r = cr.replay_commit(h, _spec(), gen, max_attempts=2)
    assert seq["n"] == 2                       # retried after the invalid-python attempt
    assert r.verdict == cr.NEEDS_HUMAN         # succeeded only on attempt 2


def test_replay_ai_can_first_try():
    # target: RED(oracle check), then GREEN(after edit); full: baseline empty, after empty
    h = FakeHarness(target_seq=[1, 0], full_failed=[set(), set()])
    r = cr.replay_commit(h, _spec(), _gen_ok, max_attempts=2)
    assert r.verdict == cr.AI_CAN and r.attempts == 1 and r.target_passed


def test_replay_needs_human_on_regression():
    # GREEN on target but the full suite gains a new failure → needs_human
    h = FakeHarness(target_seq=[1, 0], full_failed=[set(), {"tests/x::t"}])
    r = cr.replay_commit(h, _spec(), _gen_ok, max_attempts=2)
    assert r.verdict == cr.NEEDS_HUMAN and r.regressed


def test_replay_fails_when_never_green():
    h = FakeHarness(target_seq=[1, 1, 1], full_failed=[set(), set(), set(), set()])
    r = cr.replay_commit(h, _spec(), _gen_ok, max_attempts=2)
    assert r.verdict == cr.FAILS


def test_replay_skips_when_no_red_oracle():
    h = FakeHarness(target_seq=[0])  # commit's tests already pass on the parent
    r = cr.replay_commit(h, _spec(), _gen_ok)
    assert r.verdict == cr.SKIP


def test_prior_failure_fed_back_on_retry():
    # first attempt produces a non-applying edit → second attempt gets prior_failure
    seen = []
    def gen(**k):
        seen.append(k["prior_failure"])
        return [] if len(seen) == 1 else [("SRC", "FIXED")]
    h = FakeHarness(target_seq=[1, 0], full_failed=[set(), set()])
    r = cr.replay_commit(h, _spec(), gen, max_attempts=2)
    assert seen[0] is None and seen[1] is not None   # retry carried feedback
    assert r.verdict == cr.NEEDS_HUMAN               # succeeded only on attempt 2


def test_aggregate():
    rs = [
        cr.ReplayResult("a", "S", cr.AI_CAN, 1, 1, 1, True, False),
        cr.ReplayResult("b", "S", cr.FAILS, 3, 1, 1, False, False),
        cr.ReplayResult("c", "M", cr.NEEDS_HUMAN, 2, 1, 1, True, False),
        cr.ReplayResult("d", "S", cr.SKIP, 0, 0, 0, False, False),
    ]
    agg = cr.aggregate(rs)
    assert agg["n"] == 3 and agg["skipped"] == 1
    assert agg["counts"] == {cr.AI_CAN: 1, cr.NEEDS_HUMAN: 1, cr.FAILS: 1}
    assert agg["by_complexity"]["S"][cr.AI_CAN] == 1


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
