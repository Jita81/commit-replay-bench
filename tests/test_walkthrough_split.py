"""The spec that runs on a stack of its own names nothing another spec made.

11-screens runs in the ``walkthrough-screens`` CI jobs, each on a fresh stack that its own
first test seeds (the primary repository and the persona accounts). The keyboard steps the
north-star waves wrote into it opened ``/signoff?repo=walk-signable`` — the repository 08
seeds and signs in the stateful story — so once the walk was split, every screens shard
would have failed on a repository its stack never had (docs/PREVENTION.md P-193). The steps
moved to ``11b-keyboard.spec.ts``, which runs in the story after 08; this gate keeps the
class out of 11-screens.

Navigation
----------
What it is:   A source gate over ui/e2e/walkthrough/11-screens.spec.ts, the one spec the CI
              runs on a stack of its own.
What it does: Fails on any ``walk-…`` name in the spec other than its persona accounts
              (``walk-viewer``, ``walk-operator``, ``walk-approver``), naming the line; a
              negative control pins that 08's
              repository is caught; and the story's ``--grep-invert`` must still exclude
              11-screens only, so the keyboard spec runs in the story.
How:          Text scan of the TypeScript source and of .github/workflows/ci.yml; no browser.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/11-screens.spec.ts (the spec it holds),
              ui/e2e/walkthrough/11b-keyboard.spec.ts (where state-dependent steps go),
              ui/e2e/walkthrough/08-signoff.spec.ts (seeds ``walk-signable``),
              .github/workflows/ci.yml (the story and screens jobs), docs/PREVENTION.md (P-193)
Tested by:    (this is a test file)
Touch when:   never for a new repository; 11-screens seeds another account or repository of its
              own (add its name to ``OWN_NAMES`` beside the seed), or the walk is split again.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALKTHROUGH = ROOT / "ui" / "e2e" / "walkthrough"
SCREENS = WALKTHROUGH / "11-screens.spec.ts"
CI = ROOT / ".github" / "workflows" / "ci.yml"

#: The names 11-screens makes on its own stack: the three persona accounts. The primary
#: repository comes from ``primary()`` in support.ts, never a literal.
OWN_NAMES = frozenset({"walk-viewer", "walk-operator", "walk-approver"})
_WALK_NAME = re.compile(r"""['"`](walk-[A-Za-z0-9_-]+)['"`]""")


def foreign_names(text: str) -> list[str]:
    """``line: name`` for every ``walk-…`` literal that is not 11-screens' own, outside
    comments."""
    found: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(("*", "//", "/*")):
            continue
        found += [f"{i}: {m}" for m in _WALK_NAME.findall(line) if m not in OWN_NAMES]
    return found


def test_11_screens_names_no_account_or_repository_another_spec_made() -> None:
    offenders = foreign_names(SCREENS.read_text(encoding="utf-8"))
    assert offenders == [], (
        "11-screens runs on a stack of its own (the walkthrough-screens jobs): it may not name "
        "what another spec seeds — move the step to a story spec that runs after the one that "
        f"makes it (11b-keyboard runs after 08 and 10): {offenders}"
    )


def test_the_gate_catches_the_repository_08_seeds() -> None:
    """Negative control: the line the keyboard steps carried is refused; a persona is not."""
    assert foreign_names("const SIGNED_REPO = 'walk-signable'\n") == ["1: walk-signable"]
    assert foreign_names("  approver: 'walk-approver',\n") == []
    assert foreign_names(" * the repository 'walk-signable' 08 seeds\n") == []


def test_the_story_runs_every_spec_but_11_screens() -> None:
    """The keyboard steps run only if the story job still excludes 11-screens alone."""
    ci = CI.read_text(encoding="utf-8")
    assert "scripts/walkthrough.sh --grep-invert '11-screens\\.spec\\.ts'" in ci
    assert (WALKTHROUGH / "11b-keyboard.spec.ts").is_file()
    assert "keyboard: " not in SCREENS.read_text(encoding="utf-8")
