"""The image's UI build can see every document the UI bundles (P-173).

The UI bundles the eight guides and the decision records at build time
(``ui/src/help/docs.ts``, ``ui/src/help/adrs.ts``: ``import.meta.glob`` over ``../docs``).
``deploy/Dockerfile.dockerignore`` dropped ``docs`` from the build context, so the image's
``vite build`` found no file, the globs resolved to nothing — which Vite does not treat as an
error — and the image served a Help page on which every guide read "No guide with that name".
The unit tests and the walkthrough never saw it: both build from a checkout, where ``docs/``
is present. Found 2026-09-26 while bundling the decision records (G-156), by building the
image's context and listing it.

Two artefacts stop the class; this suite pins the first:

* the context rule: the ignore file re-includes ``docs/*.md`` and ``docs/adr/*.md`` after
  excluding ``docs`` — checked here against a model of Docker's matcher (last matching rule
  wins; a rule that matches a parent directory matches its contents; ``!`` re-includes), and
  the model is itself checked on the rule set that shipped the defect;
* the build gate: ``requireBundledDocs`` (ui/plugins/requireBundledDocs.ts, run by
  ui/vite.config.ts) fails ``vite build`` when a listed guide or the records are absent, so a
  context that loses them fails the ``container`` job instead of shipping. It is tested by
  running it, in ui/plugins/requireBundledDocs.test.ts: a grep of the config that stood here
  first survived the refusal being switched off, so it proved nothing.

Navigation
----------
What it is:   The prevention test for the class "a build input the UI bundles is missing
              from the image's build context" (docs/PREVENTION.md P-173).
What it does: Reads ``DOC_NAMES`` from ui/src/help/docs.ts and the record files in docs/adr,
              applies deploy/Dockerfile.dockerignore through a model of Docker's pattern
              matcher, and asserts every one of them is in the context; proves the model
              excludes them under the old rules.
How:          A regex per ignore pattern (``**`` → any depth, ``*`` / ``?`` → within one path
              segment), evaluated against the path and each of its parent directories, last
              match wins — the rule moby's ``patternmatcher`` implements.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none (DL-073)
Works with:   deploy/Dockerfile.dockerignore (the rule under test), deploy/Dockerfile (the UI
              build stage copies the whole context), ui/plugins/requireBundledDocs.ts (the build
              gate, tested by ui/plugins/requireBundledDocs.test.ts),
              ui/src/help/docs.ts and ui/src/help/adrs.ts (what the UI bundles),
              .github/workflows/ci.yml (the ``container`` job runs that build)
Tested by:    tests/test_image_bundles_docs.py
Touch when:   never for a new repository; the UI bundles another file from outside ``ui/`` (add it
              to the re-includes and to ``requireBundledDocs``), or the ignore file changes shape.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORE = ROOT / "deploy" / "Dockerfile.dockerignore"
DOCS_TS = ROOT / "ui" / "src" / "help" / "docs.ts"


def _rules(text: str) -> list[tuple[bool, re.Pattern[str]]]:
    """``(negated, regex)`` per non-comment line, in file order."""
    out: list[tuple[bool, re.Pattern[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:].strip() if negated else line
        pattern = pattern.lstrip("/").rstrip("/")
        rx = ""
        i = 0
        while i < len(pattern):
            if pattern.startswith("**/", i):
                rx += "(?:.*/)?"  # any number of directories, none included
                i += 3
            elif pattern.startswith("**", i):
                rx += ".*"
                i += 2
            elif pattern[i] == "*":
                rx += "[^/]*"
                i += 1
            elif pattern[i] == "?":
                rx += "[^/]"
                i += 1
            else:
                rx += re.escape(pattern[i])
                i += 1
        out.append((negated, re.compile(rf"^{rx}$")))
    return out


def excluded(path: str, rules: list[tuple[bool, re.Pattern[str]]]) -> bool:
    """Whether Docker leaves ``path`` out of the context: the last rule matching the path or
    one of its parent directories decides."""
    parts = path.split("/")
    candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    result = False
    for negated, rx in rules:
        if any(rx.match(c) for c in candidates):
            result = not negated
    return result


def bundled_paths() -> list[str]:
    """Every repository file the UI's build bundles: the guides and the decision records."""
    found = re.search(r"DOC_NAMES = \[([^\]]*)\]", DOCS_TS.read_text())
    assert found, "DOC_NAMES is not declared in ui/src/help/docs.ts"
    names = re.findall(r"'([^']+)'", found.group(1))
    assert len(names) == 8, names
    adrs = sorted(p.name for p in (ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert len(adrs) > 20, adrs
    return [f"docs/{n}.md" for n in names] + [f"docs/adr/{a}" for a in adrs]


def test_the_image_context_keeps_every_doc_the_ui_bundles() -> None:
    rules = _rules(IGNORE.read_text())
    missing = [p for p in bundled_paths() if excluded(p, rules)]
    assert missing == [], (
        f"deploy/Dockerfile.dockerignore drops files the UI bundles, so the image's Help "
        f"would open none of them: {missing}"
    )
    # and the rest of docs/ stays out, as the ignore file intends
    assert excluded("docs/reviews/2026-09-25-value-baseline.md", rules)


def test_the_model_catches_the_rule_that_shipped_the_defect() -> None:
    """The ignore file as it stood before P-173 — ``docs`` with no re-include — loses every
    bundled file; a model that could not see that would prove nothing above."""
    old = _rules("docs\nscripts\n")
    assert all(excluded(p, old) for p in bundled_paths())
    assert excluded("docs/adr/0001-four-belts-and-false-q1-at-write.md", old)
    assert not excluded("ui/src/help/docs.ts", old)
    # last match wins, in both directions
    assert not excluded("docs/OPERATOR.md", _rules("docs\n!docs/*.md\n"))
    assert excluded("docs/OPERATOR.md", _rules("!docs/*.md\ndocs\n"))
    assert excluded("a/b/c.pyc", _rules("**/*.pyc\n"))
