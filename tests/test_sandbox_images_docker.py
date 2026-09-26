"""The shipped reference sandbox images, proven from inside against a real daemon (F42, part 1).

``deploy/sandbox/Dockerfile.{python,node,go}`` are what a deployment points
``CRB_SANDBOX__IMAGE`` (or a repository's ``sandbox_image``) at. This module is the proof
that each of them is fit for :class:`~crb.core.execution.DockerExecutor` — the same walls
:mod:`tests.test_sandbox_docker` proves for the inline python test image, on every image
that ships, through the real runner of that language on that language's fixture:

* the image's own default user is uid 65534, and so is the user the executor runs;
* the root filesystem is read-only from inside (``/usr`` refuses a write) and so is the
  worktree at ``/src``; ``/work`` — the throwaway copy every command runs in (ADR-0019 §7) —
  and ``/tmp`` accept one, and nothing a test writes reaches the host; the image carries the
  ``sh`` and GNU ``tar`` that copy needs;
* no setuid/setgid file is in the image (the bases' ``su``, ``mount``, ``passwd`` … have the
  bits stripped by the Dockerfile) — inert under the executor anyway, held regardless;
* the network is off: a test that asserts ``example.com:443`` is reachable FAILS, attributed
  to exactly that test id by the runner's parser;
* an image that is not in the daemon's store is ``SandboxUnavailable`` — ``--pull=never``,
  the worker never reaches for a registry at run time;
* the fixture repository's feat commit qualifies (RED at the parent, gold clean) and its gold
  overlay grades clean, with nothing left behind on the host worktree;
* the image carries the OCI labels and the non-root ``USER`` the Dockerfile promises.

Which image: ``CRB_TEST_SANDBOX_IMAGE_<LANG>`` names a present tag (CI's ``sandbox-images``
job passes the image it just built from the same Dockerfile, so the bytes under test are the
bytes shipped); unset, ``crb-sandbox-<lang>:local`` is built once per session from
``deploy/sandbox/Dockerfile.<lang>`` with ``deploy/sandbox`` as the context — exactly the
operator's build command. Skipped with the probe's reason when no daemon answers; a build
or a missing named image is a skip locally and a FAILURE under ``CRB_TEST_STRICT_WARMUP=1``.

Worktrees live under ``tests/.cache/sandbox`` (the VM behind colima / Docker Desktop cannot
bind-mount pytest's ``tmp_path``).

Navigation
----------
What it is:   The suite for the shipped reference sandbox images (deploy/sandbox), one
              parametrisation per language, against a real daemon.
What it does: Pins, per image, that the default and the executor's user are uid 65534, that
              the root filesystem and the worktree (``/src``) are read-only from inside while
              the throwaway ``/work`` copy and ``/tmp`` are writable and the host tree stays
              byte-identical, that ``sh`` and GNU ``tar`` are present, that no setuid/setgid file is
              in the image, that ``/tmp`` is
              ``noexec`` except for the Go runner's command, that a network probe FAILS
              through the language's runner, that an absent image is ``SandboxUnavailable``
              rather than a pull, that the language
              fixture qualifies and grades clean under ``DockerExecutor`` leaving the host
              worktree untouched, and that the image's OCI labels and ``USER`` are set.
How:          ``lang`` is a module-scoped parametrised fixture; the image comes from
              ``CRB_TEST_SANDBOX_IMAGE_<LANG>`` or a once-per-session ``docker build`` of the
              Dockerfile; each language contributes its fixture, its ``RepoConfig`` and a
              net-probe test file; the walls are asked through ``Command`` and the runner.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   deploy/sandbox/Dockerfile.python, deploy/sandbox/Dockerfile.node,
              deploy/sandbox/Dockerfile.go (the images under test),
              src/crb/core/execution.py (``DockerExecutor`` drives them),
              tests/conftest_langs.py (``ensure_shipped_sandbox_image`` and the probes),
              tests/fixtures/langs/pyrepo_min.py, tests/fixtures/langs/noderepo.py,
              tests/fixtures/langs/gorepo.py (the fixtures), tests/test_sandbox_docker.py (the
              same walls on the inline test image, plus the kill path),
              .github/workflows/ci.yml (the ``sandbox-images`` job that builds and runs this)
Tested by:    tests/test_sandbox_images_docker.py
Touch when:   a reference image is added under deploy/sandbox (add its language to
              ``conftest_langs.SHIPPED_SANDBOX_LANGS``, its fixture, its net probe and its
              expected gold change here, and a build + smoke leg in ci.yml); a Dockerfile
              changes what it carries (the fixture must still need nothing but the toolchain).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from crb.core.execution import Command, DockerExecutor, DockerSettings, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.mine import Candidate, qualify
from crb.core.runners import get_runner
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures.posture import grade_adhoc as grade

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

pyrepo_min = langs.fixture_module("pyrepo_min")
noderepo = langs.fixture_module("noderepo")
gorepo = langs.fixture_module("gorepo")

pytestmark = [pytest.mark.docker, pytest.mark.slow, pytest.mark.sandbox_images]

#: The OCI labels every shipped Dockerfile sets (deploy/sandbox/README.md §1).
_REQUIRED_LABELS: tuple[str, ...] = (
    "org.opencontainers.image.title",
    "org.opencontainers.image.description",
    "org.opencontainers.image.vendor",
    "org.opencontainers.image.licenses",
    "org.opencontainers.image.source",
    "org.opencontainers.image.documentation",
)


@dataclass(frozen=True)
class NetProbe:
    """A test file dropped into the trial that asserts the network IS reachable — inside the
    sandbox it must FAIL, attributed to exactly ``test_id`` by the runner's parser."""

    path: str
    test_id: str
    source: str


_NODE_NET_SRC = (
    '"use strict";\n'
    'const test = require("node:test");\n'
    'const net = require("node:net");\n\n'
    'test("network reachable", (t, done) => {\n'
    '  const s = net.connect({ host: "example.com", port: 443, timeout: 5000 });\n'
    '  s.on("connect", () => { s.destroy(); done(); });\n'
    '  s.on("error", (e) => done(e));\n'
    '  s.on("timeout", () => { s.destroy(); done(new Error("timeout")); });\n'
    "});\n"
)
_GO_NET_SRC = (
    "package calc\n\n"
    'import (\n\t"net"\n\t"testing"\n\t"time"\n)\n\n'
    "func TestNetworkReachable(t *testing.T) {\n"
    '\tc, err := net.DialTimeout("tcp", "example.com:443", 5*time.Second)\n'
    "\tif err != nil {\n"
    '\t\tt.Fatalf("network unreachable: %v", err)\n'
    "\t}\n"
    "\tc.Close()\n"
    "}\n"
)


@dataclass(frozen=True)
class Lang:
    """What one language contributes: how to build its fixture, its config, the net probe,
    the source file its gold commit changes, the target scope and parent baseline the
    runner suite pins (the same reading, now from inside the image), and what a sandboxed
    run may leave on the host."""

    name: str
    net: NetProbe
    gold_src: str
    target_tests: tuple[str, ...]
    baseline_failing: tuple[str, ...]
    allowed_host_writes: frozenset[str]

    def build(self, root: Path) -> tuple[Path, str]:
        if self.name == "python":
            return pyrepo_min.build(root)
        if self.name == "node":
            return noderepo.build(root, "node")
        return gorepo.build(root)

    def config(self) -> RepoConfig:
        if self.name == "python":
            return pyrepo_min.config()
        if self.name == "node":
            return noderepo.config("node")
        return gorepo.config()


_LANGS: dict[str, Lang] = {
    "python": Lang(
        "python",
        NetProbe(pyrepo_min.NET_TEST, pyrepo_min.NET_TEST_ID, pyrepo_min.NET_TEST_SRC),
        pyrepo_min.SRC_SUB,
        (pyrepo_min.TEST_SUB,),
        # pytest attributes the ImportError at the parent to the file (collection error)
        (pyrepo_min.TEST_SUB,),
        frozenset({".pytest_scratch", ".git"}),
    ),
    "node": Lang(
        "node",
        NetProbe("__tests__/net.test.js", "network reachable", _NODE_NET_SRC),
        noderepo.SRC_SUB,
        (noderepo.test_sub("node"),),
        # node's JUnit reporter attributes a file that fails to load to the file itself
        (noderepo.test_sub("node"),),
        frozenset({".git"}),
    ),
    "go": Lang(
        "go",
        NetProbe("calc/net_test.go", f"{gorepo.CALC_PKG}::TestNetworkReachable", _GO_NET_SRC),
        gorepo.SRC_SUB,
        ("./calc",),
        # at the parent the overlaid test does not compile: RED but unattributed (empty
        # baseline, ``baseline_parse_error`` recorded) — exactly what test_runners_go pins
        (),
        frozenset({".git"}),
    ),
}
assert tuple(_LANGS) == langs.SHIPPED_SANDBOX_LANGS


# ---------------------------------------------------------------------------
# Fixtures (module-scoped per language: one image, one repo, one qualification)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=langs.SHIPPED_SANDBOX_LANGS)
def lang(request: pytest.FixtureRequest) -> Lang:
    """The language (and shipped image) under test, module-scoped."""
    return _LANGS[str(request.param)]


@pytest.fixture(scope="module")
def image(lang: Lang) -> str:
    """The image's tag, present in the daemon (skipped with the reason otherwise)."""
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    return langs.ensure_shipped_sandbox_image(lang.name)


@pytest.fixture(scope="module")
def sandbox_root(lang: Lang) -> Iterator[Path]:
    """A bind-mountable scratch root under the tests cache; removed after the module."""
    root = langs.CACHE_DIR / "sandbox" / f"image-{lang.name}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def built(lang: Lang, sandbox_root: Path) -> tuple[GitRepo, str]:
    root, feat_sha = lang.build(sandbox_root)
    return GitRepo(root), feat_sha


@pytest.fixture(scope="module")
def config(lang: Lang) -> RepoConfig:
    return lang.config()


@pytest.fixture(scope="module")
def runner(config: RepoConfig) -> BaseRunner:
    return get_runner(config)


@pytest.fixture(scope="module")
def executor(image: str) -> DockerExecutor:
    """The hardened ``DockerExecutor`` on the shipped image, exactly as the worker builds it."""
    return DockerExecutor(DockerSettings(image=image))


@pytest.fixture(scope="module")
def candidate(built: tuple[GitRepo, str], config: RepoConfig) -> Candidate:
    repo, feat_sha = built
    return langs.feat_candidate(repo, config, feat_sha)


@pytest.fixture(scope="module")
def task(
    built: tuple[GitRepo, str],
    config: RepoConfig,
    runner: BaseRunner,
    executor: DockerExecutor,
    candidate: Candidate,
    sandbox_root: Path,
) -> TaskSpec:
    """The feat task qualified once INSIDE the image; a skip reason here is an image defect."""
    repo, _ = built
    outcome = qualify(
        repo, config, candidate, runner=runner, executor=executor, scratch=sandbox_root / "mine"
    )
    assert outcome.task is not None, outcome.skipped_reason
    return outcome.task


@pytest.fixture
def trial(
    built: tuple[GitRepo, str], config: RepoConfig, candidate: Candidate, sandbox_root: Path
) -> Iterator[Workspace]:
    """A fresh worktree per test with the feat tests overlaid, removed afterwards."""
    repo, _ = built
    ws = langs.trial_worktree(
        repo, candidate, sandbox_root / f"trial-{uuid.uuid4().hex[:8]}", config
    )
    yield ws
    ws.remove()


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("docker") or "docker", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# The image as built
# ---------------------------------------------------------------------------


def test_image_declares_nobody_and_the_oci_labels(image: str):
    """``USER 65534:65534`` and every ``org.opencontainers.image.*`` label the README lists
    are in the image's config — a stray ``docker run`` of it is non-root and self-describing."""
    r = _docker("image", "inspect", "--format", "{{json .Config}}", image)
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout)
    assert cfg["User"] == "65534:65534", cfg["User"]
    labels = cfg.get("Labels") or {}
    missing = [k for k in _REQUIRED_LABELS if not labels.get(k)]
    assert not missing, f"{image} lacks labels {missing}"
    assert labels["org.opencontainers.image.licenses"] == "Apache-2.0"


def test_executor_is_hardened_on_the_image(executor: DockerExecutor, image: str):
    d = executor.describe()
    assert d["executor"] == "docker" and d["image"] == image and d["network"] == "none"
    assert d["user"] == "65534:65534"


# ---------------------------------------------------------------------------
# The walls, from inside
# ---------------------------------------------------------------------------


def test_runs_as_nobody(executor: DockerExecutor, image: str, trial: Workspace):
    """uid 65534 both as the image's own default (no ``--user``) and under the executor."""
    plain = _docker("run", "--rm", "--network=none", image, "id", "-u")
    assert plain.returncode == 0 and plain.stdout.strip() == "65534", plain.stderr
    r = executor.run(Command(("id", "-u"), trial.root, timeout=60))
    assert r.ok and r.stdout.strip() == "65534", r.combined


def _tree_hashes(root: Path) -> dict[str, str]:
    """``{relative path: sha256}`` of every regular file (symlinks by their target)."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            f = Path(dirpath) / name
            rel = os.path.relpath(f, root)
            out[rel] = (
                "link:" + os.readlink(f)
                if f.is_symlink()
                else hashlib.sha256(f.read_bytes()).hexdigest()
            )
    return out


def test_a_test_can_write_its_tree_and_nothing_reaches_the_host(executor: DockerExecutor, trial):
    """ADR-0019 §7 (the D5 finding): ``/usr`` and the worktree at ``/src`` refuse a write
    (``Read-only file system``); ``/work`` — the throwaway copy the command runs in — and
    ``/tmp`` accept one; and the host tree is byte-identical afterwards."""
    before = _tree_hashes(trial.root)
    root = executor.run(Command(("sh", "-c", "echo owned > /usr/hacked"), trial.root, timeout=60))
    assert not root.ok and "Read-only file system" in root.combined, root.combined
    src = executor.run(
        Command(("sh", "-c", "echo owned > /src/hacked.txt"), trial.root, timeout=60)
    )
    assert not src.ok and "Read-only file system" in src.combined, src.combined
    work = executor.run(
        Command(
            ("sh", "-c", "echo owned > /work/hacked.txt && cat /work/hacked.txt && pwd"),
            trial.root,
            timeout=60,
        )
    )
    assert work.ok and work.stdout.split() == ["owned", "/work"], work.combined
    tmp = executor.run(
        Command(("sh", "-c", "echo scratch > /tmp/probe && cat /tmp/probe"), trial.root, timeout=60)
    )
    assert tmp.ok and tmp.stdout.strip() == "scratch", tmp.combined
    assert not (trial.root / "hacked.txt").exists()
    assert _tree_hashes(trial.root) == before


def test_the_images_carry_sh_and_tar(image: str):
    """The throwaway tree is made by ``/bin/sh`` and GNU ``tar`` inside the image (the
    copy's ``--warning`` option is GNU's): every shipped image must carry both."""
    r = _docker(
        "run", "--rm", "--network=none", image, "/bin/sh", "-c", "command -v tar && tar --version"
    )
    assert r.returncode == 0, r.stderr
    assert "GNU tar" in r.stdout, r.stdout


def test_no_setuid_or_setgid_binary_in_the_image(executor: DockerExecutor, trial: Workspace):
    """The image carries no setuid/setgid file: the Debian bases ship ``su``, ``mount``,
    ``passwd`` and friends with the bits set, and each Dockerfile's single ``RUN`` strips
    them (``find / -xdev -perm /6000 -type f -exec chmod a-s``). They are inert under the
    executor anyway (``--cap-drop=ALL``, ``no-new-privileges``, uid 65534) — stripping them
    means the image does not depend on either flag to hold. Read from inside as the
    executor's user; ``-xdev`` keeps ``find`` off ``/proc``, ``/sys``, ``/tmp`` and ``/work``."""
    run = executor.run(
        Command(
            ("sh", "-c", "find / -xdev -perm /6000 -type f 2>/dev/null; echo end-of-list"),
            trial.root,
            timeout=120,
        )
    )
    assert run.ok, run.combined
    assert run.stdout.strip() == "end-of-list", run.combined


_TMP_PROBE = (
    "sh",
    "-c",
    # the mount line, then try to RUN a script written under /tmp
    "grep ' /tmp ' /proc/mounts; printf '#!/bin/sh\\necho ran\\n' > /tmp/probe.sh"
    " && chmod +x /tmp/probe.sh && /tmp/probe.sh",
)


def _tmp_mount_opts(combined: str) -> set[str]:
    """The option set of the ``/tmp`` line in ``/proc/mounts`` (``exec`` is the absence
    of ``noexec`` there — the kernel prints only the restrictive flags)."""
    line = next(ln for ln in combined.splitlines() if " /tmp " in ln)
    return set(line.split()[3].split(","))


def test_tmp_is_noexec_unless_the_runner_declares_exec_tmp(
    lang: Lang, trial: Workspace, runner: BaseRunner, executor: DockerExecutor
):
    """The tmpfs at ``/tmp`` is ``noexec,nosuid,nodev`` for an ordinary command — the
    kernel's own mount table says so and a script written there is refused — and ``exec``
    (``nosuid,nodev`` still held) only for a command whose runner declares
    ``Command.exec_tmp``, which is the Go runner's ``go test`` and nothing else: the
    exception is per toolchain, never per repository."""
    plain = executor.run(Command(_TMP_PROBE, trial.root, timeout=60))
    opts = _tmp_mount_opts(plain.combined)
    assert {"noexec", "nosuid", "nodev"} <= opts, plain.combined
    assert "Permission denied" in plain.combined and "ran" not in plain.stdout, plain.combined

    declared = runner.command(
        trial.root, runner.target_scope((lang.net.path,)), executor=executor, timeout=60
    )
    assert declared.exec_tmp is (lang.name == "go"), (lang.name, declared.exec_tmp)
    if not declared.exec_tmp:
        return
    go = executor.run(Command(_TMP_PROBE, trial.root, timeout=60, exec_tmp=declared.exec_tmp))
    opts = _tmp_mount_opts(go.combined)
    assert "noexec" not in opts and {"nosuid", "nodev"} <= opts, go.combined
    assert go.ok and go.stdout.rstrip().endswith("ran"), go.combined


def test_network_is_off(lang: Lang, trial, task: TaskSpec, runner: BaseRunner, executor):
    """A test asserting ``example.com:443`` is reachable FAILS through the language's runner,
    attributed to exactly that id (the parser saw a real failure, not a harness error)."""
    trial.overlay_sources(task.src_files)
    (trial.root / lang.net.path).parent.mkdir(parents=True, exist_ok=True)
    (trial.root / lang.net.path).write_text(lang.net.source, encoding="utf-8")
    run = runner.run(executor, trial.root, runner.target_scope((lang.net.path,)))
    assert run.red and not run.timed_out, run.tail
    assert not run.parse_error, run.tail
    assert lang.net.test_id in run.failing, (run.failing, run.tail)
    assert run.failing <= {lang.net.test_id, *task.target_tests}, run.failing


def test_an_absent_image_fails_closed_without_a_pull(trial: Workspace):
    """``--pull=never``: an image that is not in the daemon's store is ``SandboxUnavailable``
    (exit 125, ``No such image``) — the worker never reaches for a registry at run time.

    The match pins the daemon's *no-pull* wording: without the flag the same unpullable tag
    is still exit 125 but reads ``pull access denied … repository does not exist`` (the
    daemon went to the registry), so ``exit 125`` alone would not catch the flag's loss."""
    ex = DockerExecutor(DockerSettings(image=f"crb-sandbox-absent-{uuid.uuid4().hex[:8]}:none"))
    with pytest.raises(SandboxUnavailable, match=r"exit 125.*No such image"):
        ex.run(Command(("id", "-u"), trial.root, timeout=60))


# ---------------------------------------------------------------------------
# The instrument runs on the image
# ---------------------------------------------------------------------------


def test_fixture_qualifies_in_the_image(lang: Lang, task: TaskSpec):
    """RED at the parent, gold clean — and the baseline reads exactly as the language's
    runner suite pins it on the host, so the image changes nothing about the instrument."""
    assert task.red_checked is True
    assert task.gold_clean is True, task.gold_note
    assert task.target_tests == lang.target_tests
    assert task.baseline_failing == lang.baseline_failing, task.labels
    if not lang.baseline_failing:
        assert "unattributed" in task.labels.get("baseline_parse_error", "")
    else:
        assert "baseline_parse_error" not in task.labels


def test_gold_grades_clean_and_leaves_the_host_untouched(
    lang: Lang, trial, task, config, runner, executor
):
    trial.overlay_sources(task.src_files)
    top_before = {p.name for p in trial.root.iterdir()}
    res = grade(trial, task, config=config, runner=runner, executor=executor)
    assert res.clean is True, res.to_dict()
    assert res.belts.all_true
    assert res.changed_files == (lang.gold_src,)
    assert trial.touched_files() == sorted({*task.src_files, *task.test_files})
    stray = {p.name for p in trial.root.iterdir()} - top_before - lang.allowed_host_writes
    assert not stray, f"sandboxed run left {sorted(stray)} on the host"


# ---------------------------------------------------------------------------
# The D5 regression: a test that writes into its own package directory
# ---------------------------------------------------------------------------


def test_a_test_that_writes_its_package_reads_the_same_on_the_host_and_in_the_copy() -> None:
    """ADR-0019 §7 on ``gorepo_deps`` (cobra's ``TestDeadcodeElimination`` shape), with its
    module dependency provisioned from a ``file://`` mirror into one sealed cache:

    * at the parent the tree-writing test passes on the host AND in the throwaway copy —
      the two baselines are equal, so nothing the posture does is charged to a builder;
    * on the ``readonly`` tree it fails; measured in that posture it sits in the baseline,
      so the gold graded in that posture has no new failure — and only a baseline measured
      somewhere else (the host) would have charged it as one: the D5 defect, reproduced."""
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    if not langs.has_tool("go"):
        pytest.skip("go not on PATH (the host posture needs it)")
    import importlib

    from crb.core.execution import LocalExecutor
    from crb.provision import SealedProvider
    from crb.provision.config import ProvisionConfig
    from crb.provision.store import remove_tree

    gorepo_deps = langs.fixture_module("gorepo_deps")
    goproxy = importlib.import_module("fixtures.goproxy")
    image = langs.ensure_shipped_sandbox_image("go")
    root = langs.CACHE_DIR / "sandbox" / f"d5-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        mirror = goproxy.build(root / "mirror")
        repo_root, feat = gorepo_deps.build(root / "repo")
        repo = GitRepo(repo_root)
        cfg = gorepo_deps.config()
        provider = SealedProvider(
            ProvisionConfig(
                enabled=True, env="dev", store=root / "deps", go_proxy=f"file://{mirror}"
            )
        )
        deps = provider.resolve(repo, cfg, gold=feat)
        runner = get_runner(cfg)
        cand = langs.feat_candidate(repo, cfg, feat)
        postures = {
            "host": LocalExecutor(),
            "copy": DockerExecutor(DockerSettings(image=image)),
            "readonly": DockerExecutor(DockerSettings(image=image, tree="readonly")),
        }

        def measure(sources: tuple[str, ...]) -> dict[str, frozenset[str]]:
            ws = langs.trial_worktree(
                repo, cand, root / f"t-{uuid.uuid4().hex[:6]}", cfg, sources=sources
            )
            try:
                out = {}
                with runner.deps_bound(deps.binding_for(ws.root)):
                    for name, ex in postures.items():
                        run = runner.run(ex, ws.root, ())
                        assert not run.env_error, (name, run.tail)
                        out[name] = run.failing
                assert not (ws.root / "writer" / "generated.txt").exists()
                return out
            finally:
                ws.remove()

        baseline = measure(())
        gold = measure(("go.mod", "go.sum", gorepo_deps.SRC_BYE))
        writer = gorepo_deps.WRITER_TEST_ID
        assert writer not in baseline["host"] and baseline["host"] == baseline["copy"]
        assert writer in baseline["readonly"]
        assert gold["host"] == gold["copy"] == frozenset(), gold
        # belt 3 in the readonly posture against ITS OWN baseline: no new failure …
        assert gold["readonly"] == frozenset({writer})
        assert gold["readonly"] - baseline["readonly"] == frozenset()
        # … and against a baseline measured on the host, the D5 misattribution
        assert gold["readonly"] - baseline["host"] == frozenset({writer})
    finally:
        remove_tree(root)
