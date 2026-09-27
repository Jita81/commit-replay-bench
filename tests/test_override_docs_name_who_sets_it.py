"""Every operator document that tells a reader to set the unsealed override names who sets it.

Navigation
----------
What it is:   A ratchet over the documents an operator deploys from — ``deploy/`` (the compose
              file, the ``.env`` example, the Helm chart's values and README) and the guides
              DEPLOYMENT, OPERATOR and SECURITY and the README.
What it does: Finds every block (a paragraph, a list item, a table row or a run of comment
              lines) that tells the reader to set ``CRB_ALLOW_UNSEALED_PROD`` to ``1`` and
              fails when the same block does not also name ``CRB_ALLOW_UNSEALED_PROD_BY`` and
              ``CRB_ALLOW_UNSEALED_PROD_REASON``. In production the override without them
              stops both processes at start (ADR-0023 as amended, G-663), so a document that
              names only the one variable sends the operator to pods that crash on start
              (P-119: the Helm README, ``values.yaml`` and the compose file did, after the
              override began to require the other two).
How:          Splits each file into blocks by blank lines, list items, headings, table rows
              and — in YAML and ``.env`` files — runs of comment lines; a companion
              variable's own table row is its definition and is not asked to name itself.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0023-production-refuses-the-unsealed-posture.md
Works with:   src/crb/server/settings.py (``unsealed_override_ack_refusal``, the start-up rule
              the documents describe), docs/DEPLOYMENT.md#21-environment-reference (the
              variables' own rows), deploy/helm/crb/README.md (the chart's ``config.*`` keys
              an operator sets)
Tested by:    tests/test_override_docs_name_who_sets_it.py
Touch when:   another variable becomes required beside an existing one (add it to
              ``REQUIRES``), or an operator document is added.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: A setting that tells the reader to switch the override on, and what must stand beside it.
SETS_THE_OVERRIDE = re.compile(r"ALLOW_UNSEALED_PROD(?:=1|:\s*\"1\"|\s*:\s*'1')")
REQUIRES = ("CRB_ALLOW_UNSEALED_PROD_BY", "CRB_ALLOW_UNSEALED_PROD_REASON")
#: A companion's own row in an environment table: its definition, not an instruction.
COMPANION_ROW = re.compile(r"^\|\s*`(?:config\.)?CRB_ALLOW_UNSEALED_PROD_(?:BY|REASON)`")

GUIDES = ("README.md", "docs/DEPLOYMENT.md", "docs/OPERATOR.md", "docs/SECURITY.md")
TEXT_SUFFIXES = {".md", ".yml", ".yaml", ".example", ".tpl", ".txt", ".sh"}


def operator_documents() -> list[Path]:
    deploy = [
        p
        for p in (ROOT / "deploy").rglob("*")
        if p.is_file() and (p.suffix in TEXT_SUFFIXES or p.name.startswith(".env"))
    ]
    return sorted(deploy) + [ROOT / g for g in GUIDES]


def _is_comment_file(path: Path) -> bool:
    return path.suffix in {".yml", ".yaml", ".example", ".sh"} or path.name.startswith(".env")


def blocks(path: Path) -> list[tuple[int, str]]:
    """``(first line number, text)`` of each block in ``path``."""
    out: list[tuple[int, list[str]]] = []
    comments = _is_comment_file(path)
    prev_comment = False
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            prev_comment = False
            out.append((n, []))
            continue
        if comments:
            is_comment = line.startswith("#")
            if not (is_comment and prev_comment):
                out.append((n, []))
            prev_comment = is_comment
        elif re.match(r"(?:[-*+]|\d+\.)\s|#|\|", line) or not out:
            out.append((n, []))
        out[-1][1].append(line)
    return [(n, " ".join(lines)) for n, lines in out if lines]


def unacknowledged(path: Path) -> list[str]:
    return [
        f"{path.relative_to(ROOT)}:{n}: names the override without "
        + ", ".join(r for r in REQUIRES if r not in text)
        for n, text in blocks(path)
        if SETS_THE_OVERRIDE.search(text)
        and not COMPANION_ROW.match(text)
        and not all(r in text for r in REQUIRES)
    ]


def test_every_operator_document_that_sets_the_override_names_who_and_why() -> None:
    found = [line for p in operator_documents() for line in unacknowledged(p)]
    assert found == [], "\n".join(found)


def test_the_ratchet_reads_the_documents_that_set_the_override() -> None:
    """Not vacuous: the chart, the compose file and the guides are read, and each of them
    does tell the reader how to set the override."""
    setting = {
        str(p.relative_to(ROOT))
        for p in operator_documents()
        for _, text in blocks(p)
        if SETS_THE_OVERRIDE.search(text)
    }
    for expected in (
        "deploy/helm/crb/README.md",
        "deploy/helm/crb/values.yaml",
        "deploy/docker-compose.yml",
        "deploy/.env.example",
        "docs/DEPLOYMENT.md",
    ):
        assert expected in setting


@pytest.mark.parametrize(
    ("name", "body", "flagged"),
    [
        ("a.md", "Host is refused unless `CRB_ALLOW_UNSEALED_PROD=1`.\n", True),
        (
            "b.md",
            "Refused unless `CRB_ALLOW_UNSEALED_PROD=1` with `CRB_ALLOW_UNSEALED_PROD_BY` "
            "and\n`CRB_ALLOW_UNSEALED_PROD_REASON`.\n",
            False,
        ),
        ("c.yaml", '# refused unless\n# config.CRB_ALLOW_UNSEALED_PROD: "1"\nkey: 1\n', True),
        (
            "d.yaml",
            "# refused unless CRB_ALLOW_UNSEALED_PROD=1\n# with CRB_ALLOW_UNSEALED_PROD_BY and "
            "CRB_ALLOW_UNSEALED_PROD_REASON\n",
            False,
        ),
        # a block that names the companions elsewhere does not cover another block
        (
            "e.md",
            "- unless `CRB_ALLOW_UNSEALED_PROD=1`.\n- `CRB_ALLOW_UNSEALED_PROD_BY`, "
            "`CRB_ALLOW_UNSEALED_PROD_REASON`\n",
            True,
        ),
    ],
)
def test_the_ratchet_flags_a_block_that_names_only_the_one_variable(
    tmp_path: Path, name: str, body: str, flagged: bool
) -> None:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    hits = [
        n
        for n, text in blocks(path)
        if SETS_THE_OVERRIDE.search(text) and not all(r in text for r in REQUIRES)
    ]
    assert bool(hits) is flagged
