"""A configured builder endpoint is the endpoint the builder calls: every OpenAI-compatible
builder (tool loop, edit block, labeller) and the factory's test author are pointed by
``CRB_OPENAI_BASE_URL`` at a fake OpenAI-compatible server on localhost — no real model —
and the request must land there, the row must carry that host as its provider, and the
timeout and retry settings must be the ones the operator set.

Navigation
----------
What it is:   The endpoint-resolution test suite (product.truth.26, .27) — a small
              threaded HTTP server that answers ``POST /v1/chat/completions`` like an
              OpenAI-compatible model, and the builders run against it through the real
              ``openai`` client.
What it does: Pins that ``EndpointConfig.from_env`` reads ``CRB_OPENAI_TIMEOUT_S`` /
              ``CRB_OPENAI_MAX_TOKENS`` / ``CRB_OPENAI_MAX_RETRIES`` with stated defaults and
              refuses a bad value by name; that the tool loop, the edit-block builder and the
              labeller send their request to the configured base URL and stamp its host as
              the provider (never a silent ``cerebras``); that a rung naming a different
              provider is refused before anything is built; that a response slower than the
              configured timeout fails and one inside it succeeds; that the retry count
              is the configured one; and that the factory's test author calls the same
              endpoint, stamps its provider on what authoring returns and on each
              ``author.attempt``, is refused a rung naming another provider, and never lets
              a provider pass the builder's model as another (ADR-0021).
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
              refused), src/crb/factory/author.py (the test author's provider stamp),
              tests/fixtures/builders_repo.py and tests/fixtures/pyrepo.py (the workspaces)
Tested by:    tests/test_builders_endpoint.py
Touch when:   a new ``CRB_OPENAI_*`` variable is read (a default case and a refusal case);
              a new OpenAI-compatible builder is registered (a "lands on the fake" case).
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from crb.builders import base, builder_for_rung, labeller
from crb.builders import openai_client as oc
from crb.builders.editblock import EditBlockBuilder
from crb.builders.labeller import OpenAILabeller, make_labeller
from crb.builders.openai_agent import OpenAIAgentBuilder
from crb.core.classify import PathStat
from crb.factory.author import RungTestAuthor, author_from_label
from crb.factory.backlog import BacklogItem
from crb.factory.testfirst import (
    SameIdentityError,
    assert_distinct_identity,
    author_label,
    author_test,
)
from crb.server.schemas import RunCreateRequest
from fixtures import pyrepo as pr

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


# ---------------------------------------------------------------------------
# The factory's test author: the same endpoint, the same provider rule (G-611)
# ---------------------------------------------------------------------------

_ITEM = BacklogItem(
    id="I-9",
    title="divide two numbers",
    kind="code",
    description="calc.divide(a, b) returns a / b and raises ZeroDivisionError for b == 0.",
    acceptance_criteria=("divide(6, 3) == 2",),
    capability_class="pure_function",
)

_AUTHORED = """FILE: tests/test_divide.py
```python
from calc import divide


def test_divide() -> None:
    assert divide(6, 3) == 2
```
"""


def test_the_test_author_calls_the_configured_endpoint_and_stamps_its_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pyrepo: pr.PyRepo
) -> None:
    fake = FakeModel(reply=_AUTHORED)
    try:
        _point_at(monkeypatch, fake)
        author = author_from_label("editblock:qwen-local")
        assert author is not None
        assert author.provider == fake.host
        assert author.describe()["provider"] == fake.host
        assert author.describe()["endpoint"]["base_url"] == fake.base_url
        events: list[tuple[str, dict[str, Any]]] = []
        res = author_test(
            pyrepo.repo,
            _ITEM,
            author,
            facts={},
            config=pyrepo.config,
            scratch=tmp_path / "scratch",
            on_event=lambda action, payload: events.append((action, dict(payload))),
        )
    finally:
        fake.close()
    assert [r["path"] for r in fake.requests] == ["/v1/chat/completions"]
    assert fake.requests[0]["body"]["model"] == "qwen-local"
    assert res.authored.path == "tests/test_divide.py"
    # the provider of the endpoint that wrote the test is on what authoring returns and on
    # every attempt it records — never a silent `cerebras`
    assert res.described["provider"] == fake.host
    attempts = [p for a, p in events if a == "author.attempt"]
    assert attempts and all(p["provider"] == fake.host for p in attempts)
    # the identity the refusal compares stays builder:model — a provider is not identity
    assert res.authored.author == "editblock:qwen-local"


def test_a_test_author_rung_naming_another_provider_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch, fake: FakeModel
) -> None:
    _point_at(monkeypatch, fake)
    with pytest.raises(oc.ProviderMismatch, match=r"names provider 'cerebras'"):
        author_from_label("editblock:gpt-oss-120b:cerebras")
    with pytest.raises(oc.ProviderMismatch):
        author_from_label("editblock:gpt-oss-120b", default_provider="cerebras")
    with pytest.raises(oc.ProviderMismatch):
        RungTestAuthor(
            name="editblock",
            model="m",
            provider="cerebras",
            endpoint=oc.EndpointConfig(base_url=fake.base_url),
        )
    # naming the host it calls is accepted
    named = author_from_label(f"editblock:qwen-local@{fake.host}")
    assert named is not None and named.provider == fake.host
    assert not fake.requests  # construction calls nothing


def test_a_provider_never_lets_the_authors_model_pass_as_another(
    monkeypatch: pytest.MonkeyPatch, fake: FakeModel
) -> None:
    """ADR-0021 (#55): the author's model differs from the builder's. The provider is
    stamped, never compared as identity — the same model behind two providers is refused."""
    _point_at(monkeypatch, fake)
    author = author_from_label(f"editblock:gpt-oss-120b@{fake.host}")
    assert author is not None
    for rung in (
        base.Rung("openai_agent", "gpt-oss-120b", "cerebras"),
        base.Rung("editblock", "gpt-oss-120b", "azure"),
    ):
        with pytest.raises(SameIdentityError):
            assert_distinct_identity(author_label(author), rung.label, role="build rung 1")


def test_no_caller_stamps_a_named_provider_over_the_endpoints() -> None:
    """P-967, ratcheted: ``provider or resolved_endpoint(endpoint).provider`` (and the older
    ``provider or (endpoint.provider if endpoint else …)``) stamps whatever a rung names even
    when the endpoint called is another — the test author did so until G-611 closed. Every
    OpenAI-compatible caller takes its provider from ``resolve_endpoint``, which refuses a
    mismatch."""
    pattern = re.compile(r"provider\s+or\s+(?:\(\s*endpoint\b|resolved_endpoint\()")
    root = Path(oc.__file__).resolve().parents[1]  # src/crb
    offenders = sorted(
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    )
    assert offenders == []


# ---------------------------------------------------------------------------
# The provider column is the endpoint's host — never a credential, never a look-alike
# ---------------------------------------------------------------------------

_SECRET = "hunter2-s3cret"


@pytest.mark.parametrize(
    "url",
    [
        f"https://ops:{_SECRET}@gpu-box.internal:8080/v1",
        f"https://{_SECRET}@gpu-box.internal/v1",
        f"http://gpu-box.internal:8080/v1?api-key={_SECRET}",
        f"http://gpu-box.internal:8080/v1#{_SECRET}",
    ],
)
def test_a_base_url_carrying_a_credential_is_refused_by_name_and_never_echoed(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """P-968: the provider column (and the endpoint in every apparatus stamp) is written
    as-is to the append-only ledger, so a key in the URL's userinfo, query or fragment
    would be recorded on every row. It is refused where the URL is read — naming the
    variable, never echoing the value — and a direct ``EndpointConfig`` refuses it too."""
    with pytest.raises(ValueError, match="CRB_OPENAI_BASE_URL") as exc:
        oc.EndpointConfig.from_env({"CRB_OPENAI_BASE_URL": url})
    assert _SECRET not in str(exc.value)
    with pytest.raises(ValueError) as direct:
        oc.EndpointConfig(base_url=url)
    assert _SECRET not in str(direct.value)
    monkeypatch.setenv("CRB_OPENAI_BASE_URL", url)
    for build in (
        lambda: OpenAIAgentBuilder(model="qwen3"),
        lambda: author_from_label("editblock:qwen-small"),
    ):
        with pytest.raises(ValueError) as built:
            build()
        assert _SECRET not in str(built.value)


def test_an_azure_endpoint_carrying_a_credential_is_refused_and_never_echoed() -> None:
    with pytest.raises(ValueError, match="CRB_AZURE_ENDPOINT") as exc:
        oc.EndpointConfig.from_env(
            {
                "CRB_AZURE_ENDPOINT": f"https://ops:{_SECRET}@tenant.openai.azure.com",
                "CRB_AZURE_DEPLOYMENT": "d1",
            }
        )
    assert _SECRET not in str(exc.value)


def test_a_base_url_without_a_scheme_is_refused_without_echoing_it() -> None:
    with pytest.raises(ValueError, match="CRB_OPENAI_BASE_URL") as exc:
        oc.EndpointConfig.from_env({"CRB_OPENAI_BASE_URL": f"ops:{_SECRET}@gpu-box/v1"})
    assert _SECRET not in str(exc.value)


@pytest.mark.parametrize(
    ("url", "provider"),
    [
        ("https://api.cerebras.ai/v1", "cerebras"),
        ("https://API.Cerebras.AI:443/v1", "cerebras"),
        ("http://cerebras-mirror.lab.internal:8080/v1", "cerebras-mirror.lab.internal:8080"),
        ("https://api.cerebras.ai.attacker.example/v1", "api.cerebras.ai.attacker.example"),
        ("https://notcerebras.ai/v1", "notcerebras.ai"),
        ("http://GPU-Box.internal:8080/v1", "gpu-box.internal:8080"),
        ("http://[::1]:8080/v1", "[::1]:8080"),
        # P-975: a host that IS a provider's bare name (a compose or Kubernetes service
        # called `cerebras`) is stamped as a host, never as that provider
        ("http://cerebras/v1", "host:cerebras"),
        ("http://Azure/v1", "host:azure"),
        ("http://anthropic/v1", "host:anthropic"),
        ("http://openai/v1", "host:openai"),
    ],
)
def test_only_a_cerebras_ai_host_is_stamped_cerebras(url: str, provider: str) -> None:
    """A host that merely CONTAINS ``cerebras`` (a self-hosted mirror, a look-alike domain)
    is its own provider, so its rows never pool into Cerebras's cell."""
    assert oc.EndpointConfig.from_env({"CRB_OPENAI_BASE_URL": url}).provider == provider


@pytest.mark.parametrize("host", ["cerebras", "azure", "anthropic", "openai", "llm", "localhost"])
def test_no_host_is_ever_stamped_as_a_bare_name(host: str) -> None:
    """P-975: every provider the product names without a host (``cerebras``, ``azure``,
    ``anthropic`` …) is a bare name, so a stamp taken from a host must never be one — a host
    with no dot and no port is stamped ``host:<name>``, whatever the name is."""
    stamp = oc.EndpointConfig(base_url=f"http://{host}/v1").provider
    assert stamp == f"host:{host}"
    assert not re.fullmatch(r"[a-z0-9_-]+", stamp)


@pytest.mark.parametrize("name", ["cerebras", "azure", "anthropic"])
def test_a_rung_naming_a_provider_is_refused_on_a_host_of_that_name(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """P-975, reproduced through the real constructors: with ``CRB_OPENAI_BASE_URL`` at a
    service called ``cerebras`` a ``@cerebras`` rung (builder or test author) was accepted
    and its rows pooled into Cerebras's cell of the append-only ledger."""
    monkeypatch.setenv("CRB_OPENAI_BASE_URL", f"http://{name}/v1")
    with pytest.raises(oc.ProviderMismatch):
        builder_for_rung(base.Rung("openai_agent", "qwen-local", name))
    with pytest.raises(oc.ProviderMismatch):
        builder_for_rung(base.Rung("editblock", "llama-local", name))
    with pytest.raises(oc.ProviderMismatch):
        author_from_label(f"editblock:llama-local@{name}")


@pytest.mark.parametrize(
    ("endpoint", "provider"),
    [
        ("https://tenant.openai.azure.com", "azure"),
        ("https://tenant.cognitiveservices.azure.com", "azure"),
        ("https://gateway.azure-api.net", "azure"),
        ("https://tenant.openai.azure.us", "azure"),
        ("https://llm.corp.example", "llm.corp.example"),
        ("https://openai.azure.com.attacker.example", "openai.azure.com.attacker.example"),
        ("https://azure", "host:azure"),
    ],
)
def test_only_an_azure_domain_host_is_stamped_azure(endpoint: str, provider: str) -> None:
    """P-975: ``CRB_AZURE_ENDPOINT`` at any host was stamped ``azure``. Azure is stamped only
    for a host in an Azure domain; any other host is its own provider, like any endpoint."""
    az = oc.AzureConfig(endpoint=endpoint, api_version="2024-10-21", deployment="d")
    assert oc.EndpointConfig(azure=az).provider == provider


def test_a_cerebras_rung_is_refused_on_a_mirror_that_is_not_cerebras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRB_OPENAI_BASE_URL", "http://cerebras-mirror.lab.internal:8080/v1")
    with pytest.raises(oc.ProviderMismatch):
        builder_for_rung(base.Rung("openai_agent", "qwen3-local", "cerebras"))


# ---------------------------------------------------------------------------
# A test seam is a callable, never a value a run request can carry
# ---------------------------------------------------------------------------


def test_a_seam_that_is_not_callable_never_bypasses_the_provider_refusal() -> None:
    """A ``model_fn`` / ``chat_fn`` that is not callable calls nothing in its place, so it
    is not a seam: the provider the rung names is checked against the endpoint like any
    other (with nothing configured the endpoint is Cerebras, and ``azure`` is refused)."""
    with pytest.raises(oc.ProviderMismatch):
        builder_for_rung(base.Rung("openai_agent", "gpt-4o", "azure"), model_fn="x")
    with pytest.raises(oc.ProviderMismatch):
        builder_for_rung(base.Rung("editblock", "gpt-4o", "azure"), chat_fn="x")
    with pytest.raises(oc.ProviderMismatch):
        make_labeller(
            "editblock", model="gpt-4o", provider="azure", builder_config={"chat_fn": "x"}
        )
    with pytest.raises(oc.ProviderMismatch):
        RungTestAuthor(name="editblock", model="m", provider="azure", chat_fn="x")  # type: ignore[arg-type]
    # a real (callable) seam still stands in for the endpoint and keeps the named provider
    assert EditBlockBuilder(model="m", provider="azure", chat_fn=lambda _m: "").provider == "azure"


@pytest.mark.parametrize(
    "key", ["model_fn", "chat_fn", "endpoint", "spawn", "runner_factory", "executor"]
)
def test_a_run_request_cannot_set_a_builder_seam(key: str) -> None:
    """``builder_config`` is JSON from ``POST /runs``: an in-process seam or object a
    builder takes (the model call, the transport, the endpoint, the executor) is refused
    at the schema, with the reason, before it can reach ``builder_for_rung``."""
    with pytest.raises(ValidationError, match=rf"{key}.*seam"):
        RunCreateRequest.model_validate(
            {
                "repo": "pyrepo",
                "kind": "replay",
                "builder": "openai_agent",
                "model": "gpt-4o",
                "builder_config": {key: "x"},
            }
        )


# ---------------------------------------------------------------------------
# The labeller's reply length is the operator's when the operator sets one
# ---------------------------------------------------------------------------


def _label(lab: OpenAILabeller) -> None:
    lab.label(
        subject="fix: add returns the sum",
        message="",
        diff_stats=[PathStat(path="pkg/calc.py", added=1, deleted=1)],
        changed_paths=["pkg/calc.py"],
        path_class="bug.fix",
    )


def test_the_labeller_sends_the_configured_reply_length(
    monkeypatch: pytest.MonkeyPatch, fake: FakeModel
) -> None:
    """``CRB_OPENAI_MAX_TOKENS`` reaches the labeller's request, as it does the builders';
    unset, the labeller keeps its own shorter default; a run's ``builder_config`` still wins."""
    _point_at(monkeypatch, fake)
    _label(OpenAILabeller(model="qwen-local"))
    monkeypatch.setenv("CRB_OPENAI_MAX_TOKENS", "16000")
    _label(OpenAILabeller(model="qwen-local"))
    _label(make_labeller("openai_agent", model="qwen-local", builder_config={"max_tokens": 64}))
    sent = [r["body"]["max_tokens"] for r in fake.requests]
    assert sent == [labeller.DEFAULT_MAX_TOKENS, 16000, 64]


# ---------------------------------------------------------------------------
# The guides' count of this module's cases is this module's count
# ---------------------------------------------------------------------------

_CLAIM = re.compile(
    r"n = (\d+) test\s+cases in `tests/test_builders_endpoint\.py`: (\d+) point",
)


def _case_counts() -> tuple[int, int]:
    """(cases, fake-server cases) in this module, read from its own source: a test's cases
    are the product of its literal ``parametrize`` lists; it is a fake-server case when it
    takes the ``fake`` fixture or starts a ``FakeModel`` itself."""
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    total = fake_cases = 0
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        cases = 1
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and ast.unparse(dec.func) == "pytest.mark.parametrize":
                values = dec.args[1]
                assert isinstance(values, ast.List), f"{node.name}: parametrize a literal list"
                cases *= len(values.elts)
        uses_fake = any(a.arg == "fake" for a in node.args.args) or "FakeModel(" in ast.unparse(
            node
        )
        total += cases
        fake_cases += cases if uses_fake else 0
    return total, fake_cases


def test_the_guides_count_of_these_cases_is_this_modules() -> None:
    """P-973: the guides said n = 20 cases against a fake server when the module collected
    21 and about half used the server; ``claims_check`` checks that a tag is there, never
    its n. The two guides that cite this module state the count this module has."""
    total, fake_cases = _case_counts()
    docs = Path(__file__).resolve().parents[1] / "docs"
    for page in ("OPERATOR.md", "DEPLOYMENT.md"):
        text = " ".join((docs / page).read_text(encoding="utf-8").split())
        found = _CLAIM.findall(text)
        assert found, f"docs/{page} no longer states this module's count"
        assert {(int(t), int(f)) for t, f in found} == {(total, fake_cases)}, page
