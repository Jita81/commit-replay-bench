"""The guides name every probe ``/health`` serves, and say how many there are.

Navigation
----------
What it is:   A drift gate between the ``/health`` probe list and the two guides an operator
              reads it from: the ``GET /health`` row of docs/API.md and DEPLOYMENT §9.3.
What it does: Collects the probes the readiness route actually serves (every probe forced to
              fail, so the test needs no database, no docker daemon and no network) and
              refuses a guide that omits one by name or states the wrong count — DEPLOYMENT
              §9.3 said seven probes while ``/health`` served eleven, and API.md said ten and
              left out ``provision`` (G-403; docs/PREVENTION.md P-126) — and refuses any
              "N probes" on DEPLOYMENT, API, ARCHITECTURE or OPERATOR that is not the served
              count (§9's opening line kept "seven"; P-238). And refuses a §9.3 that names other
              probes as raising a banner than the UI raises one for: every UI reader of a probe
              is classified in ``BANNERS`` (P-188).
How:          ``collect_health`` over a session factory that raises and probe functions that
              raise, as tests/test_server_system.py's fixed-detail test does; the names come
              from the body; each guide's section is cut from the Markdown and searched for
              every name in backticks and for the count written as a word.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/routes/system.py (collect_health, the probe list under test),
              ui/src/components/Layout.tsx and ui/src/screens/Home/HomePage.tsx (the two
              banners a probe raises),
              docs/API.md (the /health row it reads), docs/DEPLOYMENT.md (§9.3 Health, which it
              reads), tests/test_server_system.py (pins the same names against the served
              body), docs/dod/journeys/operate.md (G-403, which this closes)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a probe is added to or removed from ``collect_health`` —
              name it in both guides and change the count there; this test tells you which guide is
              behind — or a screen starts reading a probe by name (classify it in ``BANNERS``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from crb.observability.probes import ProbeResult
from crb.server.routes.system import collect_health
from crb.server.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
WORDS = {
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def _served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The probe names ``/health`` serves, with every probe forced to fail."""

    def _factory() -> Session:
        raise RuntimeError("no store in this test")

    def _boom(*_: Any, **__: Any) -> ProbeResult:
        raise OSError("not probed in this test")

    for fn in ("probe_docker", "probe_toolchains", "probe_builders"):
        monkeypatch.setattr(f"crb.server.routes.system.probes.{fn}", _boom)
    monkeypatch.setattr("crb.server.routes.system.probe_provision", _boom)
    monkeypatch.setattr("crb.server.routes.system.build_stamp.probe_build", _boom)
    settings = Settings(
        env="dev",
        home=tmp_path,
        secret_key=SecretStr("s" * 40),
        sandbox={"executor": "docker"},
        log_format="text",
    )
    body = collect_health(_factory, settings, role="all", request_id="docs")  # type: ignore[arg-type]
    return [p["name"] for p in body["probes"]]


def _api_health_row() -> str:
    text = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    return next(line for line in text.split("\n") if line.startswith("| GET | `/health` |"))


def _deployment_9_3() -> str:
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    return text.split("### 9.3 Health", 1)[1].split("\n### ", 1)[0]


@pytest.mark.parametrize(
    ("guide", "section"),
    [("docs/API.md, the GET /health row", _api_health_row), ("DEPLOYMENT §9.3", _deployment_9_3)],
)
def test_each_guide_names_every_probe_health_serves_and_their_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guide: str, section: Any
) -> None:
    names = _served(tmp_path, monkeypatch)
    assert len(names) == len(set(names)) and len(names) in WORDS
    text = section()
    missing = [n for n in names if f"`{n}`" not in text]
    assert not missing, f"{guide} does not name the probe(s) {missing} that /health serves"
    assert f"{WORDS[len(names)]} probes" in text.lower(), (
        f"{guide} does not say /health runs {WORDS[len(names)]} probes"
    )


#: A screen that reads one probe finds it by name: ``probes.find((p) => p.name === '<probe>')``.
_READS_PROBE = re.compile(r"""probes\.find\(\(\w+\)\s*=>\s*\w+\.name\s*===\s*['"](\w+)['"]\)""")
#: Every (probe, file) the UI reads by name, classified: a probe that raises a banner, or one
#: whose data a screen shows. A new reader fails the test until it is classified here, so
#: the guide's banner sentence cannot fall behind a new banner unseen.
BANNERS: dict[tuple[str, str], bool] = {
    # the shell's red stop-condition banner, above every screen, on any false-Q1 row
    ("ledger", "ui/src/components/Layout.tsx"): True,
    # Home's banner when the sandbox cannot run
    ("sandbox", "ui/src/screens/Home/HomePage.tsx"): True,
    # the Measure summary names the posture the sandbox probe reports, and raises no banner
    ("sandbox", "ui/src/screens/Connect/MeasurePage.tsx"): False,
    # the run page reads the worker's heartbeat window and queue depth, and raises no banner
    ("worker", "ui/src/screens/Runs/RunDetailPage.tsx"): False,
}


def _ui_probe_readers() -> set[tuple[str, str]]:
    src = ROOT / "ui" / "src"
    return {
        (m.group(1), p.relative_to(ROOT).as_posix())
        for p in src.rglob("*.tsx")
        if ".test." not in p.name
        for m in _READS_PROBE.finditer(p.read_text(encoding="utf-8"))
    }


def test_the_guide_names_the_probes_that_raise_a_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-188: DEPLOYMENT §9.3 said only the ``sandbox`` probe raises a banner, while the shell
    raises the red stop-condition banner on every screen for the ``ledger`` probe. Every probe
    the UI reads by name is classified in ``BANNERS``, and the sentences of §9.3 that speak of
    a banner name exactly the probes classified as raising one."""
    served = set(_served(tmp_path, monkeypatch))
    readers = _ui_probe_readers()
    assert readers == set(BANNERS), (
        f"classify each UI reader of a probe in BANNERS: new {sorted(readers - set(BANNERS))}, "
        f"gone {sorted(set(BANNERS) - readers)}"
    )
    banner = {probe for (probe, _f), raises in BANNERS.items() if raises}
    assert banner <= served
    sentences = [s for s in re.split(r"(?<=[.;])\s+", _deployment_9_3()) if "banner" in s]
    named = {n for s in sentences for n in re.findall(r"`(\w+)`", s) if n in served}
    assert named == banner, (
        f"DEPLOYMENT §9.3 says {sorted(named)} raise a banner; the UI raises one for {sorted(banner)}"
    )


_COUNT = re.compile(r"\b(\d+|" + "|".join(WORDS.values()) + r")\s+probes\b", re.I)


def test_no_guide_states_another_count_of_health_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-126's first test read only DEPLOYMENT §9.3 and API.md's row, so §9's own opening
    line kept "seven probes" while ``/health`` served eleven (found when the claims gate
    widened to DEPLOYMENT, G-929; docs/PREVENTION.md P-238). Every "N probes" on the pages
    an operator reads the endpoint from must now state the served count."""
    served = len(_served(tmp_path, monkeypatch))
    wrong = []
    for rel in ("docs/DEPLOYMENT.md", "docs/API.md", "docs/ARCHITECTURE.md", "docs/OPERATOR.md"):
        for m in _COUNT.finditer((ROOT / rel).read_text(encoding="utf-8")):
            word = m.group(1).lower()
            n = int(word) if word.isdigit() else {v: k for k, v in WORDS.items()}.get(word)
            if n != served:
                wrong.append(f"{rel}: {m.group(0)!r}")
    assert not wrong, f"/health serves {served} probes; these say otherwise: {wrong}"
