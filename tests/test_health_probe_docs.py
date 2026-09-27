"""The guides name every probe ``/health`` serves, and say how many there are.

Navigation
----------
What it is:   A drift gate between the ``/health`` probe list and the two guides an operator
              reads it from: the ``GET /health`` row of docs/API.md and DEPLOYMENT §9.3.
What it does: Collects the probes the readiness route actually serves (every probe forced to
              fail, so the test needs no database, no docker daemon and no network) and
              refuses a guide that omits one by name or states the wrong count — DEPLOYMENT
              §9.3 said seven probes while ``/health`` served eleven, and API.md said ten and
              left out ``provision`` (G-403; docs/PREVENTION.md P-059).
How:          ``collect_health`` over a session factory that raises and probe functions that
              raise, as tests/test_server_system.py's fixed-detail test does; the names come
              from the body; each guide's section is cut from the Markdown and searched for
              every name in backticks and for the count written as a word.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/routes/system.py (collect_health, the probe list under test),
              docs/API.md (the /health row it reads), docs/DEPLOYMENT.md (§9.3 Health, which it
              reads), tests/test_server_system.py (pins the same names against the served
              body), docs/dod/journeys/operate.md (G-403, which this closes)
Tested by:    (this is a test file)
Touch when:   a probe is added to or removed from ``collect_health`` — name it in both guides
              and change the count there; this test tells you which guide is behind.
"""

from __future__ import annotations

import os
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
