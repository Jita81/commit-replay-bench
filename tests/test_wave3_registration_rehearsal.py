"""A dress rehearsal of the Wave 3 registration: its HTTP requests sent as the record words them.

docs/reviews/2026-10-09-wave-3-registration.md tells the operator, step by step, which requests
to send once the stack is restarted. Nothing in it has been run (every step reads "not yet
run"), and a request the product refuses would stop the campaign on the day. This file sends
those requests first, against the app in process, so a disagreement between the record and the
product is found before any spend. The bodies are read from the record at test time (its
``json`` blocks, the inline bodies of steps 6 and 9), with only the placeholders the record
itself marks (``<...>``) filled in, so the test fails when the record drifts.

Navigation
----------
What it is:   The executable rehearsal of the Wave 3 registration record's steps 4, 6, 7 and 9.
What it does: Step 4: logs in as an operator, registers the record's campaign (201, the line
              $54.00 of $108.00; the same name again 409 ``campaign_exists``) and the four
              readings from its body and its "the other bodies change only" sentence (201 each,
              the campaign named, the pool in seeded order, each cell's budget spent at 2.10% of
              5%), refuses a registration without its question (422) and meets the refusals the
              record names (``campaign_unknown``, ``pool_not_blind``, ``pool_seen``,
              ``budget_spent``, ``invalid_reading`` naming both executors on a host builder and
              the posture class with the sandbox off docker); with the loop's ``format_step``
              change in force and the repository's block silent, the record's body is refused
              409 ``reading_checks_overlay``, and registers on ``checks_arm`` ``off`` once the
              block sets the key (DL-410, RT2B-2); a retried registration is
              refused 409 ``reading_exists`` naming the first reading, which lists once; every
              reading registers under ``reserved.v1`` (``max_reruns`` 0, the ``default``
              budget profile, its pool pinned to its qualification records) — a bare body as
              the product's default, the record's body as written — and a body asking for the
              legacy rule or re-runs is refused 422 (P-792, DL-385).
              Step 6: queues ``S3`` from the remeasure plan, ``A0`` and ``A0+L`` from the
              record's bodies, each admitted under the campaign (``admitted_runs`` rising on
              every reading of it), then ``S1`` from the plan once ``S3`` delivers; meets 409
              ``campaign_ceiling``, ``campaign_required`` (also from the Learn queue),
              ``reading_posture_mismatch``, ``reading_unsealed`` and the other refusals the
              record lists, each with nothing queued; refuses part 2's body without
              ``reading_id`` 409 ``reading_required`` and queues one with neither id outside
              the campaign; checks that a reading counts only rows of runs its campaign
              admitted, each counted row reserved before its build and labelled with its
              ``reservation`` and ``treatment``, the treatment pinned once the repository's
              first run reserved (``pinned_treatment``). Step 7: reads the tally, and part 2's stop
              (``campaign_cost_unknown``, ``campaign_overrun``) in ``stopped``. Step 9: files
              the stage-2 release (the line $108.00) and resumes step 6 under it.
How:          ``make_env`` on the sealed settings with the record's test author; the
              repositories ``cobra`` and ``click``, their qualified tasks and each task's
              qualification record (``qualify_pool``) written to the store; every request
              through the in-process ``TestClient`` on the record's own paths. No worker runs:
              a finished run is the worker's status, its reservations (``reserve_for``, the
              worker's ``reading.reserved`` event) and its rows written to the store. The
              claude_code and editblock credential checks are stubbed to "present" — the
              stack's credential is the operator's, and the rehearsal never sets or reads a
              key. A disagreement found here is fixed in the record or the
              product before the run; a strict ``xfail`` marks one left open, its reason
              ``DOC-WRONG``, ``PRODUCT-WRONG`` or ``AMBIGUOUS``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md, docs/adr/0030-a-run-keeps-its-spend-cap.md
Works with:   docs/reviews/2026-10-09-wave-3-registration.md (the record rehearsed),
              src/crb/server/routes/campaigns.py (the campaign and its release),
              src/crb/server/routes/readings.py (the registration and ``GET /readings``),
              src/crb/server/routes/runs.py (``submit_refusals``, ``admit_under_campaign``),
              src/crb/server/routes/learn.py (the remeasure plan and its queue),
              src/crb/server/routes/repos.py (DL-410's config edit, ``PUT /repos/{name}``),
              tests/test_server_campaigns.py (the campaign routes' own suite),
              tests/test_server_readings.py (the readings routes' own suite)
Tested by:    this file
Touch when:   never for a new repository; when the Wave 3 registration record changes a
              request, a body or a success condition of steps 4, 6, 7 or 9, or the product
              changes what one of them answers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from crb.core.ledger import GradeRow
from crb.core.reading import READING_EVENT_ACTION, reading_cell_key, seeded_order
from crb.core.spec import TaskSpec
from crb.server.app import API_PREFIX
from crb.server.posture_view import deployment_posture_class
from crb.server.routes import runs as runs_routes
from crb.server.routes.learn import deployment_author_model
from crb.store.ledger import DbLedger
from crb.store.models import Event, Repo, Run, Task
from fixtures.readings import (
    SEALED_SETTINGS,
    format_step_in_force,
    qualify_pool,
    reserve_for,
    sealed_row,
)
from fixtures.server_seed import Env, envelope, login, make_env

RECORD = Path(__file__).resolve().parents[1] / "docs/reviews/2026-10-09-wave-3-registration.md"
#: Choice (a), step 2: the test author the deployment names, ``editblock:gpt-oss-120b`` on
#: Cerebras — ``CRB_FACTORY__TEST_AUTHOR`` on the stack.
TEST_AUTHOR = "editblock:gpt-oss-120b:cerebras"
#: Paul's form and number, fixed on 2026-10-12 (decision 10, Q-34): one hypothesis per cell,
#: naming the cell's repository and size, and one smallest effect on all four readings.
HYPOTHESIS_FORM = (
    "With the arm's treatment, the builder's blind patches on {repo} {size} commits pass the "
    "repository's own tests more often than A0's."
)
HYPOTHESIS = HYPOTHESIS_FORM.format(repo="cobra", size="XS")
SMALLEST_EFFECT = 0.2
#: Qualified ``bug.fix`` commits per cell: above the first look (20), as step 3 requires.
POOL = 24
#: A run's ``max_cost_usd`` in this rehearsal ("each run's max_cost_usd is set to fit").
CAP = 10.0
#: The repositories step 1 expects and their languages and runners.
REPOS = {"cobra": ("go", "go"), "click": ("python", "pytest")}


# --- the record, read at test time ------------------------------------------------------------


def _record() -> str:
    return RECORD.read_text(encoding="utf-8")


def _flat() -> str:
    """The record with every run of whitespace one space: a sentence wrapped over two lines
    still matches."""
    return re.sub(r"\s+", " ", _record())


def _json_block(key: str) -> str:
    """The raw text of the record's one ```json block that has ``key`` at its top level."""
    blocks = re.findall(r"```json\n(.*?)\n```", _record(), flags=re.DOTALL)
    found = [b for b in blocks if key in json.loads(b)]
    assert len(found) == 1, f"the record has {len(found)} json blocks with {key!r}"
    return found[0]


def _step(n: int) -> str:
    """Row ``n`` of the record's table of steps after the restart."""
    rows = [line for line in _record().splitlines() if line.startswith(f"| {n} | ")]
    assert len(rows) == 1, f"the record has {len(rows)} rows for step {n}"
    return rows[0]


def _fill(text: str, values: Mapping[str, str]) -> Any:
    """``text`` with each placeholder the record marks replaced by its value, as JSON. A
    placeholder this rehearsal does not know is left in and fails here: the record drifted."""
    for placeholder, value in values.items():
        assert placeholder in text, f"the record no longer has the placeholder {placeholder!r}"
        text = text.replace(placeholder, value)
    assert "<" not in text and "[the " not in text, f"an unknown placeholder is left: {text}"
    return json.loads(text)


def campaign_body() -> dict[str, Any]:
    """Part 2's campaign body — no placeholder."""
    return dict(json.loads(_json_block("ceiling_gbp")))


def registration_bodies(campaign_id: str, author: str) -> dict[tuple[str, str], dict[str, Any]]:
    """The four registration bodies: the record's cobra XS body, filled, and the three its
    "the other bodies change only" sentence derives — keyed ``(repo, size)``."""
    cobra_xs = _fill(
        _json_block("hierarchy"),
        {
            '"<the campaign, registered first at step 4>"': json.dumps(campaign_id),
            "<author>": author,
        },
    )
    assert cobra_xs["hypothesis"] == HYPOTHESIS
    assert cobra_xs["smallest_effect"] == SMALLEST_EFFECT
    sentence = (
        "The other bodies change only `repo`, `size`, `language` and the repository and size the "
        "`hypothesis` names: cobra S (`go`), click XS and click S (`python`)."
    )
    assert sentence in _flat()
    out = {("cobra", "XS"): cobra_xs}
    for repo, size, language in (
        ("cobra", "S", "go"),
        ("click", "XS", "python"),
        ("click", "S", "python"),
    ):
        out[(repo, size)] = {
            **cobra_xs,
            "repo": repo,
            "cell": {**cobra_xs["cell"], "size": size, "language": language},
            "hypothesis": HYPOTHESIS_FORM.format(repo=repo, size=size),
        }
    return out


def filing_fields(reading_id: str, campaign_id: str, cap: float) -> dict[str, Any]:
    """Step 6's three fields every body carries: ``reading_id``, ``campaign_id``, ``max_cost_usd``."""
    row = _step(6)
    head = row.split("**`S3`**")[0]
    frags = re.findall(r'`("(?:reading_id|campaign_id|max_cost_usd)": [^`]+)`', head)
    assert [f.split(":")[0] for f in frags] == ['"reading_id"', '"campaign_id"', '"max_cost_usd"']
    return dict(
        _fill(
            "{" + ", ".join(frags) + "}",
            {
                '"<the cell\'s reading>"': json.dumps(reading_id),
                '"<the campaign>"': json.dumps(campaign_id),
                "<cap>": json.dumps(cap),
            },
        )
    )


def plan_extra(arm: str) -> dict[str, Any]:
    """What step 6 adds to a plan request besides the three fields (``S3`` and ``S1``)."""
    part = _step(6).split(f"**`{arm}`**:")[1].split("**`")[0]
    (frag,) = re.findall(r'plus those three and `("budget_profile": "default")`', part)
    return dict(json.loads("{" + frag + "}"))


def a0_body(
    repo: str, pool: list[str], reading_id: str, campaign_id: str, cap: float
) -> dict[str, Any]:
    """Step 6's ``A0`` body, filled: ``task_ids`` the first 16 of the reading's pool."""
    (raw,) = re.findall(r"\*\*`A0`\*\*: `(\{.*?\})`", _step(6))
    first = re.search(r"\[the first (\d+) of the reading's pool\]", raw)
    assert first is not None
    n = int(first.group(1))
    return dict(
        _fill(
            raw,
            {
                '"<repo>"': json.dumps(repo),
                first.group(0): json.dumps(pool[:n]),
                '"<reading>"': json.dumps(reading_id),
                '"<campaign>"': json.dumps(campaign_id),
                "<cap>": json.dumps(cap),
            },
        )
    )


def a0l_body(a0: Mapping[str, Any]) -> dict[str, Any]:
    """``A0+L``: "the same with no `learning` and no `budget_profile`"."""
    assert "**`A0+L`**: the same with no `learning` and no `budget_profile`." in _step(6)
    return {k: v for k, v in a0.items() if k not in ("learning", "budget_profile")}


def release_body() -> dict[str, Any]:
    """Part 2's stage-2 release body, its decision filled."""
    (raw,) = re.findall(r'`(\{"released_gbp": \d+, "decision": "<[^`]+>"\})`', _flat())
    return dict(
        _fill(
            raw,
            {
                '"<the release\'s decision log id and words>"': json.dumps(
                    "DL-3xx: stage 2's £40 released"
                )
            },
        )
    )


# --- the world the restarted stack would have ----------------------------------------------


@dataclass
class Wave3:
    """The rehearsal's environment and what step 4 registered."""

    env: Env
    campaign: dict[str, Any] = field(default_factory=dict)
    readings: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    @property
    def cid(self) -> str:
        return str(self.campaign["campaign_id"])

    def send(self, method: str, path: str, **kw: Any) -> Any:
        """A request on the record's own path (``/api/v1/...``)."""
        assert path.startswith("/api/v1/"), path
        return self.env.client.request(method, path, **kw)


def _commit(repo: str, size: str, i: int) -> str:
    return hashlib.sha1(f"wave3-{repo}-{size}-{i}".encode()).hexdigest()


def add_repos_and_tasks(env: Env) -> None:
    """Step 1's repositories and step 3's outcome: ``POOL`` qualified ``bug.fix`` commits per
    cell, each its own change, in the repository's language — each with a ``qualified``
    record in one posture of the deployment's posture class for the repository, which a
    reserved.v1 pool is read from and pinned to (P-797)."""
    with env.factory() as s:
        for repo, (language, runner) in REPOS.items():
            s.add(
                Repo(
                    name=repo,
                    language=language,
                    runner=runner,
                    clone_path="",
                    url=f"https://example.invalid/{repo}.git",
                    config_json={"name": repo, "language": language, "runner": runner},
                    probe_status="ok",
                )
            )
            for size in ("XS", "S"):
                for i in range(POOL):
                    tid = _commit(repo, size, i)
                    spec = TaskSpec(
                        task_id=tid,
                        repo=repo,
                        subject=f"fix: {repo} {size} {i}",
                        authored="2026-08-01T12:00:00+00:00",
                        test_files=(f"t{i}_test.go",),
                        src_files=(f"s{i}.go",),
                        target_tests=(f"t{i}_test.go",),
                        belt_scope=("t",),
                        size=size,
                        src_churn=3,
                        capability_class="bug.fix",
                        language=language,
                        red_checked=True,
                        gold_clean=True,
                        labels={"change_id": f"change-{repo}-{size}-{i}"},
                    )
                    s.add(
                        Task(
                            repo=repo,
                            task_id=tid,
                            pool=spec.pool,
                            size=size,
                            capability_class="bug.fix",
                            language=language,
                            authored=spec.authored,
                            subject=spec.subject,
                            red_checked=True,
                            gold_clean=True,
                            spec_json=spec.to_dict(),
                        )
                    )
        s.commit()
        repos = {repo: s.get(Repo, repo) for repo in REPOS}
    for repo, row in repos.items():
        qualify_pool(
            env.factory,
            repo,
            [_commit(repo, size, i) for size in ("XS", "S") for i in range(POOL)],
            posture_class=deployment_posture_class(env.settings, row),
            posture_id="pst_" + hashlib.sha256(f"wave3-{repo}".encode()).hexdigest()[:24],
        )


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _credentials_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stack's builder and test-author credentials are the operator's: the rehearsal
    stubs their presence checks to "present" and never sets or reads a key."""
    for name in ("claude_code", "editblock"):
        monkeypatch.setitem(runs_routes.CREDENTIAL_CHECKS, name, lambda *_a, **_k: "")


def _env(tmp_path: Path, **settings: Any) -> Iterator[Env]:
    with make_env(tmp_path, role=None, **settings) as env:
        add_repos_and_tasks(env)
        # the record's session: POST /api/v1/auth/login, then X-CSRF-Token from crb_csrf
        assert API_PREFIX == "/api/v1"
        login(env.client, "operator")
        yield env


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Wave3]:
    """The restarted stack of step 0: sealed (sandbox and builder on docker), the record's
    test author; steps 1 to 3 done."""
    yield from (
        Wave3(env=e)
        for e in _env(tmp_path, **SEALED_SETTINGS, factory={"test_author": TEST_AUTHOR})
    )


def register_campaign_and_readings(w: Wave3) -> Wave3:
    """Step 4, the happy path: the campaign, then the four readings."""
    r = w.send("POST", "/api/v1/campaigns", json=campaign_body())
    assert r.status_code == 201, r.text
    w.campaign = r.json()
    author = deployment_author_model(w.env.settings)
    for key, body in registration_bodies(w.cid, author).items():
        r = w.send("POST", "/api/v1/readings", json=body)
        assert r.status_code == 201, (key, r.text)
        w.readings[key] = r.json()
    return w


@pytest.fixture
def wave3(stack: Wave3) -> Wave3:
    """The stack after step 4."""
    return register_campaign_and_readings(stack)


def _runs(env: Env) -> set[str]:
    with env.factory() as s:
        return {r.id for r in s.execute(select(Run)).scalars()}


def _registered(env: Env) -> int:
    with env.factory() as s:
        return int(
            s.execute(
                select(func.count()).select_from(Event).where(Event.action == READING_EVENT_ACTION)
            ).scalar_one()
        )


def _refused(r: Any, status: int, code: str) -> dict[str, Any]:
    assert r.status_code == status, r.text
    err = envelope(r)
    assert err["code"] == code, err
    return err


def _served_readings(w: Wave3, repo: str) -> dict[str, dict[str, Any]]:
    r = w.send("GET", "/api/v1/readings", params={"repo": repo})
    assert r.status_code == 200, r.text
    return {o["reading_id"]: o for o in r.json()["readings"]}


def _admitted_runs(w: Wave3) -> set[Any]:
    """``admitted_runs`` as every reading of the campaign serves it — one value, or the test
    sees the readings disagree."""
    return {o["admitted_runs"] for repo in REPOS for o in _served_readings(w, repo).values()}


def _plan_entry(w: Wave3, key: tuple[str, str]) -> dict[str, Any]:
    r = w.send("GET", "/api/v1/learn/remeasure", params={"repo": key[0]})
    assert r.status_code == 200, r.text
    rid = w.readings[key]["reading_id"]
    (entry,) = [c for c in r.json()["cells"] if c["reading_id"] == rid]
    return dict(entry)


def _s3_body(w: Wave3, key: tuple[str, str], cap: float = CAP) -> dict[str, Any]:
    """Step 6's ``S3``: the cell's plan request, plus the three fields and the profile."""
    entry = _plan_entry(w, key)
    assert entry["arm"] == "S3" and entry["next_act"] == "replay", entry
    (request,) = entry["requests"]
    return {
        **request,
        **filing_fields(w.readings[key]["reading_id"], w.cid, cap),
        **plan_extra("S3"),
    }


def _a0(w: Wave3, key: tuple[str, str], cap: float = CAP) -> dict[str, Any]:
    reading = w.readings[key]
    return a0_body(key[0], list(reading["pool"]), reading["reading_id"], w.cid, cap)


# --- step 4 -----------------------------------------------------------------------------------


def test_step4_registers_the_campaign_then_the_four_readings(stack: Wave3) -> None:
    """Step 4's success condition, request by request."""
    w = stack
    r = w.send("POST", "/api/v1/campaigns", json=campaign_body())
    assert r.status_code == 201, r.text
    w.campaign = r.json()
    assert re.fullmatch(r"cmp_[0-9a-f]{24}", w.cid)
    assert w.campaign["ceiling_usd"] == 108.0 and w.campaign["line_usd"] == 54.0
    again = w.send("POST", "/api/v1/campaigns", json=campaign_body())
    _refused(again, 409, "campaign_exists")

    author = deployment_author_model(w.env.settings)
    assert author == "gpt-oss-120b"  # step 2: not claude-sonnet-5
    for key, body in registration_bodies(w.cid, author).items():
        assert body["hierarchy"] == ["S3", f"S1@{author}"] and body["author_model"] == author
        r = w.send("POST", "/api/v1/readings", json=body)
        assert r.status_code == 201, (key, r.text)
        got = r.json()
        w.readings[key] = got
        assert re.fullmatch(r"rdg_[0-9a-f]{24}", got["reading_id"])
        assert got["campaign_id"] == w.cid
        expected = [_commit(key[0], key[1], i) for i in range(POOL)]
        assert got["pool"] == seeded_order(key[0], reading_cell_key(body["cell"]), expected)
        assert got["pool_sha256"] and got["pool_rule"]
    for repo in REPOS:
        r = w.send("GET", "/api/v1/readings", params={"repo": repo})
        assert r.status_code == 200, r.text
        served = r.json()
        ids = {o["reading_id"] for o in served["readings"]}
        assert ids == {w.readings[(repo, size)]["reading_id"] for size in ("XS", "S")}
        assert served["budget"] == 0.05
        # "its cell's budget spent at 2.10% of 5%"
        spent = sorted(f"{b['spent']:.2%}" for b in served["budgets"])
        assert spent == ["2.10%", "2.10%"] and {b["budget"] for b in served["budgets"]} == {0.05}


#: Item 2's run fields: what every registration through ``POST /readings`` reads under.
RESERVED_FIELDS = {"attempt_rule": "reserved.v1", "max_reruns": 0, "budget_profile": "default"}


def test_step4_every_reading_registers_under_reserved_v1(stack: Wave3) -> None:
    """Item 2's attempt rule (P-792): ``POST /readings`` registers every reading reserved.v1
    — a body that names no attempt rule as the product's default, and the record's body as
    written (part 5 names the three fields) — with ``max_reruns`` 0 on the ``default``
    budget profile, its pool pinned to the qualification records of the repository's
    posture. A body asking for the legacy rule or for re-runs is refused 422 with nothing
    registered: the legacy rule is no longer registered here."""
    w = stack
    cid = w.send("POST", "/api/v1/campaigns", json=campaign_body()).json()["campaign_id"]
    bodies = registration_bodies(cid, deployment_author_model(w.env.settings))
    bare = {k: v for k, v in bodies[("cobra", "XS")].items() if k not in RESERVED_FIELDS}
    posture = "pst_" + hashlib.sha256(b"wave3-cobra").hexdigest()[:24]

    def reserved_v1(body: dict[str, Any]) -> None:
        r = w.send("POST", "/api/v1/readings", json=body)
        assert r.status_code == 201, r.text
        reading = r.json()
        assert {k: reading.get(k) for k in RESERVED_FIELDS} == RESERVED_FIELDS, reading
        assert reading["pool_posture_id"] == posture, reading
        assert sorted(reading["pool_qualifications"]) == sorted(reading["pool"]), reading

    reserved_v1(bare)
    record = bodies[("cobra", "S")]
    assert {k: record.get(k) for k in RESERVED_FIELDS} == RESERVED_FIELDS, record
    reserved_v1(record)
    served = _served_readings(w, "cobra")
    assert {o["attempt_rule"] for o in served.values()} == {"reserved.v1"}, served
    asked = {
        **bodies[("click", "XS")],
        "hypothesis": HYPOTHESIS + ", on the legacy rule",
    }
    for change in (
        {"attempt_rule": ""},
        {"attempt_rule": "first_observed.v0"},
        {"max_reruns": 2},
        {"max_reruns": None},
    ):
        _refused(
            w.send("POST", "/api/v1/readings", json={**asked, **change}), 422, "validation_error"
        )
    assert _registered(w.env) == 2


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"drop": "hypothesis"}, id="no-hypothesis"),
        pytest.param({"drop": "smallest_effect"}, id="no-smallest-effect"),
        pytest.param({"hypothesis": "   "}, id="blank-hypothesis"),
        pytest.param({"hypothesis": "h" * 2001}, id="hypothesis-over-2000"),
        pytest.param({"smallest_effect": 0}, id="effect-zero"),
        pytest.param({"smallest_effect": 1.5}, id="effect-above-one"),
    ],
)
def test_step4_a_registration_without_its_question_is_refused_422(
    stack: Wave3, change: dict[str, Any]
) -> None:
    """Part 5 makes ``hypothesis`` (1 to 2,000 characters) and ``smallest_effect`` required:
    a body without either, or outside its range, is refused 422 with nothing registered."""
    w = stack
    cid = w.send("POST", "/api/v1/campaigns", json=campaign_body()).json()["campaign_id"]
    body = registration_bodies(cid, deployment_author_model(w.env.settings))[("cobra", "XS")]
    drop = change.pop("drop", None)
    body = {k: v for k, v in {**body, **change}.items() if k != drop}
    r = w.send("POST", "/api/v1/readings", json=body)
    _refused(r, 422, "validation_error")
    assert _registered(w.env) == 0


def test_step4_meets_the_refusals_the_record_names(stack: Wave3) -> None:
    """``campaign_unknown``, ``pool_not_blind``, ``pool_seen`` and ``budget_spent``, each
    with nothing registered."""
    w = stack
    cid = w.send("POST", "/api/v1/campaigns", json=campaign_body()).json()["campaign_id"]
    bodies = registration_bodies(cid, deployment_author_model(w.env.settings))
    body = bodies[("cobra", "XS")]
    _refused(
        w.send("POST", "/api/v1/readings", json={**body, "campaign_id": "cmp_" + "0" * 24}),
        404,
        "campaign_unknown",
    )
    picked = [_commit("cobra", "XS", i) for i in range(20)]
    _refused(
        w.send("POST", "/api/v1/readings", json={**body, "pool": picked}), 422, "pool_not_blind"
    )
    seen = _commit("click", "XS", 3)
    click_xs = bodies[("click", "XS")]
    DbLedger(w.env.factory).append(
        sealed_row(seen, repo="click", arm="S3", cell=click_xs["cell"], run_id="before")
    )
    err = _refused(w.send("POST", "/api/v1/readings", json=click_xs), 409, "pool_seen")
    assert err["detail"]["commits"] == [seen]
    assert _registered(w.env) == 0
    # a cell's 5% holds two look.v1 readings (2.10% each), not three
    other = {**body, "hypothesis": HYPOTHESIS + ", a second question"}
    for b in (body, other):
        assert w.send("POST", "/api/v1/readings", json=b).status_code == 201
    third = {**body, "hypothesis": HYPOTHESIS + ", a third question"}
    _refused(w.send("POST", "/api/v1/readings", json=third), 409, "budget_spent")
    assert _registered(w.env) == 2


def test_step4_a_retried_registration_is_the_same_reading_once(stack: Wave3) -> None:
    """Step 4's "budget spent at 2.10% of 5%" rests on each reading registered once: the same
    body sent again (a retried request) is refused 409 ``reading_exists`` naming the first
    reading, as the record says, and writes nothing — ``GET /readings`` reads it back."""
    w = stack
    cid = w.send("POST", "/api/v1/campaigns", json=campaign_body()).json()["campaign_id"]
    body = registration_bodies(cid, deployment_author_model(w.env.settings))[("cobra", "XS")]
    first = w.send("POST", "/api/v1/readings", json=body)
    assert first.status_code == 201, first.text
    retry = w.send("POST", "/api/v1/readings", json=body)  # the retry
    err = _refused(retry, 409, "reading_exists")
    assert err["detail"]["reading_id"] == first.json()["reading_id"], err
    assert _registered(w.env) == 1
    served = w.send("GET", "/api/v1/readings", params={"repo": "cobra"}).json()
    assert [o["reading_id"] for o in served["readings"]] == [first.json()["reading_id"]]
    (cell,) = [b for b in served["budgets"] if b["cell"]["size"] == "XS"]
    assert f"{cell['spent']:.2%}" == "2.10%" and cell["readings"] == 1
    assert "`reading_exists`" in _step(4)


def test_step4_a_reading_is_never_frozen_through_the_loops_overlay(stack: Wave3) -> None:
    """Step 4's precondition (DL-410, RT2B-2): while the loop's ``format_step`` change is in
    force on cobra and cobra's own ``checks`` block is silent on the key, the record's body is
    refused 409 ``reading_checks_overlay`` naming both arms, with nothing written; once the
    block sets ``format_step: false`` (``PUT /api/v1/repos/cobra``, DL-410's config edit) the
    same body registers, and its ``checks_arm`` reads ``off``, as the record requires."""
    w = stack
    cid = w.send("POST", "/api/v1/campaigns", json=campaign_body()).json()["campaign_id"]
    body = registration_bodies(cid, deployment_author_model(w.env.settings))[("cobra", "XS")]
    format_step_in_force(w.env.factory, "cobra")
    err = _refused(w.send("POST", "/api/v1/readings", json=body), 409, "reading_checks_overlay")
    assert err["detail"] == {"overlay_arm": "fmt", "repo_arm": "off"}, err
    assert _registered(w.env) == 0
    assert "`reading_checks_overlay`" in _step(4)
    assert "`format_step: false`" in _step(4)
    r = w.send("PUT", "/api/v1/repos/cobra", json={"checks": {"format_step": False}})
    assert r.status_code == 200, r.text
    r = w.send("POST", "/api/v1/readings", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["checks_arm"] == "off", r.json()
    assert "`checks_arm` reads `off`" in _step(4)
    assert _registered(w.env) == 1


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param({"sandbox": {"executor": "docker"}}, id="builder-on-the-host"),
        pytest.param(
            {"builder": {"executor": "docker", "image": "crb-builder:test"}}, id="sandbox-local"
        ),
    ],
)
def test_step4_an_unsealed_deployment_is_refused_naming_what_is_unsealed(
    tmp_path: Path, settings: dict[str, Any]
) -> None:
    """Step 4's two unsealed cases, as the record words them: a docker sandbox with a host
    builder is refused naming both executors; with the sandbox off docker the posture-class
    refusal fires first and names the posture class alone."""
    for env in _env(tmp_path, **settings, factory={"test_author": TEST_AUTHOR}):
        w = Wave3(env=env)
        cid = w.send("POST", "/api/v1/campaigns", json=campaign_body()).json()["campaign_id"]
        body = registration_bodies(cid, deployment_author_model(env.settings))[("cobra", "XS")]
        err = _refused(w.send("POST", "/api/v1/readings", json=body), 422, "invalid_reading")
        assert _registered(env) == 0
        detail = set(err["detail"])
        if "sandbox" in settings:  # the sandbox on docker, the builder on the host
            assert {"sandbox_executor", "builder_executor"} <= detail, err
            assert "`{sandbox_executor, builder_executor}`" in _step(4)
        else:  # the sandbox off docker: the posture class is not a sealed one
            assert "posture_class" in detail, err
            assert not detail & {"sandbox_executor", "builder_executor"}, err
            assert "`{posture_class}`" in _step(4)


# --- step 6 -----------------------------------------------------------------------------------


def test_step6_queues_s3_a0_and_a0l_under_the_campaign_until_the_line(wave3: Wave3) -> None:
    """Each body as the record words it is admitted (201), ``admitted_runs`` rises by one on
    every reading of the campaign, the campaign lists the run; the next run that does not fit
    under the $54.00 line is refused 409 ``campaign_ceiling`` with nothing queued."""
    w = wave3
    key = ("cobra", "XS")
    assert _admitted_runs(w) == {0}
    s3 = _s3_body(w, key)
    assert s3["kind"] == "replay" and s3["learning"] == "off" and s3["budget_profile"] == "default"
    a0 = _a0(w, key)
    assert len(a0["task_ids"]) == dict(w.readings[key]["descriptive"])["A0"]
    queued: list[str] = []
    for body in (s3, a0, a0l_body(a0)):
        r = w.send("POST", "/api/v1/runs", json=body)
        assert r.status_code == 201, r.text
        queued.append(r.json()["id"])
        assert _admitted_runs(w) == {len(queued)}
        view = w.send("GET", f"/api/v1/campaigns/{w.cid}").json()
        assert [x["run_id"] for x in view["runs"]] == queued
    with w.env.factory() as s:
        params = [dict(s.get(Run, rid).params_json) for rid in queued]  # type: ignore[union-attr]
    assert [p.get("learning") for p in params] == ["off", "off", None]
    assert all(p["reading_id"] == w.readings[key]["reading_id"] for p in params)
    # three runs at $10 with $5.00 headroom each hold $45 of $54: the next does not fit
    before = _runs(w.env)
    err = _refused(
        w.send("POST", "/api/v1/runs", json=_s3_body(w, ("cobra", "S"))), 409, "campaign_ceiling"
    )
    assert "nothing was queued" in err["message"]
    assert _runs(w.env) == before and _admitted_runs(w) == {3}


def test_step6_meets_the_refusals_the_record_lists_with_nothing_queued(wave3: Wave3) -> None:
    w = wave3
    key = ("cobra", "XS")
    reading = w.readings[key]
    a0 = _a0(w, key)
    before = _runs(w.env)
    # "a body without campaign_id is refused 409 campaign_required when it carries reading_id"
    no_campaign = {k: v for k, v in a0.items() if k != "campaign_id"}
    err = _refused(w.send("POST", "/api/v1/runs", json=no_campaign), 409, "campaign_required")
    assert err["detail"] == {"reading_id": reading["reading_id"], "campaign_id": w.cid}
    no_cap = {k: v for k, v in a0.items() if k != "max_cost_usd"}
    _refused(w.send("POST", "/api/v1/runs", json=no_cap), 422, "campaign_cap_required")
    unknown = {**a0, "campaign_id": "cmp_" + "0" * 24}
    _refused(w.send("POST", "/api/v1/runs", json=unknown), 404, "campaign_unknown")
    stranger = {**a0, "reading_id": "rdg_" + "0" * 24}
    _refused(w.send("POST", "/api/v1/runs", json=stranger), 422, "reading_unknown")
    host = {**a0, "executor": "local"}
    _refused(w.send("POST", "/api/v1/runs", json=host), 409, "reading_unsealed")
    # the repository's sandbox_tree moved after the registration (DL-383)
    with w.env.factory() as s:
        repo = s.get(Repo, "cobra")
        assert repo is not None
        repo.config_json = {**dict(repo.config_json or {}), "sandbox_tree": "worktree"}
        s.commit()
    err = _refused(w.send("POST", "/api/v1/runs", json=a0), 409, "reading_posture_mismatch")
    assert err["detail"]["reading_posture_class"] == reading["posture_class"]
    assert err["detail"]["run_posture_class"] == "docker/worktree/sealed"
    with w.env.factory() as s:
        repo = s.get(Repo, "cobra")
        assert repo is not None
        repo.config_json = {
            k: v for k, v in dict(repo.config_json or {}).items() if k != "sandbox_tree"
        }
        s.commit()
    # the Learn queue files no run under a campaign: refused for these readings
    entry = _plan_entry(w, key)
    r = w.send(
        "POST",
        "/api/v1/learn/remeasure/queue",
        params={"repo": "cobra"},
        json={"cell": entry["label"], "mode": entry["mode"]},
    )
    _refused(r, 409, "campaign_required")
    assert _runs(w.env) == before and _admitted_runs(w) == {0}


def test_step6_refuses_an_a0l_body_on_a_subset_or_in_another_order(wave3: Wave3) -> None:
    """NEW-1 (round 5): ``POST /runs`` admitted an ``A0+L`` body whose ``task_ids`` were any
    subset of the cell's first 16, in any order — with ``A0``'s outcomes served, ``A0+L`` could
    be filed on ``A0``'s misses alone, and the loop pair read without ``A0``'s clean commits.
    Step 6 now words the rule and the product refuses the body 422 ``reading_run_fields`` on
    ``task_ids`` with nothing queued; the record's own body is admitted."""
    w = wave3
    key = ("cobra", "XS")
    a0 = _a0(w, key, cap=1.0)
    assert w.send("POST", "/api/v1/runs", json=a0).status_code == 201
    first = a0["task_ids"]
    before = _runs(w.env)
    for tasks in ([first[9], first[4], first[1]], first[::-1], first[1:]):
        body = {**a0l_body(a0), "task_ids": tasks}
        err = _refused(w.send("POST", "/api/v1/runs", json=body), 422, "reading_run_fields")
        assert (err["detail"]["fields"], err["detail"]["arm"]) == (["task_ids"], "A0+L"), err
        assert "seeded order" in err["detail"]["reasons"]["task_ids"]
    assert _runs(w.env) == before and _admitted_runs(w) == {1}
    assert "`A0+L` files its `task_ids` in the seeded order" in _flat()
    r = w.send("POST", "/api/v1/runs", json=a0l_body(a0))
    assert r.status_code == 201, r.text


def test_step6_a_body_without_reading_id_and_one_with_neither(wave3: Wave3) -> None:
    """Part 2: a run posted with the campaign's ``campaign_id`` but no ``reading_id`` is
    refused 409 ``reading_required`` — the campaign holds reserved.v1 readings on that
    repository (P-792 C19), so a run under it names its reading — with nothing queued; a run
    of a pool commit posted with neither is queued outside it — not listed, not admitted,
    under its own cap."""
    w = wave3
    key = ("cobra", "XS")
    a0 = _a0(w, key)
    no_reading = {k: v for k, v in a0.items() if k != "reading_id"}
    before = _runs(w.env)
    err = _refused(w.send("POST", "/api/v1/runs", json=no_reading), 409, "reading_required")
    held = sorted(w.readings[("cobra", size)]["reading_id"] for size in ("XS", "S"))
    assert err["detail"] == {"campaign_id": w.cid, "reading_ids": held}, err
    assert _runs(w.env) == before and _admitted_runs(w) == {0}
    assert "is refused 409 `reading_required` when the campaign holds a reserved.v1 reading" in (
        _flat()
    )
    neither = {k: v for k, v in no_reading.items() if k != "campaign_id"}
    outside = w.send("POST", "/api/v1/runs", json=neither)
    assert outside.status_code == 201, outside.text
    view = w.send("GET", f"/api/v1/campaigns/{w.cid}").json()
    assert view["runs"] == []
    assert _admitted_runs(w) == {0}


def _grade(
    w: Wave3,
    key: tuple[str, str],
    commits: list[str],
    run_id: str,
    *,
    cost_usd: float = 0.25,
    cost_known: str = "true",
    reserved: bool = True,
) -> None:
    """The worker's attempts: each commit reserved on ``S3`` of the cell's reserved.v1
    reading for ``run_id`` before its build (``reserve_for``, the worker's
    ``reading.reserved``, P-792), then graded clean under ``S3`` by ``run_id`` in the
    reading's posture at ``cost_usd`` an attempt (default $0.25), its row labelled with the
    reservation, the treatment and the claim. ``reserved=False``: rows no reservation names
    — a run's the campaign never admitted, which the worker would never reserve."""
    reading = w.readings[key]
    ledger = DbLedger(w.env.factory)
    for commit in commits:
        labels = {"cost_known": cost_known}
        if reserved:
            labels |= reserve_for(
                w.env.factory,
                reading_id=reading["reading_id"],
                arm="S3",
                task_id=commit,
                run_id=run_id,
                repo=key[0],
                campaign_id=w.cid,
            )
        ledger.append(
            sealed_row(
                commit,
                repo=key[0],
                run_id=run_id,
                arm="S3",
                cell=reading["cell"],
                created="2099-01-01T00:00:00+00:00",
                posture_class=reading["posture_class"],
                cost_usd=cost_usd,
                labels=labels,
            )
        )


def _settle(w: Wave3, run_id: str) -> None:
    """The worker's last word on ``run_id``: ``succeeded``."""
    with w.env.factory() as s:
        run = s.get(Run, run_id)
        assert run is not None
        run.status = "succeeded"
        s.commit()


def _counted(w: Wave3, key: tuple[str, str], arm: str) -> list[str]:
    """``GET /readings``: the commits the reading counts under ``arm``."""
    served = _served_readings(w, key[0])[w.readings[key]["reading_id"]]
    (got,) = [a for a in served["arms"] if a["arm"] == arm]
    return list(got["counted_commits"])


def _deliver_s3(w: Wave3, key: tuple[str, str]) -> str:
    """Queue the cell's ``S3`` run and play the worker: every commit the plan asked for
    reserved and graded clean, the run ``succeeded``."""
    body = _s3_body(w, key)
    r = w.send("POST", "/api/v1/runs", json=body)
    assert r.status_code == 201, r.text
    run_id = str(r.json()["id"])
    _grade(w, key, list(body["task_ids"]), run_id)
    _settle(w, run_id)
    return run_id


def _counted_rows(w: Wave3, key: tuple[str, str], arm: str) -> list[GradeRow]:
    """The rows ``GET /readings`` counts under ``arm``: each counted commit's row, by the
    ``row_hash`` the reading serves for it."""
    served = _served_readings(w, key[0])[w.readings[key]["reading_id"]]
    (got,) = [a for a in served["arms"] if a["arm"] == arm]
    hashes = {c["row_hash"] for c in got["commits"] if c["commit"] in got["counted_commits"]}
    rows = [r for r in DbLedger(w.env.factory).rows(repo=key[0]) if r.row_hash in hashes]
    assert len(rows) == len(got["counted_commits"]), (hashes, got)
    return rows


def test_step6_a_reading_counts_only_rows_of_runs_its_campaign_admitted(wave3: Wave3) -> None:
    """Step 6: "only rows of runs the campaign admitted count" — the admitted ``S3`` run's
    reserved rows are counted under ``S3``, each carrying its ``reservation`` and
    ``treatment`` labels; a row of a run the campaign never admitted carries no reservation
    and is not. ``pinned_treatment`` is served once the repository's first run reserved."""
    w = wave3
    key = ("cobra", "XS")
    rid = w.readings[key]["reading_id"]
    assert _served_readings(w, "cobra")[rid]["pinned_treatment"] is None
    body = _s3_body(w, key)
    r = w.send("POST", "/api/v1/runs", json=body)
    assert r.status_code == 201, r.text
    asked = list(body["task_ids"])
    _grade(w, key, asked[:19], str(r.json()["id"]))
    _settle(w, str(r.json()["id"]))
    _grade(w, key, asked[19:], "a-run-outside-the-campaign", reserved=False)
    assert _counted(w, key, "S3") == asked[:19]
    rows = _counted_rows(w, key, "S3")
    assert all(row.labels.get("reservation") and row.labels.get("treatment") for row in rows)
    cobra = _served_readings(w, "cobra")
    served = cobra[rid]
    assert served["attempt_rule"] == "reserved.v1" and "p792" not in served, served
    assert served["reserved"]["S3"] == 19 and served["settled_unrowed"]["S3"] == 0, served
    pinned = served["pinned_treatment"]
    assert pinned["deployment"]["digest"] and set(pinned["arms"]) == {"S3"}, pinned
    # the campaign's first reservation on cobra pins its other reading's deployment half too;
    # click has had no run, so nothing is pinned there yet
    other = cobra[w.readings[("cobra", "S")]["reading_id"]]["pinned_treatment"]
    assert other == {"deployment": pinned["deployment"], "arms": {}}, other
    assert {o["pinned_treatment"] for o in _served_readings(w, "click").values()} == {None}
    assert {row.labels["treatment"] for row in rows} == {
        hashlib.sha256(
            f"{pinned['deployment']['digest']}|{pinned['arms']['S3']['digest']}".encode()
        ).hexdigest()
    }
    flat = _flat()
    for clause in (
        "each counted row carries `reservation` and `treatment` labels",
        "`pinned_treatment` is served after the first run on each repository",
    ):
        assert clause in flat, clause


def test_step6_s1_is_queued_from_the_plan_once_s3_delivers(wave3: Wave3) -> None:
    """Step 6, "S1: its request from the remeasure plan once S3 delivers, with its task_ids or
    limit, plus those three and "budget_profile": "default"" — admitted; without its count
    it is refused 422 ``campaign_s1_unbounded``."""
    w = wave3
    key = ("cobra", "XS")
    _deliver_s3(w, key)
    assert len(_counted(w, key, "S3")) == 20
    entry = _plan_entry(w, key)
    author = deployment_author_model(w.env.settings)
    assert entry["arm"] == f"S1@{author}" and entry["next_act"] == "replay", entry
    (request,) = entry["requests"]
    assert request["arm"] == "S1" and request["kind"] == "blind"
    assert request["task_ids"] and request["limit"] == len(request["task_ids"])
    s1 = {
        **request,
        **filing_fields(w.readings[key]["reading_id"], w.cid, CAP),
        **plan_extra("S1"),
    }
    before = _runs(w.env)
    unbounded = {k: v for k, v in s1.items() if k not in ("task_ids", "limit")}
    _refused(w.send("POST", "/api/v1/runs", json=unbounded), 422, "campaign_s1_unbounded")
    assert _runs(w.env) == before
    r = w.send("POST", "/api/v1/runs", json=s1)
    assert r.status_code == 201, r.text
    assert _admitted_runs(w) == {2}
    view = w.send("GET", f"/api/v1/campaigns/{w.cid}").json()
    assert r.json()["id"] in [x["run_id"] for x in view["runs"]]


# --- step 7 -----------------------------------------------------------------------------------


def test_step7_the_tally_serves_its_fields_and_stays_under_the_line(wave3: Wave3) -> None:
    w = wave3
    key = ("cobra", "XS")
    s3 = _deliver_s3(w, key)
    r = w.send("POST", "/api/v1/runs", json=_a0(w, key))
    assert r.status_code == 201, r.text
    # "GET /api/v1/runs/{id} ... only to place a figure against a run"
    run = w.send("GET", f"/api/v1/runs/{s3}")
    assert run.status_code == 200 and "cost_usd" in run.json(), run.text
    named = re.search(r"`GET /api/v1/campaigns/\{id\}` \(([^)]*)\)", _step(7))
    assert named is not None
    fields = re.findall(r"`(\w+)`", named.group(1))
    assert fields == ["spent_usd", "authoring_usd", "held_usd", "left_usd", "stopped"]
    view = w.send("GET", f"/api/v1/campaigns/{w.cid}")
    assert view.status_code == 200, view.text
    tally = view.json()
    assert set(fields) <= set(tally)
    # "stopped is empty, and spent and held stay at or under the stage's line" — the product
    # serves an empty ``stopped`` as null
    assert tally["stopped"] is None
    assert tally["spent_usd"] == pytest.approx(0.25 * 20)
    assert tally["spent_usd"] + tally["held_usd"] <= tally["line_usd"] == 54.0


@pytest.mark.parametrize(
    ("cost_usd", "cost_known", "code"),
    [
        pytest.param(0.25, "false", "campaign_cost_unknown", id="a-cost-not-known"),
        pytest.param(1.0, "true", "campaign_overrun", id="past-cap-plus-headroom"),
    ],
)
def test_step7_part_2s_stop_shows_in_stopped_and_refuses_every_new_run(
    wave3: Wave3, cost_usd: float, cost_known: str, code: str
) -> None:
    """Step 7, "otherwise part 2's stop": a run whose cost is not known (409
    ``campaign_cost_unknown``) or that spent past its cap plus its headroom — 20 attempts at
    $1.00 against $10.00 + $5.00 — (409 ``campaign_overrun``) stops the campaign; the tally
    names it in ``stopped`` and every new run is refused with nothing queued."""
    w = wave3
    key = ("cobra", "XS")
    body = _s3_body(w, key)
    r = w.send("POST", "/api/v1/runs", json=body)
    assert r.status_code == 201, r.text
    run_id = str(r.json()["id"])
    _grade(w, key, list(body["task_ids"]), run_id, cost_usd=cost_usd, cost_known=cost_known)
    stopped = w.send("GET", f"/api/v1/campaigns/{w.cid}").json()["stopped"]
    assert stopped and stopped["code"] == code and stopped["run_ids"] == [run_id], stopped
    before = _runs(w.env)
    _refused(w.send("POST", "/api/v1/runs", json=_a0(w, key, cap=1.0)), 409, code)
    assert _runs(w.env) == before


# --- step 9 -----------------------------------------------------------------------------------


def test_step9_the_release_raises_the_line_and_step6_resumes_under_it(wave3: Wave3) -> None:
    w = wave3
    key = ("cobra", "XS")
    a0 = _a0(w, key)
    for body in (_s3_body(w, key), a0, a0l_body(a0)):
        assert w.send("POST", "/api/v1/runs", json=body).status_code == 201
    waiting = _s3_body(w, ("cobra", "S"))
    _refused(w.send("POST", "/api/v1/runs", json=waiting), 409, "campaign_ceiling")
    body = release_body()
    assert body["released_gbp"] == 80
    r = w.send("POST", f"/api/v1/campaigns/{w.cid}/release", json=body)
    assert r.status_code == 200, r.text  # the record names no code; the product answers 200
    assert r.json()["line_usd"] == 108.0
    got = w.send("GET", f"/api/v1/campaigns/{w.cid}").json()
    assert got["line_usd"] == 108.0 and [x["released_gbp"] for x in got["releases"]] == [80]
    # "never passes the ceiling (409 campaign_release_invalid)"
    past = {**body, "released_gbp": 81}
    _refused(
        w.send("POST", f"/api/v1/campaigns/{w.cid}/release", json=past),
        409,
        "campaign_release_invalid",
    )
    # step 6 resumes with the line at $108.00: the run that did not fit now does
    r = w.send("POST", "/api/v1/runs", json=waiting)
    assert r.status_code == 201, r.text
    assert _admitted_runs(w) == {4}
