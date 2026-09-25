"""The runner-command audit (2026-09-25): each gap it found in the six live repositories'
checks, pinned so it cannot come back.

Navigation
----------
What it is:   The regression suite for the gaps ``scripts/audit_runner_commands.py`` found
              between what the runners derive and what the six live repositories run in CI
              (docs/reviews/2026-09-25-runner-commands-audit.md), and for the script itself.
What it does: Pins that a frozen pre-commit ``rev`` (a sha with ``# frozen: vX``, pallets/click)
              yields the pinned ruff version and a bare sha never yields ``==<sha>``; that a
              host ruff which does not satisfy the repository's pin is REFUSED (a harness error
              naming the pin) instead of reading every patch as ``lint`` (mesh-client); that
              black check mode joins belt 5 where the repository configures black; that
              ``eslint``/``stylelint`` inherit the script's ``--max-warnings`` (NHS repos); that
              prettier judges the stylesheets, JSON and Markdown it formats; that ``go vet`` is
              derived for the finish gate from ``.golangci.yml``'s ``govet`` (cobra); and that
              the audit script reports a tool the evidence names but nothing covers.
How:          Temporary checkouts shaped like each repository's configuration; small executable
              stand-ins for tools that are not installed on the host (the plan and the exit-code
              table under test are the real ones); ``run_plan`` on a ``LocalExecutor``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md, docs/adr/0021-working-by-construction.md
Works with:   src/crb/core/lint.py (the detectors), src/crb/core/finish_gate.py
              (``derived_commands``), scripts/audit_runner_commands.py (the audit),
              docs/reviews/2026-09-25-runner-commands-audit.md (the findings)
Tested by:    tests/test_runner_audit.py
Touch when:   a detector changes what it derives for one of the six repositories' shapes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from crb.core import lint as ln
from crb.core.checks import CheckCommand
from crb.core.execution import LocalExecutor
from crb.core.finish_gate import derived_commands, merge_commands

ROOT = Path(__file__).resolve().parents[1]


def _tool(path: Path, version: str, *, rc: int = 0) -> str:
    """An executable stand-in that answers ``--version`` and exits ``rc`` otherwise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then echo "{path.name} {version}"; exit 0; fi\n'
        f"exit {rc}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


# --- ruff: the repository's pinned version --------------------------------------------------


def test_a_frozen_pre_commit_rev_yields_the_frozen_version_and_a_bare_sha_none(
    tmp_path: Path,
) -> None:
    pc = tmp_path / ".pre-commit-config.yaml"
    pc.write_text(
        "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
        "    rev: c60c980e561ed3e73101667fe8365c609d19a438  # frozen: v0.15.9\n"
        "    hooks:\n      - id: ruff-check\n",
        encoding="utf-8",
    )
    assert ln.pinned_ruff_spec(tmp_path) == "==0.15.9"
    pc.write_text(pc.read_text().replace("  # frozen: v0.15.9", ""), encoding="utf-8")
    assert ln.pinned_ruff_spec(tmp_path) == ""
    pc.write_text(
        pc.read_text().replace("c60c980e561ed3e73101667fe8365c609d19a438", "0397b68f6f88c024"),
        encoding="utf-8",
    )
    assert ln.pinned_ruff_spec(tmp_path) == ""  # a sha that starts with a digit is no version


@pytest.mark.parametrize(
    ("version", "spec", "ok"),
    [
        ("0.2.5", ">=0.2.0,<0.3.0", True),
        ("0.16.7", ">=0.2.0,<0.3.0", False),
        ("0.15.9", "==0.15.9", True),
        ("0.15.11", "==0.15.9", False),
        ("1.4.2", "~=1.4", True),
        ("2.0.0", "~=1.4", False),
        ("0.4.9", "==0.4.*", True),
        ("0.5.0", "!=0.5.0", False),
        ("garbage", ">=1", None),
        ("1.0.0", "", None),
    ],
)
def test_version_satisfies_reads_the_pep_440_subset_pins_use(
    version: str, spec: str, ok: bool | None
) -> None:
    assert ln.version_satisfies(version, spec) is ok


def _mesh_shaped(tmp_path: Path, pin: str) -> Path:
    root = tmp_path / "mesh"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\nversion = "0"\n'
        f'[tool.poetry.group.dev.dependencies]\nruff = "{pin}"\n\n'
        "[tool.ruff]\nline-length = 120\n\n[tool.black]\nline-length = 120\n",
        encoding="utf-8",
    )
    (root / "pkg.py").write_text("x = 1\n", encoding="utf-8")
    return root


def test_a_host_ruff_outside_the_repositorys_pin_is_refused_never_a_verdict(
    tmp_path: Path,
) -> None:
    """mesh-client pinned ``ruff ^0.2.0``; the host's 0.16 read every patch as ``lint``."""
    root = _mesh_shaped(tmp_path, "^0.2.0")
    ruff = _tool(tmp_path / "bin" / "ruff", "0.16.7", rc=1)  # would "reject" everything
    plan = ln.python_plan(root, ruff)
    assert plan is not None and "!pin>=0.2.0,<0.3.0" in plan.detected
    run = ln.run_plan(plan, LocalExecutor(), root, ["pkg.py"])
    assert run.ok is False and "does not satisfy the repository's pin" in run.error
    assert run.steps[0].verdict is None  # a harness error, not a rejection


def test_a_host_ruff_inside_the_pin_runs_and_black_joins_the_plan(tmp_path: Path) -> None:
    root = _mesh_shaped(tmp_path, "^0.2.0")
    ruff = _tool(tmp_path / "bin" / "ruff", "0.2.2")
    black = _tool(tmp_path / "bin" / "black", "25.1.0", rc=1)  # black --check: would reformat
    plan = ln.python_plan(root, ruff)
    assert plan is not None and plan.detected == "ruff@0.2.2+black"
    assert [t.name for t in plan.tools] == ["ruff", "black"] and not plan.tools[0].refuse
    assert plan.tools[1].argv == (black, "--check", "-q")
    run = ln.run_plan(plan, LocalExecutor(), root, ["pkg.py"])
    assert run.ok is False and run.error == "" and run.steps[-1].tool == "black"
    # under the sandbox (a bare ruff) no host path is handed to the image
    sandboxed = ln.python_plan(root, "ruff")
    assert sandboxed is not None and [t.name for t in sandboxed.tools] == ["ruff"]


# --- the NHS repositories: warnings, stylesheets, the files prettier formats ----------------


def _nhs_shaped(tmp_path: Path) -> Path:
    root = tmp_path / "nhs"
    bin_dir = root / "node_modules" / ".bin"
    for tool in ("eslint", "prettier", "stylelint"):
        _tool(bin_dir / tool, "9.0.0")
    (root / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "lint:js": "eslint --cache --color --max-warnings 0 .",
                    "lint:css": 'stylelint --color --max-warnings 0 "**/*.{md,scss}"',
                    "lint:prettier": "prettier --check .",
                }
            }
        ),
        encoding="utf-8",
    )
    for cfg in ("eslint.config.mjs", ".prettierrc.js", "stylelint.config.mjs"):
        (root / cfg).write_text("export default {}\n", encoding="utf-8")
    return root


def test_nhs_lint_inherits_max_warnings_and_judges_stylesheets(tmp_path: Path) -> None:
    root = _nhs_shaped(tmp_path)
    plan = ln.js_plan(root, root / "node_modules" / ".bin")
    assert plan is not None
    assert plan.detected == "eslint(max-warnings=0)+prettier+stylelint"
    eslint, prettier, stylelint = plan.tools
    assert eslint.argv[1:] == ("--max-warnings", "0")
    assert stylelint.argv[1:] == ("--max-warnings", "0") and stylelint.findings_rcs == {2}
    assert stylelint.files_for(["a.scss", "b.mjs"]) == ("a.scss",)
    assert set(prettier.files_for(["a.scss", "b.json", "c.md", "d.mjs", "e.png"])) == {
        "a.scss",
        "b.json",
        "c.md",
        "d.mjs",
    }


# --- cobra: govet, derived for the finish gate ----------------------------------------------


def test_go_vet_is_derived_from_the_repositorys_evidence_and_a_declared_one_wins(
    tmp_path: Path,
) -> None:
    (tmp_path / "go.mod").write_text("module m\n\ngo 1.22\n", encoding="utf-8")
    assert derived_commands(tmp_path) == ()
    (tmp_path / ".golangci.yml").write_text("linters:\n  enable:\n    - govet\n", encoding="utf-8")
    (vet,) = derived_commands(tmp_path)
    assert vet == CheckCommand("vet", ("go", "vet", "./..."))
    mine = CheckCommand("vet", ("go", "vet", "-tags", "x", "./..."))
    extra = CheckCommand("test", ("go", "test", "./..."), blind_only=True)
    assert merge_commands((vet,), (mine, extra)) == (mine, extra)


# --- the audit script ------------------------------------------------------------------------


def _audit_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "audit_runner_commands", ROOT / "scripts" / "audit_runner_commands.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_audit_names_a_tool_the_evidence_runs_and_nothing_derives(tmp_path: Path) -> None:
    audit = _audit_module()
    root = tmp_path / "gomod"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "go.mod").write_text("module m\n\ngo 1.22\n", encoding="utf-8")
    (root / ".golangci.yml").write_text(
        "formatters:\n  enable:\n    - gofmt\n    - goimports\nlinters:\n  enable:\n    - govet\n",
        encoding="utf-8",
    )
    report = audit.audit(root, "go", "go", provisioned=True)
    assert report["derived"]["belt5"]["detected"] == "gofmt"
    assert report["derived"]["finish_gate_derived"] == ["go vet ./..."]
    assert report["gaps"] == ["goimports"]
    assert report["evidence"]["goimports"] == [".golangci.yml:4"]


# --- what belt 5 now reads is held by belt 1b ---------------------------------------------------


def test_the_lint_configuration_the_audit_added_is_test_infrastructure() -> None:
    """A builder cannot edit its way past the new checks: stylelint's config, the lint
    scripts belt 5 reads ``--max-warnings`` from, and ``[tool.black]`` disqualify."""
    from crb.core.test_infra import infra_sections_changed, matching_rule

    assert matching_rule("stylelint.config.mjs", "javascript", runner="jest") is not None
    before = json.dumps({"scripts": {"lint:js": "eslint --max-warnings 0 .", "build": "x"}})
    weakened = json.dumps({"scripts": {"lint:js": "eslint .", "build": "x"}})
    honest = json.dumps({"scripts": {"lint:js": "eslint --max-warnings 0 .", "build": "y"}})
    assert infra_sections_changed("package.json", before, weakened, "javascript", runner="jest")
    assert not infra_sections_changed("package.json", before, honest, "javascript", runner="jest")
    py_before = "[tool.black]\nline-length = 88\n"
    py_after = "[tool.black]\nline-length = 200\n"
    assert infra_sections_changed("pyproject.toml", py_before, py_after, "python", runner="pytest")
