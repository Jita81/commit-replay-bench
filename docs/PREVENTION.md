# Prevention register — our own bugs, and the artefact that stops each class

**Why.** The product's learning loop has one rule, set by the operator on 2026-09-25: *learn
from a bug, then go back and change the process or the context so it cannot happen again.*
We hold ourselves to the same rule. Every bug we hit while building the product is a row
here, with the class it belongs to, when it first bit us, and the artefact that now stops the
class — an artefact that **fails** if the class comes back.

**The levels**, strongest first — pick the strongest the class admits:
`construction` (the wrong thing cannot be built) › `gate` (a deterministic check refuses it) ›
`mistake-proofing` (the input makes the mistake hard) › `advisory` (a sentence someone must
read — the fallback, never the first choice). A `closed` row cites at least one reference that
can fail (`test:` or `vitest:`); prose never closes a row.

**Numbering.** The register began on the value branch (`feat/value`), whose rows are
`P-001` onwards and whose `scripts/dod_check.py` checks this file's shape. The rows below come
from the posture branch (`feat/posture`, PR #56) and start at `P-101`, so the two registers
join without renumbering. Until they are joined, every artefact below is a test that runs in
the full suite or in `npx vitest run`.

## Register

| id | bug | class | first seen | artefact | level | status | gap |
|---|---|---|---|---|---|---|---|
| P-101 | The sealed-set tests left read-only directories under their `tmp_path`, so pytest could not delete an old base temporary directory: it renamed it `garbage-<uuid>` and kept it, on every developer machine, every full run (CI runners are thrown away, so CI never saw it) | undeletable-temp-tree | PR #56, 2026-09-27 — found on the operator's machine [measured — n = 2 `garbage-<uuid>` directories left by 5 runs of the 4 sealing tests with a private base directory, 0 after the fix; method: `PYTEST_DEBUG_TEMPROOT` and a directory listing; apparatus 2.3] | `test:tests/test_tmp_tree_hygiene.py::test_the_sealing_tests_leave_a_tree_shutil_can_remove` · `test:tests/test_tmp_tree_hygiene.py::test_restore_removable_opens_a_sealed_tree_and_never_follows_a_link` | construction | closed | |
| P-102 | The API and the worker parsed `CRB_PROVISION__EXTRA_ALLOW_HOSTS` with two parsers: the API accepted a JSON list the worker split on commas, so a value `/settings` showed as valid stopped the worker at start-up; the two also fell back to different fetch proxy images | setting-parsed-twice | CodeRabbit on PR #56, 2026-09-27 [measured — n = 1 value, `'["mirror.corp:443"]'`: the API read one host, the worker raised `ValueError`; method: both parsers on the same string; apparatus 2.3] | `test:tests/test_settings_provision.py::test_the_api_and_the_worker_read_one_environment_the_same_way` · `test:tests/test_settings_provision.py::test_one_parser_reads_the_host_list_for_both_processes` | construction | closed | |
| P-103 | Three "complete" lists of what leaves a deployment disagreed: the dependency-provisioning flow was missing from the SECURITY.md boundary table and from DEPLOYMENT §1, and the git remote and the intake tracker from DEPLOYMENT §1 and §7. The first guard checked the lists only against a hand-written flow list, so a new flow still passed; the guard now discovers every endpoint-shaped setting from `Settings` and the source, and on its first run found two flows no list named — the GitHub API and the image registry | egress-list-incomplete | CodeRabbit on PR #56, 2026-09-27; adversarial check of the fix, 2026-09-27 | `test:tests/test_egress_inventory.py::test_every_endpoint_setting_belongs_to_a_flow_or_says_why_it_is_not_egress` · `test:tests/test_egress_inventory.py::test_the_boundary_table_has_exactly_one_row_per_flow` · `test:tests/test_egress_inventory.py::test_each_flow_row_names_the_settings_that_point_it` · `test:tests/test_egress_inventory.py::test_every_complete_egress_list_names_every_flow` · `test:tests/test_egress_inventory.py::test_the_provisioning_row_says_what_a_fetch_sends_and_never_sends` | gate | closed | |
| P-104 | The new-run dialog showed the qualified count of the deployment's default executor whatever executor the operator picked, so it could say "qualified" for a run the worker would refuse | query-key-omits-an-input | CodeRabbit on PR #56, 2026-09-27 | `vitest:ui/src/screens/Runs/RunNewDialog.test.tsx::"reads the posture of the executor the operator picks, not the deployment default"` | gate | closed | |
| P-105 | The posture reading was refreshed when a qualify run was queued, not when it finished, so the Posture panel kept the old count | refreshed-on-queue-not-on-finish | CodeRabbit on PR #56, 2026-09-27 | `vitest:ui/src/screens/Runs/RunDetailPage.test.tsx::"a finished %s run refreshes the repository’s posture reading"` | gate | closed | |
| P-106 | Headline tiles showed counts and means without the apparatus they were graded under (the Posture tiles, and on the Results page the route, cost, latency and clean-rate tiles) | tile-without-apparatus | CodeRabbit on PR #56, 2026-09-27 | `vitest:ui/src/screens/Capability/CapabilityPage.test.tsx::"the posture tile carries its apparatus and says no interval applies; every tile names the apparatus (PR #56 review)"` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"the posture tile carries its apparatus and says no interval applies; every map tile names the apparatus (PR #56 review)"` | gate | closed | |
