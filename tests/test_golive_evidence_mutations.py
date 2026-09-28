"""The go-live stream's evidence can fail: each named behaviour switched off, a cited test fails.

Navigation
----------
What it is:   A mutation gate over the evidence of stream P's met criteria and closed
              prevention rows (the go-live reading, its attestation record, the quarantine of
              a damaged sealed set). It is the P-359 artefact: its independent verifiers
              found five criteria whose cited tests still passed with the behaviour switched
              off (P-178's class, recurring), and this file makes that class fail here.
What it does: For each behaviour, copies ``src/crb`` to a temporary directory, switches the
              behaviour off with one exact text substitution, and runs the tests the
              criterion cites against the copy in a subprocess: at least one must fail. A
              control run of every cited test against an unchanged copy must pass, so a
              broken copy cannot pass for a killed mutation. A substitution whose text is no
              longer in the source fails the test too: the code moved, so the mutation must
              move with it.
How:          ``shutil.copytree`` then ``pytest -o pythonpath=<copy>/src`` (the ini's
              ``pythonpath = ["src"]`` would otherwise put the checkout first); the runs go
              four at a time in threads.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md,
              docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/server/golive.py (the go-live checks it switches off),
              src/crb/server/routes/golive.py (the admin refusal and the /flow reading),
              src/crb/server/posture_gate.py (the run's revocation),
              src/crb/provision/__init__.py (the resolve's re-hash),
              tests/test_golive.py (the evidence it runs),
              tests/test_server_routes_golive.py (the evidence it runs),
              tests/test_provision_quarantine.py (the evidence it runs),
              docs/PREVENTION.md (P-359, the row this gate closes)
Tested by:    tests/test_golive_evidence_mutations.py
Touch when:   never for a new repository; a criterion of the go-live journey, the posture or
              settings page, or the run-the-platform stream is flipped to met on a behaviour
              in the files above (add its mutation here), or a mutated line moves (move the
              substitution with it).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

GOLIVE = "src/crb/server/golive.py"
ROUTES = "src/crb/server/routes/golive.py"
GATE = "src/crb/server/posture_gate.py"
PROVIDER = "src/crb/provision/__init__.py"

T_GOLIVE = "tests/test_golive.py"
T_ROUTES = "tests/test_server_routes_golive.py"
T_QUARANTINE = "tests/test_provision_quarantine.py"


@dataclass(frozen=True)
class Mutation:
    """One behaviour switched off: in ``path``, ``old`` (exactly once) becomes ``new``."""

    name: str
    criterion: str
    path: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "the run does not revoke on a damaged set",
        "deploy-and-go-live.recovery.23",
        GATE,
        "if exc.code == BUNDLE_INTEGRITY and exc.keys:",
        "if False:",
        (
            f"{T_QUARANTINE}::test_a_run_that_meets_a_damaged_set_stops_quarantines_it_and_"
            "revokes_what_cites_it",
        ),
    ),
    Mutation(
        "a resolve reuses a damaged set",
        "deploy-and-go-live.recovery.23",
        PROVIDER,
        "if hit is not None and key not in self._whole:",
        "if False:",
        (
            f"{T_QUARANTINE}::test_a_resolve_that_meets_a_damaged_set_quarantines_it_and_seals_"
            "it_afresh",
        ),
    ),
    Mutation(
        "anyone signed in withdraws an attestation",
        "settings.actions.15",
        ROUTES,
        "def delete_attestation(\n    line: str,\n    *,\n    admin: AdminDep,",
        "def delete_attestation(\n    line: str,\n    *,\n    admin: ViewerDep,",
        (f"{T_ROUTES}::test_below_admin_nobody_withdraws_an_attestation",),
    ),
    Mutation(
        "an intact chain with a false-Q1 reads verified",
        "deploy-and-go-live.truth.4",
        GOLIVE,
        'if ledger.get("ok"):',
        'if ledger.get("chain_ok"):',
        (f"{T_GOLIVE}::test_a_broken_chain_or_an_unread_ledger_is_unproven",),
    ),
    Mutation(
        "an organisation account that never signed in is the live proof",
        "deploy-and-go-live.truth.4",
        GOLIVE,
        'u.issuer != "local" and u.active and u.last_login',
        'u.issuer != "local" and u.active',
        (f"{T_GOLIVE}::test_sign_in_names_every_part_that_does_not_hold",),
    ),
    Mutation(
        "a viewer reads the local admins' names",
        "deploy-and-go-live.truth.4",
        GOLIVE,
        "if stale and names:",
        "if stale:",
        (
            f"{T_GOLIVE}::test_only_an_admin_reading_is_told_the_local_admins_by_name",
            f"{T_ROUTES}::test_a_viewer_is_told_how_many_local_admins_are_stale_never_their_names",
        ),
    ),
    Mutation(
        "a task qualified in an older posture proves the repository",
        "deploy-and-go-live.truth.4",
        GOLIVE,
        "q.is_qualified for q in store_q.latest_by_task(session, repo, posture).values()",
        "True for q in store_q.latest_by_task(session, repo, posture).values()",
        (
            f"{T_GOLIVE}::test_a_task_qualified_only_in_an_older_posture_does_not_prove_the_"
            "repository",
        ),
    ),
    Mutation(
        "a factory build on the host leaves the builder sealed",
        "deploy-and-go-live.truth.4",
        GOLIVE,
        'if factory == "host":',
        "if False:",
        (f"{T_GOLIVE}::test_the_sealed_posture_is_measured_not_only_configured",),
    ),
    Mutation(
        "a run stamped unsealed leaves the posture sealed",
        "deploy-and-go-live.truth.4",
        GOLIVE,
        "if ran != SEALED_EXECUTOR:",
        "if False:",
        (f"{T_GOLIVE}::test_a_run_stamped_unsealed_leaves_the_sealed_posture_unproven",),
    ),
    Mutation(
        "the admin's today east of UTC is the future",
        "settings.actions.15",
        GOLIVE,
        "if day > today + _ONE_DAY:",
        "if day > today:",
        (f"{T_GOLIVE}::test_the_day_east_of_utc_is_not_the_future",),
    ),
    Mutation(
        "an act dated before its withdrawal is accepted",
        "settings.actions.15",
        GOLIVE,
        "if when is not None and day < when - _ONE_DAY:",
        "if False:",
        (
            f"{T_GOLIVE}::test_an_act_cannot_be_dated_before_the_withdrawal_it_follows_or_the_"
            "install",
        ),
    ),
    Mutation(
        "/flow runs the deep probes on every read",
        "run-the-platform.measure.14",
        ROUTES,
        "time.monotonic() - kept[0] < FLOW_READING_TTL_S",
        "time.monotonic() - kept[0] < 0",
        (f"{T_ROUTES}::test_the_flow_reading_does_not_run_the_deep_probes_on_every_read",),
    ),
)


def _copy(dest: Path, mutation: Mutation | None) -> Path:
    src = dest / "src"
    shutil.copytree(ROOT / "src" / "crb", src / "crb", ignore=shutil.ignore_patterns("__pycache__"))
    if mutation is not None:
        target = dest / mutation.path
        text = target.read_text(encoding="utf-8")
        assert text.count(mutation.old) == 1, (
            f"{mutation.name}: {mutation.old!r} is not in {mutation.path} exactly once — the "
            "code moved; move the mutation with it"
        )
        target.write_text(text.replace(mutation.old, mutation.new), encoding="utf-8")
    return src


def _run(src: Path, tests: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CRB_")}
    env["PYTHONPATH"] = str(src)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-x",
            "-p",
            "no:cacheprovider",
            "-o",
            f"pythonpath={src}",
            "-W",
            "ignore",
            *tests,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def test_every_mutation_names_a_cited_test_that_exists() -> None:
    for m in MUTATIONS:
        for node in m.tests:
            path, name = node.split("::")
            assert f"def {name}(" in (ROOT / path).read_text(encoding="utf-8"), node


@pytest.mark.slow
def test_each_behaviour_switched_off_fails_a_test_its_criterion_cites(tmp_path: Path) -> None:
    every = tuple(dict.fromkeys(t for m in MUTATIONS for t in m.tests))

    def control() -> subprocess.CompletedProcess[str]:
        work = tmp_path / "control"
        try:
            return _run(_copy(work, None), every)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def mutant(i: int) -> tuple[Mutation, subprocess.CompletedProcess[str]]:
        m = MUTATIONS[i]
        work = tmp_path / f"m{i}"
        try:
            return m, _run(_copy(work, m), m.tests)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        base = pool.submit(control)
        results = list(pool.map(mutant, range(len(MUTATIONS))))
        ok = base.result()
    assert ok.returncode == 0, "the unchanged copy must pass:\n" + ok.stdout[-3000:]
    survivors = [
        f"{m.name} ({m.criterion}) survived {', '.join(m.tests)}"
        for m, r in results
        if r.returncode == 0
    ]
    assert not survivors, "evidence that cannot fail:\n" + "\n".join(survivors)
    broken = [
        f"{m.name}: exit {r.returncode}\n{r.stdout[-1500:]}"
        for m, r in results
        if r.returncode != 1  # 1 = tests ran and failed; anything else is a broken run
    ]
    assert not broken, "a mutant run broke instead of failing:\n" + "\n".join(broken)
