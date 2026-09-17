# Four external documents read against the product — assessment (2026-09-17)

<!--
Navigation
----------
What it is:   A critical-friend reading of four documents outside the repository — the
              Quality Floor essay the product was built from, the Automated Agile process
              architecture, the AAF ISO architecture & code-quality guide, and the
              operator's experience profile — against the product as it stands on
              `feat/nhs-design-journey` (working tree, uncommitted edits included).
What it does: Says, per document, what the product already honours (verified in code, not
              only in documents), where it contradicts or has drifted from the document,
              and which learnings are worth a backlog row; ends in rows F27–F34 (F23–F26 were taken by the persona walkthrough recorded the same hour) shaped for
              docs/reviews/2026-09-17-enterprise-front-end.md §9 and a rejected list.
How:          Read-only. Documents extracted from disk (the two .docx via zipfile); claims
              checked against src/crb/core/{grade,routing,signoff,ledger,review,learn}.py,
              src/crb/factory/*.py, src/crb/server/routes/{factory,signoffs}.py, the ADRs,
              DECISION-LOG, EVIDENCE-AND-CLAIMS, REPRODUCING-THE-CENSUS and the three
              earlier reviews. Nothing here is a measurement; every number is quoted with
              its source.
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none — F31 (a security probe) would need one if taken (it touches what a
              review verdict means); F27 needs an EVIDENCE-AND-CLAIMS §6 note
Works with:   docs/reviews/2026-09-17-enterprise-front-end.md (the backlog this extends),
              docs/reviews/2026-09-16-external-assessment.md (B-0…B-13, which several rows
              build on), docs/reviews/2026-09-13-critical-friend.md (§4.2 play 01 — the
              spec-lever correction), docs/EVIDENCE-AND-CLAIMS.md
Tested by:    not applicable — a review record
Touch when:   a row below lands (mark it with the PR); a document is re-issued.
-->

## How to read the claims in this record

This is a reading, not a measurement (docs/EVIDENCE-AND-CLAIMS.md §1). Every statement
that the product *does* something is **[hypothesis]**: verified by reading the code named
beside it on `feat/nhs-design-journey`, and by its unit tests where they are cited, never by
an end-to-end measurement. Every "designed, not run" item and every proposed row (F27–F34)
is **[aspiration]**. Numbers quoted from the essay, the profile or the product's own
documents are quoted with their source and inherit that source's tag; none is re-measured
here and none is **[measured]** by this record.

## 1. Executive summary

1. **The Quality Floor (essay edition, labelled v3.0)** — the argument the product was built from: four belts, false-Q1 = 0, test-conditioned vs blind, the routing bar, the DoR gate, independent review, the frozen backlog, the empty half of the ledger.
   *Verdict* **[hypothesis — verified by reading the code, not measured]:** the product honours every mechanism the essay names and is stricter on most (five belts, oracle-unmeasured refusal, per-mode reporting, task count beside n); the copy on disk still carries the **pre-correction specification-lever numbers** (+23 points) that the product's own documents record as leakage — do not re-import them; two designed-but-unrun ideas are worth building (an audited sample per signed cell; a path from a review finding back into the registered backlog).
2. **Automated Agile — Process Architecture v1.0 (March 2026)** — the upstream inputs → decisions → outputs model: twelve decision types, seven meeting types, the self-curating context graph, integrations, the sign-off matrix.
   *Verdict* **[hypothesis — verified by reading the code, not measured]:** mostly out of scope by decision (DL-001 carved the instrument out of the discovery/inception pipeline) and "the platform proposes; humans approve" is already the product's write boundary; three small, transferable items — show an item's predicted route before money is spent, capture human PR review comments as evidence, and put the signed facts in the PR body.
3. **AAF ISO Guide to Architecture & Code Quality v1.0 (April 2026)** — ISO 42010 viewpoints and ADR rules, ISO 25010 characteristics with evidence artefacts, SOLID, OWASP-by-change-type, ISO 9001 nonconformity handling, Stage-5 review and Q1/Q2/Q3 scoring.
   *Verdict* **[hypothesis — verified by reading the code, not measured]:** the product already meets the standard's substance (layers enforced in CI, ADRs with alternatives, tamper-evident records, N/A never silent, corrective action re-verified on the same task); two learnings — a recurrence alarm after a prevention lands, and the repository's own security scanner as a review probe — plus two hygiene corrections (ADR-0013 is in force but "Proposed"; ADRs name no approver).
4. **Paul Glover — Experience and Knowledge Profile (August 2026)** — the operator's record of standards and practices: upstream control, DoR gates, oracle-led production, fail-closed belts, measured routing, refusal as a positive behaviour, provenance, clinical-safety framing, evidence boundaries.
   *Verdict* **[hypothesis — verified by reading the code, not measured]:** **nothing new** — the product is the embodiment of the practices the profile records; the one thing it surfaces is a prioritisation note (the operator's client base is Azure DevOps-heavy, so F21's ADO half should lead its GitLab half).

The working tree's uncommitted edits (approver display names on sign-off records, the sign-off, measure, home and login screens, admin routes) do not overlap any row proposed below.

---

## 2. The Quality Floor essay

### 2a. What it says that the product already does — verified in code **[hypothesis]**

| Essay mechanism | Where the product does it | Note |
|---|---|---|
| Four belts; "any harness error fails closed"; a green with no source change is disqualified | `src/crb/core/grade.py` (`CORE_BELT_NAMES`, `GradeResult.__post_init__` raising `FalseQ1Violation`); `src/crb/core/ledger.py` `GradeRow.assert_invariants`; ADR-0001 | The product goes further: belt 5 (`repo_lint_clean`, ADR-0011, apparatus 2.2), belt 1 covers test infrastructure (`test_infra.py`), belt 0 in blind mode, worktree-integrity DQ. |
| "false-Q1 = 0 means the mechanical count, and we will not let the phrase drift" | EVIDENCE-AND-CLAIMS §2 — mechanical vs audited-semantic, with the S1–S4 severity ladder and the vocabulary rule | Stricter than the essay: the product also refuses a *sign-off* on a cell whose oracle was never measured (`signoff-policy.v2`, DL-016). |
| Test-conditioned (sighted) vs blind are different measurements, never pooled | `crb.core.grade.MODES`; the server map filters by mode (`rows_for_mode`, default sighted — external assessment #15); README quotes 12/14 sighted vs 2/14 blind on the same NHS tasks | — |
| Routing: `deliver` only at ≥ 0.90 point **and** ≥ 0.80 Wilson lower on enough samples; "ten-for-ten stays in calibrate" | `src/crb/core/routing.py` `RoutingPolicy` defaults = `_PUBLISHED` (`min_n=10, min_point=0.90, min_ci_low=0.80`); a looser policy cannot wear `routing.v1` (`__post_init__`); every decision stamps `policy_thresholds` | 10/10 has Wilson lower 0.72 → `ci_low_below_bar` → `calibrate`. Verified by the clause order in `route()`. |
| XL granularizes; weak oracle (< 0.8) goes to a human | `granularize_sizes=("XL",)`; `REASON_ORACLE_WEAK` | See 2b(2) for the vocabulary difference. |
| The DoR gate refuses to build on unsigned context; each change-type declares the facts a good test needs; gaps are questions, never invented answers | `src/crb/factory/readiness.py` — `CATALOGUE` (14 classes, structural vs value slots), `NotReady`, `GapSignoff` (hash-chained, `verifier`, `answer` required) | The docstring already carries the *corrected* finding: "structure helps, values leak". |
| The frozen backlog; "the truth changed through the front door" as a registered evolution | `src/crb/factory/backlog.py` — `freeze` → `backlog_hash`, `BacklogFrozen`, `evolve` with `supersedes`, `active_items` | — |
| Independent review: different identity, RED reproduced from a pristine checkout, verdict before edit | `src/crb/factory/review.py` (three probes: RED re-proof from the oracle *commit*, belt re-run in a fresh tree, mutation strength); `src/crb/factory/evidence.py` `EditBeforeVerdict`; `testfirst.assert_distinct_identity` | See 2b(3): the *opinion* half is not yet a model. |
| The ledger records measurements, not claims; a never-measured cell is absent, never fabricated | ADR-0002; `crb.core.capability` ("the honest-empty cell when absent"; an unmeasured cell cannot carry a tier) | — |
| Cost must include failed attempts; task-solve-under-budget is not first-pass | one row per attempt (`trial = r1…`, `crb.core.run`); EVIDENCE §3 "attempt budgets"; summing to cost-to-accept is B-9 | Partly: `cost_usd_mean` is per attempt; B-9 is open. |
| The horizon ladder L1 → L2 → L3, checkpointed | `BacklogItem.level`; `FactoryLoop.checkpoint` → `EV_CHECKPOINT` | — |
| Operator-kind work (auth, money, accounts) is never delegated | `readiness.py:456` `KIND_OPERATOR` → `human` | — |
| Claim tags `[measured] / [hypothesis] / [aspiration]` | EVIDENCE §1; used throughout README, ADRs, reviews | — |

### 2b. Where the product contradicts or has drifted from the essay — with evidence

1. **The specification-lever numbers in this copy are stale.** The file says blind 33/48 = 68.8 % rose to 46/48 = 95.8 % with signed facts plus a checklist, "+23 points … 5.6× the lever process discipline was". The product's record says otherwise, three times: critical-friend review §4.2 play 01 ("the +23 was the author having seen the answer … corrected on 2026-07-09"), EVIDENCE §6b ("blind-authored facts 68.8 % ≈ bare 72.9 %"), external assessment #13 ("informed 91.7 % = leakage"). The copy is labelled v3.0 yet carries the pre-correction figures, so it is an earlier draft or mislabelled. **Consequence:** nothing to build; a warning — the essay on disk is not the product's source of truth on context value, and no product screen or document should quote 95.8 %/+23. The product's readiness gate already encodes the corrected finding (structural slots block, value slots never do).

2. **Route vocabulary.** The essay names four routes — *deliver / granularize / apply-pattern / calibrate* — with weak-oracle types "apply-pattern under human sign-off". The product has five (`deliver / calibrate / granularize / human / do_not_ship`, ADR-0003) and no `apply-pattern` anywhere in `src/` or `docs/`; a weak oracle routes `human` (`oracle_weak`). This is ADR-0003's deliberate reconciliation, not drift — but a reader holding both documents will look for a route that does not exist. Also: `granularize` is a *route* (a human splits), not a splitter; the essay's "granularize into higher-yield primitives" is not a mechanism the product has, and DL-001 keeps decomposition out of scope.

3. **The reviewer's opinion is not yet an independent agent.** The essay: "reviewed by an agent that is not its builder … runs adversarial probes … reviewers hunted vectors *beyond* their acceptance criteria and, finding them, minted new registered issues". The product's probes are mechanical and the `DefaultReviewer` records "no opinion beyond the mechanical probes" (`review.py:485`); a model-backed reviewer is ADR-0013's not-started follow-up (DL-032) and B-4 (adversary run kind). `issues_minted` exists only as a caller-supplied list on a horizon checkpoint (`loop.py:660`) — there is **no path from a review finding to a registered backlog evolution**. Nor is there a channel for a builder to dispute a signed fact ("builders caught four defects in our own delegated decisions and flagged them"): the gate refuses *before* the builder runs, which is better, but a builder that finds a contradiction has nowhere to put it.

4. **The forward-mode evidence is not the product's.** Essay: "roughly forty forward-mode changes … ~39 accepted without edit … zero escapes" on four private pilots. That was the upstream loop. The product has opened **no factory PR on a real repository** (external assessment #23 → B-1b), has no model-backed test author (README P6), and — correctly — cites none of ≈40, 138/139 or 58/60 anywhere (verified by grep over README, docs, ADRs). Say it plainly: crb's forward-mode n = 0.

5. **The census numbers differ by framing, not by fact.** Essay: 927 rows re-audited, 848 clean; 834/855 = 97.5 % task-level. Product (REPRODUCING-THE-CENSUS): **1,071 rows** = 927 sighted + 144 blind; **962 clean**; 706 `v3-legacy` (three belts) + 365 `v4`; false-Q1 0; chain verified. The 97.5 % appears in the product only as the `bug.fix` XS **sighted `v3-legacy`** cell, 274/281 [0.95, 0.99], printed beside the four-belt sighted 49/55 = 89.1 % [0.78, 0.95] and blind 51/60 = 85.0 % [0.74, 0.92] — and "97.5 % of the time" is on EVIDENCE §7's never-say list. Same underlying ledger, two denominators that happen to coincide; the product's presentation is the one to keep.

6. **Oracle adequacy.** Essay: mean 58.3 %, 25–76 % by cell, n = 211 mutants; adequacy gate n = 19. Product: ARCHITECTURE §9.2 quotes the same 58.3 % as `[measured on the upstream apparatus]`; the product's own readings are 0.675 over 10 dogfood tasks (DL-036), 0.36 on nhsuk-frontend with 2 of 6 scoreable (DL-016), 0.76 click XS and 0.58 seed `bug.fix` S (DL-021, DL-034). Consistent; the product's are per-task and per-repository, which is the stronger shape.

7. **"Operator-delegated" is not a tier the product can express.** The essay stamps delegated sign-offs "as such, a weaker tier of proof". The product's tiers are `untrusted / automated-pass / human-verified / ab-confirmed` (`capability.py:141–146`); a `GapSignoff` and a `SignoffRecord` carry `verifier` as an account id with no marker of whether that account is a person's OIDC subject or a local service account holding the approver role. Through the API the approver role is required (`routes/factory.py:313`, `routes/signoffs.py`) and the MCP excludes sign-offs, so today the risk is a service account given the approver role — exactly what the operator's own pilots did. See F34.

8. **The two "designed, not run" items are still not run** **[aspiration]**. (i) "No independent semantic audit of a random sample of accepted changes to convert the observed zero into a confidence bound": the product has the *record type* (`ReviewRecord`, byte-anchored, `review_cell_stats` joining `n_reviewed` / `n_review_defects` onto cells) and proposals to use reviews at sign-off (B-3) and as a routing clause (B-12), but nothing *asks for the sample* — no rule, no inbox item, no "audited false-Q1" figure beside the mechanical zero. See F27. (ii) "No prospective frozen-policy trial": the route now gates delivery (DL-038), but `policy_hash` is not pinned beside `backlog_hash` (B-0b, open; grep finds none).

### 2c. Candidate learnings

| # | Learning | Rating | Why | Effort | Persona |
|---|---|---|---|---|---|
| E1 | **Audit sample per signed cell** — a pre-registered rule (e.g. k = 3 accepted rows per signed cell per apparatus, seeded from the row hash so the pick is reproducible) that puts "read these" in the Decisions inbox; each read is a `ReviewRecord`; the cell shows *audited false-Q1 (semantic)* = defects / reads with a Wilson interval beside the mechanical 0 | **adopt** | Converts EVIDENCE §2's "audited semantic false-Q1" and §6 row 5 from vocabulary into a number; gives B-12 something to route on; the essay names it as the missing rung | M | approver, auditor/ARB |
| E2 | **Review finding → proposed follow-up item** — a `crb learn followups` verb (the `strengthen` pattern) that turns each `defect` / `regression` finding on a delivered item, and any builder-stated dispute of a signed fact, into an *unfrozen* `BacklogItem` with `supersedes` set; freezing stays the human's act | consider | Closes the essay's "minted new registered issues" loop without letting the product edit its own frozen record; the emit-items pattern already exists in `learn.py` | S | developer, operator |
| E3 | **Verifier account kind on attestations** — stamp `verifier_kind ∈ {oidc, local, service}` on `SignoffRecord` / `GapSignoff` from the users table at write; the UI and the licence sentence say "signed by a service account" when it is | consider | Makes the essay's honesty caveat machine-readable; a delegated signature can no longer read as a person's | S | auditor/ARB, approver |
| E4 | Cost-to-accept includes failed attempts | — | Already B-9; not a new row | — | — |
| E5 | Pin `policy_hash` beside `backlog_hash` | — | Already B-0b; not a new row | — | — |

---

## 3. Automated Agile — Process Architecture v1.0

### 3a. What it says that the product already does — verified in code **[hypothesis]**

- **"The platform proposes; humans approve. Every time."** — `crb.core.learn.triage_refusals` can only emit `unsure` (the dataclass refuses any other verdict); a model label never overwrites a human label (`classify.resolve`, human > intent > path); a gap is signed by an approver (`routes/factory.py:303–342`); a cell sign-off is refused at write unless every clause holds (`signoff.check_signable` → 409).
- **D7 "Nothing enters the manufacturing pipeline without a signed-off context package"** — `readiness.NotReady`: an unsigned structural slot stops the item before any builder runs; the run cannot skip the step (`loop.py` `_assess` first).
- **D6 testing contract (preconditions, postconditions, invariants, scenarios)** — the structural/value slot catalogue plus the RED proof (`testfirst.prove_red`: the authored test must fail with attributable ids before anything is built).
- **D10 triage Q1 / Q2 / Q3** — factory verdicts `accept / accept_with_edit / reject` (`review.py:85–88`) and the human `ReviewRecord` (`mergeable`, typed `findings`).
- **D11 context improvement from triage** — `crb learn refusals / strengthen / remeasure` (LEARNING-LOOP.md): a failure becomes a guard-corpus line, a weak oracle becomes a `test.add` item, an apparatus change becomes a costed re-measurement plan.
- **The sign-off matrix (produced by / reviewed by / signed by / gate it enables)** — RBAC viewer/operator/approver/admin, `policy_thresholds` and `verifier` stamped on every record, revocation as an append.
- **"Predicted queue outcome" per story** — partly: the DoR route hint (`build / test_first_authoring / human`) is on every item (`FactoryPage.tsx:80`), and the route gate withholds delivery (DL-038). See 3b(3) for what is missing.

### 3b. Where the product contradicts or has drifted from it

1. **Scope.** Meetings, quarterly cadence, the context graph, Jira/Slack/Teams capture, codebase intelligence and the pattern library are the discovery/inception pipeline DL-001 excluded ("not Athena's discovery / inception pipeline"). Not drift — a boundary.
2. **"Context readiness score 0–100 %" and "completeness score".** The product refuses blended scores on principle (DL-038 declined a composite OracleConfidence; ADR-0003 "a bar that moves is not a published bar"; EVIDENCE §3 "an aggregate without a breakdown is not published"). Readiness is a list of named open slots, never a percentage. Deliberate.
3. **The predicted outcome is not shown before money is spent.** D8/D9 want each story to show its predicted queue outcome before commitment. The factory item state carries `capability_class`, `size` and the DoR route hint, but **not the capability-map route of its (class × size) cell** (`factory_state.py:74–90`; no join to the map in `routes/factory.py` or `FactoryPage.tsx`). An operator who freezes and runs an item whose cell routes `calibrate` learns that delivery was withheld only after the build has been paid for (`delivery_withheld` in `decisions.ts:128`). See F28.
4. **Q1/Q2/Q3 vocabulary collision.** The document's Q1 is a *developer's* judgement after generation; the product's Q1/`clean` is mechanical. The document's Q2 ("solid foundation needing human finishing — the developer documents the specific gaps") is precisely the number the product does not yet record (B-9 finishing minutes and patch). No change; the product's EVIDENCE §2 keeps the terms apart.
5. **Sign-off by Slack/Teams button.** Incompatible with `signoff-policy.v2`: an attestation must name an accepted row the approver read, and the product deliberately keeps sign-off out of the MCP surface (DL-039). Reject.

### 3c. Candidate learnings

| # | Learning | Rating | Why | Effort | Persona |
|---|---|---|---|---|---|
| A1 | **Show each backlog item's cell route before the run** — join `(capability_class × size_estimate)` to the repository's capability map at freeze and on the Factory list: "cell routes `calibrate` (n = 4 < 10): delivery will be withheld"; the run form totals how many items can deliver | **adopt** | Cheap, UI + one API field; stops paid builds whose PR the route gate will refuse; D8's "predicted outcome" in the product's own terms (a route with its reason, not a score) | S | operator |
| A2 | **Capture human PR review comments on factory PRs** — when B-9 polls the PR for its merge outcome (the App's `Pull requests: read`), also record review states and comments as `ReviewRecord` findings (rung 4 evidence, human-authored); a comment that names a missing behaviour is offered as a value-slot gap on a proposed evolution (with A1/E2) | consider | §05 "feedback capture": a reviewer's "this should handle the null case" is a testing-contract gap; the maintainers' comments are the best finishing signal the product can get for free | M | developer (P7), approver |
| A3 | **PR body names the signed facts and the licensing sign-off** — add to `delivery.pr_body`: each structural slot with `verifier` and `signed_at`; the cell sign-off (approver, date, `policy_version`) that made the route `deliver`; the reviewer identity. Specifies F10's "PR-body standard" | consider | §05 "PR enrichment … trace any line back to the requirement"; the brief's P7 persona asks for "the approver who signed the cell" in the PR and it is not there today (`delivery.py:245–290`) | S | developer (P7), AppSec |
| A4 | Change-impact maps to size the belt scope | reject | The belt scope is the repository's declared scope; inferring it from co-change history would change the instrument (apparatus) and hide a wrong scope inside a heuristic — F3 shape detection covers prefixes at onboarding | — | — |
| A5 | Pattern library / anti-patterns as hard constraints in context | reject | Advisory context is the weakest prevention tier and the product's own finding is that generic context ≈ 0 (EVIDENCE §6b); the product's constraints are belts, not prose | — | — |

---

## 4. AAF ISO Guide to Architecture & Code Quality v1.0

### 4a. What it says that the product already does — verified in code **[hypothesis]**

| Guide requirement | Product | Evidence |
|---|---|---|
| ISO 42010 viewpoints (structural, behavioural, deployment, data, security) | ARCHITECTURE.md is arc42 + C4: context, containers, components, three sequence views, deployment, cross-cutting, data model, quality scenarios, risks | docs/ARCHITECTURE.md §1–§9 |
| ADRs with Context / Decision / Consequences / Alternatives; superseded ADRs retained | Template has all four; every ADR has "Alternatives considered"; the index carries status | docs/adr/README.md; `grep "Alternatives considered" docs/adr/*.md` |
| Module boundaries: single-direction dependencies, enforced by static analysis, violations block merge | import-linter layers + stdlib-core contracts, a required CI job under branch protection | ADR-0008; DL-037 |
| Every public interface documented (contract, error states, versioning) | API.md; every source file's Navigation block (what it is / proves / touch when); `APPARATUS_VERSION` bumps only with an ADR | FILE-HEADER-STANDARD; ARCHITECTURE §7.4 |
| QC-4 error prevention: warn before irreversible actions, no silent destructive defaults | Sign-off check-your-answers and "what your signature does not mean"; the Measure button names the spend; delivery default OFF; `assert_not_default_branch` before credentials | DL-042; `delivery.py` |
| QC-6 confidentiality / integrity / non-repudiation | `redact` on every stored string; gitleaks in CI; append-only tables with triggers + hash chain; `verifier` + `verified_at` on every attestation | ADR-0002, ADR-0006, SECURITY.md |
| QC-9 safety: no destructive action (delete, deploy, merge) without human approval | The factory never merges; a human merges the PR; the route gate and an approver decide whether a PR may even be opened | ADR-0003 amendment 2026-09-16 |
| A06 CVE scan; A08 artefact integrity; A09 tamper-evident logs; A10 controlled egress | pip-audit + Dependabot; cosign keyless + SPDX attestation (DL-039); hash chain; ADR-0012 egress sidecar + Helm NetworkPolicy | .github/; DEPLOYMENT.md |
| "Irrelevant checks are explicitly recorded as N/A, not silently skipped" | Belt 5 is `None` = *not evaluated* when the repository configures no linter, hashed as such, `n_lint_evaluated` shown | ADR-0011; grade.py |
| §6.3 corrective action verified "using the same story as a regression test"; effectiveness checked next sprint | `crb learn remeasure` re-runs the *same* `task_ids`; an accepted guard-corpus line makes the false positive a failing test before the next build | LEARNING-LOOP.md §2.1, §2.3 |
| Stage-5 verdict schema: perspective, verdict, findings with severity + evidence, reviewer, timestamp | `FactoryVerdict` (probes, verdict, identity, `recorded_before_edit`); `ReviewRecord` (`findings {kind, note, file, line}`, `patch_sha256_reviewed`, verifier) | review.py (both) |
| Q1 / Q2 / Q3 as review scores | `accept / accept_with_edit / reject` | review.py:85 |

### 4b. Where the product contradicts or has drifted from it

1. **ADR immutability and a named approver.** The guide: an ADR is immutable once approved and may only be superseded; it must carry `Approver — named human sign-off with date`; "MUST NOT proceed until Accepted". The product amends in place (ADR-0001, 0003 ×2, 0006, 0011, 0012 carry dated amendment sections), the template has no approver field (attribution lives in DECISION-LOG, e.g. ADR-0014 "operator decision DL-041"), and **ADR-0013 is `Proposed` while in force** — CodeRabbit was attached under DL-032, its findings adopted under DL-033, `.coderabbit.yaml` is live. In-place amendment is defensible (dated, git-tracked, one document per decision) and not worth a supersede-only rule; the status and the missing attribution line are two-line document fixes, not backlog rows.
2. **Quality thresholds on the product's own code.** Guide: coverage ≥ 80 % per module, cyclomatic complexity ≤ 10, duplicated blocks ≤ 5 lines. Product CI: `--cov-fail-under=70` aggregate (`ci.yml:164`); ruff has no `C901` and ignores `PLR0912/PLR0915`; no duplication scanner. These govern crb's code, not its verdicts. Under the "never weaken a gate" rule the floor can be ratcheted to the measured value in one line; a complexity report can be added non-blocking. A developer's one-liner, not a backlog row (see §6).
3. **Nonconformity root cause and recurrence.** Guide §6.3: every failure gets one of four root-cause categories (context gap / prompt / model ceiling / process); "3+ occurrences of the same root-cause category are escalated". Product: `failure_kind ∈ {builder_red, lint, protocol, harness, …}` is an *instrument-vs-model* split (DL-013), which is the right first cut; `crb learn refusals` groups refusals by command shape with `n`, `$` and minutes lost. What is absent is the alarm: nothing notices when a shape **recurs after** its corpus line was accepted, or when a failure class keeps recurring across runs — the "prevention verified" step. See F33.
4. **OWASP by change type.** Guide §5 triggers OWASP checks per change type, N/A recorded explicitly. Product: the factory review has no security probe; the taxonomy has no security class; EVIDENCE §2's "security gates pass" in the Semantic-Q1 definition is vocabulary only. Adopting the OWASP-A01…A10 mapping as *prose* would be advisory context (rejected, §3c A5). The transferable principle is ADR-0011's: run **the repository's own** gate. See F31.
5. **"Model names never hard-coded; capability requirements resolved by a registry".** The product does the opposite on purpose: the model id is a cell-key axis and a new id is a new cell with no inherited capability (EVIDENCE §4). Not drift.

### 4c. Candidate learnings

| # | Learning | Rating | Why | Effort | Persona |
|---|---|---|---|---|---|
| I1 | **Recurrence-after-prevention alarm** — `crb learn refusals` (and the failure-kind split) remember which shapes / kinds have an accepted prevention (corpus line, re-measure) and raise a Decisions-inbox item "prevention failed: shape X recurred n times since line accepted on D"; the metric is recurrence per class, reported with n | consider | §6.3's escalation rule made mechanical; the product's stated goal is defect-class recurrence → 0 and today nothing measures it | S | operator, developer |
| I2 | **The repository's own security scanner as a review probe** — a fourth probe in `review.default_probes` that runs the scanner the repository already configures (`bandit`/`semgrep`/`gosec`/`npm audit`/`cargo audit` at the pinned version) on the changed files; `None` = not evaluated when none is configured (never a silent pass); a finding is a `major` (caps at `accept_with_edit`) | consider | Mirrors ADR-0011 exactly; answers the AppSec persona's first question about a factory PR; needs an ADR because it changes what `accept` means | M | AppSec (P5), approver |
| I3 | ADR-0013 → `Accepted` (or state why it stays Proposed); a "Decided by: DL-NNN" line in the ADR template | — | Document hygiene; do with the next ADR touch, not a backlog row | — | auditor/ARB |
| I4 | Coverage floor ratchet + non-blocking complexity report | — | One line in CI each; not a backlog row | — | developer |

---

## 5. The operator's experience profile

### 5a. What it records that the product already embodies — verified in code **[hypothesis]**

The profile's "unifying theme" — *clarify what must be true, structure the knowledge, build quality in, measure, escalate where evidence is insufficient* — is the run pipeline in one sentence (README "The instrument in six steps"). Item by item, from its §2 "AI-enabled software manufacturing": Definition-of-Ready gates that stop on unsigned facts (`readiness.NotReady`); classification-specific rather than generic context (structural slots per class; the corrected context finding in EVIDENCE §6b); oracle-led production (`testfirst.prove_red`, belt 1 byte-identity); belts that fail closed on modified tests, regressions, or an absent source change (`grade.py`); routing on measured capability, oracle strength and confidence (`routing.py`); independent review and an append-only ledger (`review.py`, ADR-0002, `factory/evidence.py`); refusal and escalation as positive behaviours (`calibrate` / `human` "are product successes", EVIDENCE §6). From §3: mechanical vs semantic kept apart (EVIDENCE §2); held-out tests over self-assessment (no builder self-report is ever consulted, §6c rung 1); oracle adequacy measured (`crb.core.oracle`, per-task, DL-021). From §1 and §6: provenance with ownership and versioning (apparatus stamp, `policy_thresholds`, `verifier` on every record); "targeted regeneration when guidance changes" is exactly *evidence expires* (stale sign-offs at read, `crb learn remeasure`); traceability from intent to evidence (backlog item → gap sign-off → RED proof → pack hash → ledger row → PR body). The profile's "Evidence boundaries" section is EVIDENCE-AND-CLAIMS §7 in prose.

### 5b. Where the product diverges

- **Numbers.** The profile's reported-evidence table (848/927; 834/855 = 97.5 %; 33→46/48; 58/60; 58.3 %; ≈40 forward) is the essay's and inherits every caveat in §2b above — in particular the 46/48 row is the pre-correction figure and the ≈40 forward-mode changes are not crb's. The profile itself says such figures "should be supported by project evidence or references"; the product's own numbers (README "What has been measured") are the ones to put in front of a client.
- **Clinical-safety framing (hazards, controls, acceptance measures, escalation routes).** The product has the stop conditions (EVIDENCE §8.7) and a threat → mitigation table (SECURITY.md T1–T12) but not a hazard-log-shaped document. The brief already marks DCB0160 as an inference and scopes a CSO to subject repositories that are Health IT (F17). Not a new row.
- **Adoption.** "Training and adoption materials to make improved practices sustainable" — served by the Home task list, the Connect walk, ONBOARDING-A-REPO and the human-review guide; role-specific walkthroughs are the journey itself (DL-040). Nothing new.
- **Azure DevOps.** The transformation record (Next, Adare) and DL-004's "Copilot later" suggest the client base sits on ADO at least as often as GitHub. `delivery.py` already names an ADO seam. This is a prioritisation note for **F21**: split it so the ADO connector leads GitLab. Not a new row.

### 5c. Candidate learnings

None that are not already above or already on the backlog. **Verdict: nothing new** — and that is the right result for a document whose purpose is to record the standards the product was built to embody.

---

## 6. Proposed backlog rows **[aspiration]**

For docs/reviews/2026-09-17-enterprise-front-end.md §9 (F23–F26 are already taken by docs/reviews/2026-09-17-persona-walkthrough.md, so these start at F27). Only adopt / consider items; ordered by priority then effort. Sources: QF = the Quality Floor essay; AA = Automated Agile process architecture; ISO = AAF ISO guide.

| ID | Item | Source doc | Why (one line) | Persona | Effort | Priority (P1/P2/P3) |
|---|---|---|---|---|---|---|
| F27 | **Audit sample per signed cell** — a pre-registered, hash-seeded pick of k accepted rows per signed cell per apparatus lands in the Decisions inbox; each read is a byte-anchored `ReviewRecord`; the cell shows *audited false-Q1 (semantic)* with n and a Wilson interval beside the mechanical 0; EVIDENCE §6 row 5 becomes a claim the product can make | QF | The essay's own "designed, not run" rung; turns §2's audited-semantic vocabulary into a number and gives B-12 rows to route on | approver, auditor/ARB | M | P1 |
| F28 | **Item's cell route before the run** — join each backlog item's (class × size) to the capability map at freeze and on the Factory list ("routes `calibrate`, n = 4 < 10 — delivery will be withheld"); the run form counts deliverable items | AA (D8/D9) | Today the route gate's refusal is learned after the build is paid for (`decisions.ts:128`); one API field + UI | operator | S | P2 |
| F29 | **PR body names the signed facts and the licensing sign-off** — `delivery.pr_body` gains each structural slot with verifier and date, the cell sign-off (approver, date, policy version) that made the route `deliver`, and the reviewer identity; this *specifies* F10's "PR-body standard" | AA (§05 PR enrichment) | The brief's P7 persona asks for "the approver who signed the cell" in the PR; it is not there (`delivery.py:245–290`) | developer (P7), AppSec | S | P2 |
| F30 | **Human PR review comments as evidence** — when B-9 polls a factory PR for its merge outcome, also record review states and comments as human `ReviewRecord` findings; a comment naming a missing behaviour is offered as a value-slot gap on a proposed evolution (with F32) | AA (§05 feedback capture) | The maintainers' comments are the strongest free finishing signal; rung-4 human evidence, never a verdict input; extends B-9 | developer (P7), approver | M | P2 |
| F31 | **Repository's own security scanner as a review probe** — fourth probe in `review.default_probes`, the scanner the repo configures at its pinned version, on changed files; `None` when none is configured (never a silent pass); a finding caps the verdict at `accept_with_edit`; ADR required | ISO (§5) | ADR-0011's principle applied to security; the first question AppSec asks of a factory PR; keeps OWASP-as-prose out | AppSec (P5), approver | M | P2 |
| F32 | **Review finding → proposed follow-up item** — `crb learn followups`: each `defect` / `regression` finding on a delivered item, and any builder-stated dispute of a signed fact, becomes an *unfrozen* `BacklogItem` with `supersedes`; freezing stays a human act | QF; ISO (§7.2 pass-with-observations → follow-on items) | Closes "reviewers minted new registered issues" without letting the product edit its frozen record; `learn.py` already emits items this way | developer, operator | S | P3 |
| F33 | **Recurrence-after-prevention alarm** — the learning loop remembers which refusal shapes / failure kinds have an accepted prevention and raises an inbox item when one recurs; recurrence per class is the reported metric | ISO (§6.3) | "3+ occurrences escalate" made mechanical; nothing today measures whether a prevention held | operator, developer | S | P3 |
| F34 | **Verifier account kind on attestations** — `verifier_kind ∈ {oidc, local, service}` stamped on `SignoffRecord` and `GapSignoff` at write; the UI and the licence sentence say "signed by a service account" when so | QF ("operator-delegated … stamped as such") | Makes the essay's weaker-tier caveat machine-readable; a delegated signature cannot read as a person's | auditor/ARB, approver | S | P3 |

Notes for existing rows, not new ones: **F10** — its "PR-body standard" is F29; **F21** — lead with the Azure DevOps half (profile §5b); **B-0b** (`policy_hash` pinned beside `backlog_hash`) is still open and is the essay's prospective-trial precondition; **B-9** remains the blocker for any Q2/finishing number the AA document's D10/D11 assume.

---

## 7. Rejected, and why

- **Re-importing the essay's specification-lever figures (33/48 → 46/48, +23 points, 5.6×).** The product's record (critical-friend §4.2 play 01, EVIDENCE §6b, external assessment #13) says the +23 was leakage; the copy on disk predates or omits that correction.
- **Adopting the essay's `apply-pattern` route.** ADR-0003 reconciled the routes to five; a weak oracle goes to `human`. Adding a sixth route for a vocabulary match would change the instrument for no measured reason.
- **A decomposition ("granularize into primitives") mechanism.** `granularize` is an honest route to a human; decomposition is the discovery pipeline DL-001 excluded.
- **Meetings, quarterly cadence, the context graph, Jira/Slack/Teams capture, codebase-intelligence pattern library (AA §01–§05).** Out of scope by DL-001; and the pattern library is advisory context, the weakest prevention tier, against the product's own null result on generic context.
- **Context readiness / completeness scores (AA D7, M5).** A blended score is what DL-038 and ADR-0003 refuse; readiness is a list of named open slots.
- **Sign-off by Slack/Teams button (AA §05).** An attestation must name an accepted row the approver read; sign-off is deliberately not a machine surface (DL-039).
- **Change-impact maps to infer the belt scope (AA §04).** The belt scope is declared by the repository; inferring it would put a heuristic inside the instrument.
- **OWASP A01–A10 mapping by change type as prose (ISO §5).** Advisory; the transferable part is F31 (the repo's own scanner).
- **Supersede-only ADRs and an "Approver" field (ISO §2.2).** In-place amendments are dated and git-tracked and one document per decision is easier to audit; attribution already lives in DECISION-LOG. Two document fixes (ADR-0013 status; a "Decided by" line) are noted in §4b(1), not rows.
- **Coverage ≥ 80 % / complexity ≤ 10 / duplication gates (ISO §9).** They govern crb's code, not its verdicts; ratcheting the coverage floor and adding a non-blocking complexity report are one-line CI changes a developer makes without a backlog row.
- **Model registry resolving capability requirements to a model (ISO QC-8).** The product deliberately makes the model id a cell axis so no capability is inherited across ids (EVIDENCE §4).
- **A DCB0160-shaped hazard log for the product (profile).** SECURITY.md's threat table and EVIDENCE §8.7's stop conditions are the register; a CSO-facing hazard log only if the subject repositories are Health IT, which F17 already scopes.
- **Role-specific training materials (profile).** The journey (DL-040), the Connect walk, ONBOARDING-A-REPO and the human-review guide are that material.
