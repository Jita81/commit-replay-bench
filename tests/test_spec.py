"""crb.core.spec — languages, size tiers, change classes, RepoConfig, TaskSpec."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crb.core.spec import (
    ALL_CLASSES,
    BELT_AFFECTED_DIRS,
    BELT_BARE,
    BELT_TARGET_ONLY,
    POOL_HARD,
    RUNNERS,
    SIZE_TIER_NAMES,
    UNCLASSIFIED,
    Language,
    RepoConfig,
    TaskSpec,
    classify_commit,
    classify_path,
    is_test_path,
    size_tier,
)

# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("py", Language.PYTHON),
        ("python", Language.PYTHON),
        (" Python ", Language.PYTHON),
        ("go", Language.GO),
        ("golang", Language.GO),
        ("js", Language.JAVASCRIPT),
        ("javascript", Language.JAVASCRIPT),
        ("typescript", Language.JAVASCRIPT),
        ("ts", Language.JAVASCRIPT),
        ("jvm", Language.JVM),
        ("java", Language.JVM),
        ("kotlin", Language.JVM),
        ("rust", Language.RUST),
        ("rs", Language.RUST),
        ("RS", Language.RUST),
    ],
)
def test_language_parse_aliases(alias: str, expected: Language) -> None:
    assert Language.parse(alias) is expected


@pytest.mark.parametrize("bad", ["", "cobol", "c++", "py3"])
def test_language_parse_rejects_unknown(bad: str) -> None:
    with pytest.raises(ValueError, match="unknown language"):
        Language.parse(bad)


def test_language_is_a_str_enum() -> None:
    assert Language.PYTHON == "python"
    assert Language("go") is Language.GO


# ---------------------------------------------------------------------------
# Size tiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("churn", "tier"),
    [
        (0, "XS"),
        (9, "XS"),
        (10, "S"),
        (39, "S"),
        (40, "M"),
        (119, "M"),
        (120, "L"),
        (399, "L"),
        (400, "XL"),
        (10_000, "XL"),
    ],
)
def test_size_tier_boundaries(churn: int, tier: str) -> None:
    assert size_tier(churn) == tier


def test_size_tier_negative_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        size_tier(-1)


@settings(max_examples=200, database=None, deadline=None)
@given(st.integers(min_value=0, max_value=5000), st.integers(min_value=0, max_value=5000))
def test_size_tier_is_monotone_and_total(a: int, b: int) -> None:
    lo, hi = sorted((a, b))
    assert SIZE_TIER_NAMES.index(size_tier(lo)) <= SIZE_TIER_NAMES.index(size_tier(hi))
    assert size_tier(a) in SIZE_TIER_NAMES


# ---------------------------------------------------------------------------
# classify_path — one representative per class + the upstream edge cases
# ---------------------------------------------------------------------------

_REPRESENTATIVE = {
    "ci.workflow.edit": ".github/workflows/build.yml",
    "infra.terraform.edit": "infra/main.tf",
    "infra.helm.edit": "deploy/charts/app/values.yaml",
    "docs.update": "docs/content/getting-started.md",
    "test.add": "src/MigrationTools.Helpers.Tests/WorkItemHelperTests.cs",
    "frontend.route.add": "web/src/pages/Dashboard.tsx",
    "frontend.component.add": "web/src/components/Button.tsx",
    "backend.migration.add": "app/db/migrations/versions/0007_add_users.py",
    "backend.model.edit": "app/models/user.py",
    "backend.route.add": "app/api/users_controller.py",
    "bug.fix": "src/MigrationTools/Processors/WorkItemMigrationProcessor.cs",
}


@pytest.mark.parametrize(("expected", "path"), sorted(_REPRESENTATIVE.items()))
def test_each_class_has_a_reachable_path(expected: str, path: str) -> None:
    assert classify_path(path) == expected


def test_classifier_addresses_full_taxonomy() -> None:
    """Static path classification cannot see add-vs-edit, so the three edit twins are
    reachable through their canonical siblings; everything else must be direct."""
    direct = {classify_path(p) for p in _REPRESENTATIVE.values()}
    twins = {"backend.route.edit", "frontend.component.edit", "test.fix"}
    assert set(ALL_CLASSES) - (direct | twins) == set()
    assert len(ALL_CLASSES) == 14


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yaml",
        "azure-pipelines.yml",
        "Jenkinsfile",
        ".travis.yml",
        ".gitlab-ci.yml",
        ".circleci/config.yml",
    ],
)
def test_ci_paths(path: str) -> None:
    assert classify_path(path) == "ci.workflow.edit"


@pytest.mark.parametrize("path", ["infra/vars.tfvars", "modules/vpc/main.tf.json"])
def test_terraform_paths(path: str) -> None:
    assert classify_path(path) == "infra.terraform.edit"


@pytest.mark.parametrize(
    "path",
    [
        "helm/app/templates/deployment.yaml",
        "Chart.yaml",
        "values.yaml",
        "deploy/mychart/templates/svc.yml",
    ],
)
def test_helm_paths(path: str) -> None:
    assert classify_path(path) == "infra.helm.edit"


def test_templates_yaml_without_chart_hint_is_not_helm() -> None:
    assert classify_path("app/templates/config.yaml") == UNCLASSIFIED


@pytest.mark.parametrize("path", ["README.md", "docs/index.rst", "notes.txt", "a.mdx", "x.adoc"])
def test_doc_paths(path: str) -> None:
    assert classify_path(path) == "docs.update"


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_x.py",
        "pkg/foo_test.go",
        "src/__tests__/a.js",
        "src/a.spec.ts",
        "src/a.test.tsx",
        "spec/models/user_spec.rb",
        "src/Foo.Tests/FooTests.cs",
    ],
)
def test_test_paths(path: str) -> None:
    assert is_test_path(path)
    assert classify_path(path) == "test.add"


@pytest.mark.parametrize("path", ["tests/fixtures/data.json", "test/README.md", "src/latest.py"])
def test_not_test_paths(path: str) -> None:
    assert not is_test_path(path)


def test_frontend_routes_vs_components() -> None:
    assert classify_path("app/routes/home.tsx") == "frontend.route.add"
    assert classify_path("src/views/Home.vue") == "frontend.route.add"
    assert classify_path("src/app/layout.tsx") == "frontend.route.add"
    assert classify_path("src/widgets/Card.svelte") == "frontend.component.add"
    assert classify_path("Views/Shared/_Layout.cshtml") == "frontend.route.add"


def test_migration_tool_domain_trap_is_closed() -> None:
    """A *migration tool*'s domain files are not DB migrations (upstream regression)."""
    for f in [
        "MigrationTools.sln",
        "MigrationTools.slnx",
        "docs/static/images/azure-devops-migration-tools-logo.png",
        "src/MigrationTools/Processors/WorkItemMigrationProcessor.cs",
        "src/MigrationTools/Enrichers/StringManipulatorMigrationEnricher.cs",
    ]:
        assert classify_path(f) != "backend.migration.add", f


@pytest.mark.parametrize(
    "path",
    [
        "alembic/versions/abc123_create_table.py",
        "db/migrate/20240101120000_add_index.rb",
        "migrations/V3__add_column.sql",
        "app/migrations/0002_auto.py",
        "sql/schema/001_init.sql",
        "src/20240101120000_AddUsers.cs",
    ],
)
def test_real_db_migration_still_detected(path: str) -> None:
    assert classify_path(path) == "backend.migration.add"


def test_migration_dir_with_non_code_ext_is_not_migration() -> None:
    assert classify_path("migrations/README.md") == "docs.update"
    assert classify_path("migrations/notes.yaml") == UNCLASSIFIED


@pytest.mark.parametrize(
    "path",
    [
        "app/models/user.py",
        "core/entities/Order.java",
        "domain/account.go",
        "src/user_model.py",
        "src/OrderEntity.cs",
        "src/models.py",
    ],
)
def test_model_paths(path: str) -> None:
    assert classify_path(path) == "backend.model.edit"


@pytest.mark.parametrize(
    "path",
    [
        "app/controllers/users.rb",
        "src/routes/index.js",
        "pkg/api/v1/users.go",
        "src/endpoints/health.py",
        "internal/handlers/ping.go",
        "src/UsersController.cs",
        "src/router.ts",
        "src/routes.py",
        "src/health_endpoint.py",
        "lib/api.php",
    ],
)
def test_route_paths(path: str) -> None:
    assert classify_path(path) == "backend.route.add"


def test_model_wins_over_route_when_both_match() -> None:
    assert classify_path("app/api/models/user.py") == "backend.model.edit"


def test_plain_code_is_bug_fix() -> None:
    for f in ["src/util.py", "pkg/x.go", "lib/a.rs", "Main.kt", "a.scala", "b.swift", "c.h"]:
        assert classify_path(f) == "bug.fix", f


def test_non_code_files_are_unclassified() -> None:
    for f in ["logo.png", "package-lock.json", "app.csproj", "Directory.Build.props", "Makefile"]:
        assert classify_path(f) == UNCLASSIFIED, f


def test_classify_path_is_case_insensitive() -> None:
    assert classify_path("SRC/Models/User.PY") == "backend.model.edit"
    assert classify_path("Docs/Guide.MD") == "docs.update"


# ---------------------------------------------------------------------------
# classify_commit
# ---------------------------------------------------------------------------


def test_classify_commit_empty() -> None:
    assert classify_commit([]) == UNCLASSIFIED


def test_classify_commit_majority() -> None:
    files = ["app/models/a.py", "app/models/b.py", "app/api/c.py"]
    assert classify_commit(files) == "backend.model.edit"


def test_classify_commit_tie_resolves_to_first_occurrence() -> None:
    assert classify_commit(["app/api/c.py", "app/models/a.py"]) == "backend.route.add"
    assert classify_commit(["app/models/a.py", "app/api/c.py"]) == "backend.model.edit"


def test_classify_commit_single_file() -> None:
    assert classify_commit(("src/calc/__init__.py",)) == "bug.fix"


# ---------------------------------------------------------------------------
# RepoConfig
# ---------------------------------------------------------------------------


def test_repo_config_defaults_per_language() -> None:
    for lang, runner, ext in [
        (Language.PYTHON, "pytest", ".py"),
        (Language.GO, "go", ".go"),
        (Language.JAVASCRIPT, "mocha", ".js"),
        (Language.JVM, "maven", ".java"),
        (Language.RUST, "cargo", ".rs"),
    ]:
        c = RepoConfig(name="r", language=lang)
        assert (c.runner, c.ext) == (runner, ext)
        assert c.belt_scope == BELT_TARGET_ONLY
        assert c.runner in RUNNERS


@pytest.mark.parametrize("name", ["", "Has Space", "UPPER", "-lead", "a" * 65, "a/b"])
def test_repo_config_rejects_bad_names(name: str) -> None:
    with pytest.raises(ValueError, match="repo name"):
        RepoConfig(name=name, language=Language.PYTHON)


def test_repo_config_accepts_dotted_dashed_names() -> None:
    assert RepoConfig(name="my-repo.v2_x", language=Language.PYTHON).name == "my-repo.v2_x"


def test_repo_config_validation_errors() -> None:
    with pytest.raises(ValueError, match="unknown runner"):
        RepoConfig(name="r", language=Language.PYTHON, runner="nose")
    with pytest.raises(ValueError, match="test_mode"):
        RepoConfig(name="r", language=Language.PYTHON, test_mode="infix")
    with pytest.raises(ValueError, match="requires test_suffix"):
        RepoConfig(name="r", language=Language.PYTHON, test_mode="suffix")
    with pytest.raises(ValueError, match="belt_scope"):
        RepoConfig(name="r", language=Language.PYTHON, belt_scope="EVERYTHING")


def test_repo_config_belt_scope_list_becomes_tuple_and_mappings_are_copied() -> None:
    opts = {"python": "/usr/bin/python3"}
    mining = {"log_n": 5}
    c = RepoConfig(
        name="r",
        language=Language.PYTHON,
        belt_scope=["tests/a", "tests/b"],
        runner_opts=opts,
        mining=mining,
    )
    assert c.belt_scope == ("tests/a", "tests/b")
    opts["python"] = "changed"
    mining["log_n"] = 99
    assert c.runner_opts == {"python": "/usr/bin/python3"}
    assert c.mining == {"log_n": 5}


def test_python_prefix_layout() -> None:
    c = RepoConfig(name="py", language=Language.PYTHON, src_prefix="src/pkg/", test_prefix="tests/")
    assert c.is_src("src/pkg/a.py")
    assert not c.is_src("src/pkg/a.pyi")
    assert not c.is_src("tests/test_a.py")
    assert not c.is_src("other/a.py")
    assert c.is_test("tests/test_a.py")
    assert not c.is_test("tests/data.json")
    assert not c.is_test("src/pkg/test_a.py")
    assert c.language_files(["a.py", "b.md", "tests/c.py"]) == ["a.py", "tests/c.py"]


def test_python_layout_without_src_prefix_treats_non_tests_as_source() -> None:
    c = RepoConfig(name="py", language=Language.PYTHON, test_prefix="tests/")
    assert c.is_src("anything/here.py")
    assert not c.is_src("tests/test_x.py")
    no_tests = RepoConfig(name="py", language=Language.PYTHON)
    assert no_tests.is_src("tests/test_x.py")
    assert not no_tests.is_test("tests/test_x.py")


def test_go_layout() -> None:
    c = RepoConfig(name="gin", language=Language.GO)
    assert c.is_src("render/json.go")
    assert not c.is_src("render/json_test.go")
    assert c.is_test("render/json_test.go")
    assert not c.is_test("render/json.go")
    assert not c.is_test("README.md")


def test_rust_layout() -> None:
    c = RepoConfig(name="clap", language=Language.RUST)
    assert c.is_src("src/lib.rs")
    assert not c.is_src("tests/it.rs")
    assert c.is_test("tests/builder/env.rs")
    assert not c.is_test("src/lib.rs")
    assert not c.is_test("tests/data.txt")


def test_jvm_layout_spans_resources_and_modules() -> None:
    root = RepoConfig(name="petclinic", language=Language.JVM, test_prefix="src/test/java/")
    assert root.is_src("src/main/java/App.java")
    assert root.is_src("src/main/resources/app.properties")
    assert not root.is_src("src/test/java/AppTest.java")
    assert root.is_test("src/test/java/AppTest.java")
    assert root.language_files(["a.java", "b.properties"]) == ["a.java", "b.properties"]
    mod = RepoConfig(
        name="lang",
        language=Language.JVM,
        src_prefix="core/src/main/java/",
        test_prefix="core/src/test/java/",
    )
    assert mod.is_src("core/src/main/resources/x.xml")
    assert not mod.is_src("other/src/main/java/A.java")


def test_js_layout_excludes_support_dir() -> None:
    c = RepoConfig(
        name="koa",
        language=Language.JAVASCRIPT,
        runner="node",
        src_prefix="lib/",
        test_prefix="__tests__/",
    )
    assert c.is_test("__tests__/application/index.test.js")
    assert not c.is_test("__tests__/support/helper.js")
    assert c.is_src("lib/app.js")
    assert not c.is_src("__tests__/x.js")


def test_suffix_mode_layout() -> None:
    c = RepoConfig(
        name="dj",
        language=Language.PYTHON,
        test_mode="suffix",
        test_suffix="_tests.py",
        src_prefix="app/",
    )
    assert c.is_test("app/views_tests.py")
    assert not c.is_test("app/views.py")
    assert c.is_src("app/views.py")
    assert not c.is_src("app/views_tests.py")
    assert not c.is_src("lib/views.py")


def test_repo_config_round_trip() -> None:
    c = RepoConfig(
        name="r",
        language=Language.GO,
        belt_scope=["./..."],
        runner_opts={"cgo": "1"},
        mining={"log_n": 10},
        sandbox_image="img:1",
    )
    d = c.to_dict()
    assert d["language"] == "go"
    assert d["belt_scope"] == ["./..."]
    json.dumps(d)
    assert RepoConfig.from_dict("r", d) == c


# Three real entries from the census configs.json (copied verbatim).
_CENSUS_SQLALCHEMY: dict[str, Any] = {
    "lang": "py",
    "url": "https://github.com/sqlalchemy/sqlalchemy",
    "layer": "Python · ORM / data access",
    "pythonpath_suffix": "/lib",
    "pip": ["sqlalchemy", "pytest", "greenlet", "typing-extensions"],
    "pip_fallback": ["sqlalchemy", "pytest", "greenlet", "typing-extensions"],
    "uninstall": ["sqlalchemy"],
    "src_prefix": "lib/sqlalchemy/",
    "test_prefix": "test/",
    "ext": ".py",
    "belt_scope": "AFFECTED_DIRS",
    "probe": "test/base/test_utils.py",
    "target_valid": 220,
    "log_n": 15000,
    "max_candidates": 5000,
    "hard_target": 60,
}
_CENSUS_GIN: dict[str, Any] = {
    "lang": "go",
    "url": "https://github.com/gin-gonic/gin",
    "layer": "Go · web framework",
    "src_prefix": "",
    "test_prefix": "",
    "ext": ".go",
    "belt_scope": ["./..."],
    "probe": "./render/...",
    "target_valid": 90,
    "log_n": 6000,
    "max_candidates": 2500,
    "hard_target": 30,
}
_CENSUS_KOA: dict[str, Any] = {
    "lang": "js",
    "js_tool": "node",
    "url": "https://github.com/koajs/koa",
    "layer": "JavaScript · middleware framework (Node)",
    "src_prefix": "lib/",
    "test_prefix": "__tests__/",
    "ext": ".js",
    "belt_scope": ["BARE"],
    "probe": "__tests__/application/index.test.js",
    "target_valid": 25,
    "log_n": 2500,
    "max_candidates": 900,
    "hard_target": 8,
}


def test_from_dict_census_python_entry() -> None:
    c = RepoConfig.from_dict("sqlalchemy", _CENSUS_SQLALCHEMY)
    assert c.language is Language.PYTHON
    assert c.runner == "pytest"
    assert c.belt_scope == BELT_AFFECTED_DIRS
    assert c.runner_opts["pythonpath_suffix"] == "/lib"
    assert c.runner_opts["pip"] == ["sqlalchemy", "pytest", "greenlet", "typing-extensions"]
    assert c.runner_opts["uninstall"] == ["sqlalchemy"]
    assert c.mining == {
        "log_n": 15000,
        "max_candidates": 5000,
        "target_valid": 220,
        "hard_target": 60,
    }
    assert c.probe == "test/base/test_utils.py"
    assert c.url.endswith("/sqlalchemy")
    assert c.is_src("lib/sqlalchemy/orm/session.py")
    assert c.is_test("test/orm/test_session.py")


def test_from_dict_census_go_entry() -> None:
    c = RepoConfig.from_dict("gin", _CENSUS_GIN)
    assert c.language is Language.GO
    assert c.runner == "go"
    assert c.belt_scope == ("./...",)
    assert c.mining["target_valid"] == 90
    assert c.is_test("render/json_test.go") and c.is_src("render/json.go")


def test_from_dict_census_js_entry_maps_js_tool_to_runner() -> None:
    c = RepoConfig.from_dict("koa", _CENSUS_KOA)
    assert c.language is Language.JAVASCRIPT
    assert c.runner == "node"
    assert c.belt_scope == ("BARE",)
    assert c.layer.startswith("JavaScript")
    assert not c.is_test("__tests__/support/x.js")


def test_from_dict_native_shape_runner_opts_take_precedence() -> None:
    d = {
        "language": "python",
        "runner": "pytest",
        "runner_opts": {"pythonpath_suffix": "/native"},
        "pythonpath_suffix": "/legacy",
        "mining": {"log_n": 1},
        "log_n": 999,
        "belt_scope": "BARE",
    }
    c = RepoConfig.from_dict("x", d)
    assert c.runner_opts["pythonpath_suffix"] == "/native"
    assert c.mining["log_n"] == 1
    assert c.belt_scope == BELT_BARE


def test_from_dict_rejects_missing_language() -> None:
    with pytest.raises(ValueError, match="unknown language"):
        RepoConfig.from_dict("x", {"runner": "pytest"})


# ---------------------------------------------------------------------------
# TaskSpec
# ---------------------------------------------------------------------------

_SHA = "b7c6251293a287542ac8568cad7505b710fa3532"


def _task(**kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "task_id": _SHA,
        "repo": "r",
        "subject": "s",
        "authored": "2026-01-01T00:00:00+00:00",
        "test_files": ["tests/test_a.py"],
        "src_files": ["src/a.py"],
        "target_tests": ["tests/test_a.py"],
        "belt_scope": ["tests/"],
    }
    base.update(kw)
    return TaskSpec(**base)


def test_task_spec_validation() -> None:
    with pytest.raises(ValueError, match="git sha"):
        _task(task_id="not-a-sha")
    with pytest.raises(ValueError, match="git sha"):
        _task(task_id="abc")  # too short
    with pytest.raises(ValueError, match="pool"):
        _task(pool="easy")
    with pytest.raises(ValueError, match="size"):
        _task(size="XXL")
    with pytest.raises(ValueError, match="test file"):
        _task(test_files=[])
    with pytest.raises(ValueError, match="source file"):
        _task(src_files=[])


def test_task_spec_normalises_sequences_and_short_id() -> None:
    t = _task(labels={"k": "v"}, baseline_failing=["x"])
    assert isinstance(t.test_files, tuple)
    assert isinstance(t.belt_scope, tuple)
    assert isinstance(t.baseline_failing, tuple)
    assert t.labels == {"k": "v"}
    assert t.short_id == _SHA[:10]
    assert t.gold_clean is None
    assert t.pool == "standard"


def test_task_spec_round_trip() -> None:
    t = _task(
        pool=POOL_HARD,
        src_churn=45,
        size="M",
        capability_class="backend.model.edit",
        language="python",
        baseline_failing=["tests/test_b.py::test_x"],
        red_checked=True,
        gold_clean=True,
        gold_note="",
        labels={"a": "b"},
    )
    d = t.to_dict()
    json.dumps(d)
    assert d["test_files"] == ["tests/test_a.py"]
    assert TaskSpec.from_dict(d) == t


# A real census <repo>_tasks.json record (sqlalchemy), copied verbatim.
_CENSUS_TASK: dict[str, Any] = {
    "task": "b7c6251293a287542ac8568cad7505b710fa3532",
    "target_tests": ["test/dialect/postgresql/test_compiler.py"],
    "test_files": ["test/dialect/postgresql/test_compiler.py"],
    "src_files": ["lib/sqlalchemy/dialects/postgresql/base.py"],
    "authored": "2026-07-04T04:02:35-04:00",
    "subject": "SQL codestyle: trim spacing around 'INHERITS' table list",
    "baseline_failing": [
        "test/dialect/postgresql/test_compiler.py::CompileTest::test_create_table_inherits",
        "test/dialect/postgresql/test_compiler.py::CompileTest::test_create_table_inherits_quoting",
        "test/dialect/postgresql/test_compiler.py::CompileTest::test_create_table_inherits_schema_qualified_quoted_name",
        "test/dialect/postgresql/test_compiler.py::CompileTest::test_create_table_inherits_tuple",
    ],
    "src_churn": 4,
    "size": "XS",
    "gold_clean": True,
}


def test_task_spec_from_census_record() -> None:
    t = TaskSpec.from_dict({**_CENSUS_TASK, "repo": "sqlalchemy"})
    assert t.task_id == _CENSUS_TASK["task"]
    assert t.repo == "sqlalchemy"
    assert t.size == "XS"
    assert t.src_churn == 4
    assert t.red_checked is True  # baseline_failing present ⇒ RED was checked
    assert t.gold_clean is True
    assert t.belt_scope == ()  # census rows carry no belt scope: BARE
    assert len(t.baseline_failing) == 4
    assert t.capability_class == "bug.fix"  # derived from src_files


def test_task_spec_from_dict_derives_size_and_class_when_absent() -> None:
    d = _task().to_dict()
    del d["size"]
    del d["capability_class"]
    del d["path_class"]  # the same axis: a record without a class carries neither
    del d["baseline_failing"]
    d["src_churn"] = 50
    d["src_files"] = ["app/models/user.py"]
    t = TaskSpec.from_dict(d)
    assert t.size == "M"
    assert t.capability_class == "backend.model.edit"
    assert t.path_class == "backend.model.edit" and t.class_source == "path"
    assert t.red_checked is False
    assert TaskSpec.from_dict({**d, "task_id": None, "commit": _SHA}).task_id == _SHA


def test_task_spec_with_() -> None:
    t = _task()
    t2 = t.with_(gold_clean=False, gold_note="broke belt", size="L")
    assert t2.gold_clean is False
    assert t2.gold_note == "broke belt"
    assert t2.size == "L"
    assert t.gold_clean is None  # original untouched
    assert t2.task_id == t.task_id
    with pytest.raises(ValueError):
        t.with_(size="huge")


def test_ext_and_test_suffix_accept_alternatives() -> None:
    """TypeScript repos mix .ts/.tsx; design systems co-locate *.unit.test.mjs and
    *.jsdom.test.mjs next to sources — both are '|'-separated alternatives."""
    from crb.core.spec import Language, RepoConfig

    cfg = RepoConfig(
        name="ds",
        language=Language.JAVASCRIPT,
        runner="jest",
        src_prefix="src/",
        ext=".ts|.tsx",
        test_mode="suffix",
        test_suffix=".test.ts|.test.tsx",
    )
    assert cfg.is_test("src/a/__tests__/A.test.tsx") and cfg.is_test("src/__tests__/i.test.ts")
    assert not cfg.is_test("src/a/A.puppeteer.test.mjs")
    assert cfg.is_src("src/a/A.tsx") and cfg.is_src("src/index.ts")
    assert not cfg.is_src("src/a/__tests__/A.test.tsx")
    assert cfg.language_files(["src/a.ts", "src/b.tsx", "README.md"]) == ["src/a.ts", "src/b.tsx"]


# ---------------------------------------------------------------------------
# TaskSpec: the two class axes and the resolved class
# ---------------------------------------------------------------------------


def test_task_spec_capability_class_is_resolved_from_path_and_intent() -> None:
    from crb.core.classify import IntentLabel, human_label

    t = _task(capability_class="bug.fix")  # the pre-label constructor shape
    assert (t.path_class, t.capability_class, t.class_source) == ("bug.fix", "bug.fix", "path")
    assert t.intent is None and t.class_reason == "no intent label"

    confident = IntentLabel("feature.add", 0.9, "adds an option", "claude_code:claude-sonnet-5")
    t2 = t.with_(intent=confident)
    assert (t2.path_class, t2.capability_class, t2.class_source) == (
        "bug.fix",
        "feature.add",
        "intent",
    )
    weak = IntentLabel("feature.add", 0.4, "unsure", "claude_code:claude-sonnet-5")
    t3 = t.with_(intent=weak)
    assert (t3.capability_class, t3.class_source) == ("bug.fix", "path")
    assert "below threshold" in t3.class_reason
    t4 = t3.with_(intent=human_label("behavior.change", by="reviewer"))
    assert (t4.capability_class, t4.class_source) == ("behavior.change", "human")
    # clearing the label restores the path class
    assert t4.with_(intent=None).capability_class == "bug.fix"
    # a direct TaskSpec(path_class=…, intent=…) construction resolves the same way
    direct = _task(path_class="docs.update", intent=confident)
    assert direct.capability_class == "feature.add" and direct.class_source == "intent"


def test_task_spec_with_capability_class_moves_the_path_axis() -> None:
    """``capability_class`` is derived; callers who set it (fixtures, the factory) are
    setting the path/declared class, and an intent label still takes precedence."""
    from crb.core.classify import IntentLabel

    t = _task(capability_class="bug.fix").with_(capability_class="docs.update")
    assert t.path_class == "docs.update" and t.capability_class == "docs.update"
    labelled = t.with_(intent=IntentLabel("refactor", 0.95, "r", "m"))
    moved = labelled.with_(capability_class="test.add")
    assert moved.path_class == "test.add" and moved.capability_class == "refactor"


def test_task_spec_round_trip_with_intent_and_derived_fields() -> None:
    from crb.core.classify import IntentLabel

    t = _task(capability_class="bug.fix").with_(
        intent=IntentLabel(
            "perf",
            0.85,
            "faster",
            "openai_agent:gpt-oss-120b@cerebras",
            labelled_at="2026-09-13T10:00:00+00:00",
            evidence_hash="cd" * 32,
        )
    )
    d = t.to_dict()
    json.dumps(d)
    assert d["path_class"] == "bug.fix" and d["capability_class"] == "perf"
    assert d["class_source"] == "intent" and d["intent"]["labeller"].startswith("openai_agent:")
    assert TaskSpec.from_dict(d) == t
    # the derived key is informational: dropping it changes nothing
    del d["class_source"]
    assert TaskSpec.from_dict(d) == t
    # an intent given as a dict (the stored shape) or an IntentLabel loads alike
    assert TaskSpec.from_dict({**d, "intent": t.intent}) == t


def test_task_spec_loads_records_from_before_labels_existed() -> None:
    """Every stored task predating this field set carries ``capability_class`` only;
    it must load unchanged: that value is the path class and the resolved class."""
    old = _task(capability_class="backend.route.add").to_dict()
    for k in ("path_class", "intent", "class_source"):
        del old[k]
    t = TaskSpec.from_dict(old)
    assert t.path_class == "backend.route.add" and t.capability_class == "backend.route.add"
    assert t.intent is None and t.class_source == "path"
    # the census record shape (no class at all) derives both axes from src_files
    census = TaskSpec.from_dict({**_CENSUS_TASK, "repo": "sqlalchemy"})
    assert census.path_class == "bug.fix" and census.class_source == "path"


def test_intent_classes_extend_the_closed_vocabulary() -> None:
    from crb.core.spec import CLASS_VOCABULARY, INTENT_CLASSES

    assert set(INTENT_CLASSES) == {"behavior.change", "feature.add", "perf", "refactor"}
    assert set(INTENT_CLASSES).isdisjoint(ALL_CLASSES)  # bug.fix is shared, and in ALL_CLASSES
    assert set(CLASS_VOCABULARY) == set(ALL_CLASSES) | set(INTENT_CLASSES)
    # the path classifier never returns an intent-only class
    assert classify_commit(["command.go", "completions.go"]) == "bug.fix"
