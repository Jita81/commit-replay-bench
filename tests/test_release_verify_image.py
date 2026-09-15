"""``deploy/verify-image.sh`` and the release workflow agree on WHAT a verified image is.

The invariant: the image repository, the OIDC issuer and the signing-identity pattern are
stated in three places — the release workflow (which signs), the operator script (which
verifies) and the Helm values (which pull) — and they must be the same string, or a
release could be signed under one identity and "verified" under another. These tests read
the files, so a drift is caught in CI rather than by an operator at 2 a.m.

The script itself is exercised in ``--print`` mode only: it must never reach the network
from the suite. cosign is not required.

Navigation
----------
What it is:   The release-verification agreement test suite — ``deploy/verify-image.sh`` and the
              release workflow state the same identity.
What it does: Pins that the script is executable and parses, that usage exits 2 without a tag,
              that ``--print`` runs nothing and names the identity (with the digest pin and SBOM
              output forms), that a malformed digest is rejected, that the script and
              ``release.yml`` agree on the image repository, OIDC issuer and identity pattern,
              that the workflow pushes and signs only on canonical ``v*`` tags, that the Helm
              values pull the same repository, and that no action is pinned to a moving branch.
How:          Runs the script with ``bash`` in ``--print`` mode only (never the network; cosign
              not required) and reads the workflow and values files as text.
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         none
Works with:   deploy/verify-image.sh (under test), .github/workflows/release.yml (the signer),
              deploy/helm/crb/values.yaml (the puller), docs/DEPLOYMENT.md (the released image:
              name, signature, SBOM, §2.2), docs/SECURITY.md (supply chain, §3.7)
Tested by:    tests/test_release_verify_image.py
Touch when:   the image repository, issuer or signing identity changes (all three files and this
              suite together — a drift here is a release signed under one identity and
              "verified" under another).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "verify-image.sh"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
VALUES = ROOT / "deploy" / "helm" / "crb" / "values.yaml"
CI = ROOT / ".github" / "workflows" / "ci.yml"

IMAGE = "ghcr.io/jita81/commit-replay-bench"
ISSUER = "https://token.actions.githubusercontent.com"
IDENTITY_RE = (
    r"^https://github.com/Jita81/commit-replay-bench/\.github/workflows/release\.yml@refs/tags/v"
)

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
    )


def test_script_is_executable_and_parses() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "deploy/verify-image.sh must be executable"
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


def test_usage_exits_2_without_a_tag() -> None:
    r = _run()
    assert r.returncode == 2
    assert "verify-image.sh" in r.stdout  # the usage text, printed from the header comment
    assert "set -euo pipefail" not in r.stdout  # the usage range stops before the code


def test_print_mode_runs_nothing_and_names_the_identity() -> None:
    r = _run("2.0.0a1", "--print")
    assert r.returncode == 0, r.stderr
    assert "cosign verify " in r.stdout and f"{IMAGE}:2.0.0a1" in r.stdout
    assert "--certificate-oidc-issuer " + ISSUER in r.stdout
    assert "verify-attestation --type spdxjson" in r.stdout
    # The regexp is printed shell-quoted by %q; unescape and compare to the constant.
    m = re.search(r"--certificate-identity-regexp (\S+)", r.stdout)
    assert m is not None
    printed = m.group(1).replace("\\", "")
    assert printed == IDENTITY_RE.replace("\\", "")
    assert "verified:" not in r.stdout  # nothing was verified


def test_print_mode_with_digest_pin_and_sbom_out() -> None:
    digest = "sha256:" + "0" * 64
    r = _run("sha-655e732", "--print", "--digest", digest, "--sbom", "out.json")
    assert r.returncode == 0, r.stderr
    assert f"{IMAGE}@{digest}" in r.stdout
    assert "cosign triangulate --type digest" in r.stdout
    assert "jq .predicate > out.json" in r.stdout


def test_rejects_a_malformed_digest() -> None:
    r = _run("2.0.0a1", "--print", "--digest", "abc")
    assert r.returncode == 2
    assert "sha256:" in r.stderr


def test_script_and_release_workflow_agree_on_identity() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    assert f'IMAGE="${{CRB_IMAGE_REPOSITORY:-{IMAGE}}}"' in script
    assert f"IMAGE: {IMAGE}" in release
    assert ISSUER in script and ISSUER in release
    # The workflow builds the same pattern from CANONICAL_REPO; both must expand to IDENTITY_RE.
    assert f"IDENTITY_RE='{IDENTITY_RE}'" in script
    assert "CANONICAL_REPO: Jita81/commit-replay-bench" in release
    assert (
        'IDENTITY_RE="^https://github.com/${CANONICAL_REPO}/\\.github/workflows/release\\.yml@refs/tags/v"'
        in release
    )


def test_release_workflow_pushes_and_signs_only_on_canonical_tags() -> None:
    release = RELEASE.read_text(encoding="utf-8")
    assert (
        "PUSH: ${{ github.ref_type == 'tag' && github.repository == 'Jita81/commit-replay-bench' }}"
        in release
    )
    assert "if: needs.image.outputs.pushed == 'true'" in release
    assert "id-token: write" in release
    # PEP 440 pre-releases are not semver: the version tag must come from `type=match`.
    assert "type=semver" not in release.replace("`type=semver` is deliberately NOT used", "")
    assert "type=match,pattern=v(.*),group=1" in release
    assert "type=sha,prefix=sha-,format=short" in release


def test_helm_values_pull_the_same_repository() -> None:
    values = VALUES.read_text(encoding="utf-8")
    assert f"repository: {IMAGE}" in values


def test_no_action_is_pinned_to_a_moving_branch() -> None:
    for wf in (RELEASE, CI):
        for line in wf.read_text(encoding="utf-8").splitlines():
            m = re.search(r"uses:\s*(\S+)@(\S+)", line)
            if not m:
                continue
            ref = m.group(2)
            assert ref not in {"master", "main", "latest"}, f"{wf.name}: {line.strip()}"
            assert re.fullmatch(r"v\d+(\.\d+){0,2}|[0-9a-f]{40}", ref), f"{wf.name}: {line.strip()}"
