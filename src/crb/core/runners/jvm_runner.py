"""Maven (surefire) runner for JVM repos.

Setup warms the local repository (``~/.m2`` on the host) with everything the
offline test command needs, in two online steps:

1. ``mvn test -DskipTests`` — compiler, resources, the surefire plugin and the
   dependencies. It does NOT warm surefire's test-framework provider
   (``surefire-junit-platform`` / ``-junit4`` / ``-junit47`` / ``-testng`` and the
   ``junit-platform-launcher`` aligned with the project's JUnit): ``-DskipTests``
   stops surefire before it chooses one, and a filter matching no class stops it
   the same way. Alone it left the first offline ``test`` failing on a cold
   repository (PR #57, hidden until then by a shared warm ``~/.m2``).
2. The provider probe, :class:`SurefireProbe`: ``mvn -fn test -Djvm=<stub>``.
   Surefire resolves the provider inside Maven exactly as the real run will, then
   forks ``<stub>/bin/java`` — a shell script that records the module and exits
   non-zero — so no test JVM starts and none of the repository's test code runs
   with the network (docs/SECURITY.md T1). ``-fn`` carries the probe past each
   module's stub failure so every module is warmed.

Measured on a cold repository (2026-09-27) and rejected: ``dependency:go-offline``
(never resolves the provider); ``dependency:get`` of the provider (surefire then
also asks for the launcher aligned to the project's JUnit — re-implementing its
selection per version is the trap); ``-Dtest=Class#noSuchMethod`` (warms it, but
the forked launcher loads the repository's ``LauncherSessionListener`` services).
Plugin configuration in a POM outranks the command line, so a POM that keeps
surefire in-process (``<forkCount>0</forkCount>``, 2.x ``forkMode=never``) or names
its own ``<jvm>`` would bypass the stub and run the repository's launcher code. An
offline ``-X`` dry configuration (``test -DskipTests`` with the probe's flags) reads
what surefire WILL do first; unless every surefire ``test`` execution forks the
stub (:func:`surefire_forks_to_stub`), setup refuses with :data:`IN_PROCESS_REFUSED`
and readiness reads false — nothing is probed. ``-DforkCount=1`` outranks a
``forkCount`` *property*, and ``-Dtest=*#crbNoSuchMethod`` is a second wall: no
test method runs even if a fork were ever real.

Ready is the same guard and probe offline (``-o``): ready iff every module that
failed is a surefire ``test`` failure whose fork reached the stub
(:func:`surefire_probe_ready`) — i.e. the offline test run can resolve every plugin,
artifact and provider.

Navigation
----------
What it is:   The JVM runner — ``MavenRunner`` over ``mvn test`` with surefire.
What it does: Maps test files to surefire class names and directories to package globs (a
              bare directory would match nothing and exit 0 — a false green), runs ``mvn -o
              test -Dtest=…`` with the previous run's reports cleared first, parses the
              surefire XML into ``<class>::<method>`` ids, warms ``~/.m2`` in setup (the
              build, then the provider probe through a stub ``java``) and detects
              spotless/checkstyle for belt 5.
How:          ``run``: delete every ``target/surefire-reports`` → base ``run``. ``command``:
              ``./mvnw`` if present → ``-q -B -o`` → ``-Dtest`` from the scope. ``parse``:
              walk ``TEST-*.xml`` for ``<failure>``/``<error>`` children. ``SurefireProbe``:
              a temp ``bin/java`` stub; ``-X`` dry configuration → ``surefire_forks_to_stub``;
              then ``-fn`` → ``surefire_probe_ready`` over the output.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/runners/base.py (the contract), src/crb/core/lint.py (``jvm_plan``),
              src/crb/core/execution.py (``Executor.tool``; writable ``target/`` under docker),
              src/crb/core/spec.py (``src_prefix`` locates the module's ``target/``),
              src/crb/core/runners/__init__.py
Tested by:    tests/test_runners_jvm.py, tests/test_runners_parsers.py, tests/test_runners_setup.py
              (the cold-repository case runs setup against an EMPTY private local repository)
Touch when:   a Maven repository needs a JDK, extra flags or profiles — set ``runner_opts``
              (``java_home``, ``maven_flags``, ``maven_opts``, ``mvn``, ``writable``,
              ``offline``; docs/OPERATOR.md); Gradle would be a new runner, not an option here.
"""

from __future__ import annotations

import itertools
import os
import re
import shlex
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType

from crb.core.execution import Command, ExecResult, Executor, LocalExecutor
from crb.core.lint import LintPlan, jvm_plan
from crb.core.runners.base import (
    READY_CHECK_TIMEOUT_S,
    BaseRunner,
    SetupResult,
    SetupSession,
    SetupStep,
    TestRun,
    tail_of,
)
from crb.core.spec import BELT_AFFECTED_DIRS

#: One module's failure under ``-fn``: ``[ERROR] Failed to execute goal <g:a:v:goal> (…) on
#: project <name>: …`` — Maven prints one per failed module and stops that module there.
_GOAL_FAILED = re.compile(r"^\[ERROR\] Failed to execute goal (\S+) ", re.M)

#: The fake ``java``: surefire forks it only after resolving the provider. It records the
#: module (nearest ``pom.xml`` above the fork's working directory, so ``target/fork1`` counts
#: once) and exits non-zero at once — no JVM, no test class, no repository code.
_STUB_JAVA = """#!/bin/sh
# crb surefire provider probe (crb.core.runners.jvm_runner): runs nothing.
d=$(pwd -P)
while [ "$d" != / ] && [ ! -f "$d/pom.xml" ]; do d=$(dirname "$d"); done
printf '%s\\n' "$d" >> RECORD
exit 97
"""

#: Setup's note when the POM keeps surefire from forking the stub (the module docstring).
IN_PROCESS_REFUSED = (
    "surefire would not fork the probe's stub (the POM sets forkCount 0, forkMode=never or its "
    "own jvm), so its test-framework provider cannot be warmed without running tests online: "
    "warm it by hand (one online `mvn test` you trust) or drop that configuration"
)

#: ``-X``: one surefire ``test`` execution's configuration block, then its parameters.
_MOJO_BLOCK = re.compile(r"^\[DEBUG\] Configuring mojo execution '([^']*)'", re.M)
_MOJO_PARAM = re.compile(r"^\[DEBUG\]\s+\([a-z]\) (\w+) = (.*)$", re.M)


def surefire_forks_to_stub(debug_output: str, java: str) -> bool:
    """``True`` iff every surefire ``test`` execution in a ``-X`` dry configuration forks
    (``forkCount`` above 0, ``forkMode`` not ``never``) and forks ``java`` — i.e. the probe
    can start no test JVM. No surefire execution at all is ``True`` (nothing to probe);
    surefire named but no block read, or a value that does not parse, is ``False``."""
    starts = list(_MOJO_BLOCK.finditer(debug_output))
    surefire = [m for m in starts if ":maven-surefire-plugin:" in m.group(1)]
    surefire = [m for m in surefire if m.group(1).split(":")[3:4] == ["test"]]
    if not surefire:
        return "maven-surefire-plugin" not in debug_output
    ends = {m.start(): n.start() for m, n in itertools.pairwise(starts)}
    for m in surefire:
        block = debug_output[m.end() : ends.get(m.start(), len(debug_output))]
        params = {k: v.strip() for k, v in _MOJO_PARAM.findall(block)}
        if params.get("jvm") != java or params.get("forkMode") == "never":
            return False
        count = params.get("forkCount", "")
        try:
            forks = float(count[:-1] if count.endswith("C") else count)
        except ValueError:
            return False
        if forks <= 0:
            return False
    return True


class SurefireProbe:
    """A throwaway stub JDK for surefire's ``jvm`` parameter (a context manager).

    ``java`` is ``<tmp>/bin/java`` (surefire insists on that suffix); ``reached()`` is the
    set of module directories whose fork got to it. The directory is removed on exit.
    """

    def __init__(self) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="crb-surefire-probe-"))
        self.java = self._dir / "bin" / "java"
        self._record = self._dir / "reached"
        self.java.parent.mkdir()
        self.java.write_text(_STUB_JAVA.replace("RECORD", shlex.quote(str(self._record))))
        self.java.chmod(0o700)

    def __enter__(self) -> SurefireProbe:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def argv(self, mvn: str, flags: Sequence[str], *, offline: bool) -> list[str]:
        """``mvn [-o] -q -B -fn <flags> test -Djvm=<stub>`` plus ``-DforkCount=1`` (outranks
        a ``forkCount`` POM *property*) and the method filter — a second wall behind
        :func:`surefire_forks_to_stub`: no test method runs even if a fork were ever real."""
        return [
            mvn,
            *(["-o"] if offline else []),
            "-q",
            "-B",
            "-fn",
            *flags,
            "test",
            f"-Djvm={self.java}",
            "-DforkCount=1",
            "-Dtest=*#crbNoSuchMethod",
            "-Dsurefire.failIfNoSpecifiedTests=false",
        ]

    def preflight_argv(self, mvn: str, flags: Sequence[str]) -> list[str]:
        """``mvn -o -X -B <flags> test -DskipTests`` with the probe's ``jvm`` / ``forkCount``:
        prints the configuration surefire will run with, and runs no test."""
        return [
            mvn,
            "-o",
            "-X",
            "-B",
            *flags,
            "test",
            "-DskipTests",
            f"-Djvm={self.java}",
            "-DforkCount=1",
        ]

    def reached(self) -> set[str]:
        """The module directories whose surefire fork reached the stub."""
        try:
            text = self._record.read_text(encoding="utf-8")
        except OSError:
            return set()
        return {line for line in text.splitlines() if line}


def surefire_probe_ready(res: ExecResult, reached: set[str]) -> bool:
    """Ready iff Maven finished (``-fn`` exits 0 whatever failed), every failed module is a
    surefire ``test`` failure, and there are exactly as many as modules that reached the
    stub — a module that reached it always fails, so equality means none failed before its
    fork (a cold provider, plugin or dependency). Unparsed ``[ERROR]`` output fails closed."""
    if not res.ok:
        return False
    text = res.combined
    failed = _GOAL_FAILED.findall(text)
    if not failed and "[ERROR]" in text:
        return False
    if any(":maven-surefire-plugin:" not in g or not g.endswith(":test") for g in failed):
        return False
    return len(failed) == len(reached)


class MavenRunner(BaseRunner):
    """``RepoConfig.runner == "maven"``. Scopes are surefire ``-Dtest`` patterns: class
    simple names for targets, ``pkg/**/*`` globs for ``affected_dirs``."""

    name = "maven"
    default_timeout = 1500

    # --- environment -------------------------------------------------------------
    def _mvn(self, root: Path, executor: Executor) -> str:
        """The repository's wrapper when it ships one (it pins the Maven version), else the
        executor's ``mvn``; the sandbox image is expected to provide its own."""
        wrapper = root / "mvnw"
        if wrapper.exists() and executor.name != "docker":
            return "./mvnw"
        return executor.tool("mvn", self.opts.get("mvn"))

    def _flags(self) -> list[str]:
        return [str(f) for f in self.opts.get("maven_flags", []) or []]

    def _env(self, executor: Executor) -> dict[str, str]:
        """``JAVA_HOME`` when configured; under docker the local repository moves to
        ``/tmp/m2`` because ``$HOME`` is not writable in the sandbox."""
        env: dict[str, str] = {}
        if self.opts.get("java_home"):
            env["JAVA_HOME"] = str(self.opts["java_home"])
        if executor.name == "docker":
            env["MAVEN_OPTS"] = "-Dmaven.repo.local=/tmp/m2 " + str(self.opts.get("maven_opts", ""))
        return env

    # --- belt 5 -------------------------------------------------------------------
    def detect_lint(self, root: Path, executor: Executor) -> LintPlan | None:
        """``spotless:check`` / ``checkstyle:check`` (offline, module-wide) when the
        pom declares the plugin — gson (spotless), petclinic and commons-lang
        (checkstyle)."""
        root = Path(root)
        return jvm_plan(root, self._mvn(root, executor), self._flags(), self._env(executor))

    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        """The guard, then the provider probe, offline (``-o``): every plugin, artifact and
        surefire provider resolves (``surefire_probe_ready``); a POM that would not fork the
        stub, a launch error or a timeout reads not ready."""
        root = Path(root)
        mvn = "./mvnw" if (root / "mvnw").exists() else str(self.opts.get("mvn") or "mvn")
        env = {"JAVA_HOME": str(self.opts["java_home"])} if self.opts.get("java_home") else {}
        with SurefireProbe() as probe:
            try:
                dry = LocalExecutor().run(
                    Command(
                        tuple(probe.preflight_argv(mvn, self._flags())),
                        root,
                        env=env,
                        timeout=READY_CHECK_TIMEOUT_S,
                    )
                )
                if not dry.ok or not surefire_forks_to_stub(dry.combined, str(probe.java)):
                    return False
                argv = probe.argv(mvn, self._flags(), offline=True)
                res = LocalExecutor().run(
                    Command(tuple(argv), root, env=env, timeout=READY_CHECK_TIMEOUT_S)
                )
            except (OSError, ValueError):
                return False
            return surefire_probe_ready(res, probe.reached())

    def setup(
        self,
        executor: Executor,
        root: Path,
        *,
        env_dir: Path,
        timeout: int,
        on_step: Callable[[SetupStep], None] | None = None,
    ) -> SetupResult:
        """``mvn test -DskipTests`` online, the offline guard, then the provider probe
        online — the build alone leaves surefire's provider cold (the module docstring)."""
        refusal = self.sandbox_refusal(executor)
        if refusal is not None:
            return refusal
        root = Path(root)
        session = SetupSession(executor, on_step=on_step)
        if not (root / "pom.xml").is_file():
            return session.result(False, "no pom.xml: not a Maven project")
        mvn = self._mvn(root, executor)

        def online(argv: Sequence[str]) -> SetupStep:
            return session.run(
                Command(
                    tuple(argv),
                    root,
                    env=self._env(executor),
                    timeout=self.setup_timeout(timeout),
                    writable_paths=self._writable(),
                    network=True,
                )
            )

        if not online([mvn, "-q", "-B", *self._flags(), "test", "-DskipTests"]).ok:
            return self.finish_setup(session, root, Path(env_dir))
        with SurefireProbe() as probe:
            dry = self._run_quiet(
                executor,
                Command(
                    tuple(probe.preflight_argv(mvn, self._flags())),
                    root,
                    env=self._env(executor),
                    timeout=self.setup_timeout(timeout),
                    writable_paths=self._writable(),
                ),
            )
            if not dry.ok or not surefire_forks_to_stub(dry.combined, str(probe.java)):
                return session.result(False, IN_PROCESS_REFUSED)
            online(probe.argv(mvn, self._flags(), offline=False))
        return self.finish_setup(session, root, Path(env_dir))

    @staticmethod
    def _run_quiet(executor: Executor, cmd: Command) -> ExecResult:
        """A setup-phase command that is not a step: the offline ``-X`` dry configuration,
        whose multi-megabyte debug output is read, never recorded. A launch error is a
        failed result (rc 127), as ``SetupSession.run`` records one."""
        try:
            return executor.run(cmd)
        except OSError as exc:
            return ExecResult(127, "", f"{type(exc).__name__}: {exc}", False, 0.0)

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        """Surefire class simple names (``src/test/java/com/x/FooTest.java`` → ``FooTest``)."""
        # src/test/java/com/x/FooTest.java -> FooTest (surefire -Dtest=)
        return tuple(sorted({os.path.basename(f).rsplit(".", 1)[0] for f in test_files}))

    def belt_scope(self, target_tests: Sequence[str], test_files: Sequence[str]) -> tuple[str, ...]:
        """As the base rule, except ``affected_dirs`` becomes surefire package globs."""
        # `-Dtest=src/test/java/ex/` matches NO class and, with failIfNoTests=false,
        # exits 0 having run nothing — a silent false-green belt. AFFECTED_DIRS must
        # therefore be expressed as surefire package globs: "ex/**/*".
        if self.config.belt_scope == BELT_AFFECTED_DIRS:
            tp = self.config.test_prefix
            globs = set()
            for tf in test_files:
                d = os.path.dirname(tf)
                pkg = d[len(tp) :] if tp and d.startswith(tp) else d
                globs.add((pkg.strip("/") + "/**/*") if pkg.strip("/") else "**/*")
            return tuple(sorted(globs))
        return super().belt_scope(target_tests, test_files)

    def run(
        self, executor: Executor, root: Path, scope: Sequence[str], *, timeout: int = 0
    ) -> TestRun:
        """Base ``run`` on a tree with no stale surefire reports (``parse`` reads the files)."""
        # surefire never clears its reports; a narrower run after a wider failing run
        # would otherwise inherit the previous run's failures at parse time.
        for reports in root.rglob("target/surefire-reports"):
            shutil.rmtree(reports, ignore_errors=True)
        return super().run(executor, root, scope, timeout=timeout)

    def _writable(self) -> tuple[str, ...]:
        """The ``target/`` directories the sandbox must let Maven write (root and module)."""
        # every module's target/ plus the root's; derived from src_prefix when modular
        paths = {"target"}
        sp = self.config.src_prefix
        if "src/main/" in sp:
            mod = sp[: sp.find("src/main/")].rstrip("/")
            if mod:
                paths.add(f"{mod}/target")
        for extra in self.opts.get("writable", []) or []:
            paths.add(str(extra))
        return tuple(sorted(paths))

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        """``mvn -q -B -o test -Dtest=<scope>``; ``failIfNoTests=false`` on both surefire
        properties so a scope that selects nothing in a sibling module does not abort."""
        argv = [
            self._mvn(root, executor),
            "-q",
            "-B",
            "-o" if self.opts.get("offline", True) else "-U",
            *self._flags(),
            "test",
        ]
        if scope:
            argv += [
                f"-Dtest={','.join(scope)}",
                "-DfailIfNoTests=false",
                "-Dsurefire.failIfNoSpecifiedTests=false",
            ]
        return Command(
            tuple(argv),
            root,
            env=self._env(executor),
            timeout=timeout,
            writable_paths=self._writable(),
        )

    def parse(self, result: ExecResult, root: Path) -> TestRun:
        """``<classname>::<name>`` for every surefire ``<testcase>`` with a ``<failure>`` or
        ``<error>`` child; the reports on disk are the source, not stdout."""
        failing: set[str] = set()
        for xmlf in root.rglob("target/surefire-reports/TEST-*.xml"):
            try:
                xml_root = ET.parse(xmlf).getroot()  # noqa: S314 — surefire output
            except ET.ParseError:
                continue
            for tc in xml_root.iter("testcase"):
                if any(ch.tag in ("failure", "error") for ch in tc):
                    failing.add(f"{tc.get('classname', '')}::{tc.get('name', '')}")
        return TestRun(
            result.returncode,
            frozenset(failing),
            tail_of(result.combined),
            duration_s=result.duration_s,
        )
