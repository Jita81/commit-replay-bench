"""Every "complete list" of what leaves the deployment names every outbound flow (P-103).

Navigation
----------
What it is:   The guard that keeps the three exhaustive egress statements in the operator's
              documents in step with each other, with the flows the product has, and with
              every setting that points the product at an address outside the deployment.
What it does: Discovers every endpoint-shaped setting (the ``Settings`` model walked field by
              field, plus every ``CRB_…`` / ``AZURE_OPENAI_…`` endpoint name a source file
              reads) and fails when one belongs to no flow in ``FLOWS`` and is not listed in
              ``NOT_EGRESS`` with its reason; fails when the SECURITY.md boundary table's
              rows and ``FLOWS`` are not one to one, when a flow's row does not name the
              settings that point it, or when the table, DEPLOYMENT §1 or DEPLOYMENT §7
              omits a flow; fails when the statement under the table names a different set
              of writers from the rows whose "What is sent" cell names a write (P-107),
              and pins the write-verb list both ways (every usual write word counts, a
              send-and-read row does not); fails when the delivery paragraph under the
              table does not name every write seam of ``crb.factory.delivery`` and the
              re-delivery's re-pointed branch (P-111);
              pins that a setting name is found whatever quote it is written in (P-110);
              pins that the provisioning row says what a fetch sends and what it never
              sends.
How:          ``pydantic`` field walk plus a regular expression over ``src/crb`` that reads
              a whole string literal in either quote; the statements are sliced out of the
              Markdown by their opening words and the table's end; a regular expression per
              flow, and one for the verbs that change something outside.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0019-qualification-is-posture-relative.md (the provisioning flow),
              docs/adr/0014-github-app-is-the-connection.md (the GitHub API flow)
Works with:   docs/SECURITY.md (the boundary table), docs/DEPLOYMENT.md (§1 and §7),
              src/crb/server/settings.py (``Settings``, the walked model),
              src/crb/provision/fetch.py (the fetch the provisioning row describes),
              src/crb/factory/delivery.py (the write seams the delivery paragraph names),
              docs/PREVENTION.md (rows P-103, P-107, P-110 and P-111)
Tested by:    tests/test_egress_inventory.py
Touch when:   never for a new repository (a client repository adds no flow; its remote is
              the git-remote row); the product gains or loses a flow that leaves the
              deployment, or a setting that points at an address — the discovery test fails
              until the setting has a flow (and that flow a row in all three statements) or a
              ``NOT_EGRESS`` reason; or factory delivery gains a write seam — map it in
              ``_DELIVERY_WRITES`` and say in SECURITY.md what it writes; or a row uses a
              write verb not in ``_WRITE_STEMS``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel

from crb.server.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src" / "crb"


@dataclass(frozen=True)
class Flow:
    #: how the flow's row in the SECURITY.md boundary table begins
    row: str
    #: how each of the three complete lists must name the flow
    rx: str
    #: every setting that points the flow at an address; the row must name each one
    endpoints: tuple[str, ...]


#: Every flow that can leave a deployment.
FLOWS: dict[str, Flow] = {
    "model endpoint": Flow(
        "Builder / labeller / reviewer calls",
        r"model endpoint",
        (
            "CRB_OPENAI_BASE_URL",
            "CRB_AZURE_ENDPOINT",
            "AZURE_OPENAI_ENDPOINT",
            "CRB_BUILDER__ALLOW_HOSTS",
        ),
    ),
    # the address is the repository row's ``repos.url``, a column, not a setting
    "git remote": Flow("Repository clone and fetch", r"git remote|repository'?s? remote", ()),
    "GitHub API": Flow("GitHub API", r"GitHub API", ("CRB_GITHUB__API_URL",)),
    "OIDC issuer": Flow("Sign-in", r"OIDC issuer", ("CRB_OIDC__ISSUER",)),
    "tracker (intake)": Flow("Intake", r"tracker", ("CRB_INTAKE__URL",)),
    "package mirror or registry (provisioning)": Flow(
        "Dependency provisioning",
        r"package mirror|package registr",
        (
            "CRB_PROVISION__GO_PROXY",
            "CRB_PROVISION__GO_SUMDB",
            "CRB_PROVISION__PYPI_INDEX",
            "CRB_PROVISION__PYPI_FILES_HOST",
            "CRB_PROVISION__NPM_REGISTRY",
            "CRB_PROVISION__EXTRA_ALLOW_HOSTS",
        ),
    ),
    "image registry": Flow(
        "Container images",
        r"image registr",
        (
            "CRB_SANDBOX__IMAGE",
            "CRB_SANDBOX_IMAGE",
            "CRB_BUILDER__IMAGE",
            "CRB_BUILDER__PROXY_IMAGE",
            "CRB_PROVISION__PROXY_IMAGE",
            "CRB_PROVISION__GO_IMAGE",
            "CRB_PROVISION__PYTHON_IMAGE",
            "CRB_PROVISION__NODE_IMAGE",
        ),
    ),
}

#: Endpoint-shaped settings that do NOT send anything out of the deployment, and why.
NOT_EGRESS: dict[str, str] = {
    "CRB_BIND_HOST": "the address the API listens on (inbound)",
    "CRB_METRICS_HOST": "the address the worker's metrics listener binds (inbound)",
    "CRB_DATABASE_URL": "the deployment's own database",
    "CRB_PUBLIC_URL": "the deployment's own address, used to build links",
    "CRB_API_URL": "the MCP client's address for this deployment's own API",
    "CRB_OIDC__REDIRECT_URL": "the deployment's own callback; the browser returns to it",
    "CRB_GITHUB__WEB_URL": "a link the admin's browser follows to install the app; "
    "the product never calls it",
}

#: The last word of a setting that holds an address or an image reference.
_SHAPE = r"(?:URL|ENDPOINT|ISSUER|HOSTS?|REGISTRY|INDEX|PROXY|SUMDB|IMAGE)"
#: A setting name as a whole string literal, in either quote: ruff format normalises source
#: to double quotes, but a name that holds a double quote, or a file ruff skips, keeps its
#: single ones, and the inventory must not depend on the formatter (PR #61 review).
_SOURCE_NAME = re.compile(
    rf"""(['"])((?:CRB|AZURE_OPENAI|OPENAI|ANTHROPIC)_[A-Z0-9_]*{_SHAPE})\1"""
)


def _model_names(model: type[BaseModel], prefix: str) -> Iterator[str]:
    for name, field in model.model_fields.items():
        env = f"{prefix}{name.upper()}"
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            yield from _model_names(ann, f"{env}__")
        elif re.search(rf"{_SHAPE}$", env):
            yield env


def _names_in_source(text: str) -> set[str]:
    """Every endpoint-shaped setting name a Python source text reads as a string literal."""
    return {m.group(2) for m in _SOURCE_NAME.finditer(text)}


def _discovered() -> set[str]:
    names = set(_model_names(Settings, "CRB_"))
    for path in SRC.rglob("*.py"):
        names |= _names_in_source(path.read_text(encoding="utf-8"))
    return names


def _declared() -> set[str]:
    return {e for f in FLOWS.values() for e in f.endpoints} | set(NOT_EGRESS)


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i + len(start))]


def _table_end(security: str) -> int:
    """Where the SECURITY.md boundary table ends: the first blank line after its header."""
    return security.index("\n\n", security.index("\n| Flow |"))


def _statements() -> dict[str, str]:
    security = (DOCS / "SECURITY.md").read_text(encoding="utf-8")
    deployment = (DOCS / "DEPLOYMENT.md").read_text(encoding="utf-8")
    start = security.index("**What crosses the tenant boundary")
    return {
        "SECURITY.md boundary table": security[start : _table_end(security)],
        "DEPLOYMENT.md §1 invariant": _slice(
            deployment, "Both enforce the same invariants", "\n\n"
        ),
        "DEPLOYMENT.md §7 outbound list": _slice(
            deployment, "The complete outbound list is", "\n\n"
        ),
    }


def _table_rows() -> list[list[str]]:
    table = _statements()["SECURITY.md boundary table"]
    rows = [line for line in table.splitlines() if line.startswith("| ")]
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    return [c for c in cells if c[0] != "Flow"]  # drop the header row


def test_every_endpoint_setting_belongs_to_a_flow_or_says_why_it_is_not_egress() -> None:
    unclaimed = sorted(_discovered() - _declared())
    assert unclaimed == [], (
        f"{unclaimed} point at an address but belong to no flow in FLOWS and are not in "
        "NOT_EGRESS: add each to its flow (and the flow to SECURITY.md, DEPLOYMENT §1 and §7) "
        "or to NOT_EGRESS with the reason nothing leaves the deployment"
    )


def test_no_declared_endpoint_is_stale() -> None:
    stale = sorted(_declared() - _discovered())
    assert stale == [], f"{stale} are declared here but no longer read by the product"


def test_the_boundary_table_has_exactly_one_row_per_flow() -> None:
    firsts = [row[0] for row in _table_rows()]
    for first in firsts:
        owners = [k for k, f in FLOWS.items() if first.startswith(f.row)]
        assert len(owners) == 1, f"table row {first!r} matches {owners} in FLOWS, not one"
    for key, flow in FLOWS.items():
        rows = [first for first in firsts if first.startswith(flow.row)]
        assert len(rows) == 1, f"FLOWS[{key!r}] has {len(rows)} rows in the table, not one"


def _names(cell: str, env: str) -> bool:
    if env in cell:
        return True
    section, sep, leaf = env.rpartition("__")
    return bool(sep) and f"{section}__" in cell and re.search(rf"\b{leaf}\b", cell) is not None


@pytest.mark.parametrize("key", sorted(FLOWS))
def test_each_flow_row_names_the_settings_that_point_it(key: str) -> None:
    flow = FLOWS[key]
    row = next(r for r in _table_rows() if r[0].startswith(flow.row))
    endpoint_cell = row[1]
    missing = [e for e in flow.endpoints if not _names(endpoint_cell, e)]
    assert missing == [], f"the {flow.row!r} row's endpoint cell does not name {missing}"


@pytest.mark.parametrize("where", sorted(_statements()))
def test_every_complete_egress_list_names_every_flow(where: str) -> None:
    text = " ".join(_statements()[where].split())
    missing = [k for k, f in FLOWS.items() if not re.search(f.rx, text, re.IGNORECASE)]
    assert missing == [], f"{where} omits {missing}"


def test_the_provisioning_row_says_what_a_fetch_sends_and_never_sends() -> None:
    row = next(r for r in _table_rows() if r[0].startswith("Dependency provisioning"))
    assert len(row) == 4, row
    flow, endpoint, sent, never = row
    assert "off by default" in flow and "CRB_PROVISION__" in endpoint
    assert "names and versions" in sent and "go.sum" in sent
    assert "source code" in never and "credential" in never


#: The verbs that say a flow CHANGES something outside the deployment: a pushed or
#: re-pointed branch, a comment or post, an opened, created, updated, merged, closed or
#: deleted object, a label, a transition, an HTTP write method. Each is matched in every
#: form a row may use — see ``_stem_forms`` — with or without a ``re`` / ``re-`` prefix, so
#: a verb added here is recognised in every tense by construction (P-115, P-117).
_WRITE_STEMS: tuple[str, ...] = (
    "push",
    "re-point",
    "comment",
    "post",
    "close",
    "open",
    "create",
    "update",
    "merge",
    "delete",
    "label",
    "transition",
    "patch",
)


def _stem_forms(stem: str) -> str:
    """A pattern for every form of ``stem``: the base, ``-s`` / ``-es``, ``-d`` / ``-ed`` /
    ``-led`` and ``-ing`` / ``-ling``, a final ``e`` dropped before ``-ing`` ("merging",
    "closing"). The forms are built here, not listed, so a stem added above is recognised in
    every one of them (P-115, P-117)."""
    if stem.endswith("e"):
        return re.escape(stem[:-1]) + r"(?:e|es|ed|ing)"
    return re.escape(stem) + r"(?:s|es|ed|led|ing|ling)?"


#: A word in a row's "What is sent" cell that says the flow writes: one of the stems above in
#: any form, an HTTP ``PUT``, or a write TO something. A bare "writes" is not one: the
#: builder row's "the diff it writes" is content sent to the model (pinned both ways by the
#: two tests below the write-statement test).
_WRITE_VERB = re.compile(
    r"\b(?:(?:re-?)?(?:" + "|".join(map(_stem_forms, _WRITE_STEMS)) + r")"
    r"|put|(?:writes?|writing|wrote|written)\s+to)\b",
    re.IGNORECASE,
)


def _write_statement() -> str:
    """The prose under the boundary table that says which flows WRITE, up to the C6 rules."""
    security = (DOCS / "SECURITY.md").read_text(encoding="utf-8")
    end = _table_end(security)
    return security[end : security.index("Since 2026-09-25 (assessment C6", end)]


def test_the_write_statement_names_every_flow_whose_row_writes() -> None:
    """The table is the inventory: the prose under it names exactly the flows whose rows say
    they write, no fewer and no more (P-107)."""
    writers = {
        k
        for k, f in FLOWS.items()
        for row in _table_rows()
        if row[0].startswith(f.row) and _WRITE_VERB.search(row[2])
    }
    assert "tracker (intake)" in writers, writers  # the verb list still reads the table
    text = " ".join(_write_statement().split())
    named = {k for k, f in FLOWS.items() if re.search(f.rx, text, re.IGNORECASE)}
    assert named == writers, (
        f"the rows of {sorted(writers)} say they write; the statement under the table names "
        f"{sorted(named)}"
    )


@pytest.mark.parametrize(
    "source",
    [
        'os.getenv("CRB_NEW_ENDPOINT")',
        "os.getenv('CRB_NEW_ENDPOINT')",
        "os.environ['CRB_NEW_ENDPOINT']",
        "NAME = r'CRB_NEW_ENDPOINT'",
    ],
)
def test_an_endpoint_read_is_discovered_whatever_quote_it_uses(source: str) -> None:
    """An endpoint setting is discovered whatever quote or string prefix reads it (P-110)."""
    assert _names_in_source(source) == {"CRB_NEW_ENDPOINT"}


def test_a_name_that_is_not_an_endpoint_is_not_discovered() -> None:
    assert _names_in_source("os.getenv('CRB_HOME'); os.getenv(\"CRB_BUDGET_USD\")") == set()


@pytest.mark.parametrize(
    "cell",
    [
        "opens a pull request against the default branch",
        "creates an issue",
        "posts a comment on the ticket",
        "updates the work item's state",
        "merges the pull request",
        "deletes the branch",
        "a PATCH of the ticket",
        "a POST to `/issues`",
        "a PUT of the file",
        "re-points the branch to a new commit",
        "a force-push of the branch",
        "writes to the tracker",
        "pushed a branch",
        "re-pointed the branch to a new commit",
        "opened a pull request",
        "created an issue",
        "posted a comment",
        "commented on the ticket",
        "updated the state",
        "merged the pull request",
        "deleted the branch",
        "labelled the ticket",
        "labeled the ticket",
        "transitioned the work item",
        "patched the ticket",
        "wrote to the tracker",
        "pushing a branch",
        "re-pointing the branch",
        "opening a pull request",
        "closing the pull request",
        "merging the pull request",
        "creating an issue",
        "updating the state",
        "labelling the ticket",
        "writing to the tracker",
        "reopens the pull request",
        "reopened the issue",
        "re-opens the issue",
        "reposts the note",
    ],
)
def test_a_row_that_writes_in_any_of_the_usual_words_counts_as_a_writer(cell: str) -> None:
    """A row counts as a writer when its "What is sent" cell uses any write verb, in any
    tense: a push or re-point, an open, create, post, comment, update, merge, close or
    delete, a label, a transition, an HTTP write method, or a write to something. The
    write-statement test then requires the prose to name that flow (P-107, P-115)."""
    assert _WRITE_VERB.search(cell), cell


def test_every_write_stem_counts_in_every_form() -> None:
    """Each write verb counts in its base, third-person, past and ``-ing`` forms, with or
    without a ``re``/``re-`` prefix (P-115, P-117)."""
    for stem in _WRITE_STEMS:
        third = stem + ("es" if stem.endswith(("sh", "ch")) else "s")
        past = stem + ("d" if stem.endswith("e") else "ed")
        ing = (stem[:-1] if stem.endswith("e") else stem) + "ing"
        for form in (stem, third, past, ing):
            prefixes = ("",) if stem.startswith("re-") else ("", "re", "re-")
            for prefix in prefixes:
                assert _WRITE_VERB.search(f"it {prefix}{form} the object"), prefix + form


@pytest.mark.parametrize(
    "cell",
    [
        "the task brief, the source files the builder reads in its worktree, the diff it writes",
        "a read of a repository's metadata and of a delivered pull request's state",
        "requests for the installations, one installation's repositories",
        "the image references (name, tag or digest)",
        "the diff the builder is writing in its worktree",
    ],
)
def test_a_row_that_only_sends_and_reads_is_not_a_writer(cell: str) -> None:
    """The other half of the verb list's contract: widening it may not make a flow that
    only sends a request and reads the answer count as a writer (the builder's 'the diff it
    writes' is content sent to the model, not a write outside the deployment)."""
    assert not _WRITE_VERB.search(cell), cell


#: Each write seam of ``crb.factory.delivery`` (its ``#: ``<name>_fn(`` seam comments) and
#: the words the delivery paragraph under the boundary table must use for it. A new seam
#: fails the test below until it has an entry here and the paragraph says what it does.
_DELIVERY_WRITES: dict[str, tuple[str, ...]] = {
    "push_fn": ("pushes",),
    "open_pr_fn": ("opens a pull request", "opens the pull request"),
    "comment_pr_fn": ("comment",),
    "close_pr_fn": ("close",),
}

#: The re-delivery lease in ``deliver()``: a push with ``expected=`` moves an existing
#: branch — and so the pull request's content — to a new commit.
_REDELIVERY_LEASE = "expected=previous.commit_sha"


def _delivery_paragraph() -> str:
    security = (DOCS / "SECURITY.md").read_text(encoding="utf-8")
    return " ".join(_slice(security, "Factory delivery writes to", "\n\n").split())


def test_the_delivery_paragraph_names_every_write_delivery_makes() -> None:
    """The delivery paragraph names every write delivery makes: each write seam of
    ``crb.factory.delivery`` (push, open, comment, close), and the re-delivery's
    force-with-lease push that re-points the same branch to a new commit and so changes what
    the pull request contains (P-111)."""
    source = (SRC / "factory" / "delivery.py").read_text(encoding="utf-8")
    seams = set(re.findall(r"^#: ``(\w+_fn)\(", source, re.MULTILINE))
    assert "push_fn" in seams, seams  # the seam reader still reads the module
    unmapped = sorted(seams - set(_DELIVERY_WRITES))
    assert unmapped == [], f"delivery has write seams {unmapped} this test does not map"
    text = _delivery_paragraph().lower()
    missing = [s for s in sorted(seams) if not any(w in text for w in _DELIVERY_WRITES[s])]
    assert missing == [], f"the delivery paragraph does not say what {missing} write"
    assert _REDELIVERY_LEASE in source, "the re-delivery lease moved: re-read deliver()"
    assert "re-point" in text and "force-with-lease" in text, (
        "a re-delivery re-points the same branch with a force-with-lease push; the delivery "
        "paragraph does not say so"
    )


def test_the_git_remote_row_says_a_re_delivery_re_points_the_branch() -> None:
    row = next(r for r in _table_rows() if r[0].startswith("Repository clone and fetch"))
    assert "re-point" in row[2], row[2]
