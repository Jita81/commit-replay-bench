"""JVM fixture: a single-module Maven project on JUnit Jupiter 5 + surefire 3.x.

Layout::

    pom.xml                          junit-jupiter 5.14.3, surefire 3.5.6,
                                     compiler 3.14.0, resources 3.3.1 (all pinned)
    src/main/java/ex/Calc.java       Calc.add            \\  commit 1
    src/test/java/ex/CalcTest.java   addWorks            /
    src/main/java/ex/Sub.java        Sub.sub             \\  commit 2 (the feat)
    src/test/java/ex/SubTest.java    subWorks            /

Maven's target scope is the surefire class name (``SubTest``); the belt is a
bare ``mvn test``. Failing ids are ``<classname>::<method>`` from the surefire
XML, e.g. ``ex.CalcTest::addWorks``.

Maven is the one toolchain that needs a warm local repository (``~/.m2``):
the tests call :func:`conftest_langs.maven_warmup` once per session and skip
with the reason when the plugins/junit cannot be resolved.

Navigation
----------
What it is:   The JVM fixture: a single-module Maven project on JUnit Jupiter 5 with surefire.
What it does: Builds the two-commit shape for the Maven runner with every plugin version pinned
              in ``pom.xml``; ``java_home`` chooses the JDK the runner is handed. Maven is the one
              toolchain that needs a warm ``~/.m2`` — consumers call
              ``conftest_langs.maven_warmup`` first.
How:          ``two_commit_repo`` over inline Java sources and a pinned POM; ``config`` returns a
              ``RepoConfig`` whose target scope is the surefire class name.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/langs/__init__.py (the shape), src/crb/core/runners/jvm_runner.py
              (the runner under test), tests/conftest_langs.py (``maven_warmup``),
              tests/test_runners_jvm.py and tests/test_oracle_mutation_text.py (the consumers)
Tested by:    tests/test_runners_jvm.py, tests/test_oracle_mutation_text.py, tests/test_grade.py
Touch when:   a plugin or JUnit version is bumped (bump every pin together and re-warm the
              cache); a JVM test needs a second module or a profile in the parent.
"""

from __future__ import annotations

import os
from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from . import two_commit_repo

#: The JDK the brief names for this host; ``config()`` falls back to ``$JAVA_HOME``.
BREW_OPENJDK = "/opt/homebrew/opt/openjdk"

SRC_CALC = "src/main/java/ex/Calc.java"
TEST_CALC = "src/test/java/ex/CalcTest.java"
SRC_SUB = "src/main/java/ex/Sub.java"
TEST_SUB = "src/test/java/ex/SubTest.java"

CALC_TEST_ID = "ex.CalcTest::addWorks"
SUB_TEST_ID = "ex.SubTest::subWorks"

POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>ex</groupId>
  <artifactId>calc</artifactId>
  <version>0.1.0</version>
  <packaging>jar</packaging>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.14.3</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.14.0</version>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.5.6</version>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-resources-plugin</artifactId>
        <version>3.3.1</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

CALC_JAVA = (
    "package ex;\n\n"
    "public final class Calc {\n"
    "    private Calc() {}\n\n"
    "    public static int add(int a, int b) {\n"
    "        return a + b;\n"
    "    }\n"
    "}\n"
)
CALC_JAVA_BROKEN = CALC_JAVA.replace("return a + b;", "return a + b + 1;")

_INITIAL = {
    "pom.xml": POM,
    ".gitignore": "target\n",
    SRC_CALC: CALC_JAVA,
    TEST_CALC: (
        "package ex;\n\n"
        "import static org.junit.jupiter.api.Assertions.assertEquals;\n\n"
        "import org.junit.jupiter.api.Test;\n\n"
        "class CalcTest {\n"
        "    @Test\n"
        "    void addWorks() {\n"
        "        assertEquals(3, Calc.add(1, 2));\n"
        "    }\n"
        "}\n"
    ),
}

_FEAT = {
    SRC_SUB: (
        "package ex;\n\n"
        "public final class Sub {\n"
        "    private Sub() {}\n\n"
        "    public static int sub(int a, int b) {\n"
        "        return a - b;\n"
        "    }\n"
        "}\n"
    ),
    TEST_SUB: (
        "package ex;\n\n"
        "import static org.junit.jupiter.api.Assertions.assertEquals;\n\n"
        "import org.junit.jupiter.api.Test;\n\n"
        "class SubTest {\n"
        "    @Test\n"
        "    void subWorks() {\n"
        "        assertEquals(1, Sub.sub(3, 2));\n"
        "    }\n"
        "}\n"
    ),
}


def java_home() -> str:
    """The JDK for the runner: the brew path from the brief if present, else ``$JAVA_HOME``."""
    if Path(BREW_OPENJDK).is_dir():
        return BREW_OPENJDK
    return os.environ.get("JAVA_HOME", "")


def build(tmp_path: Path) -> tuple[Path, str]:
    """The two-commit Maven fixture under ``tmp_path / "jvmrepo"``; returns ``(root, feat_sha)``."""
    return two_commit_repo(Path(tmp_path) / "jvmrepo", _INITIAL, _FEAT)


def config(belt_scope: str | tuple[str, ...] = BELT_BARE, *, offline: bool = False) -> RepoConfig:
    """The ``RepoConfig`` for the fixture: the ``maven`` runner over the standard layout, with the
    JDK from :func:`java_home` and ``offline`` (``mvn -o``) when the caller has warmed ``~/.m2``.
    """
    opts: dict[str, object] = {"offline": offline}
    jh = java_home()
    if jh:
        opts["java_home"] = jh
    return RepoConfig(
        name="jvmfix",
        language=Language.JVM,
        runner="maven",
        src_prefix="src/main/java/",
        test_prefix="src/test/java/",
        ext=".java",
        belt_scope=belt_scope,
        runner_opts=opts,
    )
