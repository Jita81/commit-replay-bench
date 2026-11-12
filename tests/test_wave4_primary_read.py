"""scripts/wave4_primary_read.py — Wave 4's order check and primary read, on made-up waves.

Navigation
----------
What it is:   The suite for the one script that reads Wave 4's primary result. Every run id,
              row, event, campaign record and poster file here is invented; none is read from
              a real run, and no request leaves the process.
What it does: Pins a full passing made-up wave (2 repositories x 6 batches x 4 places plus the
              set-aside first filing of click batch 3) with a result computed by hand; one
              failing case for each order-check part (a)-(i) and T1-T7; that counts and errors
              of the records never reach the order-check output; that a provider-test stop
              prints counts and no run id; the sign-flip p-value and the t interval against
              hand values; the 0.05 boundary (m = 204 below, m = 205 not); the decision word
              on both sides of each threshold; R12's usable-test rule and the author-hit
              sensitivity results; and that the script holds no path to the poster's folder
              and makes no request except through the injected getter.
How:          The script loaded by path; a ``World`` builds the poster files, run records,
              campaign, events and rows; ``main`` runs with an injected file reader, getter,
              deviation writer and recorded constants.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/wave4_primary_read.py (under test),
              docs/reviews/2026-11-10-wave-4-registration.md (the lists and orders it checks),
              docs/reviews/2026-11-10-wave-4-registration/r5-arm-source-ruling-v2.txt (T1-T7)
Tested by:    tests/test_wave4_primary_read.py
Touch when:   never for a new repository; the read script or Wave 4's registered rules change.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import http.client
import importlib.util
import io
import json
import math
import re
import socket
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from itertools import product
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "wave4_primary_read.py"
REG = ROOT / "docs" / "reviews" / "2026-11-10-wave-4-registration.md"
RUL = ROOT / "docs" / "reviews" / "2026-11-10-wave-4-registration" / "r5-arm-source-ruling-v2.txt"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wave4_primary_read", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wave4_primary_read"] = mod
    spec.loader.exec_module(mod)
    return mod


W = _load()

POSTER = "/fixture/poster"
LOGIN = "/fixture/login.json"
DEV = "/fixture/deviation.txt"
OUTF = "/fixture/output.txt"
API = "http://fixture.invalid"
ARGV = [
    "--poster-dir", POSTER, "--login", LOGIN, "--api", API,
    "--campaign", W.CAMPAIGN_ID, "--deviation-out", DEV, "--output", OUTF,
]  # fmt: skip
NAMES = {
    "plan": "wave-batches.json",
    "pre_s3": "wave-batches.before-s3.json",
    "click_out": "click-out.json",
    "cobra_out": "cobra-out.json",
}
PASSWORD = "fixture-secret-pw"
LEAKS = ("987654", "LEAK-", PASSWORD)
BASE = datetime(2030, 1, 1, tzinfo=UTC)
AUTHORING = "authoring: the authored test is not RED at the parent"


def fid(tag: str) -> str:
    return hashlib.sha256(f"fixture|{tag}".encode()).hexdigest()[:32]


def iso(t: datetime) -> str:
    return t.isoformat()


def plain_keys() -> list[tuple[str, int, int]]:
    return [(r, b, p) for r, b in W.BATCH_KEYS for p in range(1, 5)]


def standing_id(repo: str, b: int, p: int) -> str:
    if (repo, b) == ("click", 3):
        return W.SHORT_CLICK3[p - 1] + fid(f"click-3/{p}")[8:]
    return fid(f"{repo}-{b}/{p}")


ID98 = W.SHORT_FIRST_FILING + fid("first-filing")[8:]
EXTRA_UNLISTED = fid("extra-blind-unlisted")
EXTRA_SIGHTED = fid("extra-sighted-listed")
UNLISTED_COMMITS = [hashlib.sha1(f"unlisted{i}".encode()).hexdigest() for i in range(5)]


def d_pattern(b: int) -> tuple[int, ...]:
    """U_b = 2 for batches 1/3/5 and 4 for 2/4/6 (the hand-computed pass wave)."""
    return (1, 1, 0, 0, 0) if b % 2 == 1 else (2, 1, 1, 0, 0)


def run_doc(rid: str, repo: str, tasks: list[str], created: datetime, *, status: str = "succeeded",
            rows: int = 5, kind: str = "blind") -> dict[str, Any]:  # fmt: skip
    return {
        "id": rid, "repo": repo, "kind": kind, "status": status, "mode": "blind",
        "builder": "editblock", "model": "fixture-model", "provider": "fixture-provider",
        "ladder": "LEAK-LADDER", "budget": {"max_turns": 50, "max_seconds": 900},
        "max_cost_usd": 6, "task_ids": list(tasks), "builder_config": {"temperature": 0},
        "retain": {"worktrees": False, "transcripts": True}, "created": iso(created),
        "started": iso(created), "finished": iso(created + timedelta(minutes=30)),
        "error": "LEAK-RUN-ERROR", "cost_usd": 0.765432,
        "counts": {"rows": rows, "clean": 987654, "errors": 987654},
    }  # fmt: skip


def body_doc(repo: str, tasks: list[str], arm: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "repo": repo, "kind": "blind", "task_ids": list(tasks), "builder": "editblock",
        "model": "fixture-model", "provider": "fixture-provider", "max_cost_usd": 6.0,
        "budget": {"max_turns": 50, "max_seconds": 900, "max_tokens": None},
        "builder_config": {"temperature": 0}, "retain": {"transcripts": True},
        "campaign_id": W.CAMPAIGN_ID, "env_stop": 2, "outage_stop": 3, "learning": None,
    }  # fmt: skip
    if arm == "S1":
        body |= {"arm": "S1", "test_author": W.L_VALUE}
    return body


class FakeOutput(io.StringIO):
    """The ``--output`` file: records each write and whether a flush followed it."""

    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.flushed_at: list[int] = []  # len(text) at each flush
        self.closed_text: str | None = None

    def write(self, text: str) -> int:
        self.text += text
        return len(text)

    def flush(self) -> None:
        self.flushed_at.append(len(self.text))

    def close(self) -> None:
        self.closed_text = self.text
        super().close()


@dataclass
class World:
    """A made-up Wave 4: poster files, run records, campaign, events and rows."""

    ids: dict[str, str] = field(default_factory=dict)  # plain key -> run id
    arm: dict[str, str] = field(default_factory=dict)  # run id -> arm (fixture truth)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    pre: dict[str, Any] = field(default_factory=dict)
    outs: dict[str, dict[str, Any]] = field(default_factory=dict)
    campaign: dict[str, Any] = field(default_factory=dict)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    grades: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    raw: dict[str, bytes] = field(default_factory=dict)  # replaces a file before hashing
    tamper: dict[str, bytes] = field(default_factory=dict)  # replaces a file after hashing
    fail: dict[str, int] = field(default_factory=dict)  # path -> status to answer
    place_rule: str = "slot"
    login: bytes = json.dumps({"username": "fixture-user", "password": PASSWORD}).encode()
    calls: list[tuple[str, tuple[tuple[str, str], ...]]] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    deviation: list[tuple[str, str]] = field(default_factory=list)
    outputs: dict[str, FakeOutput] = field(default_factory=dict)
    output_error: OSError | None = None

    # --- helpers for the tests ---
    def key_id(self, repo: str, b: int, p: int) -> str:
        return self.ids[f"{repo}-{b}/{p}"]

    def s1_of(self, repo: str, b: int) -> list[str]:
        return [self.key_id(repo, b, p) for p in range(1, 5) if W.ORDERS[(repo, b)][p - 1] == "S1"]

    def a0_of(self, repo: str, b: int) -> list[str]:
        return [self.key_id(repo, b, p) for p in range(1, 5) if W.ORDERS[(repo, b)][p - 1] == "A0"]

    def bodies(self, key: str) -> list[dict[str, Any]]:
        """The body under ``key`` in both the plan and its pre-S3 copy."""
        name, p = key.split("/")
        out = []
        for doc in (self.plan, self.pre):
            out.append(next(e for e in doc[name]["runs"] if e["slot"] == int(p))["body"])
        return out

    def out_entry(self, key: str) -> dict[str, Any]:
        doc = self.outs["cobra_out" if key.startswith("cobra") else "click_out"]
        return doc[key]

    def campaign_run(self, rid: str) -> dict[str, Any]:
        return next(x for x in self.campaign["runs"] if x["run_id"] == rid)

    def set_time(self, rid: str, which: str, t: datetime | str | None) -> None:
        self.runs[rid][which] = iso(t) if isinstance(t, datetime) else t

    def time(self, rid: str, which: str) -> datetime:
        return datetime.fromisoformat(self.runs[rid][which])

    # --- files ---
    def file_bytes(self) -> dict[str, bytes]:
        docs = {"plan": self.plan, "pre_s3": self.pre, **self.outs}
        return {r: self.raw.get(r, json.dumps(docs[r], indent=1).encode()) for r in W.FILE_ROLES}

    def recorded(self, **changes: Any) -> Any:
        files = self.file_bytes()
        rec = W.Recorded(
            file_names=dict(NAMES),
            file_sha256={r: hashlib.sha256(files[r]).hexdigest() for r in W.FILE_ROLES},
            standing_ids=frozenset(self.ids.values()),
            place_rule=self.place_rule,
        )
        for k, v in changes.items():
            rec = W.replace(rec, **{k: v})
        return rec

    def read_file(self, path: str) -> bytes:
        self.reads.append(path)
        if path == LOGIN:
            return self.login
        files = self.file_bytes()
        for role, name in NAMES.items():
            if path == f"{POSTER}/{name}":
                return self.tamper.get(role, files[role])
        raise FileNotFoundError(path)

    # --- the served product ---
    def open_getter(self, api: str, username: str, password: str) -> Any:
        assert (username, password) == ("fixture-user", PASSWORD)
        self.opened.append(api)
        return self.get

    def get(self, path: str, query: Any) -> tuple[int, bytes]:
        q = tuple(query)
        self.calls.append((path, q))
        if path in self.fail:
            return self.fail[path], b""
        qd = dict(q)
        if path == f"/api/v1/campaigns/{W.CAMPAIGN_ID}":
            return 200, json.dumps(self.campaign).encode()
        m = re.fullmatch(r"/api/v1/runs/([0-9a-f]+)", path)
        if m:
            doc = self.runs.get(m.group(1))
            return (200, json.dumps(doc).encode()) if doc is not None else (404, b"")
        m = re.fullmatch(r"/api/v1/runs/([0-9a-f]+)/events/log", path)
        if m:
            return 200, self._page(self.events.get(m.group(1), []), qd)
        if path == "/api/v1/grades":
            return 200, self._page(self.grades.get(qd["run_id"], []), qd)
        return 404, b""

    @staticmethod
    def _page(items: list[Any], qd: dict[str, str]) -> bytes:
        limit, offset = int(qd["limit"]), int(qd["offset"])
        page = {"items": items[offset : offset + limit], "total": len(items),
                "limit": limit, "offset": offset}  # fmt: skip
        return json.dumps(page).encode()

    def requested(self, kind: str) -> set[str]:
        if kind == "events":
            pat = r"/api/v1/runs/([0-9a-f]+)/events/log"
            return {m.group(1) for p, _ in self.calls if (m := re.fullmatch(pat, p))}
        return {dict(q)["run_id"] for p, q in self.calls if p == "/api/v1/grades"}

    def write_deviation(self, path: str, text: str) -> None:
        self.deviation.append((path, text))

    def open_output(self, path: str) -> FakeOutput:
        if self.output_error is not None:
            raise self.output_error
        assert not self.calls and not self.opened, "output opened after a request"
        assert all(r == LOGIN for r in self.reads), "output opened after a poster file read"
        f = FakeOutput()
        self.outputs[path] = f
        return f

    def all_ids(self) -> list[str]:
        return [*self.ids.values(), ID98, EXTRA_UNLISTED, EXTRA_SIGHTED,
                *(r["run_id"] for r in self.campaign["runs"])]  # fmt: skip


def out_entry_doc(rid: Any) -> dict[str, Any]:
    """An out-file entry as the poster writes it, every field but ``run.id`` filled with a
    value that must never reach any output (``brief()``, wave4_post.py lines 83-95)."""
    return {
        "arm": "LEAK-OUT-ARM", "posted": "LEAK-OUT-POSTED",
        "run": {
            "id": rid, "status": "LEAK-OUT-STATUS", "progress": "LEAK-OUT-PROGRESS",
            "clean": 987654, "errors": ["LEAK-OUT-ERRORS"], "stopped_reason": "LEAK-OUT-SR",
            "stopped_code": "LEAK-OUT-SC", "cost_usd": 0.987654, "error": "LEAK-OUT-ERROR",
        },
        "ended": "LEAK-OUT-ENDED", "clean_end": "LEAK-OUT-CLEAN-END",
    }  # fmt: skip


def s3_batches() -> dict[str, Any]:
    """Twelve batches added after the wave (S3), each malformed: never to be opened."""
    bad: list[Any] = ["LEAK-S3", None, 7, [], {}, {"runs": "LEAK-S3"}, {"runs": [1, 2]},
                      {"runs": [{"slot": 9, "arm": "LEAK-S3"}]}, {"cell": "LEAK-S3"},
                      [{"body": "LEAK-S3"}], {"runs": None}, {"runs": [{}] * 5}]  # fmt: skip
    names = [f"{r}-s3-{i}" for r in W.REPOS for i in range(1, 7)]
    return dict(zip(names, bad, strict=True))


def make_world() -> World:
    w = World()
    t = BASE
    sequence: list[tuple[str, int, int] | None] = []
    for repo, b in W.BATCH_KEYS:
        if (repo, b) == ("click", 3):
            sequence.append(None)  # the first filing of click batch 3
        sequence.extend((repo, b, p) for p in range(1, 5))
    camp: list[dict[str, Any]] = []
    for item in sequence:
        if item is None:
            tasks = list(W.batch_commits("click", 3))
            w.runs[ID98] = run_doc(ID98, "click", tasks, t, status="failed", rows=0)
            w.arm[ID98] = "A0"
            camp.append({"run_id": ID98, "s1": False})
        else:
            repo, b, p = item
            rid = standing_id(repo, b, p)
            w.ids[f"{repo}-{b}/{p}"] = rid
            w.arm[rid] = W.ORDERS[(repo, b)][p - 1]
            w.runs[rid] = run_doc(rid, repo, list(W.batch_commits(repo, b)), t)
            camp.append({"run_id": rid, "s1": w.arm[rid] == "S1"})
        t += timedelta(hours=1)
    # two other runs of the campaign that are not wave runs
    w.runs[EXTRA_UNLISTED] = run_doc(EXTRA_UNLISTED, "click", UNLISTED_COMMITS, t)
    w.runs[EXTRA_SIGHTED] = run_doc(
        EXTRA_SIGHTED, "click", list(W.batch_commits("click", 1)), t, kind="sighted"
    )
    camp += [{"run_id": EXTRA_UNLISTED, "s1": False}, {"run_id": EXTRA_SIGHTED, "s1": False}]
    for c in camp:
        c |= {"status": "LEAK-STATUS", "cap_usd": 6.0, "spent_usd": 0.987654, "commits": 5}
    w.campaign = {"id": W.CAMPAIGN_ID, "name": "LEAK-NAME", "spent_usd": 28.987654,
                  "runs": sorted(camp, key=lambda x: x["run_id"])}  # fmt: skip
    # the plan and its copy from before S3 (wave4_post.py lines 102, 127-130): one object
    # keyed by batch name; a batch holds cell, coin, order and runs; an entry holds slot,
    # the poster's own arm label (garbage here: it must never be read) and body
    plan: dict[str, Any] = {}
    for repo, b in W.BATCH_KEYS:
        tasks = list(W.batch_commits(repo, b))
        entries = [{"slot": p, "arm": "LEAK-PLAN-ARM",
                    "body": body_doc(repo, tasks, W.ORDERS[(repo, b)][p - 1])}
                   for p in range(1, 5)]  # fmt: skip
        plan[f"{repo}-{b}"] = {"cell": "LEAK-CELL", "coin": "LEAK-COIN",
                               "order": "LEAK-ORDER", "runs": entries}  # fmt: skip
    w.pre = copy.deepcopy(plan)
    w.plan = {**plan, **s3_batches()}
    # the out files (wave4_post.py lines 150-157, 169): one object keyed by the plan key
    for role, repo in (("click_out", "click"), ("cobra_out", "cobra")):
        outs = {f"{repo}-{b}/{p}": out_entry_doc(w.ids[f"{repo}-{b}/{p}"])
                for r, b, p in plain_keys() if r == repo}  # fmt: skip
        if repo == "click":
            outs[W.ATTEMPT1_KEY] = out_entry_doc(ID98)
        w.outs[role] = outs
    # events (S1 runs; A0 runs have events too, never requested) and rows
    for repo, b in W.BATCH_KEYS:
        tasks = list(W.batch_commits(repo, b))
        s1a, s1b = w.s1_of(repo, b)
        for rid in (*w.s1_of(repo, b), *w.a0_of(repo, b)):
            items: list[dict[str, Any]] = [
                {"seq": 1, "action": "run.start", "payload": {"note": "LEAK-EVENT"}},
                {"seq": 2, "action": "author.attempt",
                 "payload": {"provider": "cerebras", "reason": "LEAK-EVENT-REASON"}},
            ]  # fmt: skip
            for c in tasks:
                items.append({"seq": len(items) + 1, "action": "builder.author_test.start",
                              "payload": {"task": c, "detail": "LEAK-EVENT"}})  # fmt: skip
            w.events[rid] = items
        pattern = d_pattern(b)
        for rid in (*w.s1_of(repo, b), *w.a0_of(repo, b)):
            rows = []
            for c, dval in zip(tasks, pattern, strict=True):
                clean = (rid == s1a and dval >= 1) or (rid == s1b and dval >= 2)
                rows.append({"run_id": rid, "task_id": c, "clean": clean, "error": "",
                             "labels": ["LEAK-LABEL"], "seq": 987654})  # fmt: skip
            w.grades[rid] = rows
    # one S1 run has more events than a page holds
    first = w.s1_of("cobra", 5)[0]
    for _ in range(620):
        w.events[first].append({"seq": len(w.events[first]) + 1, "action": "builder.turn",
                                "payload": {"text": "LEAK-EVENT"}})  # fmt: skip
    return w


@dataclass
class Res:
    code: int
    out: str
    err: str
    w: World


def run(w: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *,
        argv: list[str] | None = None, recorded: Any = None, exists: bool = False,
        self_bytes: bytes | None = b"fixture-self", pin_ids: bool = True) -> Res:  # fmt: skip
    for log in (w.calls, w.opened, w.reads, w.deviation, w.outputs):
        log.clear()
    rec = recorded if recorded is not None else w.recorded()
    pin_hashes(monkeypatch, rec, pin_ids=pin_ids)
    buf = io.StringIO()
    code = W.main(
        argv if argv is not None else list(ARGV),
        read_file=w.read_file, open_getter=w.open_getter, write_deviation=w.write_deviation,
        open_output=w.open_output, path_exists=lambda _p: exists, stdout=buf, recorded=rec,
        self_bytes=self_bytes,
    )  # fmt: skip
    check_output_file(w, buf.getvalue())
    return Res(code, buf.getvalue(), capsys.readouterr().err, w)


def pin_hashes(monkeypatch: pytest.MonkeyPatch, rec: Any, *, pin_ids: bool = True) -> None:
    """Point the two recorded hash constants at the made-up wave (never the real ids)."""
    monkeypatch.setattr(
        W, "FILE_SHA256_TRUNCATED",
        {r: (h[:8], h[-6:]) for r, h in rec.file_sha256.items() if isinstance(h, str)},
    )  # fmt: skip
    ids = rec.standing_ids
    if pin_ids and isinstance(ids, frozenset) and all(isinstance(i, str) for i in ids):
        monkeypatch.setattr(W, "STANDING_IDS_SHA256", W.standing_ids_sha256(ids))


def check_output_file(w: World, stdout: str) -> None:
    """K1: once opened, the output file holds stdout byte for byte, flushed per line, closed."""
    for f in w.outputs.values():
        assert f.closed_text == stdout
        assert f.flushed_at, "the held lines were not flushed at attach"
        ends = [i + 1 for i, ch in enumerate(f.text) if ch == "\n"]
        assert all(e in f.flushed_at for e in ends if e >= f.flushed_at[0])
        assert f.flushed_at[-1] == len(f.text)


def no_leak(text: str) -> None:
    for s in LEAKS:
        assert s not in text, s


def assert_order_failed(res: Res, *parts: str) -> None:
    assert res.code == 2, res.out
    for part in parts:
        assert f"ORDER CHECK FAILED: part {part}\n" in res.out, (part, res.out)
    # test (i): the footer, no figure, no row or event read, nothing set aside
    assert res.out.rstrip("\n").endswith(W.FAIL_FOOTER)
    for word in ("DECISION:", "interval", "Order check passed", "Rows read", "m = "):
        assert word not in res.out
    assert not res.w.requested("events")
    assert not res.w.requested("grades")
    assert not res.w.deviation
    no_leak(res.out + res.err)


def run_line(res: Res, rid: str) -> str:
    r = res.w.runs[rid]
    return f"  run {rid}  created {r.get('created') or 'ABSENT'}  finished {r.get('finished') or 'ABSENT'}"


def windows(rid: str) -> set[str]:
    return {rid[i : i + 8] for i in range(len(rid) - 7)}


# ---------------------------------------------------------------------------
# registered constants against the registration and the ruling
# ---------------------------------------------------------------------------


def _reg_list(text: str, heading: str) -> list[str]:
    start = text.index(f"\n### {heading} — ")
    fence = text.index("```text\n", start) + len("```text\n")
    block = text[fence : text.index("```", fence)]
    rows = [ln.split() for ln in block.splitlines() if ln.strip()]
    assert [int(n) for n, _ in rows[:15]] == list(range(1, 16))
    return [c for _, c in rows[:15]]


def test_lists_are_the_registered_cut_lists() -> None:
    text = REG.read_text(encoding="utf-8")
    for repo in W.REPOS:
        for cell in ("XS", "S"):
            assert list(W.LISTS[(repo, cell)]) == _reg_list(text, f"{repo} {cell}")
    for (repo, cell), lst in W.LISTS.items():
        digest = hashlib.sha256("".join(c + "\n" for c in lst).encode()).hexdigest()
        row = re.search(rf"\| {repo} {cell} \| 1 to 15 \| `([0-9a-f]{{64}})` \|", text)
        assert row is not None and row.group(1) == digest
    assert len(W.LISTED) == 60


def test_orders_follow_the_coin_and_the_registered_table() -> None:
    text = REG.read_text(encoding="utf-8")
    for (repo, b), order in W.ORDERS.items():
        digit = hashlib.sha256(f"crb.wave4.order|{repo}|{b}".encode()).hexdigest()[0]
        assert order == (W.A0S1S1A0 if int(digit, 16) % 2 == 0 else W.S1A0A0S1)
        lo = 5 * ((b - 1) // 2) + 1
        row = (f"| {repo} | {b} | {W.batch_cell(b)} | {lo} to {lo + 4} | `{digit}` | "
               f"`{', '.join(order)}` |")  # fmt: skip
        assert row in text


def test_truncated_hashes_and_campaign_are_the_ruling_s() -> None:
    text = RUL.read_text(encoding="utf-8")
    for prefix, suffix in W.FILE_SHA256_TRUNCATED.values():
        assert f"`{prefix}...{suffix}`" in text
    assert W.CAMPAIGN_ID in text
    for line in W.TRUST_LINES:
        assert " ".join(line.split()) in " ".join(text.split())


def _t_cdf_upper(t: float, df: int) -> float:
    """P(T > t) for t > 0, through the regularised incomplete beta (continued fraction)."""
    x = df / (df + t * t)
    a, b = df / 2, 0.5
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x)) / a
    # Lentz's continued fraction
    tiny = 1e-300
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 400):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1 + num * d
        d = tiny if abs(d) < tiny else d
        d = 1 / d
        c = 1 + num / c
        c = tiny if abs(c) < tiny else c
        f *= c * d
    return 0.5 * front * (f - 1)


def test_t975_is_each_quantile_rounded_up_to_four_decimals() -> None:
    for df, const in W.T975.items():
        lo, hi = 0.0, 100.0
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _t_cdf_upper(mid, df) > 0.025 else (lo, mid)
        exact = (lo + hi) / 2
        assert exact <= float(const) < exact + 1e-4, (df, exact, const)
    assert W.T975[11] == "2.2010"


# ---------------------------------------------------------------------------
# the passing made-up wave
# ---------------------------------------------------------------------------


def test_pass_wave_hand_computed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    res = run(w, monkeypatch, capsys)
    assert res.code == 0, res.out
    out = res.out
    # hand result: U_b alternates 2, 4 over 12 batches; T2 = 36, T = 18, N = 60, d = 0.3;
    # only the two all-same sign vectors reach |36|, so m = 2 of 4096; Q = 12 x (1/2)^2 = 3,
    # SE^2 = (12/11) x 3 / 3600 = 1/1100; 0.3 +- 2.2010 x sqrt(1/1100) = 23.3637 .. 36.6363.
    primary = out[out.index("Primary (12 batches):") : out.index("Blocks result:")]
    assert "  units B = 12; commits N = 60\n" in primary
    assert "  T = 18; d = 30.0000 points\n" in primary
    assert "  m = 2 of 2^12 = 4096; p = 2/4096 = 0.00048828125; below 0.05: yes\n" in primary
    assert "  interval: 23.3637 to 36.6363 points (t = 2.2010, df 11)\n" in primary
    assert "  upper end below 15 points: no\n" in primary
    # R2: no author-hit batch, so both recomputed results equal the primary and are printed
    for title in ("Blocks result:", "Left-out result:"):
        part = out[out.index(title) :]
        assert "m = 2 of 2^12 = 4096" in part
        assert "interval: 23.3637 to 36.6363 points" in part
    assert (
        "  click batch 1: n = 5; S = 1 = 1.0000; without usable test 0/10; author-hit no\n" in out
    )
    assert (
        "  cobra batch 6: n = 5; S = 2 = 2.0000; without usable test 0/10; author-hit no\n" in out
    )
    assert "batches with a non-zero summed difference: 12 of 12\n" in out
    assert "usable tests: 120 of 120 (nine in ten = 108)\n" in out
    assert "whose row is clean" not in out  # R12: no clean field read for this count
    assert "DECISION: Cleared (" in out
    # the order-check pass block, in order
    order = [
        "filing time: created", "end time: finished", "status: status", "row count: counts.rows",
        "commits: task_ids", "kind: kind", f"L = {W.L_VALUE} (source: DL-378",
        "Taken on trust", "Not compared (not served): env_stop, outage_stop, learning.",
        "Order check passed.", W.S1_FLAG_SENTENCE,
        "Standing ids: from the slot-free run ledger (built from the poster's out files); "
        f"id-list sha256 {W.standing_ids_sha256(w.ids.values())}; T4 is a consistency test.",
        "test author provider shown as cerebras: 24 of 24 standing S1 runs",
        "Rows read: 240 of 240 (48 runs x 5); rows missing: 0 (each counted as a miss: row "
        "rule, part 6 item 5, A3); first filing 98fe708c: set aside unread (0 rows, A2 item 3).",
        "Primary (12 batches):", "Blocks result:", "Left-out result:", "DECISION:",
        *W.FIXED_SENTENCES,
        "Stop (b), as recorded in Amendment 3 Part D (not computed by this script):",
        "  strict reading: 0", "  git stash only (the count the methodologist signs): 2",
        "  every refused read-only git command: 4", W.STOP_B_SENTENCE,
        "Standing run ids (sorted by id; no place, no arm):",
    ]  # fmt: skip
    pos = [out.index(s) for s in order]
    assert pos == sorted(pos)
    assert "A3 records that all 240 rows exist" not in out and "Missing rows" not in out
    assert W.NO_RECORD_READ not in out
    for i, line in enumerate(W.TRUST_LINES, start=1):
        assert f"{i}. {line}\n" in out
    tail = out[out.index("Standing run ids") :].splitlines()[1:]
    assert tail == [f"  {i}" for i in sorted(w.ids.values())]
    # every full run id is printed exactly once (the list); the first filing never
    for rid in w.ids.values():
        assert out.count(rid) == 1
    assert ID98 not in out
    # hashes: self and each input file
    assert f"wave4_primary_read sha256 {hashlib.sha256(b'fixture-self').hexdigest()}\n" in out
    for role, data in w.file_bytes().items():
        assert f"{POSTER}/{NAMES[role]} sha256 {hashlib.sha256(data).hexdigest()}" in out
    # requests: events of the 24 standing S1 runs only, rows of the 48 only
    s1 = {rid for rid, a in w.arm.items() if a == "S1"}
    assert w.requested("events") == s1 and len(s1) == 24
    assert w.requested("grades") == set(w.ids.values())
    assert w.opened == [API]
    assert not w.deviation
    no_leak(res.out + res.err)
    # no table of arms by run: no line carries both an id and an arm name
    for line in out.splitlines():
        if any(rid in line for rid in w.ids.values()):
            assert "S1" not in line and "A0" not in line


def test_pass_prints_the_script_s_own_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    res = run(make_world(), monkeypatch, capsys, self_bytes=None)
    assert res.code == 0
    digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert res.out.startswith(f"wave4_primary_read sha256 {digest}\n")


# ---------------------------------------------------------------------------
# not ready (exit 1, no request)
# ---------------------------------------------------------------------------


def test_unset_standing_ids_are_not_ready() -> None:
    rec = dataclasses.replace(W.RECORDED, standing_ids=None)
    with pytest.raises(W.NotReadyError, match="STANDING_IDS not recorded"):
        W.check_ready(rec)


def test_recorded_values_are_the_poster_facts() -> None:
    """The shipped constants are the facts read from wave4_post.py (sha256 b30ca68e...);
    STANDING_IDS is the 48 full ids of the slot-free run ledger, without the first filing."""
    rec = W.RECORDED
    assert rec.file_names == {
        "plan": "wave-batches.json", "pre_s3": "wave-batches.before-s3.json",
        "click_out": "click-out.json", "cobra_out": "cobra-out.json",
    }  # fmt: skip
    assert rec.file_sha256 == {
        "plan": "ae705b68e03e1ff58972d34cdb81f5e85095ca88449e23a99a9c5276702fb45a",
        "pre_s3": "a3c592cd9e7a19210888b2f9bd6d3b8c6e05d6ce76169e996a71d36d7b2970fd",
        "click_out": "27b2747e044048c6766186a1689cc5749178c46a8dce3c78dacd6ed09a4c4170",
        "cobra_out": "59d7eefc3361caa5f78fd18bc8b66f5e0e2cc5f36a1e49915ea79033b506e0e1",
    }
    ids = rec.standing_ids
    assert ids is not None and len(ids) == 48
    assert all(W.HEX32.match(i) for i in ids)
    assert not any(i.startswith(W.SHORT_FIRST_FILING) for i in ids)
    listed = "".join(i + "\n" for i in sorted(ids)).encode()
    assert hashlib.sha256(listed).hexdigest() == (
        "b79c3cbedaf775238e0f74ddb506a7ebb86858d9b20845ca97a65dd6a7bedf3d"
    )
    # K4: the shipped constant is that hash, and the function check_ready uses agrees
    assert hashlib.sha256(listed).hexdigest() == W.STANDING_IDS_SHA256
    assert W.standing_ids_sha256(ids) == W.STANDING_IDS_SHA256
    assert rec.place_rule == "slot"
    for role, (prefix, suffix) in W.FILE_SHA256_TRUNCATED.items():
        assert rec.file_sha256[role].startswith(prefix)
        assert rec.file_sha256[role].endswith(suffix)
    W.check_ready(rec)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"standing_ids": None}, "STANDING_IDS not recorded"),
        ({"standing_ids": frozenset([fid("only-one")])}, "STANDING_IDS is not 48 full run ids"),
        ({"place_rule": None}, "PLACE_RULE not recorded"),
        ({"place_rule": "guess"}, "PLACE_RULE is not slot (wave4_post.py line 130)"),
        ({"place_rule": "position"}, "PLACE_RULE is not slot (wave4_post.py line 130)"),
    ],
)
def test_missing_recorded_constant(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
                                   change: dict[str, Any], message: str) -> None:  # fmt: skip
    w = make_world()
    res = run(w, monkeypatch, capsys, recorded=w.recorded(**change))
    assert res.code == 1
    assert f"not ready: {message}\n" in res.out
    assert not w.opened and not w.calls


def test_full_hash_must_agree_with_the_ruling_s_truncation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    w = make_world()
    buf = io.StringIO()
    code = W.main(list(ARGV), read_file=w.read_file, open_getter=w.open_getter,
                  write_deviation=w.write_deviation, path_exists=lambda _p: False,
                  stdout=buf, recorded=w.recorded(), self_bytes=b"x")  # fmt: skip
    assert code == 1
    assert "not ready: FILE_SHA256[plan] does not agree with the ruling's T1" in buf.getvalue()
    assert not w.opened


@pytest.mark.parametrize(
    "login",
    [b"not json", b'{"username": "u"}', b'{"username": "u", "password": ""}',
     b'{"username": "u", "password": "p", "extra": 1}',
     b'{"username": "u", "password": "p", "password": "q"}'],
)  # fmt: skip
def test_login_file_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], login: bytes
) -> None:
    w = make_world()
    w.login = login
    res = run(w, monkeypatch, capsys)
    assert res.code == 1
    assert "not ready: login file shape not as expected\n" in res.out
    assert not w.opened
    for secret in ("u", "p", "q"):
        assert f": {secret}\n" not in res.out


def test_wrong_campaign_and_existing_deviation_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    argv = list(ARGV)
    argv[argv.index("--campaign") + 1] = "cmp_" + "0" * 24
    res = run(w, monkeypatch, capsys, argv=argv)
    assert res.code == 1 and "not ready: campaign is not the registered" in res.out
    res = run(w, monkeypatch, capsys, exists=True)
    assert res.code == 1 and "not ready: deviation-out already exists" in res.out
    assert not w.opened
    with pytest.raises(SystemExit) as exc:
        W.main(["--poster-dir", POSTER], stdout=io.StringIO(), recorded=w.recorded())
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# the order check: one failing case per part
# ---------------------------------------------------------------------------


def test_t1_hash_differs_stops_before_any_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.tamper["cobra_out"] = w.file_bytes()["cobra_out"] + b" "
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T1")
    assert "  reason: file hash differs from the recorded one\n" in res.out
    assert not w.opened and not w.calls
    assert res.out.endswith(f"{W.NO_RECORD_READ}\n{W.FAIL_FOOTER}\n")  # C1


def test_t1_file_not_readable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    rec = w.recorded(file_names={**NAMES, "pre_s3": "absent.json"})
    res = run(w, monkeypatch, capsys, recorded=rec)
    assert_order_failed(res, "T1")
    assert not w.opened
    # K3: a fixed text naming the role, no path and no traceback; C1: no record was read
    assert "  reason: file not readable\n  file pre_s3\n" in res.out
    assert "absent.json" not in res.out
    assert "Traceback" not in res.out + res.err
    assert res.out.endswith(f"{W.NO_RECORD_READ}\n{W.FAIL_FOOTER}\n")


def test_t2_plan_and_copy_differ(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.bodies("click-4/2")[1]["max_cost_usd"] = 7
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T2")
    assert "  key click-4/2\n" in res.out
    # a T2 failure stops before any request: no getter is opened, no sign-in is sent
    assert not w.opened and not w.calls


def test_t2_equal_numbers_of_two_spellings_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.bodies("click-4/2")[1]["max_cost_usd"] = 6  # 6.0 in the plan, 6 in the copy
    w.bodies("click-4/2")[1]["budget"] = {"max_seconds": 900, "max_turns": 50, "max_tokens": None}
    assert run(w, monkeypatch, capsys).code == 0


@pytest.mark.parametrize(
    "raw",
    [b"{not json", b'{"click-1": {}, "click-1": {}}', b'{"click-1": NaN}', b"[]",
     b'{"other": []}', b'"click-1"'],
)  # fmt: skip
def test_t3_file_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw: bytes
) -> None:
    w = make_world()
    w.raw["plan"] = raw
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T3")
    assert "  reason: file shape not as recorded\n" in res.out
    assert not w.opened


def test_t3_key_in_the_wrong_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.outs["click_out"]["cobra-2/1"] = w.outs["cobra_out"].pop("cobra-2/1")
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T3")
    assert "key cobra-2/1 is in the click out file" in res.out
    assert "ORDER CHECK: part (a) not evaluated (depends on T3/T4)" in res.out


def test_t3_key_missing_or_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    del w.outs["click_out"]["click-5/3"]
    w.outs["cobra_out"]["cobra-7/1"] = out_entry_doc(fid("x"))
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T3")
    assert "key click-5/3 is missing" in res.out
    assert "key cobra-7/1 is not one of the 49 keys" in res.out


def test_t4_attempt1_is_a_standing_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.out_entry(W.ATTEMPT1_KEY)["run"]["id"] = w.key_id("click", 3, 1)
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T4")
    assert "a run id is under more than one key" in res.out


def test_t4_plain_key_not_standing_and_bad_form(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.out_entry("cobra-6/4")["run"]["id"] = fid("stranger")
    w.out_entry("cobra-6/3")["run"]["id"] = "XYZ-not-a-run-id"
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T4")
    assert "the ids under the plain keys are not the 48 standing ids" in res.out
    assert "the value under key cobra-6/3 is not a full run id" in res.out
    assert "XYZ-not-a-run-id" not in res.out


@pytest.mark.parametrize("rid", [12345, None, True, ["a"], {"id": "x"}])
def test_t3_run_id_not_a_string(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], rid: Any
) -> None:
    w = make_world()
    w.out_entry("cobra-6/3")["run"]["id"] = rid
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T3")
    assert "  reason: file shape not as recorded\n" in res.out
    assert not w.opened


@pytest.mark.parametrize(
    "change",
    ["refusal", "no-run", "run-string", "run-null", "run-no-id", "entry-string", "entry-list"],
)
def test_t3_out_entry_without_a_run_object_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    """A refused post is written with ``refusal`` and no ``run`` (wave4_post.py line 152);
    any entry with no run object holding an id is a shape failure, before any request."""
    w = make_world()
    key = "click-2/3"
    rid = w.out_entry(key)["run"]["id"]
    if change == "refusal":
        w.outs["click_out"][key] = {"arm": "LEAK-OUT-ARM", "posted": "LEAK-OUT-POSTED",
                                    "refusal": "LEAK-OUT-REFUSAL"}  # fmt: skip
    elif change == "no-run":
        del w.out_entry(key)["run"]
    elif change == "run-string":
        w.out_entry(key)["run"] = rid
    elif change == "run-null":
        w.out_entry(key)["run"] = None
    elif change == "run-no-id":
        del w.out_entry(key)["run"]["id"]
    elif change == "entry-string":
        w.outs["click_out"][key] = rid
    else:
        w.outs["click_out"][key] = [rid]
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T3")
    assert "  reason: file shape not as recorded\n" in res.out
    assert not w.opened and not w.calls


def test_campaign_membership(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    gone = w.key_id("cobra", 4, 2)
    w.campaign["runs"] = [r for r in w.campaign["runs"] if r["run_id"] != gone]
    w.campaign_run(w.key_id("click", 1, 1))["s1"] = "false"
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "campaign membership")
    assert "a standing run is not listed in the campaign" in res.out
    assert "s1 is not a boolean" in res.out
    assert "ORDER CHECK: part (d) not evaluated" in res.out


@pytest.mark.parametrize("case", ["status", "rows_bool", "rows_4", "tasks", "kind"])
def test_a_standing_run_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    w = make_world()
    rid = w.key_id("cobra", 4, 2)
    if case == "status":
        w.runs[rid]["status"] = "failed"
    elif case == "rows_bool":
        w.runs[rid]["counts"]["rows"] = True
    elif case == "rows_4":
        w.runs[rid]["counts"]["rows"] = 4
    elif case == "tasks":
        w.runs[rid]["task_ids"] = list(W.batch_commits("cobra", 2))
    else:
        w.runs[rid]["kind"] = "sighted"
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(a)")
    assert run_line(res, rid) in res.out


def test_a_short_id_matches_two_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    twin = W.SHORT_CLICK3[1] + fid("twin")[8:]
    w.runs[twin] = run_doc(twin, "click", UNLISTED_COMMITS, BASE, kind="sighted")
    w.campaign["runs"].append({"run_id": twin, "s1": False})
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(a)")
    assert f"short id {W.SHORT_CLICK3[1]} matches 2 runs of the campaign" in res.out


@pytest.mark.parametrize("case", ["listed", "empty", "absent", "kind_absent", "id98_succeeded",
                                  "id98_tasks"])  # fmt: skip
def test_b_blind_runs_on_listed_commits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    w = make_world()
    extra = fid("extra-" + case)
    if case.startswith("id98"):
        if case == "id98_succeeded":
            w.runs[ID98]["status"] = "succeeded"
        else:
            w.runs[ID98]["task_ids"] = list(W.batch_commits("click", 4))
    else:
        tasks: Any = {"listed": [*UNLISTED_COMMITS[:4], W.LISTS[("cobra", "S")][14]],
                      "empty": [], "absent": None, "kind_absent": UNLISTED_COMMITS}[case]  # fmt: skip
        w.runs[extra] = run_doc(extra, "cobra", UNLISTED_COMMITS, BASE)
        if tasks is None:
            del w.runs[extra]["task_ids"]
        else:
            w.runs[extra]["task_ids"] = tasks
        if case == "kind_absent":
            del w.runs[extra]["kind"]
        w.campaign["runs"].append({"run_id": extra, "s1": False})
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(b)")
    if case == "listed":
        # K10 reverted: times are not outcomes and every record read keeps them, so a stray
        # blind run named by (b) is printed with its id and its two served times (R5 item 2:
        # "the run ids and times concerned")
        assert run_line(res, extra) + "\n" in res.out
        assert f"  run {extra}  created {w.runs[extra]['created']}  " in res.out
        assert f"  run {extra}  created NOT KEPT" not in res.out


@pytest.mark.parametrize("case", ["finished_null", "created_naive", "created_garbage"])
def test_c_times(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    w = make_world()
    rid = w.key_id("click", 5, 2)
    if case == "finished_null":
        w.set_time(rid, "finished", None)
    elif case == "created_naive":
        w.set_time(rid, "created", w.time(rid, "created").replace(tzinfo=None))
    else:
        w.set_time(rid, "created", "yesterday")
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(c)")
    assert run_line(res, rid) in res.out
    assert (
        "ORDER CHECK: part (f) not evaluated (depends on campaign membership/(a)/(c)/(h))"
        in res.out
    )


def test_d_equal_filing_times(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    x, y = w.key_id("cobra", 3, 2), w.key_id("cobra", 3, 3)
    w.set_time(x, "created", w.time(y, "created"))
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(d)")
    assert "ORDER CHECK: part T5 not evaluated (depends on (d))" in res.out
    assert run_line(res, x) in res.out and run_line(res, y) in res.out


def test_t5_key_not_at_its_place(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    a, b = w.out_entry("click-1/1"), w.out_entry("click-1/2")
    a["run"]["id"], b["run"]["id"] = b["run"]["id"], a["run"]["id"]
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T5", "(e)", "campaign s1")
    assert "the run under click-1/1 is not in place 1 by filing time" in res.out


def test_t5_repo_and_first_filing_times(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.runs[w.key_id("click", 2, 2)]["repo"] = "cobra"
    w.set_time(ID98, "created", w.time(w.key_id("click", 2, 4), "finished") - timedelta(minutes=1))
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T5", "(g)")
    assert "the run under click-2/2 is not a click run" in res.out
    assert "run 98fe708c was filed before click batch 2 ended" in res.out


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("extra_key", "key surprise not in the field table"),
        ("model", "model differs from the run record"),
        ("campaign_id", "the body does not carry the Wave 4 campaign id"),
        ("retain", "retain is contradicted by the run record"),
        ("budget", "budget differs from the run record"),
        ("max_cost_bool", "max_cost_usd differs from the run record"),
        ("tasks_order", "task_ids differ from the run record"),
    ],
)
def test_section4_field_table_t6(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
                                 case: str, reason: str) -> None:  # fmt: skip
    w = make_world()
    key = "cobra-5/3"
    rid = w.ids[key]
    for body in w.bodies(key):
        if case == "extra_key":
            body["surprise"] = 1
        elif case == "model":
            body["model"] = "other-model"
        elif case == "campaign_id":
            del body["campaign_id"]
        elif case == "budget":
            body["budget"]["max_turns"] = 51
        elif case == "max_cost_bool":
            body["max_cost_usd"] = True
        elif case == "tasks_order":
            body["task_ids"] = list(reversed(body["task_ids"]))
    if case == "retain":
        w.runs[rid]["retain"]["worktrees"] = True
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "section 4")
    assert f"  reason: {reason}\n" in res.out
    assert run_line(res, rid) in res.out


def test_section4_absent_and_null_keys_are_not_compared(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    for body in w.bodies("cobra-5/3"):
        body["model"] = None
        del body["builder_config"]
        body["surprise"] = None
    assert run(w, monkeypatch, capsys).code == 0


@pytest.mark.parametrize("case", ["author", "arm_word", "a0_with_author"])
def test_e_body_fits_neither_arm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    w = make_world()
    key = "cobra-2/2" if case != "a0_with_author" else "cobra-2/1"
    for body in w.bodies(key):
        if case == "author":
            body["test_author"] = W.L_VALUE + " "
        elif case == "arm_word":
            body["arm"] = "s1"
        else:
            body["test_author"] = W.L_VALUE
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(e)")
    assert "  reason: body fits neither arm\n" in res.out


def test_e_arm_at_the_wrong_place(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    rid = w.key_id("click", 6, 2)  # click 6 is S1, A0, A0, S1: place 2 must be A0
    for body in w.bodies("click-6/2"):
        body |= {"arm": "S1", "test_author": W.L_VALUE}
    w.campaign_run(rid)["s1"] = True
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(e)")
    assert "  reason: body does not give the arm its place requires\n" in res.out
    assert "campaign s1" not in res.out


def test_e_explicit_a0_is_a0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    for body in w.bodies("click-6/2"):
        body["arm"] = "A0"
    assert run(w, monkeypatch, capsys).code == 0


def test_campaign_s1_flag_disagrees(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    rid = w.key_id("cobra", 1, 1)
    w.campaign_run(rid)["s1"] = False
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "campaign s1")
    assert run_line(res, rid) in res.out


def test_f_place_ended_after_next_filed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    x, y = w.key_id("click", 4, 2), w.key_id("click", 4, 3)
    w.set_time(x, "finished", w.time(y, "created") + timedelta(minutes=1))
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(f)")
    assert "click batch 4: place 2 ended after place 3 was filed" in res.out


@pytest.mark.parametrize("case", ["within_repo", "between_repos", "first_filing"])
def test_g_batch_ended_after_next_filed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    w = make_world()
    if case == "within_repo":
        x, y = w.key_id("cobra", 2, 4), w.key_id("cobra", 3, 1)
        w.set_time(x, "finished", w.time(y, "created") + timedelta(minutes=1))
        reason = "cobra batch 2 ended after batch 3 was filed"
    elif case == "between_repos":
        x, y = w.key_id("click", 6, 4), w.key_id("cobra", 1, 1)
        w.set_time(x, "finished", w.time(y, "created") + timedelta(minutes=1))
        reason = "click batch 6 ended after cobra batch 1 was filed"
    else:
        y = w.key_id("click", 3, 1)
        w.set_time(ID98, "finished", w.time(y, "created") + timedelta(minutes=1))
        reason = "run 98fe708c ended after click batch 3 place 1 was filed"
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(g)")
    assert reason in res.out


@pytest.mark.parametrize("case", ["finished", "created", "status", "rows"])
def test_h_field_not_held(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    w = make_world()
    rid = w.key_id("cobra", 6, 1)
    if case == "rows":
        del w.runs[rid]["counts"]["rows"]
    else:
        del w.runs[rid][case]
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(h)")
    field = "counts.rows" if case == "rows" else case
    assert f"the record holds no field {field}" in res.out


def test_h_first_filing_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    del w.runs[ID98]["finished"]
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(h)", "(c)")
    assert f"  run {ID98}  created {w.runs[ID98]['created']}  finished ABSENT\n" in res.out


def test_t7_place_is_the_slot_not_the_list_position(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The key is ``f"{name}/{r['slot']}"`` (wave4_post.py line 130): list order is not read."""
    w = make_world()
    for doc in (w.plan, w.pre):
        entries = doc["click-1"]["runs"]  # entries 1 and 2 swapped in the list, slots kept
        entries[0], entries[1] = entries[1], entries[0]
    assert run(w, monkeypatch, capsys).code == 0
    w = make_world()
    for doc in (w.plan, w.pre):
        entries = doc["click-1"]["runs"]  # the slot values of entries 1 and 2 swapped
        entries[0]["slot"], entries[1]["slot"] = entries[1]["slot"], entries[0]["slot"]
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(e)", "campaign s1")


@pytest.mark.parametrize(
    "slots", [(1, 1, 3, 4), (1, 2, 3, True), (0, 2, 3, 4), (1, 2, 3, 4.0), (1, 2, 3, "4"),
              (1, 2, 3, None), (1, 2, 3, 5)],
)  # fmt: skip
def test_t7_slot_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], slots: tuple[Any, ...]
) -> None:
    w = make_world()
    for doc in (w.plan, w.pre):
        for entry, s in zip(doc["click-6"]["runs"], slots, strict=True):
            entry["slot"] = s
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T3")


def test_request_failure_before_the_pass_is_an_order_check_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.fail[f"/api/v1/runs/{w.key_id('cobra', 2, 2)}"] = 503
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "request")
    assert "order-check request: GET answered 503" in res.out
    assert W.NO_RECORD_READ not in res.out  # C1: a request was made
    # the failure carries the run whose record was being requested (test (i): run ids)
    assert f"  run {w.key_id('cobra', 2, 2)}  created NOT KEPT  finished NOT KEPT\n" in res.out
    assert len([c for c in w.calls if c[0].startswith("/api/v1/runs/")]) <= len(w.runs)


def test_failure_output_never_carries_record_counts_or_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """counts.clean, the run error, the out file's arm and clean_end, spend and labels are
    filled in on every made-up record; a failure naming many runs prints none of them."""
    w = make_world()
    for rid in list(w.ids.values())[:10]:
        w.runs[rid]["status"] = "LEAK-STATUS-VALUE"
        w.runs[rid]["error"] = "authoring: LEAK-RUN-ERROR"
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "(a)")
    for s in ("987654", "LEAK", "authoring", "0.765432", "fixture-model"):
        assert s not in res.out


OUT_LEAK_SCENARIOS = ["pass", "refusal", "t4", "t5", "a", "request", "provider", "e5"]


@pytest.mark.parametrize("scenario", OUT_LEAK_SCENARIOS)
def test_out_entry_fields_never_reach_any_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scenario: str
) -> None:
    """Every out entry carries ``arm``, ``posted``, ``ended``, ``clean_end`` and a ``run``
    object with ``status``, ``progress``, ``clean``, ``errors``, ``stopped_reason``,
    ``stopped_code``, ``cost_usd`` and ``error`` filled in (wave4_post.py lines 83-95,
    150-157). Only ``run.id`` is kept: none of the others reaches stdout, stderr or the
    deviation file, on a pass or on any failure."""
    w = make_world()
    sentinel = {"arm": "LEAK-OUT-ARM-Z", "clean_end": "LEAK-OUT-CLEAN-END-Z",
                "clean": 987654, "errors": ["LEAK-OUT-ERRORS-Z"], "error": "LEAK-OUT-ERROR-Z"}  # fmt: skip
    for doc in w.outs.values():
        for entry in doc.values():
            entry["arm"], entry["clean_end"] = sentinel["arm"], sentinel["clean_end"]
            entry["run"].update(clean=sentinel["clean"], errors=sentinel["errors"],
                                error=sentinel["error"])  # fmt: skip
    want = 0
    if scenario == "refusal":
        w.outs["cobra_out"]["cobra-3/2"] = {"arm": sentinel["arm"], "posted": "LEAK-OUT-POSTED",
                                            "refusal": "LEAK-OUT-REFUSAL"}  # fmt: skip
        want = 2
    elif scenario == "t4":
        w.out_entry("cobra-6/4")["run"]["id"] = fid("stranger")
        want = 2
    elif scenario == "t5":
        a, b = w.out_entry("click-1/1"), w.out_entry("click-1/2")
        a["run"]["id"], b["run"]["id"] = b["run"]["id"], a["run"]["id"]
        want = 2
    elif scenario == "a":
        w.runs[w.key_id("cobra", 4, 2)]["status"] = "failed"
        want = 2
    elif scenario == "request":
        w.fail[f"/api/v1/runs/{w.key_id('cobra', 2, 2)}"] = 503
        want = 2
    elif scenario == "provider":
        a = w.s1_of("click", 1)[0]
        w.events[a] = [e for e in w.events[a] if e["action"] != "author.attempt"]
        want = 3
    elif scenario == "e5":
        rows = w.grades[w.a0_of("click", 5)[0]]
        rows.append(dict(rows[0]))
        want = 4
    res = run(w, monkeypatch, capsys)
    assert res.code == want, res.out
    text = res.out + res.err + "".join(t for _p, t in w.deviation)
    if scenario in ("provider", "e5"):
        assert w.deviation  # the deviation file is written, and is checked here too
    no_leak(text)
    for value in ("LEAK-OUT", "987654", "clean_end", "stopped_reason"):
        assert value not in text, (scenario, value)


class Spy(dict):  # type: ignore[type-arg]
    """A dict that logs every key read, membership test and iteration on it."""

    def __init__(self, tag: str, data: dict[str, Any], log: list[tuple[str, str, Any]]) -> None:
        super().__init__(data)
        self.tag, self.log = tag, log

    def __getitem__(self, k: Any) -> Any:
        self.log.append((self.tag, "get", k))
        return super().__getitem__(k)

    def __contains__(self, k: Any) -> bool:
        self.log.append((self.tag, "in", k))
        return super().__contains__(k)

    def get(self, k: Any, default: Any = None) -> Any:
        self.log.append((self.tag, "get", k))
        return super().get(k, default)

    def __iter__(self) -> Any:
        self.log.append((self.tag, "iter", None))
        return super().__iter__()

    def keys(self) -> Any:
        self.log.append((self.tag, "iter", None))
        return super().keys()

    def items(self) -> Any:
        self.log.append((self.tag, "iter", None))
        return super().items()

    def values(self) -> Any:
        self.log.append((self.tag, "iter", None))
        return super().values()

    def __len__(self) -> int:
        self.log.append((self.tag, "len", None))
        return super().__len__()


def test_plan_spy_reads_only_wave_names_runs_slot_and_body() -> None:
    """A spy mapping proves ``extract_plan`` never touches the entries' ``arm`` label, the
    batches' ``cell``, ``coin`` and ``order``, any S3 batch, or anything inside a body."""
    w = make_world()
    log: list[tuple[str, str, Any]] = []
    top: dict[str, Any] = {}
    for name, batch in w.plan.items():
        if not isinstance(batch, dict) or name not in {f"{r}-{b}" for r, b in W.BATCH_KEYS}:
            top[name] = Spy(f"s3:{name}", {"runs": []}, log)  # any access would be logged
            continue
        runs = [Spy(f"entry:{name}", {**e, "body": Spy(f"body:{name}", e["body"], log)}, log)
                for e in batch["runs"]]  # fmt: skip
        top[name] = Spy(f"batch:{name}", {**batch, "runs": runs}, log)
    got = W.extract_plan(Spy("top", top, log))
    assert len(got) == 48
    allowed = {"top": {"in", "get"}, "batch": {"in", "get"}, "entry": {"in", "get"}}
    for tag, op, key in log:
        kind = tag.split(":")[0]
        assert kind in allowed, (tag, op, key)  # never an S3 batch, never a body
        assert op in allowed[kind], (tag, op, key)  # never iterated
        if kind == "top":
            assert key in {f"{r}-{b}" for r, b in W.BATCH_KEYS}, key
        elif kind == "batch":
            assert key == "runs", key
        else:
            assert key in {"body", "slot"}, key
    assert not any(key == "arm" for _t, _o, key in log)
    assert any(kind == "entry" and key == "slot" for kind, _o, key in
               ((t.split(":")[0], o, k) for t, o, k in log))  # fmt: skip


def test_out_spy_reads_only_run_and_id() -> None:
    """A spy mapping proves ``extract_out`` reads, of an entry, only ``run``, and of the run
    object only ``id``: ``arm``, ``posted``, ``ended``, ``clean_end``, ``clean``, ``errors``,
    ``error`` and the rest are never accessed. Iterating the keys (K6: the key names are
    checked) reads no value."""
    w = make_world()
    for role in ("click_out", "cobra_out"):
        log: list[tuple[str, str, Any]] = []
        top = {
            k: Spy("entry", {**e, "run": Spy("run", e["run"], log)}, log)
            for k, e in w.outs[role].items()
        }
        got = W.extract_out(Spy("top", top, log))
        assert got == {k: e["run"]["id"] for k, e in w.outs[role].items()}
        for tag, op, key in log:
            if tag == "top":
                assert op in {"iter", "get"}, (op, key)
            elif tag == "entry":
                assert (op, key) in {("iter", None), ("in", "run"), ("get", "run")}, (op, key)
            else:
                assert (op, key) in {("iter", None), ("in", "id"), ("get", "id")}, (op, key)


# ---------------------------------------------------------------------------
# after the pass: provider test, E4/E5
# ---------------------------------------------------------------------------


def test_provider_test_failure_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    a, b, c = w.s1_of("click", 1)[0], w.s1_of("cobra", 4)[1], w.s1_of("cobra", 6)[0]
    w.events[a] = [e for e in w.events[a] if e["action"] != "author.attempt"]
    next(e for e in w.events[b] if e["action"] == "author.attempt")["payload"]["provider"] = (
        "openai"
    )
    del next(e for e in w.events[c] if e["action"] == "author.attempt")["payload"]["provider"]
    res = run(w, monkeypatch, capsys)
    assert res.code == 3
    lines = res.out.splitlines()
    i = lines.index("test author provider not shown as cerebras")
    assert lines[i:] == [
        "test author provider not shown as cerebras",
        "runs with no author.attempt event: 1",
        "runs with another provider value: 2",
    ]
    text = res.out + res.err
    for rid in w.all_ids():
        for win in windows(rid):
            assert win not in text, (rid, win)
    assert not w.requested("grades")
    assert len(w.deviation) == 1 and w.deviation[0][0] == DEV
    dev = w.deviation[0][1]
    assert f"{a} no event" in dev and f"{b} other value" in dev and f"{c} other value" in dev
    # test (i) applies (Amendment 4 point 4): each run's two times go into the deviation
    # file with its id; stdout carries the counts only, so no time is printed there
    for rid, why in ((a, "no event"), (b, "other value"), (c, "other value")):
        r = w.runs[rid]
        assert f"{rid} {why}  created {r['created']}  finished {r['finished']}\n" in dev
        assert r["created"] not in text and r["finished"] not in text
    no_leak(text)


def test_provider_value_compared_exactly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    rid = w.s1_of("click", 2)[1]
    w.events[rid].append({"seq": len(w.events[rid]) + 1, "action": "author.attempt",
                          "payload": {"provider": "Cerebras"}})  # fmt: skip
    res = run(w, monkeypatch, capsys)
    assert res.code == 3
    assert "runs with another provider value: 1\n" in res.out


def test_e4_failure_after_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    rid = w.s1_of("cobra", 3)[0]
    w.fail[f"/api/v1/runs/{rid}/events/log"] = 500
    res = run(w, monkeypatch, capsys)
    assert res.code == 4
    assert res.out.splitlines()[-1] == "read not made: E4 GET answered 500"
    for win in windows(rid):
        assert win not in res.out
    # K8 + C2: only the failed run is filed, with its two served times
    r = w.runs[rid]
    assert w.deviation == [
        (
            DEV,
            f"{W.SCRIPT_NAME} stop: E4\n{rid} not read  "
            f"created {r['created']}  finished {r['finished']}\n",
        )
    ]
    assert W.NO_RECORD_READ not in res.out


def test_e4_event_seq_must_increase(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    rid = w.s1_of("cobra", 3)[0]
    w.events[rid][3]["seq"] = 2
    res = run(w, monkeypatch, capsys)
    assert res.code == 4 and "read not made: E4 event seq not increasing" in res.out


@pytest.mark.parametrize(
    "case", ["extra_row", "clean_str", "other_run", "dup_task", "unlisted_task", "null_task"]
)
def test_e5_row_integrity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    w = make_world()
    rid = w.a0_of("click", 5)[0]
    rows = w.grades[rid]
    if case == "extra_row":
        rows.append(dict(rows[0]))
    elif case == "clean_str":
        rows[2]["clean"] = "true"
    elif case == "other_run":
        rows[2]["run_id"] = fid("other")
    elif case == "unlisted_task":
        rows[2]["task_id"] = UNLISTED_COMMITS[0]
    elif case == "null_task":
        rows[2]["task_id"] = None
    else:
        rows[4]["task_id"] = rows[3]["task_id"]
    res = run(w, monkeypatch, capsys)
    assert res.code == 4
    assert "read not made: rows not as the run records state (added integrity stop)" in res.out
    want_set, want_clean = (0, 1) if case == "clean_str" else (1, 0)
    assert (
        f"runs with a row for another run, an unlisted commit or one commit twice: {want_set}\n"
        in res.out
    )
    assert f"rows with a non-boolean clean: {want_clean}\n" in res.out
    for win in windows(rid):
        assert win not in res.out
    # C2: the filed line carries the run's two served times
    r = w.runs[rid]
    why = "non-boolean clean" if case == "clean_str" else "row set"
    assert w.deviation[0][1] == (
        f"{W.SCRIPT_NAME} stop: row integrity\n{rid} {why}  "
        f"created {r['created']}  finished {r['finished']}\n"
    )
    assert "DECISION:" not in res.out


@pytest.mark.parametrize("arm", ["S1", "A0"])
def test_e5_missing_row_is_a_miss_not_a_stop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], arm: str
) -> None:
    """A3: missing rows count as misses; Part 6 item 3: an S1 attempt with no row has no
    usable test. The read is made; nothing is set aside or stopped."""
    w = make_world()
    if arm == "S1":
        rid = w.s1_of("click", 5)[0]  # its first commit's row is clean (d pattern 1, 1, ...)
        w.grades[rid] = [r for r in w.grades[rid] if r["task_id"] != W.batch_commits("click", 5)[0]]
    else:
        rid = w.a0_of("click", 5)[0]
        w.grades[rid].pop()
    res = run(w, monkeypatch, capsys)
    assert res.code == 0, res.out
    assert not w.deviation
    assert (
        "Rows read: 239 of 240 (48 runs x 5); rows missing: 1 (each counted as a miss: row "
        "rule, part 6 item 5, A3); first filing 98fe708c: set aside unread (0 rows, A2 item "
        "3).\nA3 records that all 240 rows exist. 1 do not. This goes into the deviation log.\n"
    ) in res.out
    # C3: the missing row is listed after the decision word, with run id, task, batch and arm
    task = W.batch_commits("click", 5)[0 if arm == "S1" else 4]
    listing = (f"Missing rows, each counted as a miss (REG 200-202):\n"
               f"  run {rid}  task {task}  click batch 5  arm {arm}\n")  # fmt: skip
    assert listing in res.out
    assert res.out.index(listing) > res.out.index("DECISION:")
    if arm == "S1":
        # the missing clean S1 row is a miss: U for click 5 falls from 2 to 1
        assert ("  click batch 5: n = 5; S = 1/2 = 0.5000; without usable test 1/10; "
                "author-hit no\n") in res.out  # fmt: skip
        assert "usable tests: 119 of 120 (nine in ten = 108)\n" in res.out
    else:
        assert ("  click batch 5: n = 5; S = 1 = 1.0000; without usable test 0/10; "
                "author-hit no\n") in res.out  # fmt: skip
        assert "usable tests: 120 of 120 (nine in ten = 108)\n" in res.out
    assert "DECISION:" in res.out
    for win in windows(rid):
        assert win not in res.out.split("DECISION:")[0]


def test_e5_page_total_breach(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    real = w.get

    def lying(path: str, query: Any) -> tuple[int, bytes]:
        status, body = real(path, query)
        if path == "/api/v1/grades":
            page = json.loads(body)
            page["total"] = 6
            body = json.dumps(page).encode()
        return status, body

    w.get = lying  # type: ignore[method-assign]
    res = run(w, monkeypatch, capsys)
    assert res.code == 4 and "read not made: E5 short page" in res.out
    # C2: every run not read is filed with its two served times
    text = w.deviation[0][1]
    assert text.startswith(f"{W.SCRIPT_NAME} stop: E5\n")
    filed = text.splitlines()[1:]
    assert len(filed) == 48
    for rid in w.ids.values():
        r = w.runs[rid]
        assert f"{rid} not read  created {r['created']}  finished {r['finished']}" in filed


# ---------------------------------------------------------------------------
# R12, author-hit batches and the sensitivity results
# ---------------------------------------------------------------------------


def make_author_hit_world() -> World:
    """click 2 (errors "authoring:"), click 3 (no start events) and cobra 1 (failed events)
    have 6 of 10 S1 attempts without a usable test; click 4 has 5 (not author-hit); the A0
    rows of cobra 6 carry "authoring:" errors, which R12 never reads."""
    w = make_world()

    def six(repo: str, b: int) -> list[tuple[str, str]]:
        s1a, s1b = w.s1_of(repo, b)
        tasks = W.batch_commits(repo, b)
        return [(s1a, c) for c in tasks] + [(s1b, tasks[4])]

    for rid, c in six("click", 2):
        next(r for r in w.grades[rid] if r["task_id"] == c)["error"] = AUTHORING
    for rid, c in six("click", 3):
        w.events[rid] = [e for e in w.events[rid] if e["payload"].get("task") != c]
    for rid, c in six("cobra", 1):
        w.events[rid].append({"seq": len(w.events[rid]) + 1,
                              "action": "builder.author_test.failed", "payload": {"task": c}})  # fmt: skip
    for rid, c in six("click", 4)[:5]:
        next(r for r in w.grades[rid] if r["task_id"] == c)["error"] = "authoring:no space"
    for rid in w.a0_of("cobra", 6):
        for r in w.grades[rid]:
            r["error"] = AUTHORING
    return w


def test_author_hit_blocks_and_left_out(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    res = run(make_author_hit_world(), monkeypatch, capsys)
    assert res.code == 0, res.out
    out = res.out
    for repo, b, k, hit in [("click", 2, 6, "yes"), ("click", 3, 6, "yes"), ("cobra", 1, 6, "yes"),
                            ("click", 4, 5, "no"), ("cobra", 6, 0, "no")]:  # fmt: skip
        assert re.search(
            rf"  {repo} batch {b}: .*without usable test {k}/10; author-hit {hit}\n", out
        )
    # usable = 120 - 6 - 6 - 6 - 5; clean rows among them: 3 + 2 + 2 + 3 (s1a's clean commits)
    assert "usable tests: 97 of 120 (nine in ten = 108)\n" in out
    assert "whose row is clean" not in out
    blocks = out[out.index("Blocks result:") : out.index("Left-out result:")]
    # click 2 and 3 are consecutive author-hit batches: one unit (U = 4 + 2, n = 10);
    # cobra 1 stands alone. B = 11, all units positive: m = 2 of 2048.
    # Q = 10 x 1/4 + 0 = 5/2, SE^2 = (11/10)(5/2)/3600 = 11/14400, t = 2.2282.
    assert "  units: click-1, click-2+click-3, click-4, click-5, click-6, cobra-1," in blocks
    assert "  units B = 11; commits N = 60\n" in blocks
    assert "  T = 18; d = 30.0000 points\n" in blocks
    assert "  m = 2 of 2^11 = 2048; p = 2/2048 = 0.0009765625; below 0.05: yes\n" in blocks
    assert "  interval: 23.8416 to 36.1584 points (t = 2.2282, df 10)\n" in blocks
    left = out[out.index("Left-out result:") : out.index("batches with a non-zero")]
    # left out: 9 batches, N = 45, T2 = 28, d = 14/45; Q = 20/9, SE^2 = 1/810, t = 2.3061
    assert (
        "  units: click-1, click-4, click-5, click-6, cobra-2, cobra-3, cobra-4, cobra-5, cobra-6\n"
        in left
    )
    assert "  units B = 9; commits N = 45\n" in left
    assert "  T = 14; d = 31.1111 points\n" in left
    assert "  m = 2 of 2^9 = 512; p = 2/512 = 0.00390625; below 0.05: yes\n" in left
    assert "  interval: 23.0083 to 39.2139 points (t = 2.3061, df 8)\n" in left
    assert "DECISION: Cleared (" in out


def test_usable_attempt_r12() -> None:
    c = W.LISTS[("click", "XS")][0]
    other = W.LISTS[("click", "XS")][1]
    row = W.Row(run_id="r", task_id=c, clean=True, error="")
    ev = W.Events(providers=["cerebras"], started=[c], failed=[])
    assert W.usable_attempt(row, ev, c)
    assert not W.usable_attempt(None, ev, c)  # (a) no row
    assert not W.usable_attempt(row, W.Events(started=[other]), c)  # (b) no start for it
    assert not W.usable_attempt(row, W.Events(started=[c], failed=[c]), c)  # (c)
    assert W.usable_attempt(row, W.Events(started=[c], failed=[other]), c)
    assert not W.usable_attempt(row, W.Events(started=[c], failed=[W.ABSENT]), c)  # unreadable
    assert not W.usable_attempt(row, W.Events(started=[c], failed=[None]), c)
    for err in ("authoring:x", "authoring: not RED", W.ABSENT, None, 3):
        assert not W.usable_attempt(W.Row("r", c, True, err), ev, c)  # (d)
    assert W.usable_attempt(W.Row("r", c, False, "Authoring: other case"), ev, c)
    assert W.usable_attempt(W.Row("r", c, False, "protocol violation: x"), ev, c)


def _br(repo: str, b: int, u: int, hit: bool) -> Any:
    diffs = (u, 0, 0, 0, 0)
    return W.BatchRead(repo, b, diffs, 6 if hit else 0)


def test_blocks_merge_only_consecutive_hits_within_a_repository() -> None:
    hits = {("click", 5), ("click", 6), ("cobra", 1), ("cobra", 2), ("cobra", 4)}
    batches = [_br(r, b, 1, (r, b) in hits) for r, b in W.BATCH_KEYS]
    units, labels = W.block_units(batches)
    assert labels == ["click-1", "click-2", "click-3", "click-4", "click-5+click-6",
                      "cobra-1+cobra-2", "cobra-3", "cobra-4", "cobra-5", "cobra-6"]  # fmt: skip
    assert units[4] == (2, 10) and len(units) == 10
    kept, klabels = W.leftout_units(batches)
    assert len(kept) == 7 and "cobra-4" not in klabels


def test_cannot_be_calculated() -> None:
    assert W.compute([], []) is None
    assert W.compute([(2, 5)], ["x"]) is None
    assert W.compute([(2, 5), (4, 5)], ["x", "y"]) is not None
    batches = [_br(r, b, 1, not (r == "cobra" and b == 6)) for r, b in W.BATCH_KEYS]
    assert W.compute(*W.leftout_units(batches)) is None  # one batch left
    units, _ = W.block_units(batches)
    assert len(units) == 3  # click 1-6 one unit, cobra 1-5 one unit, cobra 6


# ---------------------------------------------------------------------------
# the statistic
# ---------------------------------------------------------------------------


def _brute_m(us: list[int]) -> int:
    t = abs(sum(us))
    return sum(1 for e in product((1, -1), repeat=len(us))
               if abs(sum(a * b for a, b in zip(e, us, strict=True))) >= t)  # fmt: skip


def test_sign_flip_m_hand_counts() -> None:
    assert W.sign_flip_m([2] * 12) == 2
    # twelve units of 2 with one negative: |sum| = 20 needs at most one sign different from
    # the observed or all-flipped vector: 1 + 12 + 12 + 1 = 26
    assert W.sign_flip_m([2] * 11 + [-2]) == 26
    assert W.sign_flip_m([1, -1] * 6) == 4096  # T2 = 0: every vector counts
    assert W.sign_flip_m([3, 1]) == 2
    assert W.sign_flip_m([1, 1]) == 2  # {+,-} and {-,+} reach 0 < 2
    assert W.sign_flip_m([1, -1]) == 4  # T2 = 0


def test_sign_flip_m_small_cases_exact() -> None:
    assert W.sign_flip_m([1, 1]) == _brute_m([1, 1]) == 2
    assert W.sign_flip_m([0, 0, 0]) == 8


def test_boundary_204_below_205_not() -> None:
    assert W.below_005(204, 4096)
    assert not W.below_005(205, 4096)
    assert not W.below_005(206, 4096)
    assert W.below_005(102, 2048) and not W.below_005(103, 2048)
    # real unit vectors on each side: m = 204 is below 0.05, m = 206 is not (m is even
    # whenever T2 != 0, so m = 205 cannot arise from units; the predicate is tested above)
    low = [-7, -8, -3, -9, 3, 3, 4, -2, -3, -8, -7, -1]
    high = [3, -1, -7, -3, -4, -7, -6, -9, 4, -5, -6, 4]
    assert W.sign_flip_m(low) == _brute_m(low) == 204
    assert W.sign_flip_m(high) == _brute_m(high) == 206
    r_low = W.compute([(u, 5) for u in low], [str(i) for i in range(12)])
    r_high = W.compute([(u, 5) for u in high], [str(i) for i in range(12)])
    assert r_low.below and not r_high.below


def test_interval_and_p_formatting() -> None:
    r = W.compute([(2, 5), (4, 5)] * 6, [str(i) for i in range(12)])
    assert (r.t2, r.n, r.m, r.patterns) == (36, 60, 2, 4096)
    assert r.d == Fraction(3, 10)
    assert r.se2 == Fraction(1, 1100)
    assert r.t == Fraction("2.2010")
    assert W.interval(r) == ("23.3637", "36.6363")
    assert W.exact_decimal(26, 4096) == "0.00634765625"
    r0 = W.compute([(1, 5), (-1, 5)] * 6, [str(i) for i in range(12)])
    assert (r0.t2, r0.m, r0.se2) == (0, 4096, Fraction(1, 1100))
    assert W.interval(r0) == ("-6.6363", "6.6363")
    assert W.exact_decimal(4096, 4096) == "1"


def test_upper_end_below_15_points_both_sides() -> None:
    t = Fraction("2.2010")
    edge = (Fraction(15, 100) / t) ** 2  # t^2 SE^2 = 0.15^2 exactly
    assert not W.upper_end_below(Fraction(0), edge, t)
    assert W.upper_end_below(Fraction(0), edge * Fraction(999999, 1000000), t)
    assert not W.upper_end_below(Fraction(15, 100), Fraction(0), t)  # gap 0
    assert W.upper_end_below(Fraction(1499, 10000), Fraction(0), t)
    assert not W.upper_end_below(Fraction(2, 10), Fraction(0), t)
    d = Fraction(5, 100)
    gap_edge = ((Fraction(15, 100) - d) / t) ** 2
    assert not W.upper_end_below(d, gap_edge, t) and W.upper_end_below(
        d, gap_edge - Fraction(1, 10**12), t
    )


def _res(us: list[int], n: int = 5) -> Any:
    return W.compute([(u, n) for u in us], [str(i) for i in range(len(us))])


def test_decision_words_on_both_sides() -> None:
    null = _res([1, -1] * 6)  # T2 = 0, m = 4096, upper end 6.6363 points
    # No 15-point effect: nothing below, all upper ends below 15, >= 6 non-zero, usable >= 108
    assert W.decide(null, null, null, 12, 108)[0] == "No 15-point effect"
    word, why = W.decide(null, null, null, 12, 107)
    assert word == "Inconclusive" and "usable tests 107 of 120" in why
    assert W.decide(null, null, null, 6, 108)[0] == "No 15-point effect"
    word, why = W.decide(null, null, null, 5, 108)
    assert word == "Inconclusive" and "5 of 12 batches" in why
    # an upper end not below 15 points
    wide = _res([10, -10, 9, -9, 10, -10, 9, -9, 10, -10, 9, -9])
    assert wide.t2 == 0 and not wide.upper_below_15
    assert W.decide(wide, wide, wide, 12, 120)[0] == "Inconclusive"
    # Cleared needs all three below with S1 ahead
    up = _res([2, 4] * 6)
    assert W.decide(up, up, up, 12, 0)[0] == "Cleared"
    down = _res([-2, -4] * 6)
    word, why = W.decide(down, down, down, 12, 120)
    assert word == "Inconclusive" and "without S1 ahead" in why
    # item 1: a sensitivity result that cannot be calculated, or on the other side, or of
    # another sign (three signs: two zeros agree)
    assert W.decide(up, None, up, 12, 120) == (
        "Inconclusive",
        "the blocks result cannot be calculated",
    )
    assert W.decide(up, up, None, 12, 120)[1] == "the left-out result cannot be calculated"
    assert "other side of 0.05" in W.decide(up, null, up, 12, 120)[1]
    pos_null = _res([1, -1] * 5 + [1, 1])  # T2 = 2, not below
    assert "of the other sign" in W.decide(null, null, pos_null, 12, 120)[1]
    assert W.decide(null, null, null, 12, 120)[0] == "No 15-point effect"


def test_decision_t_zero_is_not_ahead() -> None:
    assert W.sgn(0) == 0 and W.sgn(-3) == -1 and W.sgn(5) == 1


# ---------------------------------------------------------------------------
# strict JSON, equality and paging
# ---------------------------------------------------------------------------


def test_json_equal_rules() -> None:
    assert W.json_equal(6, 6.0)
    assert not W.json_equal(True, 1) and not W.json_equal(1, True)
    assert W.json_equal(True, True)
    assert not W.json_equal("6", 6)
    assert not W.json_equal([1, 2], [2, 1])
    assert not W.json_equal({"a": 1}, {"a": 1, "b": None})
    assert W.json_equal({"a": [1, {"b": 0.5}]}, {"a": [1.0, {"b": 0.5}]})
    assert not W.json_equal(None, 0)


def test_strict_json() -> None:
    with pytest.raises(W.ShapeError):
        W.strict_json(b'{"a": 1, "a": 2}')
    with pytest.raises(W.ShapeError):
        W.strict_json(b"[NaN]")
    with pytest.raises(W.ShapeError):
        W.strict_json(b"\xff")
    assert W.strict_json(b'{"a": [1.5]}') == {"a": [1.5]}


def test_get_pages_reads_every_page_and_refuses_a_changed_total() -> None:
    items = list(range(1234))
    calls: list[Any] = []

    def get(path: str, query: Any) -> tuple[int, bytes]:
        q = dict(query)
        calls.append(q)
        off, lim = int(q["offset"]), int(q["limit"])
        return 200, json.dumps({"items": items[off : off + lim], "total": len(items)}).encode()

    assert W.get_pages(get, "/x", []) == items
    assert [c["offset"] for c in calls] == ["0", "500", "1000"]

    def changing(path: str, query: Any) -> tuple[int, bytes]:
        off = int(dict(query)["offset"])
        return 200, json.dumps({"items": items[off : off + 500], "total": 1234 + off}).encode()

    with pytest.raises(W.TransportError):
        W.get_pages(changing, "/x", [])


def test_default_getter_refuses_a_non_http_api() -> None:
    with pytest.raises(W.NotReadyError):
        W.make_urllib_getter("file:///etc", "u", "p")


def test_strict_json_refuses_out_of_range_and_too_deep() -> None:
    for raw in (b"[1e999]", b"[-1e999]", b'{"a": 1E400}', b"1" * 5000,
                b"[" * 100_000 + b"]" * 100_000):  # fmt: skip
        with pytest.raises(W.ShapeError):
            W.strict_json(raw)
    assert W.strict_json(b"[1e308, -0.0, 12345678901234567890]") == [
        1e308, -0.0, 12345678901234567890,
    ]  # fmt: skip


def test_json_equal_with_non_finite_numbers() -> None:
    inf, nan = float("inf"), float("nan")
    for a, b in ((inf, inf), (-inf, -inf), (nan, nan), (inf, 1), (1, nan), ([inf], [inf]),
                 ({"x": inf}, {"x": inf})):  # fmt: skip
        assert not W.json_equal(a, b)
        assert not W.num_equal(a, b) or not W.is_number(a)
    assert W.num_equal(6, 6.0) and W.json_equal({"x": [6]}, {"x": [6.0]})
    assert not W.num_equal(True, 1) and not W.num_equal("6", 6)


def test_check_ready_refuses_a_non_string_full_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_world()
    rec = w.recorded()
    pin_hashes(monkeypatch, rec)
    W.check_ready(rec)
    for bad in (12345, b"\x00" * 32, ["a"]):
        with pytest.raises(W.NotReadyError, match=r"FILE_SHA256\[plan\] does not agree"):
            W.check_ready(W.replace(rec, file_sha256={**rec.file_sha256, "plan": bad}))


@pytest.mark.parametrize(
    "change",
    ["batch-missing", "batch-string", "batch-list", "no-runs", "runs-object", "runs-null",
     "three-entries", "five-entries", "entry-no-body", "entry-no-slot", "entry-string"],
)  # fmt: skip
@pytest.mark.parametrize("role", ["plan", "pre_s3"])
def test_t3_plan_batch_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], change: str, role: str
) -> None:
    """A wave batch not shaped as wave4_post.py lines 127-130 write it fails closed."""
    w = make_world()
    doc = w.plan if role == "plan" else w.pre
    name = "cobra-4"
    entries = doc[name]["runs"]
    if change == "batch-missing":
        del doc[name]
    elif change == "batch-string":
        doc[name] = "cobra-4"
    elif change == "batch-list":
        doc[name] = entries
    elif change == "no-runs":
        del doc[name]["runs"]
    elif change == "runs-object":
        doc[name]["runs"] = {str(e["slot"]): e for e in entries}
    elif change == "runs-null":
        doc[name]["runs"] = None
    elif change == "three-entries":
        entries.pop()
    elif change == "five-entries":
        entries.append(copy.deepcopy(entries[0]))
    elif change == "entry-no-body":
        del entries[2]["body"]
    elif change == "entry-no-slot":
        del entries[2]["slot"]
    else:
        entries[2] = "LEAK-ENTRY"
    res = run(w, monkeypatch, capsys)
    if (role, change) == ("pre_s3", "batch-missing"):
        # K7: a wave batch absent from the copy from before S3 is a T2 failure, not T3
        assert_order_failed(res, "T2")
        for place in range(1, 5):
            assert f"  key cobra-4/{place} (absent from the copy from before S3)\n" in res.out
    else:
        assert_order_failed(res, "T3")
        assert "  reason: file shape not as recorded\n" in res.out
    assert W.NO_RECORD_READ + "\n" in res.out
    assert not w.opened


def test_s3_batches_are_not_opened(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The plan file also holds twelve S3 batches; the ruling (section 5) says they are not
    opened. The fixture's S3 batches are all malformed, and the run still passes; extra
    malformed top-level members do not change that, and none of them is printed."""
    w = make_world()
    assert set(s3_batches()) <= set(w.plan) and not set(s3_batches()) & set(w.pre)
    w.plan["click-s3-7"] = {"runs": [{"slot": "LEAK-S3", "body": None}] * 9}
    w.plan["zz-other"] = "LEAK-S3-OTHER"
    res = run(w, monkeypatch, capsys)
    assert res.code == 0
    no_leak(res.out + res.err)
    for name in [*s3_batches(), "click-s3-7", "zz-other"]:
        assert name not in res.out + res.err


@pytest.mark.parametrize(
    "label", ["LEAK-PLAN-ARM", None, 0, ["A0"], {"arm": "B"}, "A1", "A0", "a1"],
)  # fmt: skip
def test_plan_arm_label_is_never_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], label: Any
) -> None:
    """The plan entries' ``arm`` label may be garbage or contradict the body; the run passes
    the same, because the label is not read (ruling section 5)."""
    w = make_world()
    for doc in (w.plan, w.pre):
        for repo, b in W.BATCH_KEYS:
            for i, entry in enumerate(doc[f"{repo}-{b}"]["runs"]):
                entry["arm"] = label if i % 2 else ("A0" if label == "A1" else label)
    res = run(w, monkeypatch, capsys)
    assert res.code == 0
    no_leak(res.out + res.err)


def test_plan_arm_label_removed_or_differing_between_copies_still_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    for repo, b in W.BATCH_KEYS:
        for entry in w.plan[f"{repo}-{b}"]["runs"]:
            del entry["arm"]
        for entry in w.pre[f"{repo}-{b}"]["runs"]:
            entry["arm"] = "LEAK-PRE-ARM"
        w.plan[f"{repo}-{b}"]["cell"] = ["LEAK-CELL-CHANGED"]
        w.pre[f"{repo}-{b}"]["order"] = None
    assert run(w, monkeypatch, capsys).code == 0


def test_run_record_with_an_out_of_range_number_is_a_request_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    rid = w.key_id("cobra", 2, 3)
    real = w.get

    def overflow(path: str, query: Any) -> tuple[int, bytes]:
        status, body = real(path, query)
        if path == f"/api/v1/runs/{rid}":
            body = body.replace(b'"max_cost_usd": 6', b'"max_cost_usd": 1e999')
            assert b"1e999" in body
        return status, body

    w.get = overflow  # type: ignore[method-assign]
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "request")
    assert f"  run {rid}  created NOT KEPT  finished NOT KEPT\n" in res.out


@pytest.mark.parametrize("api", ["file:///fixture", "ftp://fixture.invalid", "http://",
                                 "fixture.invalid", "http://fix ture.invalid", "HTTP:x"])  # fmt: skip
def test_api_scheme_checked_before_any_file_is_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], api: str
) -> None:
    w = make_world()
    argv = list(ARGV)
    argv[argv.index("--api") + 1] = api
    res = run(w, monkeypatch, capsys, argv=argv)
    assert res.code == 1
    assert "not ready: api is not an http(s) URL\n" in res.out
    assert not w.reads and not w.opened and not w.calls
    # the same with the default getter factory: still refused before the login file is read
    buf = io.StringIO()
    code = W.main(argv, read_file=w.read_file, write_deviation=w.write_deviation,
                  path_exists=lambda _p: False, stdout=buf, recorded=w.recorded(),
                  self_bytes=b"x")  # fmt: skip
    assert code == 1 and "not ready: api is not an http(s) URL\n" in buf.getvalue()
    assert not w.reads


# ---------------------------------------------------------------------------
# the default getter through a fake opener (no socket is opened)
# ---------------------------------------------------------------------------


class _Headers:
    def __init__(self, cookies: list[str]) -> None:
        self.cookies = cookies

    def get_all(self, name: str) -> list[str] | None:
        return list(self.cookies) if name == "Set-Cookie" and self.cookies else None


class _Resp:
    def __init__(self, status: int, body: bytes, cookies: list[str] = (),  # type: ignore[assignment]
                 read_error: BaseException | None = None) -> None:  # fmt: skip
        self.status, self.body, self.headers = status, body, _Headers(list(cookies))
        self.read_error = read_error

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_a: Any) -> None:
        return None

    def read(self) -> bytes:
        if self.read_error is not None:
            raise self.read_error
        return self.body


class FakeOpener:
    """Stands in for ``urllib.request.build_opener``'s result. ``route(req)`` answers each
    request with a ``_Resp`` or raises; every request is logged."""

    def __init__(self, route: Any) -> None:
        self.route = route
        self.handlers: tuple[Any, ...] = ()
        self.log: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def build(self, *handlers: Any) -> FakeOpener:
        self.handlers = handlers
        return self

    def open(self, req: urllib.request.Request, timeout: float | None = None) -> _Resp:
        assert timeout == 60
        hdrs = {k.lower(): v for k, v in req.header_items()}
        self.log.append((req.get_method(), req.full_url, hdrs, req.data))  # type: ignore[arg-type]
        return self.route(req)


def _fake(monkeypatch: pytest.MonkeyPatch, route: Any) -> FakeOpener:
    fake = FakeOpener(route)
    monkeypatch.setattr(urllib.request, "build_opener", fake.build)

    def no_socket(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a socket was opened")

    monkeypatch.setattr(socket.socket, "connect", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    return fake


def _signin_ok(req: urllib.request.Request) -> _Resp:
    if req.full_url.endswith("/api/v1/auth/login"):
        return _Resp(200, b"{}", ["crb_session=fixture-cookie; Path=/; HttpOnly", "other=1"])
    return _Resp(200, b'{"ok": true}')


def test_default_getter_signs_in_once_then_sends_the_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake(monkeypatch, _signin_ok)
    get = W.make_urllib_getter(API + "/", "fixture-user", PASSWORD)
    assert not fake.log  # nothing is sent until the first GET
    assert get("/api/v1/x", [("limit", "2"), ("offset", "0")]) == (200, b'{"ok": true}')
    assert get("/api/v1/y", []) == (200, b'{"ok": true}')
    (m0, u0, h0, d0), (m1, u1, h1, _), (m2, u2, h2, _) = fake.log
    assert (m0, u0) == ("POST", API + "/api/v1/auth/login")
    assert json.loads(d0 or b"") == {"username": "fixture-user", "password": PASSWORD}
    assert h0["content-type"] == "application/json"
    assert (m1, u1) == ("GET", API + "/api/v1/x?limit=2&offset=0")
    assert (m2, u2) == ("GET", API + "/api/v1/y")
    assert h1["cookie"] == h2["cookie"] == "crb_session=fixture-cookie; other=1"
    # the one handler refuses redirects
    (handler,) = fake.handlers
    assert isinstance(handler, urllib.request.HTTPRedirectHandler)
    assert handler.redirect_request() is None


def test_default_getter_sign_in_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(req: urllib.request.Request) -> _Resp:
        raise urllib.error.HTTPError(req.full_url, 401, "LEAK-reason", None, None)  # type: ignore[arg-type]

    fake = _fake(monkeypatch, refuse)
    get = W.make_urllib_getter(API, "fixture-user", PASSWORD)
    with pytest.raises(W.TransportError) as exc:
        get("/api/v1/x", [])
    assert str(exc.value) == "sign-in answered 401"
    assert len(fake.log) == 1  # no GET is sent without a session


def test_default_getter_returns_a_redirect_as_its_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def route(req: urllib.request.Request) -> _Resp:
        if req.full_url.endswith("/api/v1/x"):
            raise urllib.error.HTTPError(req.full_url, 307, "LEAK-redirect", None, None)  # type: ignore[arg-type]
        return _signin_ok(req)

    _fake(monkeypatch, route)
    get = W.make_urllib_getter(API, "fixture-user", PASSWORD)
    assert get("/api/v1/x", []) == (307, b"")
    with pytest.raises(W.TransportError) as exc:
        W.get_json(get, "/api/v1/x")
    assert "LEAK" not in str(exc.value)


DROPS: dict[str, Any] = {
    "incomplete_read": lambda: http.client.IncompleteRead(b"LEAK-partial"),
    "bad_status_line": lambda: http.client.BadStatusLine("LEAK-xyz"),
    "remote_disconnected": lambda: http.client.RemoteDisconnected("LEAK-gone"),
    "url_error": lambda: urllib.error.URLError("LEAK-refused"),
    "timeout": lambda: TimeoutError("LEAK-timeout"),
    "reset": lambda: ConnectionResetError("LEAK-reset"),
    "value_error": lambda: ValueError("LEAK-value"),
}


@pytest.mark.parametrize("where", ["open", "read"])
@pytest.mark.parametrize("drop", sorted(DROPS))
def test_default_getter_turns_every_drop_into_connection_failed(
    monkeypatch: pytest.MonkeyPatch, drop: str, where: str
) -> None:
    def route(req: urllib.request.Request) -> _Resp:
        if not req.full_url.endswith("/api/v1/x"):
            return _signin_ok(req)
        if where == "open":
            raise DROPS[drop]()
        return _Resp(200, b"", read_error=DROPS[drop]())

    _fake(monkeypatch, route)
    get = W.make_urllib_getter(API, "fixture-user", PASSWORD)
    with pytest.raises(W.TransportError) as exc:
        get("/api/v1/x", [])
    assert str(exc.value) == "connection failed"


@pytest.mark.parametrize("drop", ["incomplete_read", "bad_status_line"])
def test_default_getter_drop_at_sign_in(monkeypatch: pytest.MonkeyPatch, drop: str) -> None:
    def route(_req: urllib.request.Request) -> _Resp:
        raise DROPS[drop]()

    _fake(monkeypatch, route)
    with pytest.raises(W.TransportError) as exc:
        W.make_urllib_getter(API, "fixture-user", PASSWORD)("/api/v1/x", [])
    assert str(exc.value) == "connection failed"


def _route_world(w: World, drop_path: str | None, drop: str) -> Any:
    """Serve the made-up world through the fake opener; ``drop_path`` raises the drop."""

    def route(req: urllib.request.Request) -> _Resp:
        parts = urllib.parse.urlsplit(req.full_url)
        if parts.path == "/api/v1/auth/login":
            return _signin_ok(req)
        assert {k.lower(): v for k, v in req.header_items()}["cookie"] == (
            "crb_session=fixture-cookie; other=1"
        )
        query = urllib.parse.parse_qsl(parts.query)
        key = parts.path + ("?" + dict(query)["run_id"] if "run_id" in dict(query) else "")
        if key == drop_path:
            raise DROPS[drop]()
        status, body = w.get(parts.path, query)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", None, None)  # type: ignore[arg-type]
        return _Resp(status, body)

    return route


def run_default(w: World, monkeypatch: pytest.MonkeyPatch, drop_path: str | None,
                drop: str = "bad_status_line") -> Res:  # fmt: skip
    """``main`` with the default getter factory, served through the fake opener."""
    for log in (w.calls, w.opened, w.reads, w.deviation, w.outputs):
        log.clear()
    rec = w.recorded()
    pin_hashes(monkeypatch, rec)
    _fake(monkeypatch, _route_world(w, drop_path, drop))
    buf = io.StringIO()
    code = W.main(list(ARGV), read_file=w.read_file, write_deviation=w.write_deviation,
                  open_output=w.open_output, path_exists=lambda _p: False, stdout=buf,
                  recorded=rec, self_bytes=b"fixture-self")  # fmt: skip
    check_output_file(w, buf.getvalue())
    return Res(code, buf.getvalue(), "", w)


def test_main_with_default_getter_passes_through_the_fake_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    res = run_default(make_world(), monkeypatch, None)
    assert res.code == 0, res.out
    assert "DECISION: Cleared (" in res.out


@pytest.mark.parametrize("drop", ["incomplete_read", "bad_status_line", "timeout"])
def test_main_drop_before_the_pass_is_an_order_check_failure(
    monkeypatch: pytest.MonkeyPatch, drop: str
) -> None:
    w = make_world()
    rid = w.key_id("cobra", 4, 1)
    res = run_default(w, monkeypatch, f"/api/v1/runs/{rid}", drop)
    assert_order_failed(res, "request")
    assert "  reason: order-check request: connection failed\n" in res.out
    assert f"  run {rid}  created NOT KEPT  finished NOT KEPT\n" in res.out
    assert "Traceback" not in res.out


@pytest.mark.parametrize("drop", ["incomplete_read", "bad_status_line"])
def test_main_drop_in_e4_or_e5_is_read_not_made(monkeypatch: pytest.MonkeyPatch, drop: str) -> None:
    w = make_world()
    rid = w.s1_of("click", 6)[0]
    res = run_default(w, monkeypatch, f"/api/v1/runs/{rid}/events/log", drop)
    assert res.code == 4, res.out
    assert res.out.splitlines()[-1] == "read not made: E4 connection failed"
    assert len(w.deviation) == 1 and w.deviation[0][0] == DEV
    # K8: only the run whose events failed is filed, with its two times (C2)
    r = w.runs[rid]
    assert w.deviation[0][1] == (
        f"{W.SCRIPT_NAME} stop: E4\n{rid} not read  "
        f"created {r['created']}  finished {r['finished']}\n"
    )
    no_leak(res.out)
    w = make_world()
    rid = w.a0_of("cobra", 2)[1]
    res = run_default(w, monkeypatch, f"/api/v1/grades?{rid}", drop)
    assert res.code == 4, res.out
    assert res.out.splitlines()[-1] == "read not made: E5 connection failed"
    assert f"{rid} not read" in w.deviation[0][1]
    assert "DECISION:" not in res.out
    for win in windows(rid):
        assert win not in res.out


# ---------------------------------------------------------------------------
# the delivery manager's changes: C1, C6, K1, K3, K4, K5 (K10 reverted), K6;
# deviation write errors; E5 order
# ---------------------------------------------------------------------------


def test_c1_no_record_line_on_a_t2_stop_and_not_after_a_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    w.bodies("click-4/2")[1]["max_cost_usd"] = 7
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T2")
    assert res.out.endswith(f"{W.NO_RECORD_READ}\n{W.FAIL_FOOTER}\n")
    assert res.out.count(W.NO_RECORD_READ) == 1
    # a stop after the first request (T4 here) does not carry the line
    w = make_world()
    w.out_entry(W.ATTEMPT1_KEY)["run"]["id"] = w.key_id("click", 3, 1)
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T4")
    assert W.NO_RECORD_READ not in res.out


@pytest.mark.parametrize("bad", ["XYZ-not-a-run-id", "abc123", "LEAK-" + "0" * 27,
                                 "0" * 31 + "G", "A" * 32, "a" * 32 + "\n"])  # fmt: skip
def test_c6_a_malformed_out_value_reaches_neither_screen_nor_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    w = make_world()
    for key in ("cobra-6/3", W.ATTEMPT1_KEY):
        w = make_world()
        w.out_entry(key)["run"]["id"] = bad
        res = run(w, monkeypatch, capsys)
        assert_order_failed(res, "T4")
        assert f"  reason: the value under key {key} is not a full run id\n" in res.out
        assert bad not in res.out + res.err
        assert not w.deviation
        for f in w.outputs.values():
            assert bad not in (f.closed_text or "")


def test_k1_output_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for err, message in (
        (FileExistsError(17, "exists", OUTF), "output file already exists (--output)"),
        (PermissionError(13, "denied", OUTF), "output file cannot be created (--output)"),
        (FileNotFoundError(2, "no dir", OUTF), "output file cannot be created (--output)"),
    ):
        w = make_world()
        w.output_error = err
        res = run(w, monkeypatch, capsys)
        assert res.code == 1, res.out
        assert res.out.splitlines()[-1] == f"not ready: {message}"
        assert OUTF not in res.out and "Traceback" not in res.out + res.err
        assert not w.opened and not w.calls and w.reads == [LOGIN]


def test_k1_output_and_deviation_out_must_differ(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    argv = list(ARGV)
    argv[argv.index("--output") + 1] = "/fixture/../fixture/deviation.txt"
    res = run(w, monkeypatch, capsys, argv=argv)
    assert res.code == 1
    assert "not ready: output and deviation-out name the same file\n" in res.out
    assert not w.outputs and not w.reads and not w.opened


def test_k1_output_is_required() -> None:
    argv = [a for a in ARGV if a not in ("--output", OUTF)]
    with pytest.raises(SystemExit) as exc:
        W.parse_args(argv)
    assert exc.value.code == 1  # not ready (the parser's exit; 2 is test (i))


def test_k1_not_ready_creates_no_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    res = run(w, monkeypatch, capsys, exists=True)
    assert res.code == 1 and not w.outputs


def test_k1_default_open_output_is_new_0600_and_byte_identical(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    outp = tmp_path / "read.txt"
    w = make_world()
    rec = w.recorded()
    pin_hashes(monkeypatch, rec)
    argv = list(ARGV)
    argv[argv.index("--output") + 1] = str(outp)
    buf = io.StringIO()
    code = W.main(argv, read_file=w.read_file, open_getter=w.open_getter,
                  write_deviation=w.write_deviation, path_exists=lambda _p: False,
                  stdout=buf, recorded=rec, self_bytes=b"fixture-self")  # fmt: skip
    assert code == 0, buf.getvalue()
    assert outp.read_bytes() == buf.getvalue().encode()
    assert stat.S_IMODE(outp.stat().st_mode) == 0o600
    # a second run is refused: the file exists; nothing is read but the login file
    w.reads.clear()
    buf = io.StringIO()
    code = W.main(argv, read_file=w.read_file, open_getter=w.open_getter,
                  write_deviation=w.write_deviation, path_exists=lambda _p: False,
                  stdout=buf, recorded=rec, self_bytes=b"fixture-self")  # fmt: skip
    assert code == 1
    assert buf.getvalue().splitlines()[-1] == "not ready: output file already exists (--output)"
    assert w.reads == [LOGIN]
    assert outp.read_bytes().count(b"DECISION:") == 1
    # a folder that does not exist: cannot be created
    argv[argv.index("--output") + 1] = str(tmp_path / "absent" / "read.txt")
    buf = io.StringIO()
    code = W.main(argv, read_file=w.read_file, open_getter=w.open_getter,
                  write_deviation=w.write_deviation, path_exists=lambda _p: False,
                  stdout=buf, recorded=rec, self_bytes=b"fixture-self")  # fmt: skip
    assert code == 1
    assert buf.getvalue().splitlines()[-1] == "not ready: output file cannot be created (--output)"


def test_k1_default_open_output_refuses_an_existing_file(tmp_path: Path) -> None:
    outp = tmp_path / "x.txt"
    f = W._open_output(str(outp))
    f.write("a\r\nb\n")
    f.close()
    assert outp.read_bytes() == b"a\r\nb\n"  # no newline translation
    with pytest.raises(FileExistsError):
        W._open_output(str(outp))
    link = tmp_path / "link.txt"
    link.symlink_to(tmp_path / "target.txt")
    with pytest.raises(FileExistsError):
        W._open_output(str(link))
    assert not (tmp_path / "target.txt").exists()


def test_k3_login_file_not_readable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    real = w.read_file

    def refusing(path: str) -> bytes:
        if path == LOGIN:
            raise PermissionError(13, "Permission denied", path)
        return real(path)

    w.read_file = refusing  # type: ignore[method-assign]
    res = run(w, monkeypatch, capsys)
    assert res.code == 1
    assert res.out.splitlines()[-1] == "not ready: login file not readable"
    assert LOGIN not in res.out + res.err and "Traceback" not in res.out + res.err
    assert not w.outputs and not w.opened and not w.calls


def test_k4_standing_ids_must_match_their_recorded_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world()
    res = run(w, monkeypatch, capsys, pin_ids=False)  # the shipped hash, the made-up ids
    assert res.code == 1
    assert res.out.splitlines()[-1] == (
        "not ready: STANDING_IDS does not match STANDING_IDS_SHA256"
    )
    assert not w.reads and not w.outputs and not w.opened
    # one id changed: the 48-id check passes, the hash check refuses
    rec = w.recorded()
    pin_hashes(monkeypatch, rec)
    ids = set(rec.standing_ids)
    ids.remove(next(iter(sorted(ids))))
    ids.add(fid("swapped-in"))
    with pytest.raises(W.NotReadyError, match="does not match STANDING_IDS_SHA256"):
        W.check_ready(W.replace(rec, standing_ids=frozenset(ids)))


def test_k5_full_from_the_fixed_list_times_kept_for_every_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """K10 reverted: every record read keeps created and finished, so a failure naming a run
    outside the 49 prints its two served times. K5 kept: an out-file value naming that run
    does not make it full (status, row count and echo fields stay dropped)."""
    w = make_world()
    w.out_entry("cobra-6/4")["run"]["id"] = EXTRA_UNLISTED
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T4")
    assert run_line(res, EXTRA_UNLISTED) + "\n" in res.out
    assert f"  run {EXTRA_UNLISTED}  created NOT KEPT" not in res.out
    # a standing run named by the same failure keeps its two times too
    rid = w.key_id("cobra", 6, 4)
    assert run_line(res, rid) + "\n" in res.out
    # extract_run keeps the two times of any record; only a full one keeps the rest
    doc = w.runs[EXTRA_UNLISTED] | {"counts": {"rows": 5, "clean": 987654}, "error": "LEAK-E"}
    kept = W.extract_run(doc, full=False)
    assert (kept.created, kept.finished) == (doc["created"], doc["finished"])
    for name in ("status", "rows", "repo", "builder", "model", "provider", "budget",
                 "max_cost_usd", "builder_config", "retain"):  # fmt: skip
        assert getattr(kept, name) is W.ABSENT, name
    assert kept.h_present == frozenset()
    full = W.extract_run(doc, full=True)
    assert (full.created, full.finished) == (doc["created"], doc["finished"])
    assert full.status == doc["status"] and full.rows == 5
    no_leak(repr(kept) + repr(full))
    # NOT KEPT only when no record was fetched for that id
    assert W._times(None) == "created NOT KEPT  finished NOT KEPT"
    assert W._times(kept) == f"created {doc['created']}  finished {doc['finished']}"
    bare = W.extract_run({"id": EXTRA_UNLISTED}, full=False)
    assert W._times(bare) == "created ABSENT  finished ABSENT"


def _stop_world(stop: str) -> World:
    """A made-up wave that passes the order check and stops at ``stop`` (writes a deviation)."""
    w = make_world()
    if stop == "E4":
        w.fail[f"/api/v1/runs/{w.s1_of('cobra', 3)[0]}/events/log"] = 500
    elif stop == "provider test":
        rid = w.s1_of("click", 1)[0]
        w.events[rid] = [e for e in w.events[rid] if e["action"] != "author.attempt"]
    elif stop == "E5":
        w.fail["/api/v1/grades"] = 500
    else:
        w.grades[w.a0_of("click", 5)[0]][2]["clean"] = "true"
    return w


STOP_CODES = {"E4": 4, "provider test": 3, "E5": 4, "row integrity": 4}


@pytest.mark.parametrize("stop", list(STOP_CODES))
@pytest.mark.parametrize(
    "err",
    [PermissionError(13, "Permission denied", DEV), FileExistsError(17, "File exists", DEV),
     FileNotFoundError(2, "No such file", DEV), OSError(28, "No space left on device", DEV)],
)  # fmt: skip
def test_deviation_write_error_prints_one_line_and_keeps_the_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stop: str, err: OSError
) -> None:
    w = _stop_world(stop)
    tried: list[str] = []

    def refusing(path: str, text: str) -> None:
        tried.append(text)
        raise err

    w.write_deviation = refusing  # type: ignore[method-assign]
    res = run(w, monkeypatch, capsys)  # also checks the output file equals stdout
    assert res.code == STOP_CODES[stop], res.out
    assert tried and tried[0].startswith(f"{W.SCRIPT_NAME} stop: {stop}\n")
    assert res.out.splitlines()[-1] == W.DEVIATION_NOT_WRITTEN
    assert res.out.count(W.DEVIATION_NOT_WRITTEN) == 1
    assert DEV not in res.out + res.err and "Traceback" not in res.out + res.err
    assert "DECISION:" not in res.out
    no_leak(res.out + res.err)


@pytest.mark.parametrize("where", ["no_folder", "exists"])
def test_deviation_default_writer_error_is_caught(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path,
    where: str,
) -> None:  # fmt: skip
    """The default writer (O_EXCL, 0600): a folder that does not exist, or a file made after
    the not-ready check, is caught, not raised; the existing file is left as it was."""
    dev = tmp_path / ("absent" if where == "no_folder" else "") / "deviation.txt"
    if where == "exists":
        dev.write_text("before\n")
    w = _stop_world("E4")
    rec = w.recorded()
    pin_hashes(monkeypatch, rec)
    argv = list(ARGV)
    argv[argv.index("--deviation-out") + 1] = str(dev)
    buf = io.StringIO()
    code = W.main(argv, read_file=w.read_file, open_getter=w.open_getter,
                  open_output=w.open_output, path_exists=lambda _p: False, stdout=buf,
                  recorded=rec, self_bytes=b"fixture-self")  # fmt: skip
    check_output_file(w, buf.getvalue())
    out = buf.getvalue() + capsys.readouterr().err
    assert code == 4
    tail = ["read not made: E4 GET answered 500", W.DEVIATION_NOT_WRITTEN]
    assert buf.getvalue().splitlines()[-2:] == tail
    assert str(dev) not in out and str(tmp_path) not in out and "Traceback" not in out
    if where == "exists":
        assert dev.read_text() == "before\n"
    else:
        assert not dev.parent.exists()


def test_e5_requests_and_filed_list_are_in_sorted_id_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """E5 asks for rows in run id order and files the runs not yet read in run id order, so
    neither the request order nor the filed list shows an arm, a batch or a slot."""
    w = make_world()
    by_id = sorted(w.ids.values())
    by_slot = [w.key_id(r, b, p) for r, b, p in plain_keys()]
    by_arm = sorted(by_id, key=lambda i: w.arm[i])
    assert by_id not in (by_slot, by_arm)  # the fixture's orders differ, so the test bites
    k = 20
    target = by_id[k]
    real = w.get

    def failing(path: str, query: Any) -> tuple[int, bytes]:
        if path == "/api/v1/grades" and dict(query)["run_id"] == target:
            w.calls.append((path, tuple(query)))
            return 500, b""
        return real(path, query)

    w.get = failing  # type: ignore[method-assign]
    res = run(w, monkeypatch, capsys)
    assert res.code == 4 and "read not made: E5 GET answered 500" in res.out
    asked: list[str] = []
    for p, q in w.calls:
        rid = dict(q).get("run_id") if p == "/api/v1/grades" else None
        if rid is not None and (not asked or asked[-1] != rid):
            asked.append(rid)
    assert asked == by_id[: k + 1]
    lines = w.deviation[0][1].splitlines()
    assert lines[0] == f"{W.SCRIPT_NAME} stop: E5"
    filed = [ln.split()[0] for ln in lines[1:]]
    assert filed == by_id[k:] == sorted(filed)


@pytest.mark.parametrize("where", ["entry", "run"])
@pytest.mark.parametrize("change", ["extra", "missing"])
def test_k6_out_key_names_must_be_the_recorded_ones(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], where: str, change: str
) -> None:
    w = make_world()
    entry = w.out_entry("click-2/1")
    target = entry if where == "entry" else entry["run"]
    if change == "extra":
        target["LEAK-EXTRA"] = "LEAK-EXTRA"
    else:
        del target["posted" if where == "entry" else "cost_usd"]
    res = run(w, monkeypatch, capsys)
    assert_order_failed(res, "T3")
    assert "  reason: file shape not as recorded\n" in res.out
    assert not w.opened
    with pytest.raises(W.ShapeError, match=f"out {where} keys are not the recorded ones"):
        W.extract_out({"click-2/1": entry})


# ---------------------------------------------------------------------------
# the source: no path to the poster's folder, no request but through the getter
# ---------------------------------------------------------------------------


def test_source_holds_no_path_to_the_wave4_folder() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    for bad in ("~/wave4", "wave4/", "/Users/", "crb-backups", "crb-stack", "127.0.0.1"):
        assert bad not in src, bad


def test_network_code_lives_only_in_the_default_getter() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    getter = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "make_urllib_getter")  # fmt: skip
    inside = {id(n) for n in ast.walk(getter)}
    banned_mods = {"urllib", "http", "socket", "requests", "httpx", "ssl"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            if any(n.split(".")[0] in banned_mods for n in names):
                assert id(node) in inside, ast.dump(node)
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in {
                "urlopen",
                "build_opener",
                "Request",
                "HTTPConnection",
                "create_connection",
            }:
                assert id(node) in inside, ast.dump(node)
            if isinstance(f, ast.Attribute) and f.attr == "open" and isinstance(f.value, ast.Name):
                assert f.value.id == "os" or id(node) in inside, ast.dump(node)


def test_pass_wave_makes_no_request_but_through_the_injected_getter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a request outside the injected getter")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    w = make_world()
    res = run(w, monkeypatch, capsys)
    assert res.code == 0
    assert w.opened == [API]
    assert all(p.startswith("/api/v1/") for p, _ in w.calls)


# ---------------------------------------------------------------------------
# the --output file fails after it was opened: exit 5, nothing printed that is not filed
# ---------------------------------------------------------------------------


class _FailingFile:
    """An output file that takes ``good`` writes, then raises; ``close`` may raise too."""

    def __init__(self, good: int, *, close_fails: bool = False) -> None:
        self.good = good
        self.close_fails = close_fails
        self.text = ""
        self.closed = 0

    def write(self, text: str) -> int:
        if self.good <= 0:
            raise OSError(28, "No space left on device", "/secret/dir/read.txt")
        self.good -= 1
        self.text += text
        return len(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed += 1
        if self.close_fails:
            raise OSError(5, "Input/output error", "/secret/dir/read.txt")


def _run_with_file(monkeypatch: pytest.MonkeyPatch, fh: _FailingFile) -> tuple[int, str]:
    w = make_world()
    rec = w.recorded()
    pin_hashes(monkeypatch, rec)
    buf = io.StringIO()
    code = W.main(list(ARGV), read_file=w.read_file, open_getter=w.open_getter,
                  write_deviation=w.write_deviation, open_output=lambda _p: fh,
                  path_exists=lambda _p: False, stdout=buf, recorded=rec,
                  self_bytes=b"fixture-self")  # fmt: skip
    return code, buf.getvalue()


def _full_run_lines(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    fh = _FailingFile(10**6)
    code, text = _run_with_file(monkeypatch, fh)
    assert code == 0 and fh.text == text
    return text.splitlines(keepends=True)


def test_output_write_failure_stops_with_exit_5_and_prints_no_unfiled_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full = _full_run_lines(monkeypatch)
    # the first write is the held lines in one piece; each later write is one line
    for good in (0, 1, 3, len(full) - 3):
        fh = _FailingFile(good)
        code, text = _run_with_file(monkeypatch, fh)
        assert code == 5
        lines = text.splitlines(keepends=True)
        assert lines[-1] == W.OUTPUT_NOT_WRITTEN + "\n"
        # after the file is attached, stdout holds exactly what the file holds
        if good:
            assert "".join(lines[:-1]) == fh.text
        assert "/secret" not in text and "No space" not in text and "Traceback" not in text
        assert fh.closed == 1


def test_output_failure_before_the_result_prints_no_result_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full = _full_run_lines(monkeypatch)
    passed = next(i for i, ln in enumerate(full) if ln.startswith("Order check passed."))
    # the first line written after the file is attached
    held = next(i for i, ln in enumerate(full) if ln.startswith("input "))
    fh = _FailingFile(1 + passed - held + 1)  # fails on the line after "Order check passed."
    code, text = _run_with_file(monkeypatch, fh)
    assert code == 5
    assert "DECISION:" not in text
    assert text == fh.text + W.OUTPUT_NOT_WRITTEN + "\n"


def test_output_close_failure_is_exit_5_with_one_fixed_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fh = _FailingFile(10**6, close_fails=True)
    code, text = _run_with_file(monkeypatch, fh)
    assert code == 5
    assert text == fh.text + W.OUTPUT_NOT_WRITTEN + "\n"
    assert "/secret" not in text and fh.closed == 1


def test_output_write_and_close_both_failing_is_still_exit_5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fh = _FailingFile(2, close_fails=True)
    code, text = _run_with_file(monkeypatch, fh)
    assert code == 5
    assert text.count(W.OUTPUT_NOT_WRITTEN) == 1 and fh.closed == 1
