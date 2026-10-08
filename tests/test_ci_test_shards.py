"""The Python suite's shards — every test runs in exactly one shard, under the same required names.

The hermetic suite ran in one job per Python version until py3.13 took 58 of its 60 minutes on
PR #57 (docs/PREVENTION.md P-053). It now runs in N parallel ``test-shard`` jobs per version,
and the required contexts ``test (py3.12)`` and ``test (py3.13)`` moved onto aggregators that
prove the split lowered no gate. These tests hold that in place: a split that dropped a test,
ran one twice, left a shard empty, let an aggregator miss a shard, renamed a required context
or loosened the coverage threshold fails the build.

Navigation
----------
What it is:   Tests of scripts/ci_test_shards.py (the partition, the pytest plugin, the
              ``verify`` proof) and of the ``test-shard`` / ``test`` jobs in ci.yml.
What it does: Pins that ``partition`` puts every file in exactly one shard, deterministically,
              within one file's weight of balance, and refuses an empty shard; that
              ``verify_reports`` rejects a missing, doubled or stray test, an empty shard, a
              missing report, a wrong shard count and shards that collected different suites;
              that the plugin, run by pytest over a small suite, partitions what ``-m`` left
              (never what it removed) and writes reports ``verify`` accepts. In ci.yml: the
              aggregator renders exactly the two required context names, ``needs`` every job
              that loads the plugin, runs ``if: always()``, fails unless every shard succeeded,
              runs ``verify`` over all N reports and ``coverage report --fail-under=70`` on the
              combined data; each shard runs the old job's command unchanged but for the shard
              and coverage-data options, the matrix lists 1..N, the name states N, and N
              leaves no shard empty. ``weights`` keeps each file's largest measurement, never
              a sum, and ``verify`` prints the table's own refresh recipe (P-741); no test
              module that imports another's harness runs a test that module runs (P-742).
              The fresh-clone suite is split the same N ways: its aggregator needs the gates
              job and every shard, passes only when every part did and proves the partition,
              and each shard fits its budget as root (P-743). No step of either aggregator
              may carry an ``if:`` but ``always()`` (P-746).
How:          Pure calls with synthetic ids and weights; one pytest subprocess per shard over a
              suite written to ``tmp_path``; ``ci.yml`` read as text with the job parser of
              tests/test_ci_job_budget.py.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/ci_test_shards.py (the partition, plugin and proof under test),
              scripts/ci_test_weights.json (the per-file seconds the budget test reads),
              .github/workflows/ci.yml (the ``test-shard`` and ``test`` jobs it pins),
              tests/test_ci_job_budget.py (the job parser and the budget guard's own tests),
              docs/PREVENTION.md (P-053, P-740, P-741, P-742 — the classes these tests
              close)
Tested by:    (this is a test file)
Touch when:   never for a new repository (it reads this repository's own CI); the shard count
              changes (the matrix, the job names and ``--shards`` move together); the test
              command changes (change it here deliberately, in the same commit).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from test_ci_job_budget import ALL_PASSED_JQ, _jobs, _needs, _steps

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
SCRIPTS = ROOT / "scripts"
#: Branch protection matches these character for character (read 2026-09-27).
REQUIRED_TEST_CONTEXTS = {"test (py3.12)", "test (py3.13)"}
#: The single job's command before the split: every shard runs exactly this, plus its shard
#: and coverage-data options — nothing else selects or deselects a test.
SUITE_COMMAND = '.venv/bin/pytest -q -m "not sandbox_images"'
#: A shard's time outside its tests: checkout, install, helm, collection (about 70 s in PR
#: #57's logs, doubled).
SETUP_ALLOWANCE_S = 150
#: Each aggregator whose parts load the shard plugin → that shard job. ``fresh-clone`` runs
#: the same suite as root on a fresh clone, split the same N ways (P-743).
SHARDED = {"test": "test-shard", "fresh-clone": "fresh-clone-shard"}
#: The fresh-clone suite ran 63.8 min as root where the weights predict 54.5 for the runner
#: user (its first run, 2026-09-28: no uv cache, root's own ~/.m2 and npm caches), so its
#: shards are predicted at this multiple of the weights.
ROOT_SLOWDOWN = 1.2


def _shards() -> ModuleType:
    if "ci_test_shards" in sys.modules:
        return sys.modules["ci_test_shards"]
    spec = importlib.util.spec_from_file_location("ci_test_shards", SCRIPTS / "ci_test_shards.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ci_test_shards"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ids(files: dict[str, int]) -> list[str]:
    return [f"{f}::test_{i}" for f, n in files.items() for i in range(n)]


SAMPLE = {
    f"tests/test_{c}.py": n
    for c, n in zip("abcdefghij", [5, 1, 9, 2, 2, 7, 3, 1, 4, 6], strict=True)
}


# --- the partition ------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(1, 11))
def test_every_file_lands_in_exactly_one_shard_and_no_shard_is_empty(n: int) -> None:
    m = _shards()
    weights = m.Weights(files={"tests/test_c.py": 90.0, "tests/test_f.py": 30.0}, per_test_s=0.5)
    parts = m.partition(SAMPLE, n, weights)
    assert len(parts) == n
    assert all(parts), "an empty shard"
    flat = [f for p in parts for f in p]
    assert sorted(flat) == sorted(SAMPLE)
    ids = _ids(SAMPLE)
    union = [i for k in range(1, n + 1) for i in m.select(ids, k, n, weights)]
    assert sorted(union) == sorted(ids)


def test_the_partition_depends_on_the_suite_not_on_collection_order() -> None:
    m = _shards()
    weights = m.Weights(per_test_s=1.0)
    items = list(SAMPLE.items())
    random.Random(7).shuffle(items)
    assert m.partition(dict(items), 4, weights) == m.partition(SAMPLE, 4, weights)


def test_the_shards_are_within_one_files_weight_of_each_other() -> None:
    """Longest-first onto the lightest shard: the heaviest shard's last file went onto what
    was then the lightest, so no two shards differ by more than the heaviest file."""
    m = _shards()
    weights = m.load_weights()
    counts = dict.fromkeys(weights.files, 1)
    for n in (2, 4, 6, 8):
        loads = [sum(weights.cost(f, 1) for f in p) for p in m.partition(counts, n, weights)]
        assert max(loads) - min(loads) <= max(weights.cost(f, 1) for f in counts)


def test_a_file_the_weights_do_not_list_weighs_its_test_count() -> None:
    m = _shards()
    weights = m.Weights(files={"tests/test_known.py": 12.0}, per_test_s=0.25)
    assert weights.cost("tests/test_known.py", 999) == 1200
    assert weights.cost("tests/test_new.py", 40) == 1000
    assert weights.cost("tests/test_instant.py", 0) == 1  # never zero: it still counts


def test_a_shard_that_would_be_empty_or_a_bad_spec_is_refused() -> None:
    m = _shards()
    with pytest.raises(m.ShardError, match="empty"):
        m.partition({"tests/test_a.py": 3, "tests/test_b.py": 1}, 3, m.Weights())
    for bad in ("0/3", "4/3", "3", "a/b", "1/0"):
        with pytest.raises(m.ShardError):
            m.parse_spec(bad)
    assert m.parse_spec("6/6") == (6, 6)


def test_the_weights_file_is_well_formed_and_covers_a_real_suite() -> None:
    data = json.loads((SCRIPTS / "ci_test_weights.json").read_text("utf-8"))
    assert data["per_test_seconds_default"] > 0
    assert all(k.startswith("tests/") and k.endswith(".py") for k in data["files"])
    assert all(v >= 0 for v in data["files"].values())


# --- the proof the required job runs ------------------------------------------------------


def _reports(n: int, files: dict[str, int] | None = None) -> list[dict[str, Any]]:
    m = _shards()
    ids = _ids(files or SAMPLE)
    weights = m.Weights(per_test_s=1.0)
    return [
        {
            "shard": k,
            "of": n,
            "python": "3.12",
            "collected": list(ids),
            "selected": m.select(ids, k, n, weights),
            "durations": {},
        }
        for k in range(1, n + 1)
    ]


def test_a_true_partition_is_proven() -> None:
    assert _shards().verify_reports(_reports(4), 4) == []


def _one_error(reports: list[dict[str, Any]], n: int, needle: str) -> None:
    errors = _shards().verify_reports(reports, n)
    assert errors, "a broken partition was accepted"
    assert any(needle in e for e in errors), errors


def test_a_test_that_ran_in_no_shard_fails() -> None:
    r = _reports(3)
    r[1]["selected"] = r[1]["selected"][1:]
    _one_error(r, 3, "ran in no shard")


def test_a_test_that_ran_in_two_shards_fails() -> None:
    r = _reports(3)
    r[2]["selected"].append(r[0]["selected"][0])
    _one_error(r, 3, "more than one shard")


def test_an_empty_shard_fails() -> None:
    r = _reports(3)
    r[0]["selected"], r[1]["selected"] = [], r[1]["selected"] + r[0]["selected"]
    _one_error(r, 3, "ran no tests")


def test_a_missing_report_or_a_wrong_count_fails() -> None:
    _one_error(_reports(3)[:2], 3, "expected one report from each shard 1..3")
    _one_error(_reports(3), 4, "expected one report")
    r = _reports(3)
    r[0]["of"] = 2
    _one_error(r, 3, "split the suite 2 ways")
    _one_error([], 3, "expected one report")


def test_shards_that_collected_different_suites_fail() -> None:
    r = _reports(2)
    r[1]["collected"] = r[1]["collected"][:-1]
    _one_error(r, 2, "different suite")


def test_a_test_a_shard_never_collected_fails() -> None:
    r = _reports(2)
    r[0]["selected"].append("tests/test_zz.py::ghost")
    _one_error(r, 2, "never collected")


def test_verify_on_the_command_line_writes_the_summary_and_fails_a_broken_split(
    tmp_path: Path,
) -> None:
    m = _shards()
    paths = []
    for rep in _reports(2):
        p = tmp_path / f"shard-{rep['shard']}.json"
        p.write_text(json.dumps(rep), "utf-8")
        paths.append(str(p))
    summary = tmp_path / "summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(summary)}
    assert m.main(["verify", "--shards", "2", "--python", "3.12", *paths], env) == 0
    assert "ran in exactly one of 2 shards" in summary.read_text("utf-8")
    assert m.main(["verify", "--shards", "2", "--python", "3.13", *paths], env) == 1
    assert m.main(["verify", "--shards", "3", *paths], env) == 1
    assert "SHARDS DO NOT PARTITION THE SUITE" in summary.read_text("utf-8")


def test_weights_are_refreshed_from_the_reports_measured_seconds() -> None:
    r = _reports(2)
    r[0]["durations"] = {"tests/test_a.py": 3.0}
    r[1]["durations"] = {"tests/test_c.py": 6.0}
    fresh = _shards().refreshed_weights(r)
    assert fresh["files"] == {"tests/test_a.py": 3.0, "tests/test_c.py": 6.0}
    assert fresh["per_test_seconds_default"] == round(9.0 / sum(SAMPLE.values()), 2)


def test_weights_keep_each_files_largest_measurement_across_runs_and_versions() -> None:
    """A file runs in one shard per run, so a second report of it is another run or the other
    Python version: its seconds are a second measurement, not more work. Summing them inflated
    the table 1.6 times over PR #69's two versions and made the stale gate duller."""
    m = _shards()
    py12, py13, again = _reports(2), _reports(2), _reports(2)
    for r in py13:
        r["python"] = "3.13"
    py12[0]["durations"] = {"tests/test_a.py": 3.0}
    py12[1]["durations"] = {"tests/test_c.py": 6.0}
    py13[0]["durations"] = {"tests/test_a.py": 5.0}
    py13[1]["durations"] = {"tests/test_c.py": 4.0}
    again[0]["durations"] = {"tests/test_a.py": 4.0}
    again[1]["durations"] = {"tests/test_c.py": 7.0}
    fresh = m.refreshed_weights(py12 + py13 + again)
    assert fresh["files"] == {"tests/test_a.py": 5.0, "tests/test_c.py": 7.0}
    assert fresh["per_test_seconds_default"] == round(12.0 / sum(SAMPLE.values()), 2)


def test_verify_and_the_weights_table_give_the_same_refresh_recipe(tmp_path: Path) -> None:
    """The recipe verify prints is the one the table's own ``_about`` states, word for word."""
    m = _shards()
    about = json.loads((ROOT / "scripts" / "ci_test_weights.json").read_text("utf-8"))["_about"]
    assert m.REFRESH_RECIPE in about
    table = tmp_path / "weights.json"
    table.write_text(
        json.dumps({"per_test_seconds_default": 1.0, "files": {"tests/test_a.py": 10.0}}), "utf-8"
    )
    paths = []
    for rep in _timed({"tests/test_a.py": 300.0}):
        p = tmp_path / f"shard-{rep['shard']}.json"
        p.write_text(json.dumps(rep), "utf-8")
        paths.append(str(p))
    summary = tmp_path / "summary.md"
    m.main(
        ["verify", "--shards", "2", "--weights", str(table), *paths],
        {"GITHUB_STEP_SUMMARY": str(summary)},
    )
    assert m.REFRESH_RECIPE in summary.read_text("utf-8")


def _timed(durations: dict[str, float]) -> list[dict[str, Any]]:
    """Two shard reports whose measured per-file seconds are ``durations``."""
    r = _reports(2)
    files = sorted(durations)
    r[0]["durations"] = {f: durations[f] for f in files[::2]}
    r[1]["durations"] = {f: durations[f] for f in files[1::2]}
    return r


def test_weights_a_run_measured_close_to_are_not_stale() -> None:
    """A run a little slower than the table must not trip it (the table is each file's largest
    measurement over several runs, so a runner's spread sits under it: P-741)."""
    m = _shards()
    weights = m.Weights(files={"tests/test_a.py": 100.0, "tests/test_c.py": 400.0})
    assert (
        m.stale_weights(_timed({"tests/test_a.py": 130.0, "tests/test_c.py": 520.0}), weights) == []
    )
    assert m.stale_weights(_reports(2), weights) == []  # a run that measured nothing says nothing


def test_a_file_that_outgrew_its_weight_makes_the_weights_stale() -> None:
    """P-740: tests/test_factory_loop.py was weighed at 158 s and took 880; the budget test read
    the weight, predicted every shard under half its timeout, and a shard crept to 81 %."""
    m = _shards()
    weights = m.Weights(files={"tests/test_a.py": 158.0, "tests/test_c.py": 400.0})
    errors = m.stale_weights(_timed({"tests/test_a.py": 880.0, "tests/test_c.py": 410.0}), weights)
    assert errors == ["tests/test_a.py took 880 s against its weight of 158 s"]


def test_files_the_weights_do_not_list_make_them_stale_past_a_tenth_of_the_run() -> None:
    m = _shards()
    weights = m.Weights(files={"tests/test_a.py": 900.0})
    assert (
        m.stale_weights(_timed({"tests/test_a.py": 900.0, "tests/test_c.py": 90.0}), weights) == []
    )
    (error,) = m.stale_weights(
        _timed({"tests/test_a.py": 900.0, "tests/test_c.py": 90.0, "tests/test_d.py": 60.0}),
        weights,
    )
    assert "2 test file(s) the weights do not list took 14% of this run's seconds" in error
    assert "the heaviest tests/test_c.py at 90 s" in error


def test_verify_fails_on_stale_weights_and_says_how_to_refresh_them(tmp_path: Path) -> None:
    m = _shards()
    table = tmp_path / "weights.json"
    table.write_text(
        json.dumps({"per_test_seconds_default": 1.0, "files": {"tests/test_a.py": 10.0}}), "utf-8"
    )
    paths = []
    for rep in _timed({"tests/test_a.py": 300.0}):
        p = tmp_path / f"shard-{rep['shard']}.json"
        p.write_text(json.dumps(rep), "utf-8")
        paths.append(str(p))
    summary = tmp_path / "summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(summary)}
    assert m.main(["verify", "--shards", "2", "--weights", str(table), *paths], env) == 1
    text = summary.read_text("utf-8")
    assert "ran in exactly one of 2 shards" in text  # the partition itself is proven
    assert "THE SHARD WEIGHTS ARE STALE" in text and "tests/test_a.py took 300 s" in text
    assert "python3 scripts/ci_test_shards.py weights" in text


# --- the plugin, run by pytest ------------------------------------------------------------


def _mini_suite(root: Path) -> None:
    (root / "pytest.ini").write_text(
        "[pytest]\naddopts = -p no:cacheprovider\nmarkers =\n    heavy: deselected by -m\n",
        "utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    for name, n in (("alpha", 3), ("beta", 2), ("gamma", 4), ("delta", 1)):
        body = "import pytest\n\n" + "".join(f"def test_{i}():\n    pass\n\n" for i in range(n))
        body += "@pytest.mark.heavy\ndef test_heavy():\n    raise AssertionError('deselected')\n"
        (tests / f"test_{name}.py").write_text(body, "utf-8")
    (root / "weights.json").write_text(
        json.dumps({"per_test_seconds_default": 1.0, "files": {"tests/test_gamma.py": 50}}),
        "utf-8",
    )


def _pytest(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", "not heavy", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_plugin_partitions_what_m_left_and_its_reports_prove_it(tmp_path: Path) -> None:
    _mini_suite(tmp_path)
    full = _pytest(tmp_path, "--collect-only")
    assert full.returncode == 0, full.stdout + full.stderr
    suite = sorted(ln for ln in full.stdout.splitlines() if "::" in ln)
    assert len(suite) == 10 and not any("heavy" in i for i in suite)
    ran: list[str] = []
    reports = []
    for k in (1, 2, 3):
        rep = tmp_path / f"shard-{k}.json"
        done = _pytest(
            tmp_path,
            "-p",
            "ci_test_shards",
            f"--shard={k}/3",
            f"--shard-report={rep}",
            f"--shard-weights={tmp_path / 'weights.json'}",
            "-rA",
        )
        assert done.returncode == 0, done.stdout + done.stderr
        ran += re.findall(r"^PASSED (\S+)", done.stdout, re.M)
        reports.append(json.loads(rep.read_text("utf-8")))
    assert sorted(ran) == suite  # every test ran, once
    assert sorted(reports[0]["collected"]) == suite  # the plugin saw the suite after -m
    assert _shards().verify_reports(reports, 3) == []
    # the heaviest file (by the weights) is alone in its shard
    assert any(
        {i.split("::")[0] for i in r["selected"]} == {"tests/test_gamma.py"} for r in reports
    )
    assert all(r["durations"] and r["exitstatus"] == 0 for r in reports)


def test_the_plugin_refuses_a_bad_spec_and_an_empty_shard(tmp_path: Path) -> None:
    _mini_suite(tmp_path)
    bad = _pytest(tmp_path, "-p", "ci_test_shards", "--shard=4/3")
    assert bad.returncode == 4 and "need 1 <= k <= N" in bad.stderr
    empty = _pytest(tmp_path, "-p", "ci_test_shards", "--shard=1/5")
    assert empty.returncode == 4 and "leave a shard empty" in empty.stderr


def test_a_shard_option_given_after_a_space_is_refused(tmp_path: Path) -> None:
    """pytest finds its configuration file before it loads the plugin, so ``--shard-report
    PATH`` with a space reads PATH as a test path: the rootdir moves beside it and the suite
    runs under whatever configuration file sits above PATH, or none — no markers, no timeout,
    no ``pythonpath`` (it did, locally, while this was built: a shard's collection failed).
    The plugin refuses the spaced form instead of passing under the wrong configuration."""
    suite = tmp_path / "suite"
    suite.mkdir()
    _mini_suite(suite)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    lost = _pytest(
        suite, "-p", "ci_test_shards", "--shard=1/2", "--shard-report", str(elsewhere / "r.json")
    )
    assert lost.returncode == 4 and "as --option=value" in lost.stderr
    kept = _pytest(
        suite, "-p", "ci_test_shards", "--shard=1/2", f"--shard-report={elsewhere / 'r.json'}"
    )
    assert kept.returncode == 0, kept.stdout + kept.stderr


# --- the CI configuration ------------------------------------------------------------------


def _matrix(body: list[str], key: str) -> list[str]:
    line = next(ln for ln in body if re.match(rf"^\s+{key}:\s*\[", ln))
    inner = re.search(r"\[(.*)\]", line)
    assert inner is not None
    return [v.strip().strip("\"'") for v in inner.group(1).split(",") if v.strip()]


def _name(body: list[str]) -> str:
    return next(ln for ln in body if ln.startswith("    name:")).split(":", 1)[1].strip()


def _timeout(body: list[str]) -> int:
    line = next(ln for ln in body if ln.startswith("    timeout-minutes:"))
    return int(line.split(":", 1)[1])


def _shard_count() -> int:
    body = _jobs(CI.read_text("utf-8"))["test-shard"]
    m = re.search(r"of (\d+)\)$", _name(body))
    assert m is not None, "the shard job's name must state N"
    return int(m.group(1))


def test_the_required_contexts_keep_their_exact_names_on_the_aggregator() -> None:
    body = _jobs(CI.read_text("utf-8"))["test"]
    template = _name(body)
    rendered = {template.replace("${{ matrix.python }}", v) for v in _matrix(body, "python")}
    assert rendered == REQUIRED_TEST_CONTEXTS
    assert "shard" not in template


def test_the_aggregator_needs_every_shard_job_and_passes_only_when_every_part_did() -> None:
    jobs = _jobs(CI.read_text("utf-8"))
    body = jobs["test"]
    text = "\n".join(body) + "\n"
    loaders = {j for j, b in jobs.items() if "-p ci_test_shards" in "\n".join(b)}
    assert loaders == set(SHARDED.values()), "every job that loads the plugin is a known part"
    assert set(_needs(body)) == {"test-shard"}
    assert re.search(r"^    if: always\(\)\s*$", text, re.M)
    steps = _steps(body)
    gate = [s for s in steps if "toJSON(needs)" in s]
    assert len(gate) == 1 and f"jq -e '{ALL_PASSED_JQ}'" in gate[0]
    # continue-on-error only where it cannot hide a verdict: the coverage.xml upload
    soft = [s for s in steps if "continue-on-error" in s]
    assert len(soft) == 1 and "name: coverage-py" in soft[0]
    assert _matrix(body, "python") == _matrix(jobs["test-shard"], "python")


def test_the_aggregator_proves_the_partition_over_every_shards_report() -> None:
    n = _shard_count()
    steps = _steps(_jobs(CI.read_text("utf-8"))["test"])
    proof = [s for s in steps if "ci_test_shards.py verify" in s]
    assert len(proof) == 1
    cmd = " ".join(proof[0].split())
    assert f"verify --shards {n} --python ${{{{ matrix.python }}}}" in cmd
    assert re.findall(r"shards/shard-(\d+)\.json", cmd) == [str(k) for k in range(1, n + 1)]
    download = next(s for s in steps if "download-artifact" in s)
    assert "pattern: test-shard-py${{ matrix.python }}-*" in download
    upload = next(
        s for s in _steps(_jobs(CI.read_text("utf-8"))["test-shard"]) if "upload-artifact" in s
    )
    assert "name: test-shard-py${{ matrix.python }}-${{ matrix.shard }}" in upload
    assert "continue-on-error" not in upload


def aggregator_step_findings(ci_text: str) -> list[str]:
    """Each step of a sharded suite's aggregator that can be skipped: an ``if:`` other than
    ``always()`` — ``if: false`` on the every-shard-passed step or the partition proof leaves
    the aggregator green over failed shards (P-746)."""
    jobs = yaml.safe_load(ci_text)["jobs"]
    return [
        f"{agg}: step {step.get('name') or step.get('uses')!r} runs only if {step['if']!r}"
        for agg in SHARDED
        for step in jobs[agg].get("steps", [])
        if str(step.get("if", "always()")).strip() not in ("always()", "${{ always() }}")
    ]


def test_no_aggregator_step_can_be_skipped() -> None:
    assert aggregator_step_findings(CI.read_text("utf-8")) == []


@pytest.mark.parametrize(
    "step",
    [
        "      - name: Every shard passed (both Python versions)\n",
        "      - name: Every test ran in exactly one shard (the partition proof)\n",
        "      - name: coverage >= 70 on the union of the shards\n",
        "      - name: Every part passed (the gates and every shard)\n",
    ],
)
def test_the_step_check_refuses_an_aggregator_step_that_never_runs(step: str) -> None:
    text = CI.read_text("utf-8")
    assert step in text, step
    planted = text.replace(step, f"{step}        if: false\n")
    assert aggregator_step_findings(planted) != [], step


def test_coverage_is_enforced_at_70_percent_or_more_on_the_union() -> None:
    steps = _steps(_jobs(CI.read_text("utf-8"))["test"])
    cov = [s for s in steps if "coverage combine" in s]
    assert len(cov) == 1
    assert re.search(r"coverage combine --keep shards/shard-\*\.coverage", cov[0])
    m = re.search(r"coverage report --fail-under=(\d+)", cov[0])
    assert m is not None and int(m.group(1)) >= 70
    assert cov[0].index("combine") < cov[0].index("report")


def test_each_shard_runs_the_old_command_with_only_its_shard_and_coverage_data_added() -> None:
    n = _shard_count()
    body = _jobs(CI.read_text("utf-8"))["test-shard"]
    assert _matrix(body, "shard") == [str(k) for k in range(1, n + 1)]
    runs = [s for s in _steps(body) if ".venv/bin/pytest" in s]
    assert len(runs) == 1
    cmd = " ".join(runs[0].split("run: >-", 1)[1].split())
    expected = (
        f"{SUITE_COMMAND} -p ci_test_shards --shard=${{{{ matrix.shard }}}}/{n} "
        "--shard-report=shard-report/shard-${{ matrix.shard }}.json "
        "--cov=crb --cov-branch --cov-report= --cov-fail-under=0"
    )
    assert cmd == expected
    assert "PYTHONPATH: scripts" in runs[0]


def test_the_shard_count_leaves_no_shard_empty_and_fits_the_budget() -> None:
    """N shards over the suite's test files, each predicted at most half its timeout."""
    m = _shards()
    n = _shard_count()
    weights = m.load_weights()
    # every test file on disk, not only the ones the table lists: a file the table does not
    # know weighs its test count at the default (P-740 — 68 unlisted files were invisible here)
    counts = {
        str(f.relative_to(ROOT)): max(1, f.read_text("utf-8").count("\ndef test_"))
        for f in sorted((ROOT / "tests").glob("test_*.py"))
    }
    parts = m.partition(counts, n, weights)
    assert all(parts)
    budget_s = _timeout(_jobs(CI.read_text("utf-8"))["test-shard"]) * 60
    heaviest = SETUP_ALLOWANCE_S + max(
        sum(weights.cost(f, counts[f]) for f in p) / 100 for p in parts
    )
    assert heaviest <= budget_s / 2, (
        f"the heaviest of {n} shards is predicted at {heaviest / 60:.1f} min, over half of "
        f"its {budget_s // 60}-minute timeout: raise N, or split the heaviest test file "
        "(P-053, P-740)"
    )


# --- a split test file runs each of its tests once ----------------------------------------------


def _collected_names(tree: ast.Module) -> set[str]:
    """The top-level names pytest collects from a module: ``test*`` functions, ``Test*`` classes."""
    return {
        n.name
        for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"))
        or (isinstance(n, ast.ClassDef) and n.name.startswith("Test"))
    }


def _run_twice(sources: dict[str, str]) -> list[str]:
    """Every test a module that imports another test module's harness would run a second time:
    defined in both (a split module and its parent), or imported from it. ``sources`` maps a
    module name (``test_worker``) to its text. ``verify`` compares whole node ids, so the same
    test under two paths passes it (P-742)."""
    trees = {name: ast.parse(text) for name, text in sources.items()}
    errors = []
    for name, tree in sorted(trees.items()):
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or node.module not in trees:
                continue
            parent = node.module
            for dup in sorted(_collected_names(tree) & _collected_names(trees[parent])):
                errors.append(f"{dup} is defined in both tests/{name}.py and tests/{parent}.py")
            for alias in node.names:
                if alias.name.startswith(("test", "Test")):
                    errors.append(f"tests/{name}.py imports {alias.name} from tests/{parent}.py")
    return errors


def test_a_test_defined_in_a_split_module_and_its_parent_is_caught() -> None:
    parent = "def _rig():\n    pass\n\ndef test_kept():\n    pass\n\ndef test_moved():\n    pass\n"
    split = "from test_worker import _rig\n\ndef test_moved():\n    pass\n"
    assert _run_twice({"test_worker": parent, "test_worker_posture": split}) == [
        "test_moved is defined in both tests/test_worker_posture.py and tests/test_worker.py"
    ]
    imported = "from test_worker import _rig, test_kept\n"
    assert _run_twice({"test_worker": parent, "test_worker_posture": imported}) == [
        "tests/test_worker_posture.py imports test_kept from tests/test_worker.py"
    ]
    moved = parent.replace("def test_moved():\n    pass\n", "")
    assert _run_twice({"test_worker": moved, "test_worker_posture": split}) == []


def test_no_test_file_runs_a_test_its_parent_file_also_runs() -> None:
    """A merge that keeps a moved test in its old file as well (the Integrate conflict in
    tests/test_worker.py would keep 10 posture tests in both) runs it twice unnoticed."""
    sources = {f.stem: f.read_text("utf-8") for f in sorted((ROOT / "tests").glob("test_*.py"))}
    assert _run_twice(sources) == []


# --- the fresh-clone suite, split the same way (P-743) ---------------------------------------


def test_the_fresh_clone_aggregator_needs_its_shards_and_proves_their_partition() -> None:
    """The fresh-clone suite ran unsharded until its first run took 65.9 of its 75 minutes.
    Its shards are the same N as ``test-shard`` (one weights file, one partition), each one
    matrix value 1..N; the aggregator keeps the one name, needs the gates job and every
    shard, runs ``always()``, fails unless every part passed, and runs ``verify`` over all N
    reports, which every shard uploads under its own name."""
    n = _shard_count()
    jobs = _jobs(CI.read_text("utf-8"))
    agg, shard = jobs["fresh-clone"], jobs["fresh-clone-shard"]
    assert set(_needs(agg)) == {"fresh-clone-gates", "fresh-clone-shard"}
    assert re.search(r"^    if: always\(\)\s*$", "\n".join(agg), re.M)
    steps = _steps(agg)
    gate = [s for s in steps if "toJSON(needs)" in s]
    assert len(gate) == 1 and f"jq -e '{ALL_PASSED_JQ}'" in gate[0]
    assert not any("continue-on-error" in s for s in steps)
    assert _matrix(shard, "shard") == [str(k) for k in range(1, n + 1)]
    assert re.search(rf"\(\$\{{\{{ matrix\.shard \}}\}} of {n}, ", _name(shard))
    runs = [s for s in _steps(shard) if "ci_test_shards" in s]
    assert len(runs) == 1 and f'--shard="$SHARD/{n}"' in runs[0]
    assert "SHARD: ${{ matrix.shard }}" in runs[0]
    proof = [s for s in steps if "ci_test_shards.py verify" in s]
    assert len(proof) == 1
    cmd = " ".join(proof[0].split())
    assert f"verify --shards {n} --python 3.12" in cmd
    assert re.findall(r"shards/shard-(\d+)\.json", cmd) == [str(k) for k in range(1, n + 1)]
    download = next(s for s in steps if "download-artifact" in s)
    assert "pattern: fresh-clone-shard-*" in download
    upload = next(s for s in _steps(shard) if "upload-artifact" in s)
    assert "name: fresh-clone-shard-${{ matrix.shard }}" in upload
    assert "if-no-files-found: error" in upload and "continue-on-error" not in upload


def test_the_fresh_clone_shards_fit_their_budget_as_root() -> None:
    """Each fresh-clone shard, predicted from the weights at the measured root slowdown plus
    the setup allowance, stays within half of its own timeout."""
    m = _shards()
    n = _shard_count()
    weights = m.load_weights()
    # every test file on disk, as the test-shard budget test partitions them (P-740): a file
    # the table does not list weighs its test count at the default, never nothing
    counts = {
        str(f.relative_to(ROOT)): max(1, f.read_text("utf-8").count("\ndef test_"))
        for f in sorted((ROOT / "tests").glob("test_*.py"))
    }
    parts = m.partition(counts, n, weights)
    budget_s = _timeout(_jobs(CI.read_text("utf-8"))["fresh-clone-shard"]) * 60
    heaviest = SETUP_ALLOWANCE_S + ROOT_SLOWDOWN * max(
        sum(weights.cost(f, counts[f]) for f in p) / 100 for p in parts
    )
    assert heaviest <= budget_s / 2, (
        f"the heaviest fresh-clone shard is predicted at {heaviest / 60:.1f} min, over half of "
        f"its {budget_s // 60}-minute timeout: raise N for both shard jobs (P-743)"
    )
