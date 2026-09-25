"""Production refuses the unsealed posture (assessment 2026-09-25 B2, ADR-0023).

In ``prod`` the builder used to default to the host (``CRB_BUILDER__EXECUTOR=host``) and a
``local`` test executor only logged a warning. In host mode ``claude -p`` runs with Bash,
``--permission-mode dontAsk``, the API key in its environment and the gold commit reachable,
as the worker user. From ADR-0023: ``prod`` with the host builder or the local executor does
not start unless ``CRB_ALLOW_UNSEALED_PROD=1`` says so; the override is visible on
``/health`` and ``/settings`` and stamped into every run's apparatus; the builder defaults to
``docker`` in ``prod``.

Navigation
----------
What it is:   The suite for the production posture rule, in the API's ``Settings`` and in
              the worker's entrypoint, plus the deployment defaults and the documents that
              name the override.
What it does: Pins that ``prod`` + ``sandbox.executor=local`` and ``prod`` +
              ``builder.executor=host`` refuse to construct, naming ``CRB_ALLOW_UNSEALED_PROD``;
              that the override admits them, is read from the environment, is shown by
              ``redacted_dict`` and by ``/health``; that ``builder.executor`` defaults to
              ``docker`` in ``prod`` and ``host`` in ``dev``; that ``crb worker`` applies the
              same rule and carries the override stamp; that compose and the Helm chart give the
              worker the sealed builder; and that SECURITY §5 and DEPLOYMENT name the override.
How:          ``Settings(**kwargs)`` and ``Settings()`` over a monkeypatched environment;
              ``collect_health`` over a real SQLite store; ``worker_main.settings_from_args``
              with an explicit environment; the deploy files and docs read as text.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0023-production-refuses-the-unsealed-posture.md,
              docs/adr/0012-builder-in-a-sealed-container.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/settings.py (the rule), src/crb/server/worker_main.py (the
              worker's reading of it), src/crb/server/routes/system.py (``/health``),
              src/crb/server/worker.py (the apparatus stamp; its cases are in
              tests/test_worker.py), deploy/docker-compose.yml, deploy/helm/crb/values.yaml
Tested by:    tests/test_settings_posture.py
Touch when:   the override changes name, a new executor kind is added (decide whether it is
              sealed), or the deployment templates change the worker's executors.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from crb.server import settings as settings_mod
from crb.server import worker_main
from crb.server.routes.system import collect_health
from crb.server.settings import Settings
from crb.store import init_db, make_engine, make_session_factory

KEY = SecretStr("k" * 40)
#: The override's name, spelled out: the documents and the deployment templates use it.
ALLOW_UNSEALED_PROD_ENV = "CRB_ALLOW_UNSEALED_PROD"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def prod(**kw: Any) -> Settings:
    """A prod ``Settings`` at the image's own home (never created by ``Settings``)."""
    return Settings(env="prod", home=Path("/srv/crb"), secret_key=KEY, **kw)


class TestTheRule:
    def test_the_env_variable_is_the_one_the_documents_name(self) -> None:
        assert settings_mod.ALLOW_UNSEALED_PROD_ENV == ALLOW_UNSEALED_PROD_ENV

    def test_sealed_or_dev_is_never_refused(self) -> None:
        refusal = settings_mod.unsealed_prod_refusal
        assert refusal("prod", "docker", "docker", allow=False) == ""
        assert refusal("dev", "local", "host", allow=False) == ""

    @pytest.mark.parametrize(("sandbox", "builder"), [("local", "docker"), ("docker", "host")])
    def test_prod_unsealed_is_refused_with_the_override_named(
        self, sandbox: str, builder: str
    ) -> None:
        refusal = settings_mod.unsealed_prod_refusal
        reason = refusal("prod", sandbox, builder, allow=False)
        assert ALLOW_UNSEALED_PROD_ENV in reason and "ADR-0023" in reason
        assert refusal("prod", sandbox, builder, allow=True) == ""


class TestSettings:
    def test_prod_refuses_the_local_test_executor(self) -> None:
        with pytest.raises(ValidationError, match=ALLOW_UNSEALED_PROD_ENV):
            prod(sandbox={"executor": "local"})

    def test_prod_refuses_the_host_builder(self) -> None:
        with pytest.raises(ValidationError, match=ALLOW_UNSEALED_PROD_ENV):
            prod(builder={"executor": "host"})

    def test_prod_defaults_the_builder_to_docker_and_dev_to_host(self) -> None:
        s = prod()
        assert s.builder.executor == "docker" and s.sandbox.executor == "docker"
        assert s.posture() == {
            "env": "prod",
            "sandbox_executor": "docker",
            "builder_executor": "docker",
            "sealed": True,
            "unsealed_prod_override": False,
        }
        d = Settings(env="dev", home=Path("/srv/crb"))
        assert d.builder.executor == "host"
        assert d.posture()["sealed"] is False and d.posture()["unsealed_prod_override"] is False

    def test_an_explicit_docker_builder_still_needs_its_image(self) -> None:
        # the start-up check on a typo is untouched: only the DEFAULT is lenient on the image
        # (the worker fails closed when it builds without one)
        with pytest.raises(ValidationError, match="CRB_BUILDER__IMAGE"):
            prod(builder={"executor": "docker"})
        assert prod(builder={"executor": "docker", "image": "crb-builder:1"}).posture()["sealed"]

    def test_the_override_admits_it_is_shown_and_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="crb.server.settings"):
            s = prod(
                sandbox={"executor": "local"},
                builder={"executor": "host"},
                allow_unsealed_prod=True,
            )
        assert s.posture() == {
            "env": "prod",
            "sandbox_executor": "local",
            "builder_executor": "host",
            "sealed": False,
            "unsealed_prod_override": True,
        }
        assert s.redacted_dict()["posture"] == s.posture()
        assert any(ALLOW_UNSEALED_PROD_ENV in r.getMessage() for r in caplog.records)

    def test_the_override_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_ENV", "prod")
        monkeypatch.setenv("CRB_HOME", "/srv/crb")
        monkeypatch.setenv("CRB_SECRET_KEY", "e" * 40)
        monkeypatch.setenv("CRB_BUILDER__EXECUTOR", "host")
        with pytest.raises(ValidationError, match=ALLOW_UNSEALED_PROD_ENV):
            Settings()
        monkeypatch.setenv(ALLOW_UNSEALED_PROD_ENV, "1")
        assert Settings().posture()["unsealed_prod_override"] is True

    def test_an_override_that_is_not_needed_is_not_reported_as_in_force(self) -> None:
        assert prod(allow_unsealed_prod=True).posture()["unsealed_prod_override"] is False


class TestHealth:
    def test_health_shows_the_posture_and_the_override(self, tmp_path: Path) -> None:
        engine = make_engine(f"sqlite:///{tmp_path / 'crb.db'}")
        init_db(engine)
        factory = make_session_factory(engine)
        s = prod(sandbox={"executor": "local"}, allow_unsealed_prod=True)
        body = collect_health(factory, s, role="api")
        assert body["posture"] == s.posture()
        assert body["posture"]["unsealed_prod_override"] is True
        sealed = collect_health(factory, prod(), role="api")
        assert sealed["posture"]["sealed"] is True


class TestWorker:
    def _args(self) -> Any:
        return worker_main.build_parser().parse_args(["--once"])

    def test_a_prod_worker_refuses_the_local_executor_and_the_host_builder(
        self, tmp_path: Path
    ) -> None:
        home = {"CRB_HOME": str(tmp_path / "h"), "CRB_ENV": "prod"}
        with pytest.raises(ValueError, match=ALLOW_UNSEALED_PROD_ENV):
            worker_main.settings_from_args(self._args(), {**home, "CRB_SANDBOX__EXECUTOR": "local"})
        with pytest.raises(ValueError, match=ALLOW_UNSEALED_PROD_ENV):
            worker_main.settings_from_args(self._args(), {**home, "CRB_BUILDER__EXECUTOR": "host"})

    def test_a_prod_worker_defaults_to_the_sealed_posture(self, tmp_path: Path) -> None:
        s = worker_main.settings_from_args(self._args(), {"CRB_HOME": str(tmp_path / "h")})
        assert s.executor == "docker"
        assert s.refuse_unsealed is True and dict(s.unsealed_override) == {}
        dev = worker_main.settings_from_args(
            self._args(), {"CRB_HOME": str(tmp_path / "h"), "CRB_ENV": "dev"}
        )
        assert dev.executor == "local" and dev.refuse_unsealed is False

    def test_the_override_is_carried_as_the_apparatus_stamp(self, tmp_path: Path) -> None:
        s = worker_main.settings_from_args(
            self._args(),
            {
                "CRB_HOME": str(tmp_path / "h"),
                "CRB_ENV": "prod",
                "CRB_SANDBOX__EXECUTOR": "local",
                "CRB_BUILDER__EXECUTOR": "host",
                ALLOW_UNSEALED_PROD_ENV: "1",
            },
        )
        assert s.executor == "local" and s.refuse_unsealed is False
        assert dict(s.unsealed_override) == {
            "env": "prod",
            "sandbox_executor": "local",
            "builder_executor": "host",
            "override": ALLOW_UNSEALED_PROD_ENV,
            "adr": "0023",
        }


class TestDeploymentDefaults:
    def test_compose_gives_the_worker_the_sealed_builder(self) -> None:
        compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
        worker = compose.split("\n  worker:\n", 1)[1]
        assert re.search(r"CRB_SANDBOX__EXECUTOR: \$\{CRB_SANDBOX__EXECUTOR:-docker\}", worker)
        assert re.search(r"CRB_BUILDER__EXECUTOR: \$\{CRB_BUILDER__EXECUTOR:-docker\}", worker)
        assert re.search(r"CRB_BUILDER__IMAGE: \$\{CRB_BUILDER__IMAGE:-\}", worker)

    def test_helm_gives_the_worker_the_sealed_builder(self) -> None:
        values = (ROOT / "deploy" / "helm" / "crb" / "values.yaml").read_text(encoding="utf-8")
        worker = values.split("\nworker:\n", 1)[1]
        assert re.search(r"\n  builder:\n(    #[^\n]*\n)*    executor: docker\n", worker)
        tpl = ROOT / "deploy" / "helm" / "crb" / "templates" / "worker-deployment.yaml"
        text = tpl.read_text(encoding="utf-8")
        assert "name: CRB_BUILDER__EXECUTOR" in text and ".Values.worker.builder.executor" in text


class TestDocuments:
    def test_security_section_5_and_deployment_name_the_override(self) -> None:
        security = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        section5 = security.split("\n## 5", 1)[1].split("\n## ", 1)[0]
        assert ALLOW_UNSEALED_PROD_ENV in section5
        deployment = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
        assert ALLOW_UNSEALED_PROD_ENV in deployment
        assert (ROOT / "docs" / "adr" / "0023-production-refuses-the-unsealed-posture.md").exists()
