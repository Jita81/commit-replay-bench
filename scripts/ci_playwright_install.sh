#!/usr/bin/env bash
# scripts/ci_playwright_install.sh — install Playwright's Chromium and the system packages it
# needs on a CI runner, with every network wait bounded and retried, so a stalled mirror costs
# one attempt instead of the whole job.
#
# Why: on PR #69 `npx playwright install --with-deps chromium` stalled inside `apt-get update`
# (its last line at 19:47:11, then nothing) until GitHub cancelled `walkthrough-story` at its
# 40-minute timeout, 20:26:36, with no spec run (docs/PREVENTION.md P-751). Nothing bounded the
# wait, so a runner's network fault became a red required check that only a rerun could clear.
#
# What it does, from ui/ (where @playwright/test is installed):
#   1. tells apt to give up on a silent mirror after 30 s and retry it (Acquire::*::Timeout,
#      Acquire::Retries), and to wait at most 60 s for the dpkg lock;
#   2. installs the system packages AS ROOT under `timeout`, so the kill reaches apt-get and
#      dpkg too, up to CRB_PW_ATTEMPTS times; before a retry, `dpkg --configure -a` finishes
#      whatever a killed attempt left half-configured;
#   3. downloads the browser as the runner user under `timeout`, up to CRB_PW_ATTEMPTS times.
# Exits 0 when both phases succeeded, 1 when a phase used every attempt, 2 on a bad setting.
#
# Usage (CI):  cd ui && bash ../scripts/ci_playwright_install.sh
#   CRB_PW_ATTEMPTS=3          attempts per phase (default 3)
#   CRB_PW_DEPS_SECONDS=240    the bound on one system-package attempt (default 240; the slowest
#                              whole install step on PR #69's run, apt and download, took 152 s)
#   CRB_PW_BROWSER_SECONDS=150 the bound on one browser-download attempt (default 150)
#   CRB_APT_CONF=…             the apt settings file (default
#                              /etc/apt/apt.conf.d/80-crb-ci-network; the tests use a temp file)
#
# Navigation
# ----------
# What it is:   The bounded, retried Playwright install every CI job that drives a browser runs.
# What it does: Writes apt's network timeouts and retries, then installs Chromium's system
#               packages (as root) and the browser (as the runner), each attempt under `timeout`
#               and retried, and fails with the phase it could not finish rather than hanging.
# How:          `sudo tee` the apt settings → `attempt deps …` around
#               `sudo env PATH=… timeout … playwright install-deps chromium` → `attempt browser …`
#               around `timeout … playwright install chromium`; `attempt` loops CRB_PW_ATTEMPTS
#               times and runs `dpkg --configure -a` before a system-package retry.
# Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
# ADRs:         none
# Works with:   .github/workflows/ci.yml (ui-smoke, walkthrough-story and walkthrough-screens run
#               it), scripts/ci_job_budget.py (the job-budget guard a stalled install used to
#               exhaust), docs/PREVENTION.md (P-751, the class it closes)
# Tested by:    tests/test_ci_playwright_install.py
# Touch when:   never for a new repository (it installs this repository's own CI browser); a
#               job starts driving a browser (run this script, never a bare `playwright
#               install`); the install takes longer than its per-attempt bound on a healthy run.

set -euo pipefail

attempts="${CRB_PW_ATTEMPTS:-3}"
deps_seconds="${CRB_PW_DEPS_SECONDS:-240}"
browser_seconds="${CRB_PW_BROWSER_SECONDS:-150}"
apt_conf="${CRB_APT_CONF:-/etc/apt/apt.conf.d/80-crb-ci-network}"
playwright="./node_modules/.bin/playwright"

for setting in "$attempts" "$deps_seconds" "$browser_seconds"; do
  if ! [[ "$setting" =~ ^[1-9][0-9]*$ ]]; then
    echo "ci_playwright_install: '$setting' is not a positive whole number" >&2
    exit 2
  fi
done
if [[ ! -x "$playwright" ]]; then
  echo "ci_playwright_install: no $playwright here — run it from ui/ after npm ci" >&2
  exit 2
fi

printf '%s\n' \
  'Acquire::Retries "3";' \
  'Acquire::http::Timeout "30";' \
  'Acquire::https::Timeout "30";' \
  'DPkg::Lock::Timeout "60";' | sudo tee "$apt_conf" >/dev/null

# attempt <phase> <command…> — run the (already bounded) command up to $attempts times.
attempt() {
  local phase="$1"
  shift
  local n rc
  for ((n = 1; n <= attempts; n++)); do
    if [[ "$n" -gt 1 && "$phase" == deps ]]; then
      sudo dpkg --configure -a || true
    fi
    if "$@"; then
      echo "ci_playwright_install: $phase installed on attempt $n of $attempts"
      return 0
    else
      rc=$?
    fi
    if [[ "$rc" -eq 124 || "$rc" -eq 137 ]]; then
      echo "::warning::ci_playwright_install: $phase attempt $n of $attempts hit its time bound (exit $rc); retrying (P-751)"
    else
      echo "::warning::ci_playwright_install: $phase attempt $n of $attempts failed (exit $rc); retrying (P-751)"
    fi
  done
  echo "::error::ci_playwright_install: $phase failed on all $attempts attempts — the runner's network or package mirror is down, not the product (docs/PREVENTION.md P-751)"
  return 1
}

attempt deps sudo env "PATH=$PATH" timeout --kill-after=15 "$deps_seconds" \
  "$playwright" install-deps chromium
attempt browser timeout --kill-after=15 "$browser_seconds" "$playwright" install chromium
