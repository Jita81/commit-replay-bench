# Prevention register — our own bugs, and the artefact that stops each class

**Why.** The product's learning loop has one rule, set by the operator on 2026-09-25: *learn
from a bug, then go back and change the process or the context so it cannot happen again.*
We hold ourselves to the same rule. Every bug we hit while building the product is a row
here, with the class it belongs to, when it first bit us, and the artefact that now stops the
class — an artefact that **fails** if the class comes back.

**The rule** (`docs/dod/STANDARD.md` §7): a defect is closed only with the artefact that fails
if its class recurs. `scripts/dod_check.py --check` (CI job `dod`) enforces it on this file:

- every artefact reference resolves, in the typed forms of STANDARD §3 (`test:`, `vitest:`,
  `spec:`, `ci:`, `code:` …);
- a `closed` row cites at least one reference that can fail (`test:`, `vitest:`, `spec:` or
  `ci:`) — a `code:` reference proves a thing exists, not that it works;
- `advisory` text never closes a row: prose cannot fail when the class recurs, so an advisory
  fix stays `pending` with a gap toward a gate;
- a `pending` row names its gap (`G-7nn` below, with the owner layer) or a backlog id.

**The levels**, strongest first — pick the strongest the class admits:
`construction` (the wrong thing cannot be built) › `gate` (a deterministic check refuses it) ›
`mistake-proofing` (the input makes the mistake hard) › `advisory` (a sentence someone must
read — the fallback, never the first choice).

The pull-request template (`.github/pull_request_template.md`) asks every change that fixes a
bug for its row here.

## Register

| id | bug | class | first seen | artefact | level | status | gap |
|---|---|---|---|---|---|---|---|
| P-001 | A CI job whose rendered name is 100 characters or more can never satisfy a required status check: GitHub truncates the check-run name at 100 and branch protection matches the full name, so the pull request waits for a context no run reports | ci-job-name-truncated | PR #48, 2026-09-22/23 — the `dod` job's first name; before this row the only guard was a comment in `ci.yml` asking the next author to count | `test:tests/test_ci_job_names.py::test_every_ci_job_name_is_under_100_characters` · `test:tests/test_ci_job_names.py::test_a_long_name_and_a_long_matrix_value_are_caught` · `ci:test` | gate | closed | |
| P-002 | The stack served stale code: the checkout it ran was behind `origin/main` and `ui/dist` was built from an older tree still, and nothing in the product said so | served-code-stale | the operator's stack, 2026-09-25, found while measuring the sealed posture (F42 part 2): a merged fix was "not working" because it was not running | `test:tests/test_server_system.py::test_health_serves_the_served_commits_and_a_stale_flag` · `test:tests/test_cli_doctor.py::test_crb_doctor_exits_1_on_a_stale_bundle` · `test:tests/test_build_stamp.py::test_the_vite_build_writes_the_stamp_this_module_reads` · `test:tests/test_build_stamp.py::test_the_image_carries_the_commit_into_the_ui_build_and_the_runtime` | gate | closed | |
| P-003 | A run queued with a builder auth that has no credential failed at $0 on every task: `claude_code` on the served default `api_key` with no key | builder-credential-absent | run `8d9c5e55`, 2026-09-25 — every attempt `model_error: ANTHROPIC_API_KEY is not set` [measured — n = 9 attempts of 9, method: the run's ledger rows on the operator's stack, apparatus 2.2] | `test:tests/test_server_routes_runs.py::test_api_key_auth_with_no_key_is_refused_with_the_fix_and_nothing_queued` · `test:tests/test_server_routes_runs.py::test_a_rung_further_up_the_ladder_is_checked_too` · `vitest:ui/src/screens/Runs/RunNewDialog.test.tsx::"a submit refused for a builder with no credential shows the refusal and its fix, and nothing is created"` | gate | closed | |
| P-004 | A runner tool missing from the repository's environment was graded as a harness failure after the builder had been called: `jest` absent on nhsuk-react-components | harness:runner-tool-missing | runs `a44f2875` and `9b4b0c42`, 2026-09-13 [measured — n = 6 rows with `errclass` EJ of 618, method: the product's failure rule over the operator's ledger export of 2026-09-25, apparatus 2.0] | `test:tests/test_builders_toolcheck.py::test_a_missing_runner_tool_refuses_the_attempt_before_any_builder_call` · `test:tests/test_builders_toolcheck.py::test_jest_missing_from_the_repository_is_named` | gate | closed | |
| P-005 | Provider usage-limit rows were counted as observations of the model, and a run kept spending into an outage | outage-as-observation | the census, 2026-09 (the `outage` kind, ADR-0003 amendment) | `test:tests/test_ledger.py::test_outage_rows_are_not_observations` · `test:tests/test_worker.py::test_replay_stops_after_consecutive_provider_outages` | gate | closed | |
| P-006 | A review whose statement says "Mergeable" is stored with `mergeable=false` | review-flag-contradicts-statement | the review store, 2026-09-25 [measured — n = 2 of 10 review records, method: reading the store's export, apparatus 2.2] | pending | gate | pending | G-701 |
| P-007 | The product threw away what it made: no clean patch could be retrieved for audit, review or re-grading | output-not-retained | the ledger export, 2026-09-25 [measured — n = 0 of 190 clean patches retrievable, method: the export's retention columns, apparatus 2.2] | pending | construction | pending | G-702 |
| P-008 | Under the docker posture an environment failure (no dependencies in the sealed container) was graded `builder_red` — the model blamed for the environment | posture-misattribution | run `0c44ff24`, 2026-09-25 (F42 part 2) [measured — n = 3 attempts of 3 before the run was cancelled, method: the run's rows and a reproduction by hand, apparatus 2.2] | pending | construction | pending | G-703 |
| P-009 | UI type errors, hint-ratchet and copy regressions were caught only when somebody remembered to run the UI's gates by hand (the job now fails on every pull request; making it a *required* check is G-930, an administrator's setting) | types-unchecked-until-release | CHANGELOG, stream E of the shippable wave ("Until now those ran only when somebody remembered them") | `ci:ui-unit` · `ci:types` | gate | closed | |
| P-010 | mesh-client's linter is not pinned to the repository's own version, so belt 5 reads every row as `lint` against a newer host ruff | lint-tool-unpinned | the NHS patch reviews, 2026-09-14 (`docs/reviews/2026-09-14-nhs-patch-reviews.md`) | pending | mistake-proofing | pending | G-704 |
| P-011 | The served-commit stamp (this wave) located the checkout from `crb.__file__`, which is `None` because `crb` is a namespace package — every `/health` raised in the first draft | namespace-package-file | this wave, 2026-09-25 — caught by the new `/health` tests before it was committed | `test:tests/test_build_stamp.py::test_the_default_source_root_is_this_checkout` · `test:tests/test_build_stamp.py::test_nothing_in_src_reads_the_namespace_package_file` | gate | closed | |
| P-012 | A mechanical edit that replaced a header sentence joined the rest of the old line onto the new one, leaving header lines of up to 132 columns against the 100-column rule — nothing checked the width | header-width-unchecked | this wave, 2026-09-25 — caught by a hand-run width check before commit [measured — n = 4 joined lines in 3 files, method: `awk 'length > 101'` over the diff, apparatus 2.2] | `test:tests/test_header_width.py::test_module_headers_do_not_grow_wider_than_100_columns` | gate | closed | |
| P-013 | The runner-tool refusal (this wave) emitted a new event action, `builder.refused`, without its row in the event vocabulary, so a consumer reading the table would never know it exists | event-undocumented | this wave, 2026-09-25 — caught by the existing vocabulary ratchet in the full suite before commit | `test:tests/test_event_vocabulary.py::test_every_emitted_action_is_in_the_vocabulary_table` | gate | closed | |

## Gaps
- **G-701** — a review statement and its stored `mergeable` flag can disagree, and the store is evidence so it cannot be rewritten · find the source of the flag, fix it with a ratchet test and add an append-only correction path (stream K, `feat/value-k`) · server
- **G-702** — graded patches are not kept independently of worktree retention · store every graded patch, redacted and content-addressed, and serve it from `GET /grades/{row_hash}/patch` (stream K, `feat/value-k`) · server
- **G-703** — the sealed posture grades an environment failure as the model's · posture-relative qualification that refuses a replay the posture cannot grade before any builder call (the `feat/posture` workflow, ADR-0019) · server
- **G-704** — a repository's linter version is whatever the host has, not what the repository pins · pin the lint command per repository in its configuration, starting with mesh-client (stream W, `feat/value-w`) · server
