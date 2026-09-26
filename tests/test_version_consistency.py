"""The package version is declared in three places that must never drift — and the
Helm chart's own ``version`` is its SemVer 2 form.

``release.yml`` refuses a ``v*`` tag whose version differs from ``pyproject.toml``;
``/version`` and every evidence pack report ``crb.core.version.__version__``; the Helm
chart's ``appVersion`` is what an operator sees in ``helm list``. One number, three
readers — pinned here so a bump that misses one is a failing test, not a refused tag
or a mislabelled deployment. The chart's ``version`` (SemVer 2, what ``helm package``
names the archive and the ``helm.sh/chart`` label carries) tracks the same number with
a PEP 440 pre-release rendered as SemVer's hyphenated pre-release (``2.0.0b1`` →
``2.0.0-b1``; ``2.1.0rc1`` → ``2.1.0-rc1``; a final release is the same string) — the
rule docs/RELEASING.md §1 states, pinned by ``test_chart_version_is_the_semver_form_of_the_package_version``.
``APPARATUS_VERSION`` is deliberately NOT tied to it: it moves only when the meaning of a
verdict changes (ADR-0011 → 2.2).

Navigation
----------
What it is:   The version-drift test suite — one package version in three places, and the
              chart version as its SemVer form.
What it does: Pins that ``pyproject.toml``, ``crb.core.version.__version__`` and the Helm chart's
              ``appVersion`` are the same string, that the chart's ``version`` is
              ``semver_of(__version__)``, that ``release.yml``'s tag rule would accept
              ``v<version>``, that ``APPARATUS_VERSION`` is deliberately independent of it,
              that the CHANGELOG has a dated header for the current version, and that the gate
              tools (mypy, ruff) are pinned exactly with Dependabot moving them, that local
              coverage output is ignored, and that CONTRIBUTING's gate commands are the ones
              CI runs — a gate's verdict must not drift with the day the environment was
              resolved, nor with where it is run.
How:          Reads the files as text / TOML (ci.yml's ``run:`` steps split into shell words);
              no subprocess. ``semver_of`` is the one rule.
Layer:        tests — docs/ARCHITECTURE.md#74-versioning
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/version.py (the source of truth), deploy/helm/crb/Chart.yaml
              (``appVersion`` and ``version``), .github/workflows/release.yml (the tag rule),
              docs/RELEASING.md (§1 — the numbers, and this suite as the check),
              docs/EVIDENCE-AND-CLAIMS.md (the apparatus stamp — why the two versions
              differ, §4), .github/dependabot.yml (the ``dev-tooling`` group that bumps the
              gate tools), docs/CONTRIBUTING.md and .github/workflows/ci.yml (the documented
              gate commands and the ones CI runs)
Tested by:    tests/test_version_consistency.py
Touch when:   releasing (bump all four and the CHANGELOG together — this suite is the
              checklist); never tie ``APPARATUS_VERSION`` to the package version.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
import sys
import tomllib
from pathlib import Path

import pytest

from crb.core.version import APPARATUS_VERSION, __version__

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHART = ROOT / "deploy" / "helm" / "crb" / "Chart.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CONTRIBUTING = ROOT / "docs" / "CONTRIBUTING.md"

_SPEC = importlib.util.spec_from_file_location(
    "check_release_tag", ROOT / "scripts" / "check_release_tag.py"
)
assert _SPEC and _SPEC.loader
crt = importlib.util.module_from_spec(_SPEC)
sys.modules["check_release_tag"] = crt
_SPEC.loader.exec_module(crt)

#: PEP 440 for the shapes this project releases (``2.0.0a1``, ``2.1.0``, ``2.1.0rc1``).
_PEP440 = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def _pyproject_version() -> str:
    with PYPROJECT.open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def _chart_app_version() -> str:
    m = re.search(r'^appVersion:\s*"([^"]+)"\s*$', CHART.read_text(encoding="utf-8"), re.M)
    assert m, "appVersion not found in Chart.yaml"
    return m.group(1)


def _chart_version() -> str:
    m = re.search(r"^version:\s*([^\s#]+)\s*$", CHART.read_text(encoding="utf-8"), re.M)
    assert m, "version not found in Chart.yaml"
    return m.group(1)


def semver_of(pep440: str) -> str:
    """The chart-version rule (docs/RELEASING.md §1): a PEP 440 pre-release suffix becomes
    SemVer 2's hyphenated pre-release; a final release is unchanged."""
    m = re.match(r"^(\d+\.\d+\.\d+)((?:a|b|rc)\d+)?$", pep440)
    assert m, pep440
    return m.group(1) if m.group(2) is None else f"{m.group(1)}-{m.group(2)}"


def test_package_version_is_one_number_in_three_places() -> None:
    assert _PEP440.match(__version__), __version__
    assert _pyproject_version() == __version__
    assert _chart_app_version() == __version__


@pytest.mark.parametrize(
    ("pep440", "semver"),
    [
        ("2.0.0a1", "2.0.0-a1"),
        ("2.0.0b1", "2.0.0-b1"),
        ("2.1.0rc1", "2.1.0-rc1"),
        ("2.1.0", "2.1.0"),
    ],
)
def test_the_chart_version_rule(pep440: str, semver: str) -> None:
    assert semver_of(pep440) == semver


def test_chart_version_is_the_semver_form_of_the_package_version() -> None:
    """``Chart.yaml`` ``version`` — a SemVer 2 string Helm accepts — is the package version
    with its pre-release hyphenated, so ``helm package`` names ``crb-<semver>.tgz`` for the
    release the ``appVersion`` runs (RELEASING §1 and its checklist name this test)."""
    assert _chart_version() == semver_of(__version__)


def test_release_tag_rule_accepts_only_the_version_tag() -> None:
    """The rule ``release.yml`` runs (``scripts/check_release_tag.py``): on a tag push only
    ``v<pyproject version>`` passes; a wrong version, a missing or upper-case ``v``, a suffix
    are refused; a branch push is a no-op. The workflow must call that script."""
    v = _pyproject_version()
    assert crt.check("tag", f"v{v}", v) is None
    for bad in (f"v{v}-rc1", f"V{v}", v, "v9.9.9", "vlatest"):
        assert crt.check("tag", bad, v), bad
    assert crt.check("branch", "main", v) is None
    assert crt.pyproject_version() == __version__
    # the CLI form the workflow runs
    assert crt.main(["--ref-type", "tag", "--ref-name", f"v{v}"]) == 0
    assert crt.main(["--ref-type", "tag", "--ref-name", "v0.0.0"]) == 1
    assert "python scripts/check_release_tag.py" in RELEASE.read_text(encoding="utf-8")


def test_apparatus_version_is_independent_of_the_package_version() -> None:
    assert re.match(r"^\d+\.\d+$", APPARATUS_VERSION)
    assert APPARATUS_VERSION == "2.2"  # bumps only with an ADR (see crb.core.version)


def test_changelog_has_a_dated_header_for_the_current_version() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    header = re.search(rf"^## \[{re.escape(__version__)}\] — (\d{{4}}-\d{{2}}-\d{{2}})", text, re.M)
    assert header, f"CHANGELOG.md has no dated header for {__version__}"
    assert "tag pending" not in text.split(header.group(0), 1)[1].split("\n## ", 1)[0]
    assert f"[{__version__}]: https://" in text  # the compare link is present


#: The tools whose verdict is a CI gate. A range lets the verdict move with the day the
#: environment was resolved; an exact pin moves only in a reviewed Dependabot pull request.
GATE_TOOLS = ("mypy", "ruff")


def _dev_extra() -> list[str]:
    with PYPROJECT.open("rb") as fh:
        return [str(r) for r in tomllib.load(fh)["project"]["optional-dependencies"]["dev"]]


def test_the_gate_tools_are_pinned_exactly_and_dependabot_moves_them() -> None:
    """``mypy>=1.11`` let a fresh environment and CI's disagree about the same tree
    (assessment 2026-09-25 §E1). Each gate tool is pinned with ``==`` in the dev extra, and
    Dependabot's ``dev-tooling`` group is what bumps it."""
    extra = _dev_extra()
    for tool in GATE_TOOLS:
        (spec,) = [r for r in extra if re.match(rf"^{tool}\b", r)]
        assert re.fullmatch(rf"{tool}==\d+(\.\d+)+", spec), f"{spec!r} is not an exact pin"
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    group = re.search(r"dev-tooling:\s*\n\s*patterns:\s*\[([^\]]*)\]", dependabot)
    assert group, "dependabot.yml has no dev-tooling group"
    for tool in GATE_TOOLS:
        assert f'"{tool}"' in group.group(1), f"Dependabot does not bump {tool}"


def test_local_coverage_output_is_ignored() -> None:
    """The CI coverage command writes ``.coverage`` and ``coverage.xml``; a local run of the
    same command must not leave them untracked in every clone."""
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".coverage" in ignored and "coverage.xml" in ignored


def _ci_commands() -> list[list[str]]:
    """Every command a ``run:`` step of ci.yml runs, as shell words: a folded block (``>-``)
    is one command, a literal block (``|``) is one command per line."""
    lines = CI.read_text(encoding="utf-8").splitlines()
    commands: list[str] = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        if rest and rest[0] not in "|>":
            commands.append(rest)
            continue
        body: list[str] = []
        for following in lines[i + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following.strip())
        if rest.startswith(">"):
            commands.append(" ".join(b for b in body if b))
        else:
            commands.extend(b for b in body if b)
    words: list[list[str]] = []
    for command in commands:
        try:
            words.append(shlex.split(command, comments=True))
        except ValueError:  # a shell fragment shlex cannot read is no gate command
            continue
    return words


def _documented_gates() -> list[list[str]]:
    """The commands in CONTRIBUTING's "The gates" block, as shell words."""
    section = CONTRIBUTING.read_text(encoding="utf-8").split("## The gates", 1)[1]
    block = re.search(r"```bash\n(.*?)```", section, re.S)
    assert block, 'CONTRIBUTING "The gates" has no bash block'
    return [shlex.split(line, comments=True) for line in block.group(1).splitlines() if line]


def _verdict_words(words: list[str]) -> list[str]:
    """A command without its report-only options: ``--cov-report`` changes what is printed,
    never whether the gate passes."""
    return [w for w in words if not w.startswith("--cov-report")]


def test_the_documented_gate_commands_are_the_ones_ci_runs() -> None:
    """CONTRIBUTING tells a contributor that its gate block is what CI runs. The local
    ``pytest`` line once left out ``--cov-branch``, so it measured line coverage where CI
    measures branch coverage and could pass the 70% floor locally and fail it in CI (PR #51
    review). Each documented command must be one CI runs, word for word, apart from
    report-only options."""
    ci = [_verdict_words(c) for c in _ci_commands()]
    documented = _documented_gates()
    assert documented, 'CONTRIBUTING "The gates" block is empty'
    for command in documented:
        assert _verdict_words(command) in ci, (
            f"CONTRIBUTING documents {shlex.join(command)!r}, which no CI step runs"
        )
