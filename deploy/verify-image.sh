#!/usr/bin/env bash
# Verify a released crb image before you run it: keyless signature, SBOM attestation, and
# (optionally) that a tag still resolves to the digest you pinned.
#
#   deploy/verify-image.sh 2.0.0a1                       # by version tag
#   deploy/verify-image.sh sha-655e732                   # by commit tag
#   deploy/verify-image.sh 2.0.0a1 --digest sha256:…     # also assert the tag → digest pin
#   deploy/verify-image.sh 2.0.0a1 --sbom sbom.spdx.json # also write the attested SBOM out
#   deploy/verify-image.sh 2.0.0a1 --print               # print the commands, run nothing
#
# What "verified" means here: the signature was produced by THIS repository's release
# workflow (`.github/workflows/release.yml`) running on a `v*` tag, authenticated by GitHub's
# OIDC issuer and recorded in the Sigstore transparency log. Nothing else is accepted: not a
# fork, not a branch, not a manual dispatch. Requires `cosign` ≥ 2 (and `jq` for --sbom).
#
# Exit codes: 0 verified; 1 verification failed; 2 usage / missing tool.
set -euo pipefail

IMAGE="${CRB_IMAGE_REPOSITORY:-ghcr.io/jita81/commit-replay-bench}"
ISSUER="https://token.actions.githubusercontent.com"
IDENTITY_RE='^https://github.com/Jita81/commit-replay-bench/\.github/workflows/release\.yml@refs/tags/v'

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

tag=""
digest=""
sbom_out=""
print_only=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --digest) digest="${2:-}"; shift 2 ;;
        --sbom) sbom_out="${2:-}"; shift 2 ;;
        --print) print_only=1; shift ;;
        -h|--help) usage ;;
        -*) echo "unknown option: $1" >&2; usage ;;
        *) if [ -n "$tag" ]; then echo "one tag only" >&2; usage; fi; tag="$1"; shift ;;
    esac
done
[ -n "$tag" ] || usage
case "$digest" in
    ""|sha256:*) ;;
    *) echo "--digest must look like sha256:<64 hex>" >&2; exit 2 ;;
esac

ref="${IMAGE}:${tag}"

run() {
    if [ "$print_only" = 1 ]; then
        printf '%q ' "$@"; printf '\n'
    else
        "$@"
    fi
}

if [ "$print_only" = 0 ]; then
    command -v cosign > /dev/null 2>&1 || { echo "cosign not found (https://docs.sigstore.dev/cosign/system_config/installation/)" >&2; exit 2; }
    if [ -n "$sbom_out" ]; then
        command -v jq > /dev/null 2>&1 || { echo "jq not found (needed for --sbom)" >&2; exit 2; }
    fi
fi

echo "# 1. signature — must come from release.yml on a v* tag of Jita81/commit-replay-bench"
run cosign verify "$ref" \
    --certificate-oidc-issuer "$ISSUER" \
    --certificate-identity-regexp "$IDENTITY_RE"

echo "# 2. SBOM attestation (in-toto, predicate type spdxjson) by the same identity"
if [ -n "$sbom_out" ]; then
    if [ "$print_only" = 1 ]; then
        printf 'cosign verify-attestation --type spdxjson %q --certificate-oidc-issuer %q --certificate-identity-regexp %q | jq -r .payload | base64 -d | jq .predicate > %q\n' \
            "$ref" "$ISSUER" "$IDENTITY_RE" "$sbom_out"
    else
        cosign verify-attestation --type spdxjson "$ref" \
            --certificate-oidc-issuer "$ISSUER" \
            --certificate-identity-regexp "$IDENTITY_RE" \
            | jq -r .payload | base64 -d | jq .predicate > "$sbom_out"
        echo "SBOM written to $sbom_out"
    fi
elif [ "$print_only" = 1 ]; then
    run cosign verify-attestation --type spdxjson "$ref" \
        --certificate-oidc-issuer "$ISSUER" \
        --certificate-identity-regexp "$IDENTITY_RE"
else
    cosign verify-attestation --type spdxjson "$ref" \
        --certificate-oidc-issuer "$ISSUER" \
        --certificate-identity-regexp "$IDENTITY_RE" > /dev/null
fi

if [ -n "$digest" ]; then
    echo "# 3. the tag still resolves to the pinned digest"
    if [ "$print_only" = 1 ]; then
        # The $(...) below is for the reader's shell, not this one.
        # shellcheck disable=SC2016
        printf 'test "$(cosign triangulate --type digest %q)" = %q\n' "$ref" "${IMAGE}@${digest}"
    else
        resolved="$(cosign triangulate --type digest "$ref")"
        if [ "$resolved" != "${IMAGE}@${digest}" ]; then
            echo "DIGEST MISMATCH: ${ref} -> ${resolved}, expected ${IMAGE}@${digest}" >&2
            exit 1
        fi
        echo "pinned: ${resolved}"
    fi
fi

[ "$print_only" = 1 ] || echo "verified: ${ref}"
