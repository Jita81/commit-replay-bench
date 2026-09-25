"""A configured builder endpoint is the endpoint the builder calls: every OpenAI-compatible
builder (tool loop, edit block, labeller) is pointed by ``CRB_OPENAI_BASE_URL`` at a fake
OpenAI-compatible server on localhost — no real model — and the request must land there,
the row must carry that host as its provider, and the timeout and retry settings must be
the ones the operator set.

Navigation
----------
What it is:   The endpoint-resolution test suite (product.truth.26, G-610) — a small
              threaded HTTP server that answers ``POST /v1/chat/completions`` like an
              OpenAI-compatible model, and the builders run against it through the real
              ``openai`` client.
What it does: Pins that ``EndpointConfig.from_env`` reads ``CRB_OPENAI_TIMEOUT_S`` /
              ``CRB_OPENAI_MAX_TOKENS`` / ``CRB_OPENAI_MAX_RETRIES`` with stated defaults and
              refuses a bad value by name; that the tool loop, the edit-block builder and the
              labeller send their request to the configured base URL and stamp its host as
              the provider (never a silent ``cerebras``); that a rung naming a different
              provider is refused before anything is built; that a response slower than the
              configured timeout fails and one inside it succeeds; and that the retry count
              is the configured one.
How:          ``FakeModel`` (``http.server`` on 127.0.0.1:0) records each request's path and
              JSON body and replies after an optional delay; ``_point_at`` sets the
              ``CRB_OPENAI_*`` variables (and a throwaway key under a test-only name) with
              monkeypatch; ``fixtures.builders_repo`` supplies the workspace for real builds.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/openai_client.py (``resolve_endpoint``, ``from_env``,
              ``make_chat`` — under test), src/crb/builders/openai_agent.py and
              src/crb/builders/editblock.py (the builders that must call the configured
              endpoint), src/crb/builders/labeller.py (the labeller id's provider),
              src/crb/builders/__init__.py (``builder_for_rung`` — where a mismatch is
              refused), tests/fixtures/builders_repo.py (the workspace)
Tested by:    tests/test_builders_endpoint.py
Touch when:   a new ``CRB_OPENAI_*`` variable is read (a default case and a refusal case);
              a new OpenAI-compatible builder is registered (a "lands on the fake" case).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from crb.builders import base, builder_for_rung
from crb.builders import openai_client as oc
from crb.builders.editblock import EditBlockBuilder
from crb.builders.labeller import OpenAILabeller
from crb.builders.openai_agent import OpenAIAgentBuilder
from crb.core.classify import PathStat

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))
from builders_repo import make_fixture  # noqa: E402

pytest.importorskip("openai")

_ENV_NAMES = (
    "CRB_OPENAI_BASE_URL",
    "CRB_OPENAI_KEY_ENV",
    "CRB_OPENAI_TIMEOUT_S",
    "CRB_OPENAI_MAX_TOKENS",
    "CRB_OPENAI_MAX_RETRIES",
    "CRB_AZURE_ENDPOINT",
    "CRB_AZURE_DEPLOYMENT",
    "CRB_AZURE_API_VERSION",
    "CRB_AZURE_KEY_ENV",
)
_KEY_ENV = "CRB_TEST_FAKE_MODEL_KEY"  # a test-only name; the value is not a credential


class FakeModel:
    """An OpenAI-compatible ``/v1/chat/completions`` on 127.0.0.1 that records requests."""

    def __init__(self, *, reply: str = "done", delay_s: float = 0.0) -> None:
        self.reply = reply
        self.delay_s = delay_s
        self.requests: list[dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append({"path": self.path, "body": body})
                if fake.delay_s:
                    time.sleep(fake.delay_s)
                payload = json.dumps(
                    {
                        "id": "fake-1",
                        "object": "chat.completion",
                        "created": 0,
                        "model": body.get("model", ""),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": fake.reply},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
                    }
                ).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client timed out and hung up — that is the case under test

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.base_url = f"http://{self.host}/v1"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No endpoint variable from the developer's shell leaks into a case."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


@pytest.fixture
def fake() -> Iterator[FakeModel]:
    f = FakeModel()
    yield f
    f.close()


def _point_at(monkeypatch: pytest.MonkeyPatch, fake: FakeModel, **extra: str) -> None:
    monkeypatch.setenv("CRB_OPENAI_BASE_URL", fake.base_url)
    monkeypatch.setenv("CRB_OPENAI_KEY_ENV", _KEY_ENV)
    monkeypatch.setenv(_KEY_ENV, "fake-model-key-not-a-secret")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


# ---------------------------------------------------------------------------
# from_env: the tuning variables
# ---------------------------------------------------------------------------


def test_from_env_reads_the_tuning_variables_with_stated_defaults() -> None:
    ep = oc.EndpointConfig.from_env({})
    assert (ep.base_url, ep.api_key_env) == (oc.CEREBRAS_BASE_URL, oc.CEREBRAS_KEY_ENV)
    assert (ep.timeout_s, ep.max_tokens, ep.max_retries) == (120.0, 4000, 4)
    tuned = oc.EndpointConfig.from_env(
        {
            "CRB_OPENAI_BASE_URL": "http://gpu-box.internal:8080/v1",
            "CRB_OPENAI_TIMEOUT_S": "900",
            "CRB_OPENAI_MAX_TOKENS": "8192",
            "CRB_OPENAI_MAX_RETRIES": "0",
        }
    )
    assert (tuned.timeout_s, tuned.max_tokens, tuned.max_retries) == (900.0, 8192, 0)
    assert tuned.provider == "gpu-box.internal:8080"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CRB_OPENAI_TIMEOUT_S", "0"),
        ("CRB_OPENAI_TIMEOUT_S", "soon"),
        ("CRB_OPENAI_TIMEOUT_S", "nan"),
        ("CRB_OPENAI_TIMEOUT_S", "86400"),
        ("CRB_OPENAI_MAX_TOKENS", "0"),
        ("CRB_OPENAI_MAX_TOKENS", "12.5"),
        ("CRB_OPENAI_MAX_RETRIES", "-1"),
        ("CRB_OPENAI_MAX_RETRIES", "2.5"),
    ],
)
def test_from_env_refuses_a_bad_value_by_name(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        oc.EndpointConfig.from_env({name: value})


def test_from_env_refuses_a_base_url_that_is_not_http() -> None:
    with pytest.raises(ValueError, match="CRB_OPENAI_BASE_URL"):
        oc.EndpointConfig.from_env({"CRB_OPENAI_BASE_URL": "gpu-box:8080/v1"})


# ---------------------------------------------------------------------------
# The request lands on the configured endpoint; the row carries its provider
# ---------------------------------------------------------------------------


def test_the_tool_loop_calls_the_configured_endpoint_and_stamps_its_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeModel
) -> None:
    _point_at(monkeypatch, fake)
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(fx.task, config=fx.config)
    builder = OpenAIAgentBuilder(model="qwen-local")
    assert builder.provider == fake.host
    assert builder.describe()["endpoint"]["base_url"] == fake.base_url
    out = builder.build(ws, brief, base.Budget(max_turns=1, wall_clock_s=60))
    assert fake.requests, "the tool loop never reached the configured endpoint"
    assert fake.requests[0]["path"] == "/v1/chat/completions"
    assert fake.requests[0]["body"]["model"] == "qwen-local"
    assert out.provider == fake.host and out.builder_ref().provider == fake.host
    assert out.tokens_in == 11
    ws.remove()


def test_the_edit_block_builder_calls_the_configured_endpoint_and_stamps_its_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeModel
) -> None:
    _point_at(monkeypatch, fake, CRB_OPENAI_MAX_TOKENS="1234")
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(fx.task, config=fx.config)
    out = EditBlockBuilder(model="qwen-local").build(
        ws, brief, base.Budget(max_turns=1, wall_clock_s=60)
    )
    assert [r["path"] for r in fake.requests] == ["/v1/chat/completions"]
    assert fake.requests[0]["body"]["max_tokens"] == 1234  # the operator's setting, sent
    assert out.provider == fake.host
    ws.remove()


def test_the_labeller_calls_the_configured_endpoint_and_names_its_host(
    monkeypatch: pytest.MonkeyPatch, fake: FakeModel
) -> None:
    _point_at(monkeypatch, fake)
    lab = OpenAILabeller(model="qwen-local")
    assert lab.name == f"openai_agent:qwen-local@{fake.host}"
    lab.label(
        subject="fix: add returns the sum",
        message="",
        diff_stats=[PathStat(path="pkg/calc.py", added=1, deleted=1)],
        changed_paths=["pkg/calc.py"],
        path_class="bug.fix",
    )
    assert fake.requests and fake.requests[0]["body"]["model"] == "qwen-local"


def test_a_rung_naming_another_provider_is_refused_before_anything_is_built(
    monkeypatch: pytest.MonkeyPatch, fake: FakeModel
) -> None:
    _point_at(monkeypatch, fake)
    with pytest.raises(oc.ProviderMismatch, match=r"names provider 'cerebras'"):
        builder_for_rung(base.Rung("openai_agent", "gpt-oss-120b", "cerebras"))
    with pytest.raises(oc.ProviderMismatch):
        EditBlockBuilder(model="gpt-oss-120b", provider="cerebras")
    with pytest.raises(oc.ProviderMismatch):
        OpenAILabeller(model="gpt-oss-120b", provider="cerebras")
    # naming the host it calls, or naming nothing, is accepted and stamps that host
    named = builder_for_rung(base.Rung("openai_agent", "qwen-local", fake.host))
    assert named.provider == fake.host
    assert builder_for_rung(base.Rung("editblock", "qwen-local", "")).provider == fake.host
    assert not fake.requests  # construction calls nothing


def test_an_explicit_endpoint_still_wins_and_is_checked_against_the_rung() -> None:
    ep = oc.EndpointConfig(base_url="http://10.0.0.5:8000/v1")
    assert OpenAIAgentBuilder(model="m", endpoint=ep).provider == "10.0.0.5:8000"
    with pytest.raises(oc.ProviderMismatch):
        OpenAIAgentBuilder(model="m", provider="cerebras", endpoint=ep)
    # with nothing configured the endpoint is Cerebras and a cerebras rung is accepted
    assert OpenAIAgentBuilder(model="gpt-oss-120b", provider="cerebras").provider == "cerebras"


# ---------------------------------------------------------------------------
# A self-hosted model's generation time: the timeout and retries are the operator's
# ---------------------------------------------------------------------------


def _one_call(model: str = "qwen-local") -> oc.ModelTurn:
    builder = OpenAIAgentBuilder(model=model)
    return builder._model()([{"role": "user", "content": "hi"}], None)


def test_the_configured_timeout_is_honoured_both_ways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow = FakeModel(delay_s=2.5)  # a model still generating when the configured 1 s runs out
    try:
        _point_at(monkeypatch, slow, CRB_OPENAI_TIMEOUT_S="1", CRB_OPENAI_MAX_RETRIES="0")
        started = time.monotonic()
        with pytest.raises(oc.ModelCallError, match="Timeout"):
            _one_call()
        assert time.monotonic() - started < 2.4  # gave up at the configured second
        assert len(slow.requests) == 1  # CRB_OPENAI_MAX_RETRIES=0: no regeneration
        monkeypatch.setenv("CRB_OPENAI_TIMEOUT_S", "10")
        turn = _one_call()
        assert turn.content == "done" and len(slow.requests) == 2
    finally:
        slow.close()


def test_the_configured_retry_count_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    slow = FakeModel(delay_s=1.6)
    try:
        _point_at(monkeypatch, slow, CRB_OPENAI_TIMEOUT_S="1", CRB_OPENAI_MAX_RETRIES="1")
        with pytest.raises(oc.ModelCallError, match=r"after 2 attempt"):
            _one_call()
        deadline = time.monotonic() + 5
        while len(slow.requests) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(slow.requests) == 2
    finally:
        slow.close()
