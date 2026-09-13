"""Maven (surefire) runner for JVM repos."""

from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

from crb.core.execution import Command, ExecResult, Executor
from crb.core.runners.base import BaseRunner, TestRun, tail_of
from crb.core.spec import BELT_AFFECTED_DIRS


class MavenRunner(BaseRunner):
    name = "maven"
    default_timeout = 1500

    def target_scope(self, test_files: Sequence[str]) -> tuple[str, ...]:
        # src/test/java/com/x/FooTest.java -> FooTest (surefire -Dtest=)
        return tuple(sorted({os.path.basename(f).rsplit(".", 1)[0] for f in test_files}))

    def belt_scope(self, target_tests: Sequence[str], test_files: Sequence[str]) -> tuple[str, ...]:
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
        # surefire never clears its reports; a narrower run after a wider failing run
        # would otherwise inherit the previous run's failures at parse time.
        for reports in root.rglob("target/surefire-reports"):
            shutil.rmtree(reports, ignore_errors=True)
        return super().run(executor, root, scope, timeout=timeout)

    def _writable(self) -> tuple[str, ...]:
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
        wrapper = root / "mvnw"
        mvn = (
            "./mvnw"
            if wrapper.exists() and executor.name != "docker"
            else executor.tool("mvn", self.opts.get("mvn"))
        )
        argv = [
            mvn,
            "-q",
            "-B",
            "-o" if self.opts.get("offline", True) else "-U",
            *[str(f) for f in self.opts.get("maven_flags", []) or []],
            "test",
        ]
        if scope:
            argv += [
                f"-Dtest={','.join(scope)}",
                "-DfailIfNoTests=false",
                "-Dsurefire.failIfNoSpecifiedTests=false",
            ]
        env: dict[str, str] = {}
        if self.opts.get("java_home"):
            env["JAVA_HOME"] = str(self.opts["java_home"])
        if executor.name == "docker":
            env["MAVEN_OPTS"] = "-Dmaven.repo.local=/tmp/m2 " + str(self.opts.get("maven_opts", ""))
        return Command(tuple(argv), root, env=env, timeout=timeout, writable_paths=self._writable())

    def parse(self, result: ExecResult, root: Path) -> TestRun:
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
