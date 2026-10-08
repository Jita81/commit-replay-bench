"""gitleaks passes exactly the product's dependency-store keys, and no path in docs/src/deploy.

#56 committed review evidence carrying ``dep_<sha256>`` keys under ``"...key"`` fields, and
gitleaks' ``generic-api-key`` rule read each one as an API key: main's security job went red
on 406ff747's push and every pull request whose scan range reaches that commit fails
(docs/PREVENTION.md P-675). ``.gitleaks.toml`` now allowlists the key's exact shape. These
tests hold that allowlist to ``crb.core.deps.KEY_RE`` — the one place the product defines the
shape — so a key format change cannot leave the scanner allowlisting the old shape (and
failing on the new one), and a loosened regex cannot start passing credentials that merely
begin like a key.

Navigation
----------
What it is:   The gate that ties .gitleaks.toml's dependency-store-key allowlist to the
              product's key shape and keeps the config's path doctrine.
What it does: Reads .gitleaks.toml with tomllib; finds the allowlist whose secret-target
              regexes pass a key made the way the dependency store makes one
              (``crb.core.provision.bundle_key``) and requires exactly one, scoped to
              ``generic-api-key``, matched against the captured secret, with nothing but
              regexes; requires that it and ``KEY_RE`` accept and refuse the same strings —
              real keys, keys one hex digit short or long, upper-case, prefixed, suffixed,
              embedded, mis-separated; requires every secret-target regex in the config to be
              anchored at both ends (a secret is passed whole or not at all); passes every key
              the committed evidence that first tripped the rule carries; and refuses any
              allowlisted path that names a file under docs/, src/ or deploy/.
How:          Each allowlist regex is evaluated the way gitleaks evaluates it — an unanchored
              search over the captured secret (Go's ``MatchString``); the patterns used here
              mean the same in RE2 and Python's ``re`` (no sample ends in a newline, where
              ``$`` differs). The gitleaks binary itself runs in CI's ``security`` job, not
              here: no test job installs it, and a test may not skip on its own tool lookup
              (P-744, P-747).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   .gitleaks.toml (under test), src/crb/core/deps.py (``KEY_RE``),
              src/crb/core/provision.py (``bundle_key``), .github/workflows/ci.yml (the
              ``security`` job that runs gitleaks 8.30.1), docs/PREVENTION.md (P-675 — the bug
              this closes)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the dependency store's key shape changes (move
              KEY_RE and the allowlist together); an allowlist entry is added to .gitleaks.toml.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.core.deps import KEY_RE
from crb.core.provision import RECIPE_GO, RECIPE_NODE, RECIPE_PY, bundle_key

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".gitleaks.toml"
#: The committed evidence whose keys first tripped generic-api-key (#56, 406ff747).
EVIDENCE = ROOT / "docs" / "reviews" / "2026-09-25-sealed-posture"
#: The trees no allowlisted path may reach: what ships, what deploys, and what we publish.
GUARDED_TREES = ("docs", "src", "deploy")


def _config() -> dict[str, Any]:
    with CONFIG.open("rb") as fh:
        return tomllib.load(fh)


def _allowlists(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every allowlist the config declares: the top-level ``[[allowlists]]``, the legacy
    single ``[allowlist]`` and any rule's own."""
    out: list[dict[str, Any]] = list(config.get("allowlists", []))
    if "allowlist" in config:
        out.append(config["allowlist"])
    for rule in config.get("rules", []):
        out.extend(rule.get("allowlists", []))
        if "allowlist" in rule:
            out.append(rule["allowlist"])
    return out


def _targets_secret(entry: dict[str, Any]) -> bool:
    """gitleaks matches an allowlist's regexes against the captured secret unless the entry
    names another ``regexTarget`` (``match`` or ``line``)."""
    return entry.get("regexTarget", "secret") == "secret"


def _passes(pattern: str, secret: str) -> bool:
    """What gitleaks does with an allowlist regex: ``regexp.MatchString`` — a search."""
    return re.search(pattern, secret) is not None


def _real_keys() -> list[str]:
    """Keys made the way the dependency store makes them, across recipes and inputs."""
    return [
        bundle_key(RECIPE_GO, "sha256:" + "a" * 64, ["h1:abc=", "h1:def="]),
        bundle_key(RECIPE_PY, "sha256:" + "0" * 64, []),
        bundle_key(RECIPE_NODE, "", ["sha512-xyz"]),
    ]


def _near_misses(key: str) -> list[str]:
    """Strings one edit away from a real key — each refused by KEY_RE, so each must be
    refused by the allowlist too."""
    prefix, digest = key.split("_", 1)
    return [
        key[:-1],  # one hex digit short
        key + "0",  # one hex digit long
        f"{prefix}_{digest.upper()}",  # upper-case hex
        f"{prefix.upper()}_{digest}",  # upper-case prefix
        f"{prefix}-{digest}",  # mis-separated
        "x" + key,  # extra prefix
        key + ".tar",  # a suffix gitleaks' capture group would keep
        key + "=",
        f"{prefix}_{digest[:-1]}g",  # one non-hex digit
        f"{prefix}_",  # no digest at all
        digest,  # the digest without its prefix
        " " + key,
        f'key": "{key}"',  # the whole match, not the captured secret
    ]


def _dep_key_allowlist() -> dict[str, Any]:
    entries = [
        e
        for e in _allowlists(_config())
        if _targets_secret(e)
        and any(_passes(p, k) for p in e.get("regexes", []) for k in _real_keys())
    ]
    assert len(entries) == 1, (
        "expected exactly one secret-target allowlist in .gitleaks.toml that passes a real "
        f"dependency-store key (crb.core.provision.bundle_key), found {len(entries)}: without "
        "it generic-api-key fails every scan that reaches #56's review evidence (P-675)"
    )
    return entries[0]


def test_a_real_key_matches_the_products_own_shape() -> None:
    """The samples are what the product makes and accepts — or the agreement below is vacuous."""
    for key in _real_keys():
        assert KEY_RE.fullmatch(key), key
        assert all(not KEY_RE.fullmatch(s) for s in _near_misses(key))


def test_the_dep_key_allowlist_is_scoped_to_one_rule_and_the_secret_alone() -> None:
    entry = _dep_key_allowlist()
    assert entry.get("targetRules") == ["generic-api-key"], (
        "the dep_ key allowlist must apply only to the rule that misreads the key"
    )
    assert _targets_secret(entry), "the anchored regex must be matched against the secret"
    extra = set(entry) - {"description", "targetRules", "regexes", "regexTarget"}
    assert not extra, f"the dep_ key allowlist may carry only its regexes, not {sorted(extra)}"
    assert len(entry["regexes"]) == 1, entry["regexes"]


def test_the_allowlist_accepts_exactly_what_key_re_accepts() -> None:
    (pattern,) = _dep_key_allowlist()["regexes"]
    for key in _real_keys():
        for s in [key, *_near_misses(key)]:
            assert _passes(pattern, s) == bool(KEY_RE.fullmatch(s)), (
                f"the allowlist {pattern!r} and crb.core.deps.KEY_RE disagree on {s!r}: move "
                "them together (P-675)"
            )


def _secret_regexes() -> Iterator[str]:
    for entry in _allowlists(_config()):
        if _targets_secret(entry):
            yield from entry.get("regexes", [])


def test_every_secret_target_regex_passes_a_whole_secret_or_nothing() -> None:
    """An unanchored secret regex passes any secret that merely contains the shape — a real
    token glued to a key would be waved through."""
    patterns = list(_secret_regexes())
    assert patterns, "the config carries no secret-target regex — the dep_ key allowlist is gone"
    for p in patterns:
        assert p.startswith("^") and p.endswith("$") and not p.endswith(r"\$"), (
            f"{p!r} must be anchored at both ends: gitleaks searches, it does not fullmatch"
        )


def _string_fields(node: object, field: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _string_fields(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _string_fields(v, field)
    elif isinstance(node, str):
        yield field, node


def _evidence_docs() -> Iterator[object]:
    for path in sorted(EVIDENCE.iterdir()):
        if path.suffix == ".json":
            yield json.loads(path.read_text("utf-8"))
        elif path.suffix == ".jsonl":
            for line in path.read_text("utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)


def test_the_evidence_that_tripped_the_rule_is_passed() -> None:
    """Every ``dep_`` value under a ``...key`` field of #56's evidence — what gitleaks
    captured as a secret on 406ff747's push — is a real key and is passed."""
    (pattern,) = _dep_key_allowlist()["regexes"]
    keys = [
        value
        for doc in _evidence_docs()
        for field, value in _string_fields(doc)
        if field.lower().endswith("key") and value.startswith("dep_")
    ]
    assert keys, f"no dep_ key found under {EVIDENCE.relative_to(ROOT)} — the probe is stale"
    for value in keys:
        assert KEY_RE.fullmatch(value), value
        assert _passes(pattern, value), value


def _guarded_files() -> list[str]:
    return [
        p.relative_to(ROOT).as_posix()
        for tree in GUARDED_TREES
        for p in (ROOT / tree).rglob("*")
        if p.is_file()
    ]


def _path_violations(allowlists: list[dict[str, Any]], files: list[str]) -> list[str]:
    """Every allowlisted path regex that passes a file under a guarded tree, with a sample."""
    return [
        f"{p!r} reaches {hits[:3]}"
        for entry in allowlists
        for p in entry.get("paths", [])
        if (hits := [f for f in files if _passes(p, f)])
    ]


def test_no_allowlisted_path_reaches_docs_src_or_deploy() -> None:
    """The config's doctrine: only the test tree is allowlisted by path."""
    files = _guarded_files()
    assert {f.split("/", 1)[0] for f in files} == set(GUARDED_TREES), "a guarded tree is empty"
    allowlists = _allowlists(_config())
    paths = [p for entry in allowlists for p in entry.get("paths", [])]
    assert any(_passes(p, "tests/test_redact.py") for p in paths), (
        "the test tree is not allowlisted"
    )
    assert _path_violations(allowlists, files) == []


@pytest.mark.parametrize("planted", ["^docs/reviews/", "^src/", "deploy/", "\\.jsonl$"])
def test_the_path_check_refuses_a_planted_path(planted: str) -> None:
    """The path check is not vacuous: an allowlisted path that reaches a guarded tree fails."""
    allowlists = [*_allowlists(_config()), {"paths": [planted]}]
    assert _path_violations(allowlists, _guarded_files())
