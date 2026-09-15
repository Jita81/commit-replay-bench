# FINDINGS — file-header programme, scope `src/crb/core/*.py` (2026-09-15)

Observations made while documenting; nothing here was changed in code.

- `docs/OPERATOR.md` §7 ("When the sandbox is unavailable") says a run's status becomes
  `blocked` on `SandboxUnavailable`. `src/crb/server/worker.py` (`_run_one`, ~line 537) sets
  `STATUS_FAILED` with `error="sandbox unavailable: …"`; the worker docstring says the same.
  Doc drift, not a code defect — the header in `execution.py` follows the code.
- `tests/test_version_consistency.py::test_changelog_has_a_dated_header_for_the_current_version`
  fails on `reboot/v2` at `ec0da78` (before this branch): `CHANGELOG.md` line 13 reads
  `## [2.0.0a1] — unreleased — …` and the test requires a `YYYY-MM-DD` date after the em
  dash. Pre-existing; out of this scope (no code or CHANGELOG change was made here).
