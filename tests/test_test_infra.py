"""crb.core.test_infra — the test-infrastructure pattern table and the section-aware
compare, as pure functions. Every rule in the table has a positive AND a negative
case here; every section-aware file has an honest edit (not tamper) and an
oracle-relevant edit (tamper)."""

from __future__ import annotations

import pytest

from crb.core import test_infra as ti
from crb.core.runners import runner_names
from crb.core.spec import Language

# ---------------------------------------------------------------------------
# The table itself is well-formed
# ---------------------------------------------------------------------------


def test_every_rule_has_a_reason_a_known_language_and_known_runners() -> None:
    langs = {lang.value for lang in Language} | {ti.ANY_LANGUAGE}
    known_runners = set(runner_names())
    for rule in ti.INFRA_RULES:
        assert rule.reason.strip(), rule
        assert rule.language in langs, rule
        assert set(rule.runners) <= known_runners, rule
        assert rule.globs and all(g == g.lower() for g in rule.globs), rule


def test_rule_without_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="reason"):
        ti.InfraRule("python", ("x",), "   ")


def test_rules_for_unknown_language_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown language"):
        ti.rules_for("cobol")


def test_rules_for_accepts_aliases_and_enum() -> None:
    assert ti.rules_for("py") == ti.rules_for(Language.PYTHON) == ti.rules_for("python")


def test_every_partial_rule_has_a_section_parser() -> None:
    """A section-aware row whose file no parser knows would fail closed on every
    edit — that is a table bug, caught here rather than in production."""
    for rule in ti.INFRA_RULES:
        if not rule.partial:
            continue
        for g in rule.globs:
            name = g.rsplit("/", 1)[-1]
            assert (
                name in ti._TOML_SECTIONS
                or name in ti._INI_SECTIONS
                or name in {"package.json", "go.mod", "pom.xml"}
            ), rule


# ---------------------------------------------------------------------------
# is_test_infra — one positive + one negative per pattern
# ---------------------------------------------------------------------------

POSITIVE: list[tuple[str, str]] = [
    # every language
    ("python", "tests/__snapshots__/test_x.ambr"),
    ("javascript", "src/__tests__/__snapshots__/app.test.js.snap"),
    ("go", "pkg/__snapshots__/x"),
    # belt 5 lint configuration (ADR-0011 amendment; 2026-09-14 independent review pass, finding 2)
    ("python", "ruff.toml"),
    ("python", "pkg/ruff.toml"),
    ("python", ".ruff.toml"),
    ("python", ".flake8"),
    ("python", ".pre-commit-config.yaml"),
    ("javascript", ".eslintrc"),
    ("javascript", ".eslintrc.json"),
    ("javascript", "eslint.config.mjs"),
    ("javascript", ".eslintignore"),
    ("javascript", ".prettierrc"),
    ("javascript", ".prettierrc.yaml"),
    ("javascript", "prettier.config.cjs"),
    ("javascript", ".prettierignore"),
    ("javascript", "packages/ui/.editorconfig"),
    ("go", ".golangci.yml"),
    ("go", ".golangci.yaml"),
    ("go", ".golangci.toml"),
    ("jvm", "src/checkstyle/nohttp-checkstyle.xml"),
    ("jvm", "src/checkstyle/nohttp-checkstyle-suppressions.xml"),
    ("jvm", "config/checkstyle.xml"),
    ("rust", "rustfmt.toml"),
    ("rust", ".rustfmt.toml"),
    ("rust", "clippy.toml"),
    ("rust", "crates/a/.clippy.toml"),
    # python
    ("python", "conftest.py"),
    ("python", "tests/conftest.py"),
    ("python", "src/pkg/sub/conftest.py"),
    ("python", "Conftest.py"),  # case-insensitive, fail closed
    ("python", "./conftest.py"),
    ("python", "pytest.ini"),
    ("python", "tests/pytest.ini"),
    ("python", ".pytest.ini"),
    ("python", "pyproject.toml"),
    ("python", "sub/pyproject.toml"),
    ("python", "setup.cfg"),
    ("python", "tox.ini"),
    ("python", "sitecustomize.py"),
    ("python", "src/sitecustomize.py"),
    ("python", "usercustomize.py"),
    ("python", "easy-install.pth"),
    ("python", "lib/foo.pth"),
    ("python", "pytest.py"),
    ("python", "pytest/__init__.py"),
    ("python", "_pytest/main.py"),
    ("python", "pluggy/__init__.py"),
    ("python", "tests/__snapshots__/x.ambr"),
    ("python", "tests/snap/test_x.ambr"),
    # javascript
    ("javascript", "package.json"),
    ("javascript", "packages/a/package.json"),
    ("javascript", "jest.config.js"),
    ("javascript", "jest.config.ts"),
    ("javascript", "jest.config.mjs"),
    ("javascript", "jest.config.json"),
    ("javascript", "packages/a/jest.config.cjs"),
    ("javascript", "jest-preset.js"),
    ("javascript", "jest.setup.js"),
    ("javascript", "src/setupTests.js"),
    ("javascript", "vitest.config.ts"),
    ("javascript", "vitest.workspace.ts"),
    ("javascript", "vitest.projects.js"),
    ("javascript", "vite.config.ts"),
    ("javascript", ".mocharc"),
    ("javascript", ".mocharc.yml"),
    ("javascript", ".mocharc.cjs"),
    ("javascript", "test/mocha.opts"),
    ("javascript", "babel.config.js"),
    ("javascript", ".babelrc"),
    ("javascript", ".babelrc.json"),
    ("javascript", ".swcrc"),
    ("javascript", "tsconfig.json"),
    ("javascript", "tsconfig.build.json"),
    ("javascript", "node.config.json"),
    ("javascript", "__tests__/__snapshots__/a.test.js.snap"),
    ("javascript", "test/a.snap"),
    # go
    ("go", "calc/calc_test.go"),
    ("go", "other_test.go"),
    ("go", "testdata/golden.txt"),
    ("go", "pkg/testdata/in/x.json"),
    ("go", "go.mod"),
    ("go", "sub/go.mod"),
    ("go", "go.work"),
    # jvm
    ("jvm", "pom.xml"),
    ("jvm", "module-a/pom.xml"),
    ("jvm", ".mvn/maven.config"),
    ("jvm", ".mvn/jvm.config"),
    ("jvm", ".mvn/extensions.xml"),
    ("jvm", ".mvn/wrapper/maven-wrapper.properties"),
    ("jvm", "mvnw"),
    ("jvm", "mvnw.cmd"),
    ("jvm", "src/test/resources/junit-platform.properties"),
    ("jvm", "src/test/resources/META-INF/services/org.junit.jupiter.api.extension.Extension"),
    ("jvm", "src/test/java/ex/HelperTest.java"),
    ("jvm", "module-a/src/test/kotlin/ex/X.kt"),
    (
        "jvm",
        "src/main/resources/META-INF/services/org.junit.platform.launcher.TestExecutionListener",
    ),
    # rust
    ("rust", "tests/common/mod.rs"),
    ("rust", "tests/fixtures/input.txt"),
    ("rust", "crates/a/tests/it.rs"),
    ("rust", "build.rs"),
    ("rust", "crates/a/build.rs"),
    ("rust", "Cargo.toml"),
    ("rust", "crates/a/Cargo.toml"),
    ("rust", ".cargo/config.toml"),
    ("rust", ".cargo/config"),
    ("rust", "rust-toolchain"),
    ("rust", "rust-toolchain.toml"),
    ("rust", "src/snapshots/x.snap"),
    ("rust", "src/snapshots/x.snap.new"),
]

NEGATIVE: list[tuple[str, str]] = [
    # python: ordinary source, tests, docs, packaging that is not pytest config
    ("python", "src/calc/__init__.py"),
    ("python", "tests/test_calc.py"),
    ("python", "src/calc/conftest_helpers.py"),
    ("python", "myconftest.py"),
    ("python", "README.md"),
    ("python", "setup.py"),
    ("python", "requirements.txt"),
    ("python", "src/pytest_plugin_thing.py"),
    ("python", "src/_pytest/main.py"),  # the pytest repo itself: src layout is not the root
    ("python", "docs/pytest.rst"),
    ("python", "src/site.py"),
    ("python", ".editorconfig"),  # only prettier (JS) reads it — see the JS lint rule
    ("go", ".editorconfig"),
    ("rust", ".editorconfig"),
    # javascript
    ("javascript", "src/calc.js"),
    ("javascript", "__tests__/calc.test.js"),
    ("javascript", "package-lock.json"),
    ("javascript", "README.md"),
    ("javascript", "src/jest.helpers.js"),
    ("javascript", "webpack.config.js"),
    ("javascript", "rollup.config.js"),
    ("javascript", "index.d.ts"),
    # go
    ("go", "calc/calc.go"),
    ("go", "go.sum"),
    ("go", "vendor/modules.txt"),
    ("go", "internal/data/fixture.json"),
    ("go", "Makefile"),
    # jvm
    ("jvm", "src/main/java/ex/Calc.java"),
    ("jvm", "src/main/resources/application.properties"),
    ("jvm", "README.md"),
    ("jvm", "build.gradle"),  # no gradle runner: not this oracle's config
    # rust
    ("rust", "src/lib.rs"),
    ("rust", "src/sub.rs"),
    ("rust", "Cargo.lock"),
    ("rust", "benches/bench.rs"),
    ("rust", "examples/demo.rs"),
    ("rust", "src/tests_helper.rs"),
]


@pytest.mark.parametrize(("language", "path"), POSITIVE)
def test_is_test_infra_positive(language: str, path: str) -> None:
    assert ti.is_test_infra(path, language), path


@pytest.mark.parametrize(("language", "path"), NEGATIVE)
def test_is_test_infra_negative(language: str, path: str) -> None:
    assert not ti.is_test_infra(path, language), path


def test_rules_are_per_language() -> None:
    """A path is only infra for the language whose runner reads it."""
    assert ti.is_test_infra("conftest.py", "python")
    assert not ti.is_test_infra("conftest.py", "javascript")
    assert ti.is_test_infra("jest.config.js", "javascript")
    assert not ti.is_test_infra("jest.config.js", "python")
    assert ti.is_test_infra("go.mod", "go")
    assert not ti.is_test_infra("go.mod", "rust")
    assert ti.is_test_infra("build.rs", "rust")
    assert not ti.is_test_infra("build.rs", "go")
    assert ti.is_test_infra("pom.xml", "jvm")
    assert not ti.is_test_infra("pom.xml", "python")


@pytest.mark.parametrize(
    ("path", "runner", "expected"),
    [
        ("jest.config.js", "jest", True),
        ("jest.config.js", "mocha", False),
        ("jest.config.js", "node", False),
        ("jest.config.js", "", True),  # no runner → the fail-closed union
        (".mocharc.yml", "mocha", True),
        (".mocharc.yml", "jest", False),
        ("vitest.config.ts", "vitest", True),
        ("vitest.config.ts", "jest", False),
        ("vite.config.ts", "vitest", True),
        ("vite.config.ts", "mocha", False),
        ("babel.config.js", "jest", True),
        ("babel.config.js", "mocha", True),
        ("babel.config.js", "vitest", False),
        ("tsconfig.json", "jest", True),
        ("tsconfig.json", "vitest", True),
        ("tsconfig.json", "node", False),
        ("node.config.json", "node", True),
        ("node.config.json", "jest", False),
        ("package.json", "node", True),  # every runner: section-aware
        ("x.snap", "node", True),  # every runner
    ],
)
def test_runner_narrowing_for_javascript(path: str, runner: str, expected: bool) -> None:
    assert ti.is_test_infra(path, "javascript", runner=runner) is expected


def test_matching_rule_prefers_whole_file_over_partial_and_reports_partial() -> None:
    rule = ti.matching_rule("pyproject.toml", "python")
    assert rule is not None and rule.partial
    rule = ti.matching_rule("conftest.py", "python")
    assert rule is not None and not rule.partial
    assert ti.matching_rule("src/calc.py", "python") is None


# ---------------------------------------------------------------------------
# infra_sections_changed — honest edits are not tamper; oracle edits are
# ---------------------------------------------------------------------------

PYPROJECT = """[build-system]
requires = ["hatchling"]

[project]
name = "calc"
version = "0.1.0"
dependencies = ["requests>=2"]

[project.optional-dependencies]
test = ["pytest"]

[tool.pytest.ini_options]
testpaths = ["tests"]
filterwarnings = ["error"]

[tool.ruff]
line-length = 100
"""


class TestPyprojectToml:
    def test_version_bump_and_dependency_add_are_honest(self) -> None:
        after = PYPROJECT.replace('version = "0.1.0"', 'version = "0.2.0"').replace(
            'dependencies = ["requests>=2"]', 'dependencies = ["requests>=2", "rich"]'
        )
        assert not ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")

    def test_comment_or_whitespace_change_is_honest(self) -> None:
        after = PYPROJECT + "\n# trailing\n"
        assert not ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")

    def test_ruff_config_change_is_tamper(self) -> None:
        """2026-09-14 independent review pass, finding 2: ``[tool.ruff.lint] select = []``
        turned a ``repo_lint_clean=False`` row CLEAN. The whole ``[tool.ruff*]`` tree
        is belt 5's definition of acceptable (ADR-0011 amendment)."""
        after = PYPROJECT.replace("line-length = 100", "line-length = 88")
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")
        after = PYPROJECT + "\n[tool.ruff.lint]\nselect = []\n"
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")
        after = PYPROJECT.replace("[tool.ruff]\nline-length = 100\n", "")
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")
        # a [tool.*] table belt 5 never reads is still an honest edit
        after = PYPROJECT + "\n[tool.hatch.build]\ninclude = ['src']\n"
        assert not ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")

    def test_relaxing_filterwarnings_is_tamper(self) -> None:
        after = PYPROJECT.replace('filterwarnings = ["error"]', "")
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")

    def test_adding_pythonpath_is_tamper(self) -> None:
        after = PYPROJECT.replace(
            'testpaths = ["tests"]', 'testpaths = ["tests"]\npythonpath = ["shim"]'
        )
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")

    def test_new_file_with_pytest_table_is_tamper_without_is_not(self) -> None:
        assert ti.infra_sections_changed("pyproject.toml", "", PYPROJECT, "python")
        honest = '[project]\nname = "calc"\nversion = "0.1.0"\n'
        assert not ti.infra_sections_changed("pyproject.toml", "", honest, "python")

    def test_deleting_pytest_config_is_tamper(self) -> None:
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, "", "python")

    def test_native_tool_pytest_table_is_covered(self) -> None:
        after = PYPROJECT + '\n[tool.pytest]\naddopts = "-p shim"\n'
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")

    def test_plugin_entry_point_is_tamper(self) -> None:
        after = PYPROJECT + '\n[project.entry-points.pytest11]\nshim = "shim.plugin"\n'
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, after, "python")

    def test_unparsable_side_fails_closed(self) -> None:
        assert ti.infra_sections_changed(
            "pyproject.toml", PYPROJECT, "[tool.pytest\nbroken", "python"
        )
        assert ti.infra_sections_changed("pyproject.toml", "= broken", PYPROJECT, "python")

    def test_oversize_fails_closed(self) -> None:
        big = PYPROJECT + "#" * (ti.MAX_PARSE_BYTES + 1)
        assert ti.infra_sections_changed("pyproject.toml", PYPROJECT, big, "python")


SETUP_CFG = """[metadata]
name = calc
version = 0.1.0

[options]
packages = find:

[tool:pytest]
testpaths = tests
addopts = -ra

[flake8]
max-line-length = 100
"""


class TestSetupCfgAndToxIni:
    def test_metadata_edit_is_honest(self) -> None:
        after = SETUP_CFG.replace("version = 0.1.0", "version = 0.2.0")
        assert not ti.infra_sections_changed("setup.cfg", SETUP_CFG, after, "python")

    def test_pytest_section_edit_is_tamper(self) -> None:
        after = SETUP_CFG.replace("testpaths = tests", "testpaths = tests\npython_files = *.py")
        assert ti.infra_sections_changed("setup.cfg", SETUP_CFG, after, "python")

    def test_header_with_trailing_comment_or_spaces_still_matches(self) -> None:
        spaced = SETUP_CFG.replace("[tool:pytest]", "[ tool:pytest ]  # cfg")
        assert not ti.infra_sections_changed("setup.cfg", SETUP_CFG, spaced, "python")
        assert ti.infra_sections_changed(
            "setup.cfg", SETUP_CFG, spaced.replace("addopts = -ra", "addopts = -p shim"), "python"
        )

    def test_removing_the_section_is_tamper(self) -> None:
        after = SETUP_CFG.split("[tool:pytest]")[0] + "[flake8]\nmax-line-length = 100\n"
        assert ti.infra_sections_changed("setup.cfg", SETUP_CFG, after, "python")

    def test_flake8_section_is_lint_config(self) -> None:
        """ADR-0011 amendment (2026-09-14): ``[flake8]`` is belt 5's definition of
        acceptable; ``[options]`` is packaging."""
        after = SETUP_CFG.replace("max-line-length = 100", "max-line-length = 200")
        assert ti.infra_sections_changed("setup.cfg", SETUP_CFG, after, "python")
        after = SETUP_CFG.replace("packages = find:", "packages = calc")
        assert not ti.infra_sections_changed("setup.cfg", SETUP_CFG, after, "python")
        tox = "[tox]\nenvlist = py312\n\n[flake8]\nmax-line-length = 100\n"
        assert ti.infra_sections_changed(
            "tox.ini", tox, tox.replace("max-line-length = 100", "extend-ignore = E501"), "python"
        )

    def test_tox_ini_environments_are_honest_pytest_section_is_not(self) -> None:
        tox = "[tox]\nenvlist = py312\n\n[testenv]\ncommands = pytest\n\n[pytest]\ntestpaths = tests\n"
        assert not ti.infra_sections_changed(
            "tox.ini", tox, tox.replace("envlist = py312", "envlist = py312,py313"), "python"
        )
        assert ti.infra_sections_changed(
            "tox.ini", tox, tox.replace("testpaths = tests", "testpaths = shim"), "python"
        )
        assert ti.infra_sections_changed("tox.ini", "[tox]\nenvlist = py312\n", tox, "python")


PACKAGE_JSON = """{
  "name": "calcfix",
  "version": "0.1.0",
  "private": true,
  "scripts": { "test": "jest --ci", "build": "tsc" },
  "dependencies": { "lodash": "^4" },
  "devDependencies": { "jest": "^29" },
  "jest": { "testEnvironment": "node" }
}
"""


class TestPackageJson:
    def test_version_and_dependency_edits_are_honest(self) -> None:
        after = PACKAGE_JSON.replace('"version": "0.1.0"', '"version": "0.2.0"').replace(
            '"lodash": "^4"', '"lodash": "^4", "dayjs": "^1"'
        )
        assert not ti.infra_sections_changed("package.json", PACKAGE_JSON, after, "javascript")

    def test_build_script_edit_is_honest_test_script_is_not(self) -> None:
        assert not ti.infra_sections_changed(
            "package.json",
            PACKAGE_JSON,
            PACKAGE_JSON.replace('"build": "tsc"', '"build": "tsc -p ."'),
            "javascript",
        )
        assert ti.infra_sections_changed(
            "package.json",
            PACKAGE_JSON,
            PACKAGE_JSON.replace('"test": "jest --ci"', '"test": "true"'),
            "javascript",
        )

    def test_jest_key_edit_is_tamper(self) -> None:
        after = PACKAGE_JSON.replace(
            '"testEnvironment": "node"', '"testEnvironment": "node", "setupFiles": ["./shim.js"]'
        )
        assert ti.infra_sections_changed("package.json", PACKAGE_JSON, after, "javascript")

    def test_runner_narrowing_ignores_another_runners_key(self) -> None:
        after = PACKAGE_JSON.replace('"jest": {', '"mocha": { "require": "shim" }, "jest": {')
        assert ti.infra_sections_changed("package.json", PACKAGE_JSON, after, "javascript")
        assert ti.infra_sections_changed(
            "package.json", PACKAGE_JSON, after, "javascript", runner="mocha"
        )
        assert not ti.infra_sections_changed(
            "package.json", PACKAGE_JSON, after, "javascript", runner="jest"
        )

    def test_babel_key_counts_for_jest_and_mocha_only(self) -> None:
        after = PACKAGE_JSON.replace('"jest": {', '"babel": { "plugins": ["shim"] }, "jest": {')
        assert ti.infra_sections_changed(
            "package.json", PACKAGE_JSON, after, "javascript", runner="jest"
        )
        assert ti.infra_sections_changed(
            "package.json", PACKAGE_JSON, after, "javascript", runner="mocha"
        )
        assert not ti.infra_sections_changed(
            "package.json", PACKAGE_JSON, after, "javascript", runner="vitest"
        )

    def test_lint_keys_are_tamper_for_every_runner(self) -> None:
        """ADR-0011 amendment (2026-09-14): ``eslintConfig``, ``prettier`` and
        ``scripts.lint`` are belt 5's config; belt 5 is orthogonal to the test runner."""
        for key in ('"eslintConfig": { "rules": {} }', '"prettier": { "semi": false }'):
            after = PACKAGE_JSON.replace('"private": true,', f'"private": true, {key},')
            for runner in ("", "jest", "mocha", "vitest", "node"):
                assert ti.infra_sections_changed(
                    "package.json", PACKAGE_JSON, after, "javascript", runner=runner
                ), (key, runner)
        after = PACKAGE_JSON.replace('"build": "tsc"', '"build": "tsc", "lint": "standard"')
        assert ti.infra_sections_changed("package.json", PACKAGE_JSON, after, "javascript")
        # a script belt 5 never reads is still honest
        after = PACKAGE_JSON.replace('"build": "tsc"', '"build": "tsc", "docs": "typedoc"')
        assert not ti.infra_sections_changed("package.json", PACKAGE_JSON, after, "javascript")

    def test_unparsable_or_non_object_fails_closed(self) -> None:
        assert ti.infra_sections_changed("package.json", PACKAGE_JSON, "{ oops", "javascript")
        assert ti.infra_sections_changed("package.json", PACKAGE_JSON, "[1, 2]", "javascript")

    def test_new_package_json_without_runner_keys_is_honest(self) -> None:
        assert not ti.infra_sections_changed(
            "package.json", "", '{"name": "x", "version": "1.0.0"}', "javascript"
        )


GO_MOD = """module example.com/m

go 1.22

require (
\tgithub.com/x/y v1.2.3 // indirect
\tgolang.org/x/text v0.14.0
)
"""


class TestGoMod:
    def test_require_and_go_directive_edits_are_honest(self) -> None:
        after = GO_MOD.replace("go 1.22", "go 1.23").replace(
            "\tgolang.org/x/text v0.14.0", "\tgolang.org/x/text v0.15.0\n\tgithub.com/a/b v1.0.0"
        )
        assert not ti.infra_sections_changed("go.mod", GO_MOD, after, "go")

    def test_replace_directive_is_tamper(self) -> None:
        assert ti.infra_sections_changed(
            "go.mod", GO_MOD, GO_MOD + "\nreplace github.com/x/y => ../shim\n", "go"
        )
        block = GO_MOD + "\nreplace (\n\tgithub.com/x/y => ../shim\n)\n"
        assert ti.infra_sections_changed("go.mod", GO_MOD, block, "go")

    def test_single_line_and_block_forms_compare_equal(self) -> None:
        one = GO_MOD + "\nreplace github.com/x/y => ../shim\n"
        block = GO_MOD + "\nreplace (\n\tgithub.com/x/y   =>   ../shim  // why\n)\n"
        assert not ti.infra_sections_changed("go.mod", one, block, "go")

    def test_exclude_godebug_toolchain_are_tamper(self) -> None:
        for line in ("exclude github.com/x/y v1.2.3", "godebug panicnil=1", "toolchain go1.23.1"):
            assert ti.infra_sections_changed("go.mod", GO_MOD, GO_MOD + f"\n{line}\n", "go"), line

    def test_deleting_a_replace_is_tamper(self) -> None:
        before = GO_MOD + "\nreplace github.com/x/y => ../shim\n"
        assert ti.infra_sections_changed("go.mod", before, GO_MOD, "go")


POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>ex</groupId>
  <artifactId>calc</artifactId>
  <version>0.1.0</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
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
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.5.6</version>
      </plugin>
    </plugins>
  </build>
</project>
"""


class TestPomXml:
    def test_version_and_dependency_edits_are_honest(self) -> None:
        after = POM.replace("<version>0.1.0</version>", "<version>0.2.0</version>").replace(
            "  </dependencies>",
            "    <dependency><groupId>com.google.guava</groupId><artifactId>guava</artifactId>"
            "<version>33.0.0-jre</version></dependency>\n  </dependencies>",
        )
        assert not ti.infra_sections_changed("pom.xml", POM, after, "jvm")

    def test_whitespace_only_reformat_is_honest(self) -> None:
        after = POM.replace(
            "\n        <version>3.5.6</version>", "\n\n        <version>3.5.6</version>  "
        )
        assert not ti.infra_sections_changed("pom.xml", POM, after, "jvm")

    def test_surefire_configuration_is_tamper(self) -> None:
        after = POM.replace(
            "<version>3.5.6</version>",
            "<version>3.5.6</version><configuration><skipTests>true</skipTests></configuration>",
        )
        assert ti.infra_sections_changed("pom.xml", POM, after, "jvm")

    def test_properties_profiles_and_parent_are_tamper(self) -> None:
        cases = [
            POM.replace(
                "<maven.compiler.release>17",
                "<skipTests>true</skipTests><maven.compiler.release>17",
            ),
            POM.replace("</build>", "</build><profiles><profile><id>x</id></profile></profiles>"),
            POM.replace(
                "<groupId>ex</groupId>",
                "<parent><groupId>p</groupId></parent><groupId>ex</groupId>",
            ),
        ]
        for after in cases:
            assert ti.infra_sections_changed("pom.xml", POM, after, "jvm")

    def test_doctype_or_unparsable_fails_closed(self) -> None:
        assert ti.infra_sections_changed(
            "pom.xml", POM, '<!DOCTYPE x [<!ENTITY a "b">]>' + POM, "jvm"
        )
        assert ti.infra_sections_changed("pom.xml", POM, POM.replace("</project>", ""), "jvm")


CARGO = """[package]
name = "calc"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = "1"

[dev-dependencies]
insta = "1"

[features]
default = []
"""


class TestCargoToml:
    def test_version_dependency_and_feature_edits_are_honest(self) -> None:
        after = (
            CARGO.replace('version = "0.1.0"', 'version = "0.2.0"')
            .replace('serde = "1"', 'serde = "1"\nanyhow = "1"')
            .replace("default = []", 'default = ["fast"]\nfast = []')
        )
        assert not ti.infra_sections_changed("Cargo.toml", CARGO, after, "rust")

    def test_dev_dependency_edit_is_tamper(self) -> None:
        assert ti.infra_sections_changed(
            "Cargo.toml",
            CARGO,
            CARGO.replace('insta = "1"', 'insta = "1"\nshim = { path = "shim" }'),
            "rust",
        )

    def test_lints_table_is_belt_five_config(self) -> None:
        """ADR-0011 amendment (2026-09-14): clippy reads ``[lints]`` / ``[workspace.lints]``."""
        assert ti.infra_sections_changed(
            "Cargo.toml", CARGO, CARGO + '\n[lints.clippy]\nall = "allow"\n', "rust"
        )
        assert ti.infra_sections_changed(
            "Cargo.toml", CARGO, CARGO + '\n[workspace.lints.rust]\nunused = "allow"\n', "rust"
        )

    @pytest.mark.parametrize(
        "table",
        [
            '[[test]]\nname = "sub"\nharness = false\n',
            '[patch.crates-io]\nserde = { path = "shim" }\n',
            "[profile.test]\noverflow-checks = false\n",
            '[lib]\npath = "shim/lib.rs"\n',
            '[target."cfg(unix)".dev-dependencies]\nshim = "1"\n',
        ],
    )
    def test_oracle_tables_are_tamper(self, table: str) -> None:
        assert ti.infra_sections_changed("Cargo.toml", CARGO, CARGO + "\n" + table, "rust")

    def test_package_build_script_is_tamper(self) -> None:
        after = CARGO.replace('edition = "2021"', 'edition = "2021"\nbuild = "build.rs"')
        assert ti.infra_sections_changed("Cargo.toml", CARGO, after, "rust")

    def test_crate_level_cargo_toml_is_covered(self) -> None:
        assert ti.infra_sections_changed(
            "crates/a/Cargo.toml", CARGO, CARGO + '\n[[test]]\nname = "x"\n', "rust"
        )


class TestWholeFileAndNonInfra:
    def test_whole_file_rule_is_always_changed(self) -> None:
        assert ti.infra_sections_changed("conftest.py", "", "# empty\n", "python")
        assert ti.infra_sections_changed("pytest.ini", "[pytest]\n", "[pytest]\n", "python")

    def test_non_infra_path_is_never_changed(self) -> None:
        assert not ti.infra_sections_changed("src/calc.py", "a", "b", "python")
        assert not ti.infra_sections_changed(
            "go.mod", "", "replace a => b", "python"
        )  # wrong language
