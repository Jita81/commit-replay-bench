"""gitleaks passes exactly the dep_ store keys and ADR-0025's label; no path in docs/src/deploy.

#56 committed review evidence carrying ``dep_<sha256>`` keys under ``"...key"`` fields, and
gitleaks' ``generic-api-key`` rule read each one as an API key: main's security job went red
on 406ff747's push and every pull request whose scan range reaches that commit fails
(docs/PREVENTION.md P-675). ``.gitleaks.toml`` now allowlists the key's exact shape. These
tests hold that allowlist's regex to ``crb.core.deps.KEY_RE`` — the one place the product
defines the shape — string for string, so a key format change cannot leave the scanner
allowlisting the old shape (and failing on the new one), and a loosened regex cannot start
passing credentials that merely begin like a key. The full-history scan found one more value
of the same class — ADR-0025's public HMAC label ``crb.ledger.anchor.v1``, read as a key on
#69's push 435d2a49 — and its entry is held to the label the ADR derives the key from the
same way. A sample of near-misses cannot prove two regexes agree (an alternation slips past
any sample), so agreement is exact, and the whole allowlist is pinned entry by entry: a new
entry is a new decision, made in this file with its reason. The config is read the way gitleaks
reads it, every key case-insensitively, and the rest of it is pinned too — gitleaks' own rules
whole, and no rule of our own: an inventory that read keys exactly let a rule-level allowlist
spelled ``[[rules.AllowLists]]`` hide a planted token that gitleaks then honoured.

Navigation
----------
What it is:   The gate that holds .gitleaks.toml's allowlist regexes to the product's own
              definitions (``KEY_RE``'s pattern, ADR-0025's anchor label), pins the whole
              config — every allowlist, ``[extend]``, no rule of our own — and keeps the
              config's path doctrine.
What it does: Reads .gitleaks.toml with tomllib and folds every key to lower case, as
              gitleaks (viper) does, refusing two spellings of one key; finds the allowlist
              whose secret-target
              regexes pass a key made the way the dependency store makes one
              (``crb.core.provision.bundle_key``) and requires exactly one, scoped to
              ``generic-api-key``, matched against the captured secret, with nothing but
              regexes, whose one regex is ``KEY_RE.pattern`` string for string (and
              ``KEY_RE`` flag-free) — near-misses (keys one hex digit short or long,
              upper-case, prefixed, suffixed, embedded, mis-separated) are kept as
              documentation; requires every secret-target regex in the config to be anchored
              at both ends (a secret is passed whole or not at all); passes every key the
              committed evidence that first tripped the rule carries; refuses any allowlisted
              path that names a file under docs/, src/ or deploy/; passes ADR-0025's anchor
              label alone, as ``^`` + ``re.escape(label)`` + ``$`` with the label read from the
              ADR (no code constant defines it yet), while the ADR still derives the anchor key
              from it; and requires the config's allowlists, each by its shape (scope and every
              key but ``description``), to equal ``EXPECTED_ALLOWLISTS`` — planted extra,
              widened, unscoped and removed entries are refused, a reworded description is not
              — and the rest of the config to be ``EXPECTED_TOP_LEVEL`` with ``[extend]``
              exactly ``EXPECTED_EXTEND``: a rule-level allowlist however it is spelled, a
              second spelling of ``allowlists``, a disabled default rule, a rule of our own and
              an ``[extend]`` path are refused, planted in the config's text, while respelling
              a key's case is not.
How:          Each allowlist regex is evaluated the way gitleaks evaluates it — an unanchored
              search over the captured secret (Go's ``MatchString``); the patterns used here
              mean the same in RE2 and Python's ``re`` (no sample ends in a newline, where
              ``$`` differs). The gitleaks binary itself runs in CI's ``security`` job, not
              here: no test job installs it, and a test may not skip on its own tool lookup
              (P-744, P-747).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md, docs/adr/0025-routing-v2.md
Works with:   .gitleaks.toml (under test), src/crb/core/deps.py (``KEY_RE``),
              src/crb/core/provision.py (``bundle_key``), docs/adr/0025-routing-v2.md (the
              anchor label), .github/workflows/ci.yml (the ``security`` job that runs
              gitleaks 8.30.1), docs/PREVENTION.md (P-675 — the bug this closes)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the dependency store's key shape changes (move
              KEY_RE, the allowlist and ``EXPECTED_ALLOWLISTS`` together); the product defines
              the anchor label in code (read it from that constant here instead of the ADR);
              an allowlist entry is added, changed or removed in .gitleaks.toml (change
              ``EXPECTED_ALLOWLISTS`` with its one-line reason); the config gains a top-level
              key, an ``[extend]`` key or a rule of its own (change ``EXPECTED_TOP_LEVEL`` or
              ``EXPECTED_EXTEND`` with the reason, and say what the new key may do).
"""

from __future__ import annotations

import copy
import json
import re
import tomllib
from collections import Counter
from collections.abc import Callable, Iterator
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


class KeyCollision(ValueError):
    """Two spellings of one key in one table: gitleaks reads them as one key and honours
    whichever it meets, in an order nothing here pins."""


def _fold(node: object, where: str = "the top level") -> Any:
    """``node`` with every table key lower-cased — what gitleaks reads. Its config loader
    (viper) matches keys case-insensitively, so ``[[rules.AllowLists]]``, ``[[Rules]]`` and
    ``UseDefault`` are ``[[rules.allowlists]]``, ``[[rules]]`` and ``useDefault`` to it. Two
    spellings of one key are refused: a planted ``[[AllowLists]]`` beside ``[[allowlists]]``
    hid a token from gitleaks 8.30.1."""
    if isinstance(node, dict):
        folded: dict[str, Any] = {}
        for key, value in node.items():
            low = key.lower()
            if low in folded:
                raise KeyCollision(f"{where}: two spellings of the key {low!r}")
            folded[low] = _fold(value, low)
        return folded
    if isinstance(node, list):
        return [_fold(item, where) for item in node]
    return node


def _parse(text: str) -> dict[str, Any]:
    """A config's text as gitleaks reads it: TOML, every key folded to lower case."""
    config: dict[str, Any] = _fold(tomllib.loads(text))
    return config


def _config() -> dict[str, Any]:
    return _parse(CONFIG.read_text("utf-8"))


def _scoped_allowlists(config: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every allowlist the config declares, with where it applies: the top-level
    ``[[allowlists]]`` and the legacy single ``[allowlist]`` (``global``), and any rule's own
    (``rule <id>``)."""
    for entry in config.get("allowlists", []):
        yield "global", entry
    if "allowlist" in config:
        yield "global", config["allowlist"]
    for rule in config.get("rules", []):
        scope = f"rule {rule.get('id', '?')}"
        for entry in rule.get("allowlists", []):
            yield scope, entry
        if "allowlist" in rule:
            yield scope, rule["allowlist"]


def _allowlists(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every allowlist the config declares, wherever it applies."""
    return [entry for _, entry in _scoped_allowlists(config)]


def _targets_secret(entry: dict[str, Any]) -> bool:
    """gitleaks matches an allowlist's regexes against the captured secret unless the entry
    names another ``regexTarget`` (``match`` or ``line``)."""
    return entry.get("regextarget", "secret") == "secret"


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
    assert entry.get("targetrules") == ["generic-api-key"], (
        "the dep_ key allowlist must apply only to the rule that misreads the key"
    )
    assert _targets_secret(entry), "the anchored regex must be matched against the secret"
    extra = set(entry) - {"description", "targetrules", "regexes", "regextarget"}
    assert not extra, f"the dep_ key allowlist may carry only its regexes, not {sorted(extra)}"
    assert len(entry["regexes"]) == 1, entry["regexes"]


def test_the_allowlist_accepts_exactly_what_key_re_accepts() -> None:
    """Exactly: the allowlist's one regex is ``KEY_RE``'s own pattern, string for string, and
    ``KEY_RE`` carries no flag that would read that pattern differently. A sample cannot prove
    two regexes agree — ``^(dep_[0-9a-f]{64}|[A-Za-z0-9]{20,40})$`` agrees with ``KEY_RE`` on
    every near-miss below and passes a 32-character token — so the near-misses are kept as
    documentation of what the shape refuses, not as the proof."""
    (pattern,) = _dep_key_allowlist()["regexes"]
    assert pattern == KEY_RE.pattern, (
        f"the allowlist regex {pattern!r} is not crb.core.deps.KEY_RE's pattern "
        f"{KEY_RE.pattern!r}: move them together, and EXPECTED_ALLOWLISTS with them (P-675)"
    )
    assert KEY_RE.flags == re.UNICODE, (
        f"KEY_RE carries flags {KEY_RE.flags!r}: the allowlist regex cannot carry them, so "
        "the two no longer read the same pattern the same way (P-675)"
    )
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


#: ADR-0025's ledger-anchor HMAC label: a public domain-separation string, not a key. The
#: product defines it only in the ADR (no constant under src/ yet); the test reads it from
#: there and requires this copy, which names the samples below, to match.
ANCHOR_LABEL = "crb.ledger.anchor.v1"
ADR_0025 = ROOT / "docs" / "adr" / "0025-routing-v2.md"
#: How ADR-0025 writes the derivation: ``HMAC(key, "<label>")``.
ADR_LABEL_RE = re.compile(r'HMAC\(key, "([^"]+)"\)')


def _adr_anchor_label() -> str:
    """The one label ADR-0025 derives the ledger anchor's key from."""
    labels = sorted(set(ADR_LABEL_RE.findall(ADR_0025.read_text("utf-8"))))
    assert len(labels) == 1, (
        f"ADR-0025 derives the anchor key from {labels}, not one label: with none, drop the "
        "allowlist entry and its EXPECTED_ALLOWLISTS row; with several, decide each (P-675)"
    )
    return labels[0]


def test_the_adr_0025_anchor_label_is_passed_alone() -> None:
    """The label generic-api-key read as an API key on #69's push 435d2a49 is passed — and
    only that label, as the whole secret, for that rule (P-675). The entry's one regex is
    ``^`` + ``re.escape(label)`` + ``$`` string for string, the label read from the ADR; the
    look-alikes below document what that refuses, they are not the proof."""
    label = _adr_anchor_label()
    assert label == ANCHOR_LABEL, (
        f"ADR-0025's label is now {label!r}: move ANCHOR_LABEL, the allowlist entry and "
        "EXPECTED_ALLOWLISTS with it"
    )
    entries = [
        e
        for e in _allowlists(_config())
        if _targets_secret(e) and any(_passes(p, label) for p in e.get("regexes", []))
    ]
    assert len(entries) == 1, f"expected one allowlist passing {label!r}, got {entries}"
    (entry,) = entries
    assert entry.get("targetrules") == ["generic-api-key"], entry
    (pattern,) = entry["regexes"]
    literal = "^" + re.escape(label) + "$"
    assert pattern == literal, (
        f"the label allowlist regex {pattern!r} is not the literal, anchored label {literal!r}: "
        "move them together, and EXPECTED_ALLOWLISTS with them (P-675)"
    )
    for s in [
        "crbXledgerXanchorXv1",  # an unescaped dot passes any character
        "crb.ledger.anchor.v2",
        "crb.ledger.anchor.v1" + "A1b2C3d4E5f6G7h8",
        "Z9y8X7w6" + "crb.ledger.anchor.v1",
        "crb.ledger.anchor.v1.token",
    ]:
        assert not _passes(pattern, s), f"{pattern!r} passes {s!r}"


#: The two secret-target regexes as EXPECTED_ALLOWLISTS pins them — literals, so the inventory
#: does not move when KEY_RE or the ADR does (the tests above tie them to those).
DEP_KEY_REGEX = "^dep_[0-9a-f]{64}$"
LABEL_REGEX = r"^crb\.ledger\.anchor\.v1$"

#: The whole allowlist .gitleaks.toml may carry, entry by entry, each with why it may exist —
#: written as the entry's shape (every key but ``description``, spelled as the TOML spells it
#: and folded to lower case as gitleaks reads it; all apply globally). Adding,
#: widening, narrowing or removing an entry fails test_the_allowlist_inventory_is_pinned until
#: this table changes with its reason (P-675).
EXPECTED_ALLOWLISTS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "the test tree, by path alone: redaction tests carry deliberately fake credentials",
        {"paths": ["^tests/"]},
    ),
    (
        "one whole dependency-store key (KEY_RE: dep_ + sha256 hex), for generic-api-key alone",
        {"targetRules": ["generic-api-key"], "regexes": [DEP_KEY_REGEX]},
    ),
    (
        "ADR-0025's ledger-anchor HMAC label, whole and literal, for generic-api-key alone",
        {"targetRules": ["generic-api-key"], "regexes": [LABEL_REGEX]},
    ),
    (
        "documentation placeholders ([REDACTED], sk-xxxxxxxx, key = <...>), on the whole match",
        {
            "regexTarget": "match",
            "regexes": [
                r"(?i)\[REDACTED[A-Z-]*\]",
                r"(?i)sk-(?:live|test|proj|ant)?-?x{8,}",
                r"(?i)(?:secret|token|password|api[_-]?key)\s*[=:]\s*<[^>]+>",
            ],
        },
    ),
)

#: One allowlist's shape: where it applies and every key but ``description``, lists sorted
#: (gitleaks reads each list as a set).
Shape = tuple[tuple[str, object], ...]


def _shape(entry: dict[str, Any], scope: str) -> Shape:
    fields: dict[str, object] = {"(scope)": scope}
    for key, value in entry.items():
        if key != "description":
            fields[key] = tuple(sorted(value)) if isinstance(value, list) else value
    return tuple(sorted(fields.items()))


def _inventory_drift(config: dict[str, Any]) -> list[str]:
    """Every allowlist shape the config carries that EXPECTED_ALLOWLISTS does not, and every
    expected shape the config lacks — counted, so a duplicate is drift too."""
    found = Counter(_shape(entry, scope) for scope, entry in _scoped_allowlists(config))
    expected = Counter(_shape(_fold(entry), "global") for _, entry in EXPECTED_ALLOWLISTS)
    return [f"not in EXPECTED_ALLOWLISTS: {dict(s)}" for s in (found - expected).elements()] + [
        f"missing from .gitleaks.toml: {dict(s)}" for s in (expected - found).elements()
    ]


def test_the_allowlist_inventory_is_pinned() -> None:
    """The whole allowlist is EXPECTED_ALLOWLISTS, shape for shape: a widened, loosened, added
    or removed entry — or one moved into a rule — fails until the table changes with its
    reason, so no allowlist decision is made in .gitleaks.toml alone."""
    for reason, entry in EXPECTED_ALLOWLISTS:
        assert reason.strip() and "\n" not in reason, f"{entry} needs a one-line reason"
    assert _inventory_drift(_config()) == []


#: Every top-level key .gitleaks.toml may carry, folded: its title, the oldest gitleaks it runs
#: on, ``[extend]`` and the allowlists above. No ``rules``: a rule of our own replaces or adds
#: to gitleaks' (a rule-level allowlist rides on one), so it is a scanner decision this table
#: makes first, with its reason (P-675).
EXPECTED_TOP_LEVEL = frozenset({"title", "minversion", "extend", "allowlists"})
#: ``[extend]``, folded: gitleaks' own rules, whole. ``disabledRules`` switches one off, and a
#: ``path`` or ``url`` reads another config this file does not pin.
EXPECTED_EXTEND: dict[str, Any] = {"usedefault": True}


def _settings_drift(config: dict[str, Any]) -> list[str]:
    """Every top-level key the config adds or drops, and an ``[extend]`` that is not gitleaks'
    own rules whole."""
    keys = set(config)
    drift = [f"top-level key not pinned: {k!r}" for k in sorted(keys - EXPECTED_TOP_LEVEL)]
    drift += [f"pinned top-level key missing: {k!r}" for k in sorted(EXPECTED_TOP_LEVEL - keys)]
    if config.get("extend") != EXPECTED_EXTEND:
        drift.append(f"[extend] is {config.get('extend')!r}, not {EXPECTED_EXTEND!r}")
    return drift


def _drift(config: dict[str, Any]) -> list[str]:
    """Everything the config says that the pins above do not."""
    return _settings_drift(config) + _inventory_drift(config)


def _text_drift(text: str) -> list[str]:
    """The drift of a config's text as gitleaks reads it; two spellings of one key are drift."""
    try:
        config = _parse(text)
    except KeyCollision as exc:
        return [str(exc)]
    return _drift(config)


def test_the_rest_of_the_config_is_pinned() -> None:
    """Read as gitleaks reads it, the config is the pins and nothing else: gitleaks' own rules
    whole, no rule of our own, and the allowlists above (P-675)."""
    assert _text_drift(CONFIG.read_text("utf-8")) == []


def _entry_with(config: dict[str, Any], field: str, value: str) -> dict[str, Any]:
    (entry,) = [e for e in config["allowlists"] if value in e.get(field, [])]
    return entry


def _plant_broad_entry(config: dict[str, Any]) -> None:
    config["allowlists"].append(
        {
            "description": "planted",
            "targetrules": ["generic-api-key"],
            "regexes": ["^[A-Za-z0-9]{32}$"],
        }
    )


def _plant_dep_key_alternation(config: dict[str, Any]) -> None:
    _entry_with(config, "regexes", DEP_KEY_REGEX)["regexes"] = [
        "^(dep_[0-9a-f]{64}|[A-Za-z0-9]{20,40})$"
    ]


def _plant_label_alternation(config: dict[str, Any]) -> None:
    _entry_with(config, "regexes", LABEL_REGEX)["regexes"] = [
        r"^(crb\.ledger\.anchor\.v1|[A-Za-z0-9]{32,40})$"
    ]


def _plant_unscoped_dep_key(config: dict[str, Any]) -> None:
    del _entry_with(config, "regexes", DEP_KEY_REGEX)["targetrules"]


def _plant_docs_path(config: dict[str, Any]) -> None:
    _entry_with(config, "paths", "^tests/")["paths"].append("^docs/")


def _plant_stopword(config: dict[str, Any]) -> None:
    _entry_with(config, "regexes", DEP_KEY_REGEX)["stopwords"] = ["key"]


def _plant_removed_label(config: dict[str, Any]) -> None:
    config["allowlists"].remove(_entry_with(config, "regexes", LABEL_REGEX))


def _plant_rule_allowlist(config: dict[str, Any]) -> None:
    config["rules"] = [{"id": "generic-api-key", "allowlists": [{"regexes": ["^dep_"]}]}]


def _plant_legacy_allowlist(config: dict[str, Any]) -> None:
    config["allowlist"] = {"paths": ["^tests/"]}


PLANTS: dict[str, Callable[[dict[str, Any]], None]] = {
    "an extra broad entry": _plant_broad_entry,
    "an alternation in the dep_ key regex": _plant_dep_key_alternation,
    "an alternation in the label regex": _plant_label_alternation,
    "the dep_ key entry unscoped from its rule": _plant_unscoped_dep_key,
    "a docs/ path on the test-tree entry": _plant_docs_path,
    "a stopword on the dep_ key entry": _plant_stopword,
    "the label entry removed": _plant_removed_label,
    "a rule's own allowlist": _plant_rule_allowlist,
    "a duplicate entry in the legacy [allowlist] table": _plant_legacy_allowlist,
}


@pytest.mark.parametrize("plant", sorted(PLANTS))
def test_the_inventory_refuses_a_planted_change(plant: str) -> None:
    """The negative control: each change, planted in a parsed copy of the config, is drift —
    from a baseline with none, so the refusal is the plant's and not the config's."""
    config = copy.deepcopy(_config())
    assert _drift(config) == [], "the control needs the config to match the pins"
    PLANTS[plant](config)
    assert _drift(config), f"the pins let {plant!r} through"


def test_the_inventory_ignores_descriptions() -> None:
    """The positive control: rewording every description changes no entry's shape."""
    config = copy.deepcopy(_config())
    for entry in config["allowlists"]:
        entry["description"] = "reworded"
    assert _drift(config) == []


def _replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the plant needs exactly one {old!r} in .gitleaks.toml"
    return text.replace(old, new)


#: A token-shaped allowlist regex: what each planted allowlist below would wave through.
TOKEN = "'''^[A-Za-z0-9]{32}$'''"
RULE_ALLOWLIST = f'\n[[rules]]\nid = "generic-api-key"\n[[rules.AllowLists]]\nregexes = [{TOKEN}]\n'
RULES_TABLE = f'\n[[Rules]]\nid = "generic-api-key"\n[[Rules.allowlists]]\nregexes = [{TOKEN}]\n'
SECOND_SPELLING = f"\n[[AllowLists]]\nregexes = [{TOKEN}]\n"
OWN_RULE = "\n[[rules]]\nid = \"crb-planted\"\nregex = '''planted'''\n"
EXTEND = "useDefault = true"

#: Changes planted in the config's text, where gitleaks reads it: each is valid TOML. Measured
#: with gitleaks 8.30.1 on 2026-10-09, the three planted allowlists each hid a 32-character
#: token the committed config reports, and the disabled rule loaded without a word.
TEXT_PLANTS: dict[str, Callable[[str], str]] = {
    "a rule-level allowlist spelled [[rules.AllowLists]]": lambda t: t + RULE_ALLOWLIST,
    "a rule spelled [[Rules]] with its own allowlist": lambda t: t + RULES_TABLE,
    "an [[AllowLists]] entry beside [[allowlists]]": lambda t: t + SECOND_SPELLING,
    "a rule of our own": lambda t: t + OWN_RULE,
    "a default rule switched off": lambda t: _replace_once(
        t, EXTEND, f'{EXTEND}\ndisabledRules = ["aws-access-token"]'
    ),
    "a default rule switched off, spelled DisabledRules": lambda t: _replace_once(
        t, EXTEND, f'{EXTEND}\nDisabledRules = ["aws-access-token"]'
    ),
    "an [extend] path to another config": lambda t: _replace_once(
        t, EXTEND, f'{EXTEND}\npath = "other.toml"'
    ),
    "gitleaks' own rules dropped": lambda t: _replace_once(t, EXTEND, "useDefault = false"),
}


@pytest.mark.parametrize("plant", sorted(TEXT_PLANTS))
def test_the_config_refuses_a_planted_text_change(plant: str) -> None:
    """The negative control where gitleaks reads the config — its text — from a baseline with
    no drift, so the refusal is the plant's: the parser accepts each plant, and the pins refuse
    it."""
    text = CONFIG.read_text("utf-8")
    assert _text_drift(text) == [], "the control needs the config to match the pins"
    planted = TEXT_PLANTS[plant](text)
    tomllib.loads(planted)
    assert _text_drift(planted), f"the pins let {plant!r} through"


def test_the_config_reads_keys_as_gitleaks_does() -> None:
    """The positive control: respelling a key's case changes nothing gitleaks reads — the
    config with ``UseDefault``, ``TargetRules`` and ``RegexTarget`` still loads gitleaks' own
    rules under 8.30.1 — so it changes nothing pinned."""
    text = CONFIG.read_text("utf-8")
    for key in ("useDefault", "targetRules", "regexTarget"):
        assert key in text, f".gitleaks.toml no longer spells {key!r}: pick another key"
        text = text.replace(key, key[0].upper() + key[1:])
    assert _text_drift(text) == []
