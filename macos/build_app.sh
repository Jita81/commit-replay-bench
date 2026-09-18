#!/usr/bin/env bash
# macos/build_app.sh — assemble dist/crb.app: a fully self-contained, double-clickable macOS
# application with its OWN CPython runtime, the crb server stack and the built SPA inside it.
# Nothing on the user's machine is required at runtime: no Python, no node, no pip, no network.
#
#   macos/build_app.sh
#   macos/build_app.sh --sign "Developer ID Application: NAME (TEAMID)"
#   macos/build_app.sh --python 3.12 --sign "…"
#
# Build-time requirements: `uv` (the runtime download and the install) and `npm` (the SPA).
# Neither is needed by the finished bundle.
#
#   CRB_MACOS_PYTHON_VERSION=3.12   the embedded interpreter (default 3.12; --python wins)
#   CRB_MACOS_NPM_CI=0              reuse ui/node_modules instead of running `npm ci`
#
# The bundle it writes:
#
#   dist/crb.app/Contents/
#     Info.plist                 macos/Info.plist with the pyproject version substituted in
#     MacOS/crb                  the launcher: exec's the embedded python on `-m crb.desktop`
#     Resources/python/          the embedded CPython + crb[server] (bin/python3, bin/crb, lib/…)
#     Resources/ui/              the built SPA, source maps excluded
#     Resources/crb.icns         only when macos/crb.icns exists; skipped silently otherwise
#
# LSUIElement is true in Info.plist because crb.desktop opens the user's browser rather than
# drawing a window of its own: without it macOS treats the process as a GUI application that
# never finishes launching, and it bounces in the Dock forever. See macos/Info.plist.
#
# Signing is optional. Unsigned is correct for a locally built bundle — it carries no
# com.apple.quarantine attribute, so Gatekeeper does not challenge it. A bundle that travels
# (downloaded, or unpacked from a downloaded archive) does carry the attribute and needs a
# Developer ID signature AND notarisation: sign here with --sign, then run macos/notarise.sh.
#
# Exit codes: 0 built; 1 a build step failed; 2 usage / a missing build tool.
#
# Navigation
# ----------
# What it is:   The macOS packaging script: it assembles dist/crb.app, a self-contained
#               double-clickable bundle carrying its own CPython, the crb server stack and the SPA.
# What it does: Builds the SPA and copies it in without source maps, downloads a standalone CPython
#               into the bundle, installs the repository with its ``[server]`` extra into that
#               runtime, trims the parts a shipped interpreter never needs (tests, IDLE, tkinter,
#               2to3, bytecode caches, static libraries), writes the launcher and the versioned
#               Info.plist, and optionally codesigns and verifies the result. It refuses to start
#               without ``uv`` or ``npm`` and never touches the developer's own interpreters.
# How:          Preflight the tools → build ``ui/dist`` → stage ``dist/crb.app.build`` → ``uv python
#               install --install-dir`` → delete the runtime's ``EXTERNALLY-MANAGED`` marker (it is
#               a vendored interpreter, not a system one) → ``uv pip install "<repo>[server]"`` →
#               trim and measure → launcher, Info.plist, icon → swap the staged bundle into place →
#               ``codesign --deep --options runtime --timestamp`` and ``codesign --verify --strict``
#               when ``--sign`` was given.
# Layer:        desktop — docs/ARCHITECTURE.md#6-deployment-view
# ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
# Works with:   src/crb/desktop/__main__.py (the entry point the launcher exec's; its ``--port`` /
#               ``--no-browser`` flags are this script's contract), src/crb/desktop/paths.py (reads
#               the CRB_UI_DIST / CRB_DESKTOP_CRB_BIN the launcher exports), macos/Info.plist (the
#               bundle metadata it substitutes the version into), macos/notarise.sh (the step after
#               signing: .dmg, notarytool, stapler), .github/workflows/macos-app.yml (builds and
#               smoke-boots this bundle on macos-14), scripts/check_release_tag.py (the pyproject
#               version reader it reuses rather than re-parsing the TOML), deploy/Dockerfile (the
#               other packaging of the same server + UI — keep the two honest)
# Tested by:    untested — no unit test; the smoke test in .github/workflows/macos-app.yml boots
#               the built bundle and asserts readiness
# Touch when:   the embedded Python version moves; the ``[server]`` extra gains a dependency with
#               native code (re-check the trim list and the signature); the desktop entry point's
#               flags or environment contract changes (the launcher and the smoke test move
#               together); a bundle resource is added (add it here and to the smoke test).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_VERSION="${CRB_MACOS_PYTHON_VERSION:-3.12}"
SIGN_IDENTITY=""

usage() {
    sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

die() {
    echo "build_app: $*" >&2
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --sign)
            [ "$#" -ge 2 ] || die "--sign needs an identity, e.g. 'Developer ID Application: NAME (TEAMID)'"
            SIGN_IDENTITY="$2"
            shift 2
            ;;
        --python)
            [ "$#" -ge 2 ] || die "--python needs a version, e.g. 3.12"
            PY_VERSION="$2"
            shift 2
            ;;
        -h|--help) usage ;;
        *) echo "build_app: unknown argument: $1" >&2; usage ;;
    esac
done

# --- 0. preflight -------------------------------------------------------------------------
command -v uv >/dev/null || die "uv is required to download the embedded runtime and install crb.
  Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh
  (or:  brew install uv)"
command -v npm >/dev/null || die "npm is required to build the SPA that the bundle serves.
  Install Node 22 with:  brew install node@22
  (or download it from https://nodejs.org/)"
[ -f "$ROOT/pyproject.toml" ] || die "no pyproject.toml at $ROOT — run this from inside the repository"
[ -d "$ROOT/ui" ] || die "no ui/ directory at $ROOT — the bundle serves the built SPA"

DIST="$ROOT/dist"
APP="$DIST/crb.app"
BUILD="$DIST/crb.app.build"
CONTENTS="$BUILD/Contents"
RESOURCES="$CONTENTS/Resources"
PYROOT="$RESOURCES/python"
UIDEST="$RESOURCES/ui"
# LIBDIR is discovered after the runtime is unpacked: `--python 3.12.11` would make
# lib/python$PY_VERSION wrong, and every trim below is an `rm -rf` that would silently
# succeed against a path that does not exist, shipping an untrimmed runtime.
LIBDIR=""

# The staging directory is removed on every run, so a re-run never inherits a half-built
# bundle; only the finished bundle is swapped into place at the end.
rm -rf "$BUILD"
mkdir -p "$CONTENTS/MacOS" "$RESOURCES"

# --- 1. the SPA ---------------------------------------------------------------------------
echo "build_app: building the SPA (ui/dist)"
if [ "${CRB_MACOS_NPM_CI:-1}" = "1" ]; then
    # No --legacy-peer-deps: the lockfile installs cleanly, and the flag would hide a real
    # peer-dependency conflict behind a bundle that still builds.
    (cd "$ROOT/ui" && npm ci --no-audit --no-fund)
else
    echo "build_app: CRB_MACOS_NPM_CI=0 — reusing ui/node_modules"
fi
(cd "$ROOT/ui" && npm run build)
[ -f "$ROOT/ui/dist/index.html" ] || die "npm run build produced no ui/dist/index.html"

mkdir -p "$UIDEST"
cp -R "$ROOT/ui/dist/." "$UIDEST/"
# Source maps are ~80 % of the bundle's UI bytes and are of no use to someone running the app.
find "$UIDEST" -type f -name '*.map' -delete
echo "build_app: SPA staged ($(du -sh "$UIDEST" | cut -f1), source maps excluded)"

# --- 2. the embedded runtime ---------------------------------------------------------------
# `uv python install --install-dir DIR` unpacks a standalone CPython into
# DIR/cpython-<full version>-<triple>/; the exact directory name depends on the patch release
# and the host triple, so it is discovered rather than assumed.
RUNTIME_PARENT="$BUILD/.runtime"
mkdir -p "$RUNTIME_PARENT"
echo "build_app: downloading a standalone CPython $PY_VERSION"
uv python install --install-dir "$RUNTIME_PARENT" "$PY_VERSION"

runtime_src=""
for candidate in "$RUNTIME_PARENT"/cpython-*; do
    if [ -d "$candidate" ] && [ -x "$candidate/bin/python3" ]; then
        runtime_src="$candidate"
        break
    fi
done
[ -n "$runtime_src" ] || die "uv python install left no cpython-* runtime under $RUNTIME_PARENT"

mv "$runtime_src" "$PYROOT"
rm -rf "$RUNTIME_PARENT"
PYBIN="$PYROOT/bin/python3"
[ -x "$PYBIN" ] || die "no interpreter at $PYBIN after the move"

# A vendored interpreter is not an externally managed system Python: the marker exists so that
# `pip install` cannot damage a distribution-owned runtime, and this runtime is ours alone.
# Without deleting it `uv pip install` refuses with "externally-managed-environment".
find "$PYROOT/lib" -maxdepth 2 -name EXTERNALLY-MANAGED -delete

echo "build_app: installing crb[server] into the embedded runtime"
uv pip install --python "$PYBIN" "${ROOT}[server]"
[ -x "$PYROOT/bin/crb" ] || die "the install produced no $PYROOT/bin/crb"

# --- 3. trim the runtime --------------------------------------------------------------------
for candidate in "$PYROOT"/lib/python*/; do
    if [ -d "$candidate" ] && [ -f "$candidate/os.py" ]; then
        LIBDIR="${candidate%/}"
        break
    fi
done
[ -n "$LIBDIR" ] || die "no lib/python*/ standard library found under $PYROOT"

SIZE_BEFORE="$(du -sh "$PYROOT" | cut -f1)"
rm -rf "$LIBDIR/test" "$LIBDIR/idlelib" "$LIBDIR/tkinter" "$LIBDIR/lib2to3"
find "$PYROOT" -depth -type d -name '__pycache__' -exec rm -rf {} +
find "$PYROOT" -type f -name '*.pyc' -delete
find "$PYROOT/lib" -maxdepth 1 -type f -name '*.a' -delete
find "$LIBDIR" -maxdepth 1 -type d -name 'config-*' -exec rm -rf {} +
SIZE_AFTER="$(du -sh "$PYROOT" | cut -f1)"
echo "build_app: runtime trimmed $SIZE_BEFORE -> $SIZE_AFTER"

# The trim must not have removed anything the server imports.
"$PYBIN" -c "import crb.core, crb.server.app, crb.store.migrate; print('build_app: embedded imports ok')"

# --- 4. the version, read the way scripts/check_release_tag.py reads it ----------------------
# One parser for the release tag rule and for this bundle: tomllib on [project].version.
APP_VERSION="$(
    "$PYBIN" -c 'import sys; sys.path.insert(0, sys.argv[1]); import check_release_tag as c; print(c.pyproject_version())' \
        "$ROOT/scripts"
)"
[ -n "$APP_VERSION" ] || die "could not read [project].version from pyproject.toml"
# CFBundleVersion must be one to three dot-separated integers; PEP 440 pre-release suffixes
# (2.0.0a1) are not accepted there, so the numeric prefix goes in CFBundleVersion and the full
# PEP 440 string in CFBundleShortVersionString.
BUNDLE_VERSION="$(printf '%s' "$APP_VERSION" | sed -E 's/^([0-9]+(\.[0-9]+)*).*$/\1/')"

# --- 5. Info.plist, the launcher and the icon ------------------------------------------------
ICON_ENTRY=""
if [ -f "$ROOT/macos/crb.icns" ]; then
    cp "$ROOT/macos/crb.icns" "$RESOURCES/crb.icns"
    ICON_ENTRY='<key>CFBundleIconFile</key><string>crb</string>'
    echo "build_app: bundled macos/crb.icns"
else
    echo "build_app: no macos/crb.icns — the bundle ships without a custom icon"
fi

sed \
    -e "s|__CRB_SHORT_VERSION__|$APP_VERSION|g" \
    -e "s|__CRB_BUNDLE_VERSION__|$BUNDLE_VERSION|g" \
    -e "s|<!-- __CRB_ICON_ENTRY__ -->|$ICON_ENTRY|" \
    "$ROOT/macos/Info.plist" > "$CONTENTS/Info.plist"
if command -v plutil >/dev/null; then
    plutil -lint "$CONTENTS/Info.plist" >/dev/null || die "the generated Info.plist is not a valid plist"
fi

# The launcher resolves its own location so the bundle works from anywhere, including paths
# with spaces ("/Users/Some One/Applications/crb.app"); every expansion below is quoted.
cat > "$CONTENTS/MacOS/crb" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES="$(cd "$DIR/../Resources" && pwd)"

# Point the server at the resources inside THIS bundle, never at a developer checkout that
# happens to be on the machine. Both are absolute paths.
export CRB_UI_DIST="$RESOURCES/ui"
export CRB_DESKTOP_CRB_BIN="$RESOURCES/python/bin/crb"

exec "$RESOURCES/python/bin/python3" -m crb.desktop "$@"
LAUNCHER
chmod +x "$CONTENTS/MacOS/crb"

# --- 6. swap the staged bundle into place -----------------------------------------------------
rm -rf "$APP"
mv "$BUILD" "$APP"
# Nudge LaunchServices so Finder picks up a rebuilt bundle rather than a cached one.
touch "$APP"

# --- 7. signing -------------------------------------------------------------------------------
if [ -n "$SIGN_IDENTITY" ]; then
    command -v codesign >/dev/null || die "--sign was given but codesign is not on PATH (Xcode command line tools)"
    echo "build_app: signing with $SIGN_IDENTITY"
    # --deep is deprecated by Apple in favour of signing nested code inside-out, but it is the
    # one command that covers a vendored CPython's several hundred .so/.dylib files. If a
    # future macOS drops it, replace this with an inside-out walk of Resources/python.
    # --options runtime is the hardened runtime, which notarisation requires. A CPython that
    # loads no JIT needs no extra entitlements today; add an --entitlements plist here if a
    # dependency ever needs allow-jit or allow-unsigned-executable-memory.
    codesign --deep --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP"
    codesign --verify --strict --verbose=2 "$APP"
    echo "build_app: signed and verified — run macos/notarise.sh next to notarise a .dmg of it"
else
    echo "build_app: NOT signed. A bundle built here carries no com.apple.quarantine attribute, so"
    echo "           it opens without a Gatekeeper prompt on this machine; a DOWNLOADED copy would"
    echo "           be quarantined and needs --sign plus macos/notarise.sh."
fi

# --- 8. what was built ---------------------------------------------------------------------------
echo
echo "build_app: built $APP"
echo "build_app: version $APP_VERSION (CFBundleVersion $BUNDLE_VERSION), python $PY_VERSION"
echo "build_app: total size $(du -sh "$APP" | cut -f1)"
echo
echo "    open dist/crb.app"
echo
