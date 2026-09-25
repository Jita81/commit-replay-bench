"""Go: the parent's and the gold's modules in one sealed cache, offline at test time (D4).

The daemon test is the proof the sealed posture was missing (F42 part 2, defects D1 and
D4): a real fetch container fills one module cache from a ``file://`` mirror with no
network, the store seals it, and the shipped Go sandbox image then runs the fixture's tests
at the parent AND at the gold with ``--network=none`` and ``GOPROXY=off`` against that one
read-only cache. The other tests pin the recipe's refusals without a daemon.

Navigation
----------
What it is:   The suite for the Go recipe (``crb.provision.go``) and the providers
              (``crb.provision``) on a Go repository with a module dependency.
What it does: Pins that one fetch seals ``example.com/dep`` v1.0.0 AND v1.1.0 in one cache (the
              builder's parent-only set holds v1.0.0 only), that the parent and the gold then
              build and pass offline in the shipped sandbox image, that a second resolve reuses
              the set; that the fetch never uses ``direct`` or a VCS; that a private module
              without a private proxy and a too-new ``go`` directive are refused before any
              request; and that provisioning switched off refuses a repository with modules.
How:          ``goproxy.build`` (the mirror) + ``gorepo_deps.build`` under ``tests/.cache`` →
              ``SealedProvider.resolve`` → ``GoRunner`` bound to each role's set on a
              ``DockerExecutor`` over the shipped ``crb-sandbox-go`` image.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/provision/go.py and src/crb/provision/__init__.py (under test),
              tests/fixtures/goproxy.py (the mirror), tests/fixtures/langs/gorepo_deps.py (the
              D4 repository), tests/conftest_langs.py (the shipped image)
Tested by:    tests/test_provision_go.py
Touch when:   the Go recipe's plan, environment or refusals change.
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.deps import SCOPE_RUN, ProvisionRefused
from crb.core.execution import DockerExecutor, DockerSettings
from crb.core.git import GitRepo
from crb.core.provision import LockInputs
from crb.core.runners import get_runner
from crb.core.workspace import Workspace
from crb.provision import (
    DisabledProvider,
    HostEnvProvider,
    SealedProvider,
    make_deps_provider,
)
from crb.provision import go as go_recipe
from crb.provision.config import DEFAULT_GO_IMAGE, ProvisionConfig
from crb.provision.store import BundleStore, remove_tree

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs

gorepo_deps = langs.fixture_module("gorepo_deps")
gorepo = langs.fixture_module("gorepo")
goproxy = importlib.import_module("fixtures.goproxy")

DEP = goproxy.MODULE


@pytest.fixture
def repo(tmp_path: Path) -> tuple[GitRepo, str]:
    root, feat = gorepo_deps.build(tmp_path)
    return GitRepo(root), feat


def test_go_fetch_never_uses_direct_or_a_vcs(repo: tuple[GitRepo, str]) -> None:
    r, feat = repo
    cfg = gorepo_deps.config()
    sets = [LockInputs.from_git(r, r.parent(feat), cfg), LockInputs.from_git(r, feat, cfg)]
    plan = go_recipe.plan(sets, key="dep_" + "0" * 64, config=ProvisionConfig(), opts={})
    assert plan.env["GOPROXY"] == "https://proxy.golang.org"
    assert "direct" not in " ".join(plan.env.values())
    assert plan.env["GOVCS"] == "*:off" and plan.env["GOTOOLCHAIN"] == "local"
    assert plan.env["GOENV"] == "off" and plan.env["GOWORK"] == "off"
    assert plan.env["GOFLAGS"] == "-mod=readonly"
    assert plan.registry_hosts == ("proxy.golang.org", "sum.golang.org")
    assert plan.argv == (
        "sh",
        "-c",
        "cd /in/s0 && go mod download -json && cd /in/s1 && go mod download -json",
    )
    assert set(plan.inputs) == {"s0/go.mod", "s0/go.sum", "s1/go.mod", "s1/go.sum"}
    # a proxy list with direct (or off) is refused at configuration
    for bad in ("https://proxy.golang.org,direct", "direct", "off", "https://a|https://b"):
        with pytest.raises(ValueError, match="never 'direct'"):
            ProvisionConfig(go_proxy=bad)
    # a file:// mirror: GOPROXY is the mounted mirror, no sum database, no hosts at all
    mirror = go_recipe.plan(
        sets[:1], key="dep_" + "0" * 64, config=ProvisionConfig(go_proxy="file:///srv/m"), opts={}
    )
    assert mirror.env["GOPROXY"] == "file:///mirror" and mirror.env["GOSUMDB"] == "off"
    assert mirror.registry_hosts == () and mirror.mirror == Path("/srv/m")


def test_a_private_module_without_a_proxy_is_refused_before_any_request(
    repo: tuple[GitRepo, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    r, feat = repo
    cfg = gorepo_deps.config()
    sets = [LockInputs.from_git(r, feat, cfg)]
    with pytest.raises(ProvisionRefused) as ei:
        go_recipe.plan(
            sets, key="dep_" + "0" * 64, config=ProvisionConfig(), opts={"goprivate": "example.com"}
        )
    assert ei.value.code == "PROVISION_PRIVATE_MODULE" and f"{DEP}@v1.1.0" in ei.value.message
    # through the provider: refused before any fetch container is started
    started: list[object] = []
    provider = SealedProvider(
        ProvisionConfig(enabled=True, env="dev", store=r.path.parent / "deps")
    )
    monkeypatch.setattr(provider, "image_id", lambda image: "sha256:" + "f" * 64)
    monkeypatch.setattr(provider, "fetch", lambda *a, **k: started.append(a))
    private_cfg = type(cfg)(
        name=cfg.name,
        language=cfg.language,
        runner="go",
        runner_opts={"goprivate": "example.com/*"},
    )
    with pytest.raises(ProvisionRefused, match="PROVISION_PRIVATE_MODULE"):
        provider.resolve(r, private_cfg, gold=feat)
    assert started == []
    assert not any(provider.store.root.glob("go/dep_*")), "nothing sealed"
    # a private (tenant) proxy may serve it: GONOSUMDB names the module, no refusal
    ok = go_recipe.plan(
        sets,
        key="dep_" + "0" * 64,
        config=ProvisionConfig(go_proxy="https://goproxy.corp.example"),
        opts={"goprivate": "example.com"},
    )
    assert ok.env["GONOSUMDB"] == "example.com"


def test_a_newer_go_directive_is_toolchain_too_old(tmp_path: Path) -> None:
    fx = importlib.import_module("fixtures.langs")
    fx.init_repo(tmp_path / "r")
    fx.write_files(
        tmp_path / "r",
        {
            "go.mod": f"module example.com/x\n\ngo 1.99\n\nrequire {DEP} v1.0.0\n",
            "go.sum": goproxy.go_sum(["v1.0.0"]),
        },
    )
    sha = fx.commit_all(tmp_path / "r", "new go")
    inputs = LockInputs.from_git(GitRepo(tmp_path / "r"), sha, gorepo_deps.config())
    with pytest.raises(ProvisionRefused) as ei:
        go_recipe.plan([inputs], key="dep_" + "0" * 64, config=ProvisionConfig(), opts={})
    assert ei.value.code == "PROVISION_TOOLCHAIN_TOO_OLD" and "1.26.8" in ei.value.message
    assert go_recipe.toolchain_of(DEFAULT_GO_IMAGE) == (1, 26, 8)


def test_disabled_provisioning_refuses_a_repository_with_dependencies(
    repo: tuple[GitRepo, str], tmp_path: Path
) -> None:
    r, feat = repo
    off = ProvisionConfig(enabled=False, store=tmp_path / "deps")
    provider = make_deps_provider(off, executor_kind="docker")
    assert isinstance(provider, DisabledProvider) and provider.mode == "sealed"
    with pytest.raises(ProvisionRefused) as ei:
        provider.resolve(r, gorepo_deps.config(), gold=feat)
    assert ei.value.code == "PROVISION_DISABLED" and ei.value.scope == SCOPE_RUN
    assert "CRB_PROVISION__ENABLED" in ei.value.fix and f"{DEP}@v1.0.0" in ei.value.message
    # a repository that declares no dependencies is sealed and empty — nothing to refuse
    root, plain = gorepo.build(tmp_path / "plain")
    deps = provider.resolve(GitRepo(root), gorepo.config(), gold=plain)
    assert deps.keys == () and not deps.gold.sealed and deps.mode == "sealed"
    # the local posture with provisioning off keeps the host's own setup
    host = make_deps_provider(off, executor_kind="local")
    assert isinstance(host, HostEnvProvider)
    assert host.resolve(r, gorepo_deps.config(), gold=feat).mode == "host-env"


# ---------------------------------------------------------------------------
# Against a daemon: a real fetch, a real seal, a real offline test run
# ---------------------------------------------------------------------------


@pytest.fixture
def scratch() -> Iterator[Path]:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    langs.require_docker_image(DEFAULT_GO_IMAGE, "the pinned Go fetch image")
    root = langs.CACHE_DIR / "provision" / f"go-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    remove_tree(root)


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.sandbox_images
def test_go_fetch_puts_parent_and_gold_in_one_cache(scratch: Path) -> None:
    image = langs.ensure_shipped_sandbox_image("go")
    mirror = goproxy.build(scratch / "mirror")
    root, feat = gorepo_deps.build(scratch / "repo")
    repo = GitRepo(root)
    cfg = gorepo_deps.config()
    events: list[str] = []
    config = ProvisionConfig(
        enabled=True, env="dev", store=scratch / "deps", go_proxy=f"file://{mirror}"
    )
    provider = make_deps_provider(
        config, executor_kind="docker", on_event=lambda a, p: events.append(a), probe_image=image
    )
    assert isinstance(provider, SealedProvider)
    deps = provider.resolve(repo, cfg, gold=feat)
    # D4: ONE cache holds the parent's and the gold's versions; the builder's holds the parent's
    assert deps.parent.key == deps.gold.key != deps.builder.key
    assert {f"{DEP}@v1.0.0", f"{DEP}@v1.1.0"} <= set(deps.gold.manifest)
    assert f"{DEP}@v1.1.0" not in deps.builder.manifest
    assert events.count("provision.fetch") == 2 and events.count("provision.seal") == 2
    sealed = BundleStore(config.store).verify(deps.gold.key)
    assert sealed.manifest["fetch_image_id"].startswith("sha256:")
    assert sealed.manifest["modules"][f"{DEP}@v1.1.0"].startswith("h1:")
    # a second task on the same lockfiles reuses the set: no fetch
    events.clear()
    again = provider.resolve(repo, cfg, gold=feat)
    assert again.keys == deps.keys and events == ["provision.reuse", "provision.reuse"]

    # D1: the shipped sandbox image, --network=none, GOPROXY=off, the one read-only cache:
    # the parent and the gold both build and pass
    executor = DockerExecutor(DockerSettings(image=image))
    runner = get_runner(cfg)
    cand = langs.feat_candidate(repo, cfg, feat)
    for role, sources in (("parent", ()), ("gold", ("go.mod", "go.sum", gorepo_deps.SRC_BYE))):
        ws = Workspace.create(repo, feat, scratch / f"trial-{role}", config=cfg)
        try:
            if role == "gold":
                ws.overlay_tests(cand.test_files)
                ws.overlay_sources(list(sources))
            binding = deps.binding_for(ws.root)
            with runner.deps_bound(binding):
                probe = runner.probe_environment(executor, ws.root)
                assert probe is not None and probe.ok, probe.combined if probe else ""
                run = runner.run(executor, ws.root, ("./app",))
                cmd = runner.command(ws.root, ("./app",), executor=executor, timeout=60)
            assert run.green, (role, run.tail)
            assert cmd.env["GOPROXY"] == "off" and cmd.ro_mounts == deps.gold.mounts
        finally:
            ws.remove()
    # and without the set the same tree cannot build offline — the D1 defect, reproduced
    ws = Workspace.create(repo, feat, scratch / "trial-bare", config=cfg)
    try:
        bare = runner.run(executor, ws.root, ("./app",))
        assert bare.red and not bare.failing, bare.tail
    finally:
        ws.remove()
