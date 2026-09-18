#!/usr/bin/env bash
# macos/notarise.sh — package a SIGNED dist/crb.app as a .dmg, send that .dmg to Apple's
# notary service, and staple the resulting ticket to it (and to the app inside it).
#
#   macos/notarise.sh                              # dist/crb.app -> dist/crb.dmg
#   macos/notarise.sh dist/crb.app                 # the same, explicitly
#   macos/notarise.sh dist/crb.app --dmg out.dmg   # a chosen .dmg path
#
# Credentials come from the environment, never from arguments (they would land in the shell
# history and in CI logs):
#
#   APPLE_ID            the Apple ID of an account on the developer team (an email address)
#   APPLE_TEAM_ID       the 10-character team identifier, e.g. ABCDE12345
#   APPLE_APP_PASSWORD  an app-specific password for that Apple ID (appleid.apple.com),
#                       NOT the account password
#
# The .dmg is what is notarised because the .dmg is what a user downloads: the ticket must
# cover the distributable, not only the bundle inside it. Notarisation is a separate step from
# signing on purpose — macos/build_app.sh --sign produces the signature, this script proves to
# Gatekeeper that Apple has seen it, which is what lifts the quarantine prompt on a downloaded
# copy. An unsigned or ad-hoc-signed bundle is rejected by the notary service; this script
# checks the signature first so that failure is reported here rather than minutes later.
#
# Exit codes: 0 notarised and stapled; 1 notarisation or stapling failed; 2 usage / missing
# environment / missing tool.
#
# Navigation
# ----------
# What it is:   The macOS notarisation step: a .dmg of the signed bundle, submitted to Apple's
#               notary service and stapled.
# What it does: Refuses to run unless APPLE_ID, APPLE_TEAM_ID and APPLE_APP_PASSWORD are all set
#               and the bundle carries a valid signature, builds a compressed .dmg of the app,
#               submits it with ``xcrun notarytool submit --wait``, prints the submission log on
#               rejection, then staples the ticket to the .dmg and to the .app. It never signs
#               anything itself and never takes a credential as an argument.
# How:          Argument and environment checks → ``codesign --verify --strict`` → ``hdiutil
#               create -format UDZO`` → ``notarytool submit --wait`` (``notarytool log`` on a
#               non-accepted status) → ``stapler staple`` + ``stapler validate`` on the .dmg,
#               then a best-effort staple of the .app inside the tree.
# Layer:        desktop — docs/ARCHITECTURE.md#6-deployment-view
# ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
# Works with:   macos/build_app.sh (produces and signs the bundle this submits),
#               macos/Info.plist (the CFBundleIdentifier the ticket is issued against),
#               .github/workflows/macos-app.yml (runs this when the Apple secrets are present),
#               deploy/verify-image.sh (the same idea for the container image: prove to the user
#               that what they downloaded is what this repository published),
#               docs/DEPLOYMENT.md (how crb is shipped)
# Tested by:    untested — no unit test; the smoke test in .github/workflows/macos-app.yml boots
#               the built bundle and asserts readiness
# Touch when:   Apple changes the notarytool or stapler interface; the .dmg layout or volume name
#               changes; a second distributable (a .pkg installer) is added — it needs its own
#               submission, a ticket does not transfer between formats.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/dist/crb.app"
DMG=""
VOLNAME="Commit Replay Bench"

usage() {
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

die() {
    echo "notarise: $*" >&2
    exit 2
}

app_given=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dmg)
            [ "$#" -ge 2 ] || die "--dmg needs a path"
            DMG="$2"
            shift 2
            ;;
        -h|--help) usage ;;
        -*) echo "notarise: unknown option: $1" >&2; usage ;;
        *)
            [ "$app_given" -eq 0 ] || die "one app path only"
            APP="$1"
            app_given=1
            shift
            ;;
    esac
done

# --- 0. the environment ---------------------------------------------------------------------
missing=""
for var in APPLE_ID APPLE_TEAM_ID APPLE_APP_PASSWORD; do
    [ -n "${!var:-}" ] || missing="$missing $var"
done
if [ -n "$missing" ]; then
    echo "notarise: unset:$missing" >&2
    echo "  Notarisation needs all three. Export them (from CI secrets, or locally):" >&2
    echo "    export APPLE_ID='you@example.com'          # an Apple ID on the developer team" >&2
    echo "    export APPLE_TEAM_ID='ABCDE12345'          # the 10-character team identifier" >&2
    echo "    export APPLE_APP_PASSWORD='xxxx-xxxx-xxxx-xxxx'  # app-specific, from appleid.apple.com" >&2
    exit 2
fi

command -v xcrun >/dev/null || die "xcrun is not on PATH — install the Xcode command line tools (xcode-select --install)"
command -v hdiutil >/dev/null || die "hdiutil is not on PATH — this script only runs on macOS"
command -v codesign >/dev/null || die "codesign is not on PATH — install the Xcode command line tools"

[ -d "$APP" ] || die "no application bundle at $APP — build it first: macos/build_app.sh --sign '…'"

# --- 1. the bundle must already be signed ------------------------------------------------------
# The notary service rejects an unsigned or ad-hoc bundle minutes after submission; catching it
# here costs a second and says exactly what to do.
if ! codesign --verify --strict --verbose=2 "$APP" 2>&1; then
    die "$APP is not validly signed. Sign it first:
  macos/build_app.sh --sign 'Developer ID Application: NAME (\$APPLE_TEAM_ID)'"
fi

# --- 2. the distributable ------------------------------------------------------------------------
if [ -z "$DMG" ]; then
    DMG="$(dirname "$APP")/$(basename "$APP" .app).dmg"
fi
mkdir -p "$(dirname "$DMG")"
rm -f "$DMG"

echo "notarise: building $DMG from $APP"
hdiutil create \
    -volname "$VOLNAME" \
    -srcfolder "$APP" \
    -fs HFS+ \
    -format UDZO \
    -ov \
    "$DMG"
[ -f "$DMG" ] || die "hdiutil produced no $DMG"

# --- 3. submit and wait ----------------------------------------------------------------------------
echo "notarise: submitting $DMG to the Apple notary service (this can take several minutes)"
submit_log="$(mktemp "${TMPDIR:-/tmp}/crb-notarise.XXXXXX")"
trap 'rm -f "$submit_log"' EXIT

status=0
xcrun notarytool submit "$DMG" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" \
    --wait \
    2>&1 | tee "$submit_log" || status=$?

if [ "$status" -ne 0 ]; then
    echo "notarise: notarytool submit failed (exit $status)" >&2
    exit 1
fi
if ! grep -qi 'status: *Accepted' "$submit_log"; then
    echo "notarise: the submission was not Accepted — fetching the notary log" >&2
    submission_id="$(sed -n 's/^ *id: *\([0-9a-fA-F-]\{36\}\).*$/\1/p' "$submit_log" | head -1)"
    if [ -n "$submission_id" ]; then
        xcrun notarytool log "$submission_id" \
            --apple-id "$APPLE_ID" \
            --team-id "$APPLE_TEAM_ID" \
            --password "$APPLE_APP_PASSWORD" >&2 || true
    fi
    exit 1
fi

# --- 4. staple -----------------------------------------------------------------------------------------
# Stapling writes the ticket into the artefact so Gatekeeper can clear it offline. The .dmg is
# the distributable and must carry one.
echo "notarise: stapling the ticket to $DMG"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

# The ticket also covers the app's own code directory hash, so the .app can be stapled too —
# useful when the .app is published beside the .dmg. It is not fatal if Apple has not yet
# published that ticket: the .dmg is stapled and is what users download.
echo "notarise: stapling the ticket to $APP"
if xcrun stapler staple "$APP"; then
    xcrun stapler validate "$APP"
else
    echo "notarise: could not staple $APP (the .dmg IS stapled and is the distributable)" >&2
fi

echo
echo "notarise: notarised and stapled"
echo "notarise: $DMG"
echo
echo "    spctl --assess --type open --context context:primary-signature -vv '$DMG'"
echo
