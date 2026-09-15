"""The package version is declared in three places that must never drift.

``release.yml`` refuses a ``v*`` tag whose version differs from ``pyproject.toml``;
``/version`` and every evidence pack report ``crb.core.version.__version__``; the Helm
chart's ``appVersion`` is what an operator sees in ``helm list``. One number, three
readers — pinned here so a bump that misses one is a failing test, not a refused tag
or a mislabelled deployment. ``APPARATUS_VERSION`` is deliberately NOT tied to it: it
moves only when the meaning of a verdict changes (ADR-0011 → 2.2).

Navigation
----------
What it is:   The version-drift test suite — one package version in three places.
What it does: Pins that ``pyproject.toml``, ``crb.core.version.__version__`` and the Helm chart's
              ``appVersion`` are the same string, that ``release.yml``'s tag rule would accept
              ``v<version>``, that ``APPARATUS_VERSION`` is deliberately independent of it, and
              that the CHANGELOG has a dated header for the current version.
How:          Reads the files as text / TOML; no subprocess.
Layer:        tests — docs/ARCHITECTURE.md#74-versioning
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/version.py (the source of truth), deploy/helm/crb/Chart.yaml
              (``appVersion``), .github/workflows/release.yml (the tag rule),
              docs/EVIDENCE-AND-CLAIMS.md (the apparatus stamp — why the two versions differ, §4)
Tested by:    tests/test_version_consistency.py
Touch when:   releasing (bump all three and the CHANGELOG together — this suite is the
              checklist); never tie ``APPARATUS_VERSION`` to the package version.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from crb.core.version import APPARATUS_VERSION, __version__

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHART = ROOT / "deploy" / "helm" / "crb" / "Chart.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"

#: PEP 440 for the shapes this project releases (``2.0.0a1``, ``2.1.0``, ``2.1.0rc1``).
_PEP440 = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def _pyproject_version() -> str:
    with PYPROJECT.open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def _chart_app_version() -> str:
    m = re.search(r'^appVersion:\s*"([^"]+)"\s*$', CHART.read_text(encoding="utf-8"), re.M)
    assert m, "appVersion not found in Chart.yaml"
    return m.group(1)


def test_package_version_is_one_number_in_three_places() -> None:
    assert _PEP440.match(__version__), __version__
    assert _pyproject_version() == __version__
    assert _chart_app_version() == __version__


def test_release_tag_check_would_accept_the_version_tag() -> None:
    """The exact rule ``release.yml`` applies: ``v<pyproject version>`` is the only tag
    the build job accepts."""
    tag = f"v{__version__}"
    assert tag[1:] == _pyproject_version()


def test_apparatus_version_is_independent_of_the_package_version() -> None:
    assert re.match(r"^\d+\.\d+$", APPARATUS_VERSION)
    assert APPARATUS_VERSION == "2.2"  # bumps only with an ADR (see crb.core.version)


def test_changelog_has_a_dated_header_for_the_current_version() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    header = re.search(rf"^## \[{re.escape(__version__)}\] — (\d{{4}}-\d{{2}}-\d{{2}})", text, re.M)
    assert header, f"CHANGELOG.md has no dated header for {__version__}"
    assert "tag pending" not in text.split(header.group(0), 1)[1].split("\n## ", 1)[0]
    assert f"[{__version__}]: https://" in text  # the compare link is present
