"""scripts/code_map.py — the header parser and the gate, on synthetic files.

Navigation
----------
What it is:   Unit tests for the code-map generator (the file-header gate).
What it does: Pins that a valid Navigation block parses into its keys, that a missing key, a
              key out of order, a dangling link and a blank Tested by are refused, that a
              path git ignores is dangling even when it is on the disk (P-327), that the
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
              REQUIRED_KEYS and these cases together).
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


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_a_path_git_ignores_does_not_resolve_even_when_it_is_on_disk(repo: Path) -> None:
    """P-327: a header named ``ui/.tsbuild/``, the type-check's build info.
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
