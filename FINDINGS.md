# FINDINGS — file-header programme, scope `src/crb/core/*.py` (2026-09-15)

Observations made while documenting; nothing here was changed in code.

- `docs/OPERATOR.md` §7 ("When the sandbox is unavailable") says a run's status becomes
  `blocked` on `SandboxUnavailable`. `src/crb/server/worker.py` (`_run_one`, ~line 537) sets
  `STATUS_FAILED` with `error="sandbox unavailable: …"`; the worker docstring says the same.
  Doc drift, not a code defect — the header in `execution.py` follows the code.
