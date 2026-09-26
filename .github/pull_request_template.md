## What changes

<!-- One paragraph: what is true after this change that was not before. -->

## Evidence

<!-- The gates you ran, verbatim (ruff, mypy, lint-imports, code_map, dod_check, claims_check,
pytest, and in ui/ `npm run typecheck` + vitest when the UI changed). Tag every quantified
claim: [measured — n, method, apparatus] · [hypothesis] · [aspiration] · [gap]. -->

## Definition of done

<!-- The criteria in docs/dod/ this closes or adds, and GAP-ANALYSIS.md regenerated. -->

## Bugs: the artefact that stops the class (docs/dod/STANDARD.md §7)

A defect is closed only with the artefact that fails if its class recurs.

- [ ] This change fixes no bug, **or**
- [ ] each bug it fixes has a row in `docs/PREVENTION.md` naming its class, its first-seen
      evidence, its level (construction › gate › mistake-proofing › advisory) and the artefact
      (`test:` / `vitest:` / `spec:` / `ci:`) — or `pending` with a gap and an owner
- [ ] I broke or removed each prevention artefact once and watched its test fail, then
      restored it (say which, below)

<!-- P-nnn: the class, the artefact, and the failure you saw when you removed it. -->
