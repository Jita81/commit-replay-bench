#!/usr/bin/env bash
# scripts/walkthrough.sh — boot a FRESH crb stack in a temporary CRB_HOME and drive it
# through the browser walkthrough suite (ui/e2e/walkthrough), then tear everything down.
#
# Tier 1 (default) is hermetic: no network, no model, no credential. The "public" repo
# is a local bare clone of tests/fixtures/pyrepo.py served over file:// (the server and
# worker run with CRB_ALLOW_LOCAL_CLONE=1, a test/dev switch), the replay uses the
# test-only `fixture_gold` builder (CRB_ENABLE_FIXTURE_BUILDER=1, never in production),
# and the pytest runner is pinned to this venv's interpreter so no `pip install` runs.
#
# Tier 2 (opt-in, needs the network / a model) reuses the same specs:
#   CRB_E2E_PUBLIC=1              onboard github.com/spf13/cobra + pallets/click for real
#   CRB_E2E_BUILDER=claude_code   05 runs a REAL replay (claude_code, auth=cli, limit 2)
# See ui/e2e/walkthrough/README.md.
#
# Isolation contract (this script may run next to an operator's live stack):
#   * everything it creates lives under ONE `mktemp -d` directory: CRB_HOME, the SQLite
#     database, the fixture repo, logs, downloads, the Playwright report and traces;
#   * it refuses to start if CRB_HOME or CRB_DATABASE_URL is already set — it never
#     inherits, migrates or writes another stack's home or database;
#   * it binds a FREE ephemeral port (never 8000) and the specs use CRB_E2E_BASE_URL only;
#   * it stops ONLY the two processes it started (tracked PIDs; never `pkill`);
#   * it removes ONLY its own temp directory, and keeps it on failure (or CRB_E2E_KEEP=1)
#     so the report and the logs survive;
#   * it reads no env.sh / secrets file; the only files it touches outside the temp dir
#     are ui/dist (built if missing) and the report/output dirs YOU point it at.
#
# Usage:  scripts/walkthrough.sh [extra playwright args…]
#   CRB_E2E_KEEP=1        keep the temp directory even on success (path is printed)
#   CRB_E2E_PORT=NNNN     bind the API to a fixed port (never 8000; default: a free one)
#   CRB_E2E_PAD=N         padding commits on the fixture history (default 40)
#   CRB_PYTHON=…          interpreter with crb[server,dev] installed (default .venv/bin/python)
#   CRB_E2E_REPORT_DIR=…  Playwright HTML report dir (default <tmp>/playwright-report)
#   CRB_E2E_OUTPUT_DIR=…  Playwright traces/screenshots dir (default <tmp>/test-results)
#
# Exit code is Playwright's. Server/worker log tails are printed on failure.
#
# Navigation
# ----------
# What it is:   The browser-walkthrough driver: boots a FRESH crb stack in a temporary
#               ``CRB_HOME`` and runs the Playwright suite against it, then tears it down.
# What it does: Tier 1 (default) is hermetic — a padded ``fixtures.pyrepo`` served as a bare
#               ``file://`` remote, the test-only ``fixture_gold`` builder, the venv's own pytest;
#               tier 2 (``CRB_E2E_PUBLIC`` / ``CRB_E2E_BUILDER``) reuses the same specs against real
#               repositories and a real model. It refuses to run when ``CRB_HOME`` or
#               ``CRB_DATABASE_URL`` is already set and never binds port 8000, so it cannot touch an
#               operator's live stack.
# How:          Refuse-if-configured → build ``ui/dist`` if stale → build and bare-clone the
#               fixture → export a fresh env (secret, admin, local sandbox, dev switches) →
#               ``crb migrate`` → ``crb serve`` + ``crb worker`` on a free port → wait for
#               ``/health`` → export the ``CRB_E2E_*`` contract → ``npx playwright test``; the
#               trap stops only the two PIDs it started and removes only its own temp dir (kept
#               on failure or ``CRB_E2E_KEEP=1``).
# Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
# ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
# Works with:   ui/e2e/walkthrough/README.md (the tiers and the spec list),
#               ui/playwright.walkthrough.config.ts (the config it runs), tests/fixtures/pyrepo.py
#               (the fixture it pads), src/crb/builders/fixture_gold.py (the builder it enables),
#               src/crb/cli/main.py (``migrate`` / ``serve`` / ``worker``), .github/workflows/ci.yml
#               (the ``walkthrough`` job)
# Tested by:    ui/e2e/walkthrough/01-login.spec.ts, ui/e2e/walkthrough/05-replay-fake.spec.ts
#               (the suite it drives; the script itself has no unit test — CI runs it end to end)
# Touch when:   a spec needs another ``CRB_E2E_*`` variable (export it in step 4 and document it in
#               the README); the server or worker CLI flags change; never to inherit an existing
#               home, database or port.

set -euo pipefail

# --- 0. refuse to touch another stack ----------------------------------------------------
for v in CRB_HOME CRB_DATABASE_URL; do
  if [[ -n "${!v:-}" ]]; then
    echo "walkthrough: $v is set ($v=${!v}) — refusing to run: this script boots its OWN stack in a" >&2
    echo "  temporary directory and must never inherit, migrate or write another stack's home/database." >&2
    echo "  Unset it (env -u $v scripts/walkthrough.sh …) to continue." >&2
    exit 2
  fi
done
if [[ "${CRB_E2E_PORT:-}" == "8000" ]]; then
  echo "walkthrough: CRB_E2E_PORT=8000 is refused — 8000 is the default port of a live crb server" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${CRB_PYTHON:-$ROOT/.venv/bin/python}"
CRB="$(dirname "$PY")/crb"
UI="$ROOT/ui"

if [[ ! -x "$PY" ]]; then
  echo "walkthrough: no interpreter at $PY — create the venv first:" >&2
  echo "  uv venv -q .venv --python 3.12 && uv pip install -q -e '.[server,dev]' --python .venv/bin/python" >&2
  exit 2
fi
if [[ ! -x "$CRB" ]]; then
  echo "walkthrough: $CRB missing — install the [server] extra" >&2
  exit 2
fi
if ! "$PY" -c "import crb.server.app" 2>/dev/null; then
  echo "walkthrough: the server layer is not installed in $PY (pip install -e '.[server,dev]')" >&2
  exit 2
fi
command -v git >/dev/null || { echo "walkthrough: git is required" >&2; exit 2; }
command -v npx >/dev/null || { echo "walkthrough: node/npx is required" >&2; exit 2; }
command -v curl >/dev/null || { echo "walkthrough: curl is required" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/crb-walkthrough.XXXXXX")"
case "$WORK" in */crb-walkthrough.*) ;; *) echo "walkthrough: unexpected temp dir $WORK" >&2; exit 2 ;; esac
API_LOG="$WORK/api.log"
WORKER_LOG="$WORK/worker.log"
API_PID=""
WORKER_PID=""
STATUS=1

# SIGTERM first (the worker finishes its poll and exits; a run in flight keeps it busy),
# SIGKILL after a bounded grace so a failed suite never leaves the script hanging.
stop_proc() {
  local pid="$1" name="$2" i
  [[ -n "$pid" ]] || return 0
  kill "$pid" 2>/dev/null || return 0
  for i in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || { wait "$pid" 2>/dev/null; return 0; }
    sleep 0.5
  done
  echo "walkthrough: $name did not stop on SIGTERM; killing" >&2
  kill -9 "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null || true
}

cleanup() {
  local rc=$?
  set +e
  stop_proc "$WORKER_PID" worker
  stop_proc "$API_PID" api
  if [[ "$STATUS" -ne 0 ]]; then
    echo "----- walkthrough: api log (tail) -----" >&2
    tail -n 60 "$API_LOG" >&2 2>/dev/null
    echo "----- walkthrough: worker log (tail) -----" >&2
    tail -n 60 "$WORKER_LOG" >&2 2>/dev/null
  fi
  if [[ "${CRB_E2E_KEEP:-0}" == "1" || "$STATUS" -ne 0 ]]; then
    echo "walkthrough: temp directory kept at $WORK (logs, report, traces)" >&2
  else
    case "$WORK" in */crb-walkthrough.*) rm -rf "$WORK" ;; esac   # only ever our own temp dir
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

# --- 1. the UI bundle -----------------------------------------------------------------
# Always rebuild: a stale dist (older than any source file) silently tests the wrong UI —
# the walkthrough specs rely on data-testids that only a current build carries.
newest_src="$(find "$UI/src" "$UI/index.html" "$UI/public" -type f -newer "$UI/dist/index.html" 2>/dev/null | head -1 || true)"
if [[ ! -f "$UI/dist/index.html" || -n "$newest_src" || "${CRB_E2E_REBUILD_UI:-0}" == "1" ]]; then
  echo "walkthrough: building the UI (dist missing or stale)" >&2
  (cd "$UI" && npm run build >"$WORK/ui-build.log" 2>&1) || { cat "$WORK/ui-build.log" >&2; exit 2; }
fi

# --- 2. the "public" repo: tests/fixtures/pyrepo.py as a bare file:// remote -----------
# The three-commit fixture is padded with CRB_E2E_PAD (default 40) further coupled
# src+test commits — each RED at its parent and GREEN with its own source, exactly the
# shape the miner admits — so a full mine takes long enough for 06 to cancel it while
# it is running, while a `limit 3` mine (03) still returns in seconds.
FIXTURE_SRC="$WORK/fixture-src"
FIXTURE_BARE="$WORK/pyrepo.git"
(cd "$ROOT" && PYTHONPATH="$ROOT/tests" "$PY" - "$FIXTURE_SRC" "${CRB_E2E_PAD:-40}" <<'PYEOF'
import sys
from pathlib import Path
from fixtures import pyrepo

root, pad = Path(sys.argv[1]), int(sys.argv[2])
r = pyrepo.build(root)
for i in range(pad):
    (root / "src" / "calc" / f"op{i}.py").write_text(
        f"def op{i}(a: int, b: int) -> int:\n    return a + b + {i}\n", encoding="utf-8"
    )
    (root / "tests" / f"test_op{i}.py").write_text(
        f"from calc.op{i} import op{i}\n\n\ndef test_op{i}():\n    assert op{i}(1, 2) == {3 + i}\n",
        encoding="utf-8",
    )
    pyrepo.git(root, "add", "-A")
    pyrepo.git(root, "commit", "-q", "-m", f"feat: add op{i}")
print(f"fixture repo at {r.path}: feat {r.feat_sha[:8]} + {pad} padding commits", file=sys.stderr)
PYEOF
)
git clone -q --bare "$FIXTURE_SRC" "$FIXTURE_BARE"
REPO_URL="file://$FIXTURE_BARE"

# --- 3. a fresh stack in a temp CRB_HOME -------------------------------------------------
export CRB_HOME="$WORK/home"
mkdir -p "$CRB_HOME"
export CRB_ENV=dev
export CRB_DATABASE_URL="sqlite:///$CRB_HOME/crb.db"
export CRB_UI_DIST="$UI/dist"
export CRB_SANDBOX__EXECUTOR=local
export CRB_LOG_FORMAT=text
export CRB_LOG_LEVEL="${CRB_LOG_LEVEL:-INFO}"
export CRB_ALLOW_LOCAL_CLONE=1        # file:// remotes (test/dev switch)
export CRB_ENABLE_FIXTURE_BUILDER=1   # registers the test-only fixture_gold builder
export CRB_ENABLE_FAKE_TRACKER=1      # admits the file-backed fake tracker (ADR-0017); NO real ADO/Jira is ever contacted
export CRB_INTAKE__TRACKER=fake
export CRB_INTAKE__URL="https://tracker.invalid"
export CRB_INTAKE__PROJECT=Widgets
export CRB_INTAKE__COLUMN="Ready for manufacture"
# the worker's own timed poll is parked for the length of the run (a day): spec 12 drives the
# OPERATOR's reads — "Re-read the column now" — and asserts what each one did (1 read, 1
# registered). A 30-second timer raced those clicks and made "1 seen, 0 read" a real outcome,
# because the worker had already handled the ticket at that revision. The timed poll itself is
# covered by tests/test_intake_worker.py, which owns the timer.
export CRB_INTAKE__POLL_S=86400
E2E_USER="${CRB_E2E_USER:-walkthrough-admin}"
E2E_PASS="${CRB_E2E_PASS:-$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')}"
export CRB_BOOTSTRAP_ADMIN__USERNAME="$E2E_USER"
export CRB_BOOTSTRAP_ADMIN__PASSWORD="$E2E_PASS"
export CRB_SECRET_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"   # always fresh; never an inherited key

free_port() {
  "$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}
PORT="${CRB_E2E_PORT:-$(free_port)}"
while [[ "$PORT" == "8000" ]]; do PORT="$(free_port)"; done   # never a live server's default
BASE_URL="http://127.0.0.1:$PORT"
# the stack's own address, so the links intake writes on the fake board are absolute and
# openable — a listener may not be switched on without it
export CRB_PUBLIC_URL="$BASE_URL"

"$CRB" migrate >"$API_LOG" 2>&1

"$CRB" serve --host 127.0.0.1 --port "$PORT" >>"$API_LOG" 2>&1 &
API_PID=$!
"$CRB" worker --home "$CRB_HOME" --executor local --poll 0.5 >"$WORKER_LOG" 2>&1 &
WORKER_PID=$!

# wait for the API (and the worker's first heartbeat is not required — runs are queued)
for _ in $(seq 1 120); do
  if curl -fsS "$BASE_URL/api/v1/health" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$API_PID" 2>/dev/null; then echo "walkthrough: API exited early" >&2; exit 2; fi
  sleep 0.5
done
curl -fsS "$BASE_URL/api/v1/health" >/dev/null || { echo "walkthrough: API never became healthy" >&2; exit 2; }
if ! kill -0 "$WORKER_PID" 2>/dev/null; then echo "walkthrough: worker exited early" >&2; exit 2; fi

echo "walkthrough: stack up at $BASE_URL (home $CRB_HOME, repo $REPO_URL)" >&2

# --- 4. what the specs need ----------------------------------------------------------------
export CRB_E2E_BASE_URL="$BASE_URL"
export CRB_E2E_USER="$E2E_USER"
export CRB_E2E_PASS="$E2E_PASS"
export CRB_E2E_REPO_URL="$REPO_URL"
export CRB_E2E_REPO_NAME="${CRB_E2E_REPO_NAME:-walk-pyrepo}"
export CRB_E2E_PYTHON="$PY"            # the pytest runner's interpreter (has pytest; no install)
export CRB_E2E_CRB="$CRB"              # `crb ledger verify --path` for the exported JSONL
export CRB_E2E_WORK="$WORK"            # downloads land here
export CRB_E2E_BOARD="$CRB_HOME/intake-fake.json"   # the fake tracker's whole board (ADR-0017)
export CRB_E2E_REPORT_DIR="${CRB_E2E_REPORT_DIR:-$WORK/playwright-report}"
export CRB_E2E_OUTPUT_DIR="${CRB_E2E_OUTPUT_DIR:-$WORK/test-results}"

# --- 5. the walkthrough ---------------------------------------------------------------------
set +e
(cd "$UI" && npx playwright test --config playwright.walkthrough.config.ts --project=chromium "$@")
STATUS=$?
set -e
exit "$STATUS"
