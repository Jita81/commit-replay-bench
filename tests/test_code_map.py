"""scripts/code_map.py — the header parser and the gate, on synthetic files.

Navigation
----------
What it is:   Unit tests for the code-map generator (the file-header gate).
What it does: Pins that a valid Navigation block parses into its keys, that a missing key, a
              key out of order, a dangling link and a blank Tested by are refused, that a
              path git ignores is dangling even when it is on the disk (P-355), that the
              three languages (Python docstring, TS leading comment, shell comment) are read,
              and that --check fails on a stale map.
How:          Writes tiny files under tmp_path (a ``git init`` there where ignoring
              matters), points the module's ROOT at it via monkeypatch, and calls
              read_header / render / main directly.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/code_map.py (the code under test), docs/FILE-HEADER-STANDARD.md (the
              format these tests pin)
Tested by:    tests/test_code_map.py
Touch when:   never for a new repository; the standard gains or renames a key (update
              REQUIRED_KEYS and these cases together), or a header check is added.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "code_map", Path(__file__).resolve().parent.parent / "scripts" / "code_map.py"
)
assert _SPEC and _SPEC.loader
cm = importlib.util.module_from_spec(_SPEC)
sys.modules["code_map"] = cm
_SPEC.loader.exec_module(cm)

BLOCK = """Navigation
----------
What it is:   A thing.
What it does: Does a thing,
              across two lines.
How:          By doing.
Layer:        core — docs/ARCHITECTURE.md#x
ADRs:         none
Works with:   src/crb/core/other.py (why)
Tested by:    tests/test_thing.py
Touch when:   never for a new repository.
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "src/crb/core").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/ARCHITECTURE.md").write_text("# a\n", encoding="utf-8")
    (tmp_path / "src/crb/core/other.py").write_text('"""x"""\n', encoding="utf-8")
    (tmp_path / "tests/test_thing.py").write_text('"""x"""\n', encoding="utf-8")
    monkeypatch.setattr(cm, "ROOT", tmp_path)
    monkeypatch.setattr(cm, "OUT", tmp_path / "docs" / "CODE-MAP.md")
    return tmp_path


def _py(repo: Path, rel: str, block: str, prose: str = "Summary line.\n\nSome prose.\n\n") -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'"""{prose}{block}"""\n\nX = 1\n', encoding="utf-8")
    return p


def test_valid_python_block_parses(repo: Path) -> None:
    h = cm.read_header(_py(repo, "src/crb/core/thing.py", BLOCK))
    assert h.problems == [] and h.summary == "Summary line."
    assert h.fields["What it does"] == "Does a thing, across two lines."
    assert h.fields["Tested by"] == "tests/test_thing.py"


def test_typescript_and_shell_blocks_parse(repo: Path) -> None:
    ts = repo / "ui/src/x.ts"
    ts.parent.mkdir(parents=True)
    body = "\n".join(" * " + ln for ln in ("Screen.", "", *BLOCK.splitlines()))
    ts.write_text(f"/**\n{body}\n */\nimport x from 'y'\n", encoding="utf-8")
    assert cm.read_header(ts).problems == []
    sh = repo / "scripts/run.sh"
    sh.parent.mkdir(parents=True)
    sh.write_text(
        "#!/bin/sh\n# Runs.\n#\n"
        + "".join(f"# {ln}\n" for ln in BLOCK.splitlines())
        + "\nset -e\n",
        encoding="utf-8",
    )
    assert cm.read_header(sh).problems == []


@pytest.mark.parametrize(
    ("mutation", "problem"),
    [
        (lambda b: b.replace("How:          By doing.\n", ""), "missing key 'How'"),
        (
            lambda b: b.replace("Tested by:    tests/test_thing.py", "Tested by:    tests/nope.py"),
            "does not exist",
        ),
        (
            lambda b: b.replace("Tested by:    tests/test_thing.py", "Tested by:"),
            "empty key 'Tested by'",
        ),
        (
            lambda b: b.replace("ADRs:         none\n", "") + "ADRs:         none\n",
            "keys out of order",
        ),
        (lambda b: "", "no Navigation block"),
    ],
)
def test_defects_are_refused(repo: Path, mutation, problem: str) -> None:
    h = cm.read_header(_py(repo, "src/crb/core/thing.py", mutation(BLOCK)))
    assert any(problem in p for p in h.problems), h.problems


def test_check_fails_on_a_stale_map_and_passes_after_a_write(repo: Path, capsys) -> None:
    _py(repo, "src/crb/core/thing.py", BLOCK)
    (repo / "src/crb/core/other.py").write_text(f'"""Other.\n\n{BLOCK}"""\n', encoding="utf-8")
    (repo / "tests/test_thing.py").write_text(f'"""T.\n\n{BLOCK}"""\n', encoding="utf-8")
    assert cm.main(["--check"]) == 1  # no map yet
    assert cm.main([]) == 0
    out = (repo / "docs" / "CODE-MAP.md").read_text(encoding="utf-8")
    assert "[`src/crb/core/thing.py`](../src/crb/core/thing.py)" in out
    assert "[`tests/test_thing.py`](../tests/test_thing.py)" in out  # links rendered
    assert cm.main(["--check"]) == 0
    _py(repo, "src/crb/core/thing.py", BLOCK.replace("A thing.", "A changed thing."))
    assert cm.main(["--check"]) == 1  # the map is stale


@pytest.mark.parametrize(
    ("touch", "refused"),
    [
        ("never for a new repository; a key is added.", False),
        ("never for a new repository (configure the runner instead); a key is added.", False),
        ("onboarding a repository whose tests need a service; a key is added.", False),
        ("a client repository pins a lock format no recipe reads; a key is added.", False),
        ("a key is added to the standard.", True),
        ("a model is re-priced; never for a new repository.", True),
        ("a model is re-priced. Never for a new repository.", True),
        ("a model is re-priced — never for a new repository.", True),
        ("a Go repository needs cgo or a pinned ``go`` binary; a key is added.", False),
        ("THIS is the verb a new repository starts with; a key is added.", False),
        ("a stage is added to onboarding; a key is added.", False),
        # A repository named only as a thing the file handles is not onboarding one (P-116).
        ("`GET /repos/{name}` gains a field a reader needs; a key is added.", True),
        ("``GET /repos`` gains a column; a key is added.", True),
        ("the image repository, issuer or signing identity changes.", True),
        ("the repository layer gains a table.", True),
        ("a key is added to src/crb/server/routes/repos.py.", True),
        ("an `OptKind` is added to ui/src/screens/Repos/runnerOpts.ts.", True),
        ("a column is added to the list or the role rule for Add repo changes.", True),
    ],
)
def test_touch_when_addresses_onboarding_a_client_repository_first(
    repo: Path, touch: str, refused: bool
) -> None:
    """The first clause of ``Touch when`` speaks about onboarding a client repository — a new,
    client or language-named repository, or onboarding itself — so that developer reads first
    whether the file concerns them. A repository in a code span, a path or a phrase such as
    "the image repository" does not count (P-114, P-116)."""
    block = BLOCK.replace("Touch when:   never for a new repository.", f"Touch when:   {touch}")
    h = cm.read_header(_py(repo, "src/crb/core/thing.py", block))
    assert any("onboarding" in p for p in h.problems) is refused, h.problems


def test_the_onboarding_baseline_only_shrinks(repo: Path, capsys) -> None:
    """Files older than the rule are listed in the baseline and pass; one that now addresses
    onboarding first must leave it, and an entry for a file that is gone fails ``--check``."""
    old = BLOCK.replace("never for a new repository.", "a key is added to the standard.")
    (repo / "scripts").mkdir()
    baseline = repo / cm.ONBOARDING_BASELINE
    baseline.write_text("# older than the rule\nsrc/crb/core/old.py\n", encoding="utf-8")
    assert cm.read_header(_py(repo, "src/crb/core/old.py", old)).problems == []
    assert cm.read_header(_py(repo, "src/crb/core/new.py", old)).problems != []
    fixed = cm.read_header(_py(repo, "src/crb/core/old.py", BLOCK))
    assert any("remove it from" in p for p in fixed.problems), fixed.problems
    (repo / "src/crb/core/new.py").unlink()
    (repo / "src/crb/core/other.py").write_text(f'"""Other.\n\n{BLOCK}"""\n', encoding="utf-8")
    (repo / "tests/test_thing.py").write_text(f'"""T.\n\n{BLOCK}"""\n', encoding="utf-8")
    _py(repo, "src/crb/core/old.py", old)
    assert cm.main([]) == 0
    assert cm.main(["--check"]) == 0
    baseline.write_text("src/crb/core/old.py\nsrc/crb/core/gone.py\n", encoding="utf-8")
    assert cm.main(["--check"]) == 1
    assert "src/crb/core/gone.py" in capsys.readouterr().err


#: The size of ``scripts/code_map_onboarding_baseline.txt`` when the check was added (PR #61).
#: Lower it as files leave the list; raising it is adding a file to the baseline, which the
#: baseline exists to stop.
BASELINE_CEILING = 357


def test_the_real_onboarding_baseline_never_grows() -> None:
    root = Path(__file__).resolve().parent.parent
    lines = (root / cm.ONBOARDING_BASELINE).read_text(encoding="utf-8").splitlines()
    entries = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
    assert entries == sorted(set(entries)), "keep the baseline sorted and without repeats"
    assert len(entries) <= BASELINE_CEILING, (
        f"{len(entries)} files in the onboarding baseline, above {BASELINE_CEILING}: a new "
        "file's Touch when must address onboarding a client repository first"
    )


def test_a_change_may_not_edit_a_baseline_file_or_add_to_the_baseline() -> None:
    """Under ``--changed-since``, a file in the baseline that the change edits must leave it
    (its ``Touch when`` fixed first), and no path may join the baseline — removals only."""
    baseline = frozenset({"src/a.py", "src/b.py", "src/new.py"})
    before = frozenset({"src/a.py", "src/b.py", "src/c.py"})
    found = cm.baseline_violations(baseline, {"src/a.py", "docs/x.md"}, before)
    assert any(f.startswith("src/a.py:") and "edited" in f for f in found), found
    assert any(f.startswith("src/new.py:") and "added" in f for f in found), found
    assert not any(f.startswith("src/b.py") for f in found), found
    assert cm.baseline_violations(baseline, set(), None) == []  # the baseline's first change


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_check_with_changed_since_refuses_an_edited_baseline_file(repo: Path, capsys) -> None:
    old = BLOCK.replace("never for a new repository.", "a key is added to the standard.")
    (repo / "scripts").mkdir()
    (repo / cm.ONBOARDING_BASELINE).write_text("src/crb/core/old.py\n", encoding="utf-8")
    _py(repo, "src/crb/core/old.py", old)
    (repo / "src/crb/core/other.py").write_text(f'"""Other.\n\n{BLOCK}"""\n', encoding="utf-8")
    (repo / "tests/test_thing.py").write_text(f'"""T.\n\n{BLOCK}"""\n', encoding="utf-8")
    assert cm.main([]) == 0
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    assert cm.main(["--check", "--changed-since", "main"]) == 0  # nothing edited
    _py(repo, "src/crb/core/old.py", old, prose="Summary line.\n\nEdited prose.\n\n")
    assert cm.main([]) == 0
    _git(repo, "commit", "-q", "-am", "edit")
    assert cm.main(["--check"]) == 0  # without the base the edit is not seen
    assert cm.main(["--check", "--changed-since", "main~1"]) == 1
    assert "src/crb/core/old.py" in capsys.readouterr().err
    assert cm.main(["--check", "--changed-since", "no-such-ref"]) == 1  # fails closed


def test_a_path_git_ignores_does_not_resolve_even_when_it_is_on_disk(repo: Path) -> None:
    """P-355: a header named ``ui/.tsbuild/``, the type-check's build info.
    The directory is ignored by git, so it existed in the builder's checkout (after
    ``npm run typecheck``) and not in CI's fresh clone: the gate passed on the dirty tree
    and failed on the clean one. A path resolves only if a fresh clone would have it —
    tracked, or new and not ignored — whatever happens to be on this disk."""
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("docs/built/\n", encoding="utf-8")
    (repo / "docs/built").mkdir()
    (repo / "docs/built/info.json").write_text("{}\n", encoding="utf-8")
    ignored = BLOCK.replace(
        "Works with:   src/crb/core/other.py (why)",
        "Works with:   src/crb/core/other.py (why), docs/built/ (the build info)",
    )
    h = cm.read_header(_py(repo, "src/crb/core/thing.py", ignored))
    assert any("docs/built/ does not exist" in p for p in h.problems), h.problems
    # a new file that is not ignored resolves before anybody runs ``git add``
    assert cm.read_header(_py(repo, "src/crb/core/thing.py", BLOCK)).problems == []
    # and a tracked file that has been deleted from the disk does not
    _git(repo, "add", "-A")
    (repo / "src/crb/core/other.py").unlink()
    h = cm.read_header(_py(repo, "src/crb/core/thing.py", BLOCK))
    assert any("src/crb/core/other.py does not exist" in p for p in h.problems), h.problems


def test_outside_a_git_checkout_the_disk_is_the_answer(repo: Path) -> None:
    """An exported tree (``git archive``) has no ``.git``: nothing in it was ignored, so the
    disk is what a fresh clone would hold, and the gate reads the disk."""
    (repo / "docs/built").mkdir()
    listed = BLOCK.replace("Tested by:    tests/test_thing.py", "Tested by:    docs/built/")
    assert cm.read_header(_py(repo, "src/crb/core/thing.py", listed)).problems == []
