"""RED proof — the authored test must FAIL on the base before anything is built.

Forward mode has no held-out test, so the factory manufactures the oracle
first: a test file authored by the operator, or — on the
``test_first_authoring`` route — by a *test author* rung that is a different
identity from every builder that will build the source. The proof is mechanical:

1. a fresh worktree at the repository HEAD (no commit parent — the work does not
   exist yet), with the repo's post-create fixups applied;
2. the authored test written in, and only it; the runner's target scope for it
   is run;
3. the run must be RED **with attributable failing ids**. A green run means the
   test does not test the change (:class:`NotRed`); a timeout or an
   unattributed failure (collection crash the runner could not parse) is a
   harness problem, not a proof, and is refused too — fail closed;
4. the test file's SHA-256 is recorded. That hash is the immutable oracle for
   the build: :mod:`crb.factory.build` stages the same bytes as a throwaway
   commit, so belt 1 (``tests_unmodified``) is the real belt 1, and the
   reviewer re-runs this exact proof from a pristine worktree.

Identity separation is enforced here: :func:`assert_distinct_identity` compares
rung labels (``builder:model``) and refuses a build whose builder authored the
oracle it is graded against.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from crb.core.evidence import utc_now_iso
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace
from crb.factory.backlog import BacklogItem

EventFn = Callable[[str, Mapping[str, Any]], None]

RED_PROOF_SCHEMA = "crb.factory.red_proof.v1"

#: Identity prefix for a human-authored oracle (never collides with a rung label,
#: which is ``<builder>:<model>``).
OPERATOR_AUTHOR_PREFIX = "operator:"


class NotRed(ValueError):
    """The authored test is not a proof: green at base, timed out, or unattributable."""


class SameIdentityError(ValueError):
    """The identity that authored the oracle would also build (or review) against it."""


def assert_distinct_identity(author: str, other: str, *, role: str = "builder") -> None:
    """Refuse when ``author`` (the test author's identity) equals ``other``'s.

    Labels are ``builder:model`` rung labels or ``operator:<name>``; comparison is
    exact after whitespace/case normalisation so ``Editblock:GPT`` cannot slip past
    ``editblock:gpt``.
    """
    a = author.strip().lower()
    b = other.strip().lower()
    if not a or not b:
        raise SameIdentityError("both identities must be non-empty rung labels")
    if a == b:
        raise SameIdentityError(
            f"the {role} {other!r} is the identity that authored the oracle — "
            "the test author must never build or review against its own test"
        )


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


@dataclass(frozen=True)
class AuthoredTest:
    """An oracle authored for one item: repo-relative path, exact content, and the
    identity that wrote it (``operator:<name>`` or a rung label)."""

    path: str
    content: str
    author: str

    def __post_init__(self) -> None:
        if (
            not self.path.strip()
            or self.path.startswith(("/", ".."))
            or ".." in self.path.split("/")
        ):
            raise ValueError(f"authored test path must be repo-relative, got {self.path!r}")
        if not self.author.strip():
            raise ValueError("an authored test must name its author identity")
        if not self.content.strip():
            raise ValueError("an authored test cannot be empty")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def operator_authored(self) -> bool:
        return self.author.startswith(OPERATOR_AUTHOR_PREFIX)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "author": self.author}


@dataclass(frozen=True)
class RedProof:
    """The recorded proof that the authored test fails on the base."""

    item_id: str
    test_path: str
    test_sha256: str
    failing_ids: tuple[str, ...]
    runner: str
    executor: Mapping[str, Any]
    base_sha: str
    target_scope: tuple[str, ...]
    author: str
    returncode: int = 1
    tail: str = ""
    existed_at_base: bool = False
    duration_s: float = 0.0
    created: str = ""
    schema: str = RED_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if not self.failing_ids:
            raise NotRed("a RED proof must carry at least one failing test id")
        object.__setattr__(self, "failing_ids", tuple(self.failing_ids))
        object.__setattr__(self, "target_scope", tuple(self.target_scope))
        object.__setattr__(self, "executor", dict(self.executor))
        object.__setattr__(self, "tail", redact_and_cap(self.tail, max_chars=2000))
        if not self.created:
            object.__setattr__(self, "created", utc_now_iso())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "item_id": self.item_id,
            "test_path": self.test_path,
            "test_sha256": self.test_sha256,
            "failing_ids": list(self.failing_ids),
            "runner": self.runner,
            "executor": dict(self.executor),
            "base_sha": self.base_sha,
            "target_scope": list(self.target_scope),
            "author": self.author,
            "returncode": self.returncode,
            "tail": self.tail,
            "existed_at_base": self.existed_at_base,
            "duration_s": round(self.duration_s, 3),
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RedProof:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def worktree_at(
    repo: GitRepo, ref: str, dest: Path, *, config: RepoConfig | None = None
) -> Workspace:
    """A forward-mode worktree checked out AT ``ref`` (see :meth:`Workspace.at_ref`)."""
    return Workspace.at_ref(repo, ref, dest, config=config)


def write_authored(ws: Workspace, authored: AuthoredTest) -> Path:
    p = ws.root / authored.path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(authored.content, encoding="utf-8")
    return p


def prove_red(
    repo: GitRepo,
    item: BacklogItem,
    authored: AuthoredTest,
    *,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    base_ref: str = "HEAD",
    timeout: int = 0,
    on_event: EventFn | None = None,
) -> RedProof:
    """Write ``authored`` into a fresh worktree at ``base_ref`` and require RED.

    Raises :class:`NotRed` (green, timeout, unattributable, malformed oracle, or a
    path the repo config does not classify as a test) and
    :class:`SandboxUnavailable` (infrastructure). Never returns a proof it did not
    observe.
    """
    started = time.monotonic()
    if not config.is_test(authored.path):
        raise NotRed(
            f"{authored.path!r} is not a test path for repo {config.name!r} — "
            "the oracle must live where the repo keeps its tests"
        )
    head = repo.rev_parse(base_ref)
    dest = Path(scratch) / f"red-{config.name}-{item.id}-{head[:10]}"
    _emit(on_event, "red.start", item=item.id, base=head, path=authored.path)
    ws = worktree_at(repo, head, dest, config=config)
    try:
        existed = ws.exists(authored.path)
        write_authored(ws, authored)
        if not runner.is_valid_oracle(ws.root, authored.path):
            raise NotRed(f"{authored.path!r} is a malformed oracle (defines no tests)")
        scope = runner.target_scope([authored.path])
        try:
            run = runner.run(executor, ws.root, scope, timeout=timeout)
        except SandboxUnavailable:
            raise
        except Exception as exc:  # a harness error is never a proof
            raise NotRed(f"harness error while proving RED: {type(exc).__name__}: {exc}") from exc
        if run.timed_out:
            raise NotRed("target timed out at base — not a RED proof (fail closed)")
        if run.green:
            raise NotRed(
                f"{authored.path!r} is GREEN at base — it does not test the change; refused"
            )
        if run.parse_error or not run.failing:
            raise NotRed(
                "target failed without attributable test ids "
                f"({run.parse_error or 'no failing ids parsed'}) — a harness problem, not a proof"
            )
        proof = RedProof(
            item_id=item.id,
            test_path=authored.path,
            test_sha256=authored.sha256,
            failing_ids=tuple(sorted(run.failing)),
            runner=runner.name,
            executor=executor.describe(),
            base_sha=head,
            target_scope=scope,
            author=authored.author,
            returncode=run.returncode,
            tail=run.tail,
            existed_at_base=existed,
            duration_s=time.monotonic() - started,
        )
        _emit(
            on_event,
            "red.proved",
            item=item.id,
            path=authored.path,
            sha256=proof.test_sha256,
            failing=len(proof.failing_ids),
        )
        return proof
    except NotRed as exc:
        _emit(on_event, "red.refused", item=item.id, path=authored.path, reason=str(exc))
        raise
    finally:
        ws.remove()


# ---------------------------------------------------------------------------
# Test authoring (the ``test_first_authoring`` route)
# ---------------------------------------------------------------------------


@runtime_checkable
class TestAuthor(Protocol):
    """Authors an oracle for an item. A DIFFERENT identity from every build rung.

    The builder contract (:class:`crb.builders.base.Builder`) cannot author tests —
    its guards refuse every test-path write by design — so test authoring is its
    own small protocol. The result is proven RED by :func:`prove_red` before it is
    trusted; the author's own claim is never a verdict.
    """

    name: str
    model: str
    provider: str

    def author(
        self,
        workspace: Workspace,
        item: BacklogItem,
        *,
        facts: Mapping[str, str],
        config: RepoConfig,
        on_event: EventFn | None = None,
    ) -> AuthoredTest: ...

    def describe(self) -> dict[str, Any]: ...


def author_label(author: TestAuthor) -> str:
    return f"{author.name}:{author.model}"


@dataclass(frozen=True)
class AuthoringResult:
    authored: AuthoredTest
    author: str
    duration_s: float
    described: Mapping[str, Any] = field(default_factory=dict)


def author_test(
    repo: GitRepo,
    item: BacklogItem,
    author: TestAuthor,
    *,
    facts: Mapping[str, str],
    config: RepoConfig,
    scratch: Path,
    base_ref: str = "HEAD",
    on_event: EventFn | None = None,
) -> AuthoringResult:
    """Run a test author in a fresh worktree at ``base_ref``; return what it wrote.

    The worktree is disposable and removed afterwards — the authored content is
    carried as bytes and proven RED separately in *another* fresh worktree, so a
    stray source edit by the author can never leak into the proof.
    """
    started = time.monotonic()
    head = repo.rev_parse(base_ref)
    dest = Path(scratch) / f"author-{config.name}-{item.id}-{head[:10]}"
    ws = worktree_at(repo, head, dest, config=config)
    try:
        _emit(on_event, "author.start", item=item.id, author=author_label(author))
        authored = author.author(ws, item, facts=facts, config=config, on_event=on_event)
        authored = AuthoredTest(authored.path, authored.content, author_label(author))
        _emit(
            on_event,
            "author.done",
            item=item.id,
            author=authored.author,
            path=authored.path,
            sha256=authored.sha256,
        )
        return AuthoringResult(
            authored, authored.author, time.monotonic() - started, author.describe()
        )
    finally:
        ws.remove()


__all__ = [
    "OPERATOR_AUTHOR_PREFIX",
    "RED_PROOF_SCHEMA",
    "AuthoredTest",
    "AuthoringResult",
    "NotRed",
    "RedProof",
    "SameIdentityError",
    "TestAuthor",
    "assert_distinct_identity",
    "author_label",
    "author_test",
    "prove_red",
    "worktree_at",
    "write_authored",
]
