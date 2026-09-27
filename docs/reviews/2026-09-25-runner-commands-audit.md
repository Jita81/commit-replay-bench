# Runner-command audit — the six live repositories, 2026-09-25

**What this is.** For each repository the operator's stack measures, what the product derives
(belt 5's plan, the format step's formatter, the finish gate's derived commands, the test
harness command) set against what the repository's own CI runs on every pull request — and
what was fixed where they disagreed. It is the evidence behind ADR-0024's amendment to
ADR-0011's detectors.

**How it was measured.** `scripts/audit_runner_commands.py` over a shallow clone of each
repository's upstream default branch **[measured — n = 6 repositories (spf13/cobra @ adbc881,
pallets/click @ 06b2a67, koajs/koa @ 824c1cf, nhsuk/nhsuk-frontend @ b1a40ba,
NHSDigital/nhsuk-react-components @ 4074920, NHSDigital/mesh-client @ eed9813), method: the
audit script's derived checks against each repository's workflows, Makefile, `package.json`
scripts, `pyproject.toml` / `tox` and pre-commit hooks, read on 2026-09-25, apparatus 2.2]**.
The JavaScript repositories were read as the provisioned sandbox reads them
(`--assume-installed`: their `node_modules` were not installed for the audit).

**What it cannot see.** The configurations stored in the operator's stack were not read (the
stack is the operator's); the stack replays historical commits whose configuration can differ
from the upstream head (mesh-client pinned `ruff ^0.2.0` in 2026-09; its head pins
`>=0,<1`). A gap listed below is therefore a gap in what the runner derives for that
repository's *current* configuration **[gap — re-run the script on the stack's own clones at
the replayed commits]**.

## The findings

| repository | CI runs | derived before | fixed here | still a gap (and the fix) |
|---|---|---|---|---|
| cobra | golangci-lint (formatters `gofmt`, `goimports`; linters incl. `govet`, `staticcheck`), `make richtest` | `gofmt -l` | `go vet ./...` derived for the finish gate from `.golangci.yml`'s `govet` | `goimports`, `golangci-lint`, `staticcheck` are not in the Go toolchain or the Go sandbox image — declare them under `RepoConfig.lint` / `checks.commands` once the image carries them |
| click | pre-commit `ruff-check` + `ruff-format` (rev frozen to v0.15.9), `tox -e typing` (mypy + pyright), codespell | `ruff check` + `ruff format --check` with **no version pin** (the frozen-sha rev was unreadable) | the pin `==0.15.9` is read from the `# frozen:` comment; a ruff outside the pin refuses its step (a harness error naming the pin) instead of judging | mypy, pyright, codespell — declare `checks.commands` `typing: [python, -m, mypy]` where the repository's environment installs the `typing` group |
| koa | `npm run lint` (`standard`), `npm run test:coverage` | `standard` for belt 5; no formatter for the format step | `standard --fix` is koa's formatter (its own `lint:fix` script) | none |
| nhsuk-frontend | `lint:js` (eslint `--max-warnings 0`), `lint:css` (stylelint `--max-warnings 0` on `**/*.{md,scss}`), `lint:prettier` (`prettier --check .`), `lint:types` (tsc), jest | eslint **without** `--max-warnings` (a warning passed), prettier on JS/TS files only, no stylelint, tsc | eslint and stylelint inherit `--max-warnings 0`; stylelint joins belt 5; prettier judges `.scss`, `.css`, `.json`, `.md`, `.yml`, `.html` too; the lint scripts and stylelint configuration are test infrastructure | none |
| nhsuk-react-components | `yarn lint` (tsc `lint:types`, eslint `--max-warnings 0`, `prettier --check .`), jest | eslint without `--max-warnings`, prettier on JS/TS only, tsc | as nhsuk-frontend | none |
| mesh-client | `make black-check`, `make lint` (ruff, mypy, shellcheck), tox | `ruff check` only; a host ruff outside the repository's pin judged every patch (the 2026-09-14 review: "belt 5 needs a pinned lint command or it reads every row as `lint`") | black's check mode joins belt 5 on the host; the pin gate refuses a ruff outside `^0.2.0` instead of reading `lint`; `[tool.black]` is test infrastructure | mypy — declare `checks.commands` `typing: [python, -m, mypy, .]` once the environment has it; under the sandbox, add black to the repository's image and declare it in `RepoConfig.lint` |

Every fix above is pinned by a test that fails if it regresses (`tests/test_runner_audit.py`),
and `lint_run.detected` records the new plan on every pack
(`eslint(max-warnings=0)+prettier+stylelint+tsc:lint:types`, `ruff@0.16.7!pin>=0.2.0,<0.3.0`).

## Observed, not changed here

- **The blind harness command for Go ends in `./...`**, and the brief appends `<paths>`
  (`go test -json ./... <paths>`); `-json` floods a builder's context with one JSON event per
  test. It is what a blind builder sees today, so changing it is an opt-in arm, not a fix
  **[hypothesis — a contributor to cobra's `budget` stops; the prevention loop's register
  measures it]**.
- The repository configurations that `PUT /repos/{name}` can write now include `checks`; the
  six live repositories carry none until the operator or the prevention loop writes one, so
  nothing changes for them until then.
