#!/usr/bin/env sh
# exmap/start.sh — one command: installs, builds, starts, opens the browser
set -eu
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v node >/dev/null 2>&1; then
  echo "exmap needs Node.js 22.12 or newer, and 'node' is not on your PATH." >&2
  echo "Install it from https://nodejs.org (LTS) and run this again." >&2
  exit 2
fi
exec node "$dir/bin/exmap.mjs" "$@"
