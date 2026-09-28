#!/usr/bin/env python3
"""The Python suite's shards — every test in exactly one of N parallel CI jobs, proven per run.

The hermetic suite ran in one job per Python version and grew with every wave until py3.13
took 58 of its 60 minutes on PR #57 (and py3.12 51 on the next push): a job that creeps to its
timeout is cancelled, and a cancelled required check blocks every merge (docs/PREVENTION.md
P-051, P-053). This splits it. Each shard job runs the SAME command as the old job — the same
``-m "not sandbox_images"``, nothing else deselected — with this module loaded as a pytest
plugin, which keeps only the test files assigned to that shard:

    PYTHONPATH=scripts pytest -m "not sandbox_images" -p ci_test_shards \\
        --shard=3/6 --shard-report=shard-3.json

Files, not tests, are the unit, so a module's fixtures and its test order are what they were
in the single job. The assignment is deterministic — longest-processing-time first over the
per-file seconds in ``scripts/ci_test_weights.json`` (a file it does not list weighs its test
count times the file's default), ties broken by path — so every shard computes the same
partition of the same collection, and it balances the shards where a hash of the path could
not (measured on PR #57's logs: a path hash left one of six shards at 21 of 54 minutes).

Each shard writes a report: every test id it collected, the ids it kept, and each kept file's
seconds. The required ``test (py…)`` job then runs ``verify`` over the N reports and fails
unless there are exactly N, each kept at least one test, all N collected the same suite, and
the kept sets are disjoint and together are that suite — so a test that runs in no shard, or
in two, fails the build on the run where it happens, not in a review. ``weights`` turns the
reports' seconds into a fresh weights file when the suite has moved — each file's largest
measurement across every report given, never their sum.

Navigation
----------
What it is:   The shard plugin (pytest hooks, loaded with ``-p ci_test_shards``) and its
              stdlib CLI: ``verify`` (the partition proof the required ``test`` jobs run),
              ``weights`` (refresh ``scripts/ci_test_weights.json`` from shard reports) and
              ``plan`` (predicted seconds per shard for node ids read from stdin); ``verify``
              also fails when the run's measured seconds say the weights are stale.
What it does: ``partition(counts, n, weights)`` assigns every test file to one of ``n``
              shards (LPT over integer centiseconds, ties by path) and raises ``ShardError``
              when a shard would be empty; the plugin deselects every item outside its shard
              (after ``-m``, via ``pytest_deselected``), records each file's setup + call +
              teardown seconds and writes the report at session end; ``verify_reports``
              returns every way N reports fail to be one exact partition of one suite;
              ``stale_weights`` every file whose measured seconds left its weight far behind,
              or the share of the run the table does not list at all.
How:          Pure functions over node ids and ``{file: count}``; the pytest hooks are thin
              wrappers, and ``pytest`` is imported only when the plugin runs, so ``verify``
              needs nothing but the standard library.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the ``test-shard`` jobs load the plugin; the ``test``
              aggregators run ``verify`` and combine coverage), scripts/ci_test_weights.json
              (the per-file seconds), scripts/ci_job_budget.py (fails a shard that creeps
              past 80 % of its timeout), docs/PREVENTION.md (P-053)
Tested by:    tests/test_ci_test_shards.py
Touch when:   never for a new repository (it splits this repository's own suite); the shard
              count changes (the matrix, the job names and ``--shards`` move together —
              tests/test_ci_test_shards.py holds them equal); a shard nears its budget or
              ``verify`` says the weights are stale (refresh them with ``weights``, then raise
              N or split the heaviest test file — files are the unit, P-740).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WEIGHTS = Path(__file__).resolve().parent / "ci_test_weights.json"


class ShardError(ValueError):
    """A shard specification or a partition that cannot be honoured."""


@dataclass(frozen=True)
class Weights:
    """Per-file seconds, and the per-test seconds for a file the table does not list."""

    files: Mapping[str, float] = field(default_factory=dict)
    per_test_s: float = 1.0

    def cost(self, path: str, count: int) -> int:
        """The file's weight in integer centiseconds (so the assignment never depends on
        float rounding), at least 1 so an unlisted or instant file still counts."""
        seconds = self.files.get(path)
        if seconds is None:
            seconds = count * self.per_test_s
        return max(1, round(seconds * 100))


def load_weights(path: Path | None = None) -> Weights:
    data = json.loads((path or WEIGHTS).read_text("utf-8"))
    return Weights(
        files={str(k): float(v) for k, v in data["files"].items()},
        per_test_s=float(data["per_test_seconds_default"]),
    )


def parse_spec(spec: str) -> tuple[int, int]:
    """``"k/N"`` → ``(k, N)`` with 1 <= k <= N."""
    try:
        k_raw, n_raw = spec.split("/")
        k, n = int(k_raw), int(n_raw)
    except ValueError:
        raise ShardError(f"--shard must be k/N, got {spec!r}") from None
    if n < 1 or not 1 <= k <= n:
        raise ShardError(f"--shard {spec!r}: need 1 <= k <= N")
    return k, n


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def counts_of(nodeids: Iterable[str]) -> dict[str, int]:
    return dict(Counter(file_of(i) for i in nodeids))


def partition(counts: Mapping[str, int], n: int, weights: Weights) -> list[list[str]]:
    """Every file in exactly one of ``n`` shards: heaviest first onto the lightest shard (the
    lowest index on a tie). Raises ``ShardError`` when a shard would be empty."""
    if n < 1:
        raise ShardError(f"the shard count must be positive, got {n}")
    if len(counts) < n:
        raise ShardError(f"{n} shards over {len(counts)} test files would leave a shard empty")
    order = sorted(counts, key=lambda f: (-weights.cost(f, counts[f]), f))
    loads = [0] * n
    shards: list[list[str]] = [[] for _ in range(n)]
    for f in order:
        i = min(range(n), key=lambda j: (loads[j], j))
        loads[i] += weights.cost(f, counts[f])
        shards[i].append(f)
    return [sorted(s) for s in shards]


def select(nodeids: Sequence[str], k: int, n: int, weights: Weights) -> list[str]:
    """The ids shard ``k`` of ``n`` keeps, in collection order."""
    mine = set(partition(counts_of(nodeids), n, weights)[k - 1])
    return [i for i in nodeids if file_of(i) in mine]


def plan(nodeids: Sequence[str], n: int, weights: Weights) -> list[tuple[int, int, float]]:
    """``[(files, tests, predicted seconds)]`` per shard."""
    counts = counts_of(nodeids)
    out = []
    for files in partition(counts, n, weights):
        secs = sum(weights.cost(f, counts[f]) for f in files) / 100
        out.append((len(files), sum(counts[f] for f in files), secs))
    return out


# --- the proof the required job runs --------------------------------------------------------


def verify_reports(reports: Sequence[Mapping[str, Any]], n: int) -> list[str]:
    """Every way ``reports`` fail to be one exact partition of one collected suite into ``n``
    non-empty shards. Empty means proven."""
    errors: list[str] = []
    if n < 1:
        return [f"the shard count must be positive, got {n}"]
    shards = sorted(int(r.get("shard", 0)) for r in reports)
    if shards != list(range(1, n + 1)):
        errors.append(f"expected one report from each shard 1..{n}, got shards {shards}")
    for r in reports:
        if int(r.get("of", 0)) != n:
            errors.append(f"shard {r.get('shard')} split the suite {r.get('of')} ways, not {n}")
    if not reports:
        return errors or ["no shard reports"]
    suite = Counter(reports[0].get("collected", []))
    if not suite:
        errors.append(f"shard {reports[0].get('shard')} collected no tests")
    for r in reports[1:]:
        if Counter(r.get("collected", [])) != suite:
            errors.append(
                f"shard {r.get('shard')} collected a different suite from shard "
                f"{reports[0].get('shard')} — every shard must run the same command"
            )
    dup = [i for i, c in suite.items() if c > 1]
    if dup:
        errors.append(f"{len(dup)} test id(s) collected twice, e.g. {dup[0]}")
    union: Counter[str] = Counter()
    for r in reports:
        kept = r.get("selected", [])
        if not kept:
            errors.append(f"shard {r.get('shard')} ran no tests")
        stray = set(kept) - set(r.get("collected", []))
        if stray:
            errors.append(f"shard {r.get('shard')} ran {len(stray)} test(s) it never collected")
        union.update(kept)
    twice = sorted(i for i, c in union.items() if c > 1)
    if twice:
        errors.append(f"{len(twice)} test(s) ran in more than one shard, e.g. {twice[0]}")
    missing = sorted(set(suite) - set(union))
    if missing:
        errors.append(f"{len(missing)} test(s) ran in no shard, e.g. {missing[0]}")
    return errors


def refreshed_weights(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A weights table from shard reports' measured per-file seconds: each file's LARGEST
    measurement. Files are the shard unit, so a file runs in one shard of a run; a second report
    of it is another run or the other Python version — a second measurement of the same work,
    which a sum would count twice (P-741)."""
    files: dict[str, float] = {}
    tests: set[str] = set()
    for r in reports:
        for f, s in r.get("durations", {}).items():
            files[f] = max(files.get(f, 0.0), round(float(s), 1))
        tests.update(r.get("selected", []))
    total = sum(files.values())
    return {
        "per_test_seconds_default": round(total / len(tests), 2) if tests else 1.0,
        "files": dict(sorted(files.items())),
    }


#: How to refresh the table — printed by ``verify`` when it is stale and stated, word for word,
#: in ``scripts/ci_test_weights.json``'s ``_about`` (tests/test_ci_test_shards.py holds them
#: equal, so the two can never give different recipes again: P-741).
REFRESH_RECIPE = (
    "download the test-shard-py* artifacts of one or more CI runs, both Python versions, and "
    "run `python3 scripts/ci_test_shards.py weights <every shard-*.json>`: it keeps each file's "
    "largest measurement, never a sum"
)


#: The committed weights are STALE — the partition and the budget test are planning on numbers
#: the suite no longer has — when a listed file took more than ``STALE_FACTOR`` times its weight
#: plus ``STALE_SLACK_S`` seconds in this run, or when the files the table does not list took
#: more than ``UNLISTED_SHARE`` of the run's seconds. Runners differ by far more than a quarter:
#: tests/test_worker_fetch.py ran the same 7 tests in 35 s and in 133 s, 3.7 times [measured,
#: n = 6 shard reports of that file, both Python versions of main run 36443202051, PR #68 run
#: 36476128848 and PR #69 run 36476376620; method: per-file seconds from the ``test-shard``
#: artifacts; apparatus n/a, a finding about the product's own CI]. So the margin holds only
#: because the table is each file's LARGEST measurement over several runs and both versions
#: (``REFRESH_RECIPE``): a fast run under a slow run's weight never trips it, while a table
#: months old, which moves a file by five, does (P-740, P-741).
STALE_FACTOR = 2.0
STALE_SLACK_S = 60.0
UNLISTED_SHARE = 0.10


def stale_weights(reports: Sequence[Mapping[str, Any]], weights: Weights) -> list[str]:
    """Every way this run's measured per-file seconds say ``weights`` has gone stale. Empty
    means the table still describes the suite."""
    measured = refreshed_weights(reports)["files"]
    total = sum(measured.values())
    if total <= 0:
        return []
    errors: list[str] = []
    unlisted = {f: s for f, s in measured.items() if f not in weights.files}
    share = sum(unlisted.values()) / total
    if share > UNLISTED_SHARE:
        heaviest = max(unlisted, key=lambda f: unlisted[f])
        errors.append(
            f"{len(unlisted)} test file(s) the weights do not list took {share:.0%} of this "
            f"run's seconds (at most {UNLISTED_SHARE:.0%}), the heaviest {heaviest} at "
            f"{unlisted[heaviest]:.0f} s"
        )
    for f, secs in sorted(measured.items()):
        w = weights.files.get(f)
        if w is not None and secs > STALE_FACTOR * w + STALE_SLACK_S:
            errors.append(f"{f} took {secs:.0f} s against its weight of {w:.0f} s")
    return errors


# --- the pytest plugin ------------------------------------------------------------------------


def _trylast[F: Callable[..., Any]](fn: F) -> F:
    """Mark a hook to run after every other implementation of it (``-m`` included)."""
    try:
        import pytest  # noqa: PLC0415 — lazily: ``verify`` runs where pytest is not installed
    except ImportError:  # pragma: no cover — the CLI runs without pytest
        return fn
    return pytest.hookimpl(trylast=True)(fn)


#: The plugin's options — each is accepted only as ``--opt=value`` (see ``pytest_configure``).
_OPTIONS = ("--shard", "--shard-report", "--shard-weights")


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("crb shards", "run one of N deterministic shards of the suite")
    group.addoption("--shard", default=None, help="k/N: run only shard k of N")
    group.addoption("--shard-report", default=None, help="write this shard's report (JSON)")
    group.addoption("--shard-weights", default=None, help="per-file seconds (JSON)")


def pytest_configure(config: Any) -> None:
    spec = config.getoption("--shard")
    if not spec:
        return
    # pytest finds its configuration file before it loads a ``-p`` plugin, so a value given
    # after a space (``--shard-report out/r.json``) is read as a test path at that point: the
    # rootdir moves beside it and the suite runs under whatever configuration file sits above
    # that path, or none — no markers, no timeout, no ``pythonpath``. Only ``--opt=value`` is
    # safe, and a shard given the other form refuses to run rather than pass under the wrong
    # configuration.
    spaced = [a for a in config.invocation_params.args if str(a) in _OPTIONS]
    if spaced:
        import pytest  # noqa: PLC0415 — lazily: ``verify`` runs where pytest is not installed

        raise pytest.UsageError(
            f"give {', '.join(spaced)} as --option=value: pytest reads its configuration file "
            "before it loads this plugin, and takes a value after a space for a test path"
        )
    config.pluginmanager.register(ShardPlugin(spec, config), "crb-shard")


class ShardPlugin:
    """One shard's selection and report: registered only when ``--shard`` is given."""

    def __init__(self, spec: str, config: Any) -> None:
        self.spec = spec
        self.config = config
        self.state: dict[str, Any] | None = None
        self.durations: dict[str, float] = {}

    @_trylast  # after -m has deselected: every shard partitions the same suite
    def pytest_collection_modifyitems(self, items: list[Any]) -> None:
        import pytest  # noqa: PLC0415 — lazily: ``verify`` runs where pytest is not installed

        try:
            k, n = parse_spec(self.spec)
            weights_opt = self.config.getoption("--shard-weights")
            weights = load_weights(Path(weights_opt) if weights_opt else None)
            collected = [it.nodeid for it in items]
            keep = set(partition(counts_of(collected), n, weights)[k - 1])
        except ShardError as exc:
            raise pytest.UsageError(str(exc)) from None
        selected = [it for it in items if file_of(it.nodeid) in keep]
        deselected = [it for it in items if file_of(it.nodeid) not in keep]
        if not selected:
            raise pytest.UsageError(f"shard {self.spec} selected no tests")
        self.config.hook.pytest_deselected(items=deselected)
        items[:] = selected
        self.state = {
            "shard": k,
            "of": n,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "collected": collected,
            "selected": [it.nodeid for it in selected],
        }

    def pytest_runtest_logreport(self, report: Any) -> None:
        f = file_of(report.nodeid)
        self.durations[f] = self.durations.get(f, 0.0) + float(report.duration)

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        out = self.config.getoption("--shard-report")
        if self.state is None or not out:
            return
        report = dict(self.state)
        report["exitstatus"] = int(exitstatus)
        report["durations"] = {f: round(s, 2) for f, s in sorted(self.durations.items())}
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


# --- the CLI --------------------------------------------------------------------------------


def _read(paths: Sequence[str]) -> list[dict[str, Any]]:
    return [json.loads(Path(p).read_text("utf-8")) for p in paths]


def main(argv: Sequence[str], environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="prove N shard reports are one exact partition")
    v.add_argument("--shards", type=int, required=True)
    v.add_argument("--python", default=None, help="every report must be from this version")
    v.add_argument("--weights", default=None, help="the per-file seconds to check (JSON)")
    v.add_argument("reports", nargs="*")
    w = sub.add_parser(
        "weights", help="a fresh weights table: each file's largest seconds across the reports"
    )
    w.add_argument("reports", nargs="+")
    p = sub.add_parser("plan", help="predicted seconds per shard for node ids on stdin")
    p.add_argument("--shards", type=int, required=True)
    args = ap.parse_args(list(argv))

    if args.cmd == "weights":
        print(json.dumps(refreshed_weights(_read(args.reports)), indent=1))
        return 0
    if args.cmd == "plan":
        ids = [ln.strip() for ln in sys.stdin if "::" in ln]
        try:
            rows = plan(ids, args.shards, load_weights())
        except ShardError as exc:
            print(f"error: {exc}")
            return 1
        for k, (files, tests, secs) in enumerate(rows, 1):
            print(f"shard {k}/{args.shards}: {files} files, {tests} tests, ~{secs / 60:.1f} min")
        return 0

    reports = _read(args.reports)
    errors = verify_reports(reports, args.shards)
    if args.python:
        errors += [
            f"shard {r.get('shard')} ran on Python {r.get('python')}, not {args.python}"
            for r in reports
            if r.get("python") != args.python
        ]
    lines = ["| shard | tests | files | seconds in tests |", "|---|---|---|---|"]
    for r in sorted(reports, key=lambda r: int(r.get("shard", 0))):
        durations = r.get("durations", {})
        lines.append(
            f"| {r.get('shard')} of {r.get('of')} | {len(r.get('selected', []))} | "
            f"{len({file_of(i) for i in r.get('selected', [])})} | "
            f"{sum(durations.values()):.0f} |"
        )
    verdict = (
        f"**Shards — every one of the {len(reports[0]['collected'])} collected tests ran in "
        f"exactly one of {args.shards} shards.**"
        if not errors
        else "## SHARDS DO NOT PARTITION THE SUITE\n\n" + "\n".join(f"- {e}" for e in errors)
    )
    stale = stale_weights(reports, load_weights(Path(args.weights) if args.weights else None))
    if stale:
        verdict += (
            "\n\n## THE SHARD WEIGHTS ARE STALE\n\n"
            + "\n".join(f"- {e}" for e in stale)
            + "\n\nRefresh scripts/ci_test_weights.json: "
            + REFRESH_RECIPE
            + ". Then run tests/test_ci_test_shards.py: it says whether the shard count still "
            "fits the budget (P-740)."
        )
    text = verdict + "\n\n" + "\n".join(lines) + "\n"
    summary_path = env.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as fh:
            fh.write(text)
    print(text, end="")
    for e in errors:
        print(f"::error title=test shards::{e}")
    for e in stale:
        print(f"::error title=stale shard weights::{e}")
    return 1 if errors or stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
