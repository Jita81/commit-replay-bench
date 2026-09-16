"""Single-shot SEARCH/REPLACE builder for cheap models (the census "thin" process).

The model is shown the brief plus a handful of source files it is *likely* to
need — chosen by name heuristics from the subject and (sighted) the target
tests' imports; never by the task's ``src_files``, which the builder is not
told — and asked for ``<<<<<<< SEARCH … ======= … >>>>>>> REPLACE`` blocks. The
parser is tolerant (marker width, whitespace, CRLF) and the applier tries an
exact then a whitespace-insensitive match, because that is what the bring-up
measured cheap models actually emit. An edit that does not apply, or that
leaves a Python file un-compilable, is fed back as ``prior_failure`` for the
next attempt (up to ``budget.max_turns``). The held-out tests are **never** run
by this builder: the only feedback is apply/compile.

The model call goes through an injected ``chat_fn(messages) -> str | ChatReply``
seam; the OpenAI-compatible default lives in :mod:`crb.builders.openai_client`.

Navigation
----------
What it is:   The cheapest builder — ``EditBlockBuilder`` — and its pure parts: the tolerant
              SEARCH/REPLACE parser, the fuzzy applier, the Python compile check and the
              name-overlap file chooser.
What it does: Shows a model a few likely source files (never the task's ``src_files``) and
              applies the edit blocks it returns through the ``TestFileGuard``; retries with
              the apply/compile failure as feedback up to ``max_turns``; never runs the
              tests. A refused write or an un-compilable result is feedback, not a pass.
How:          ``candidate_source_files`` → ``build_messages`` → ``chat_fn`` →
              ``parse_file_edit_blocks`` → ``apply_edit_blocks`` (exact, then
              indentation-insensitive with re-indent) → ``compile_check`` → write via
              ``guard.resolve_write`` → outcome with the meter's totals.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/base.py (brief, budget, outcome, ``TestFileGuard``),
              src/crb/builders/openai_client.py (the default ``chat_fn``),
              src/crb/builders/budget.py (``BudgetTracker``/``CostMeter``),
              src/crb/builders/openai_agent.py (the agentic sibling on the same client),
              src/crb/builders/__init__.py (registered as ``"editblock"``)
Tested by:    tests/test_builders_editblock.py
Touch when:   never for a new repository; a marker shape a model emits that the parser
              drops is a parser test first (the strict regex once silently dropped valid
              edits); a language other than Python that needs a compile check extends
              ``compile_check``.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from crb.builders.base import (
    STOP_DONE,
    STOP_MODEL_ERROR,
    Budget,
    BuildBrief,
    BuildOutcome,
    EventFn,
    GuardRefused,
    TestFileGuard,
    emit,
)
from crb.builders.budget import BudgetTracker, CostMeter, price_for
from crb.builders.openai_client import ChatFn, ChatReply, EndpointConfig, make_chat
from crb.core.redact import redact_and_cap
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace

# ---------------------------------------------------------------------------
# Pure: tolerant SEARCH/REPLACE parsing (ported from the census commit_replay)
# ---------------------------------------------------------------------------

_SEARCH_RE = re.compile(r"^\s*<{5,}\s*SEARCH\b")
_DIVIDER_RE = re.compile(r"^\s*={5,}\s*$")
_REPLACE_RE = re.compile(r"^\s*>{5,}\s*REPLACE\b")
_FILE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?FILE:\s*`?([^`\s]+)`?\s*$")


def parse_edit_blocks(text: str) -> list[tuple[str, str]]:
    """Parse SEARCH/REPLACE blocks, tolerant of the markers the model actually
    emits — any run of >=5 of the marker char, surrounding whitespace, a bare
    ``====`` divider line, and CRLF. (A strict regex silently dropped valid edits.)"""
    return [(s, r) for _, s, r in parse_file_edit_blocks(text, default_path="")]


def parse_file_edit_blocks(text: str, *, default_path: str) -> list[tuple[str, str, str]]:
    """Like :func:`parse_edit_blocks` but each block carries the path it targets.

    A ``FILE: path`` line (optionally a markdown heading) before a block sets the
    path for the blocks that follow; blocks before any header go to
    ``default_path``. Returns ``(path, search, replace)`` triples.
    """
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    blocks: list[tuple[str, str, str]] = []
    current = default_path
    i = 0
    while i < len(lines):
        m = _FILE_RE.match(lines[i])
        if m:
            current = m.group(1).strip()
            i += 1
            continue
        if _SEARCH_RE.match(lines[i]):
            i += 1
            search: list[str] = []
            while i < len(lines) and not _DIVIDER_RE.match(lines[i]):
                search.append(lines[i])
                i += 1
            i += 1  # skip the ==== divider
            repl: list[str] = []
            while i < len(lines) and not _REPLACE_RE.match(lines[i]):
                repl.append(lines[i])
                i += 1
            i += 1  # skip the >>>> end marker
            blocks.append((current, "\n".join(search), "\n".join(repl)))
        else:
            i += 1
    return blocks


# ---------------------------------------------------------------------------
# Pure: fuzzy apply
# ---------------------------------------------------------------------------


def _find_window(lines: list[str], search: list[str], key: Callable[[str], str]) -> int:
    """First index where ``search`` matches ``lines`` under ``key``, or ``-1``."""
    for i in range(len(lines) - len(search) + 1):
        if all(key(lines[i + j]) == key(search[j]) for j in range(len(search))):
            return i
    return -1


def _leading_ws(line: str) -> str:
    """The indentation prefix of a line."""
    return line[: len(line) - len(line.lstrip())]


def apply_edit_blocks(src: str, blocks: Iterable[tuple[str, str]]) -> tuple[str, int]:
    """Apply each block by locating its SEARCH lines and substituting REPLACE.
    Tries an exact match (trailing-ws-insensitive) then a fuzzy match (ignoring
    leading indentation, since the model sometimes re-indents). On a fuzzy match
    the REPLACE lines are re-indented by the same offset the SEARCH lines were
    off by, so a consistently mis-indented block still lands correctly. Returns
    the new source and how many blocks applied."""
    lines = src.split("\n")
    applied = 0
    for search, repl in blocks:
        sl = search.split("\n")
        while sl and sl[-1].strip() == "":
            sl.pop()
        if not sl:
            continue
        rl = repl.split("\n")
        i = _find_window(lines, sl, lambda x: x.rstrip())
        if i < 0:
            i = _find_window(lines, sl, lambda x: x.strip())
            if i >= 0:
                want, got = _leading_ws(lines[i]), _leading_ws(sl[0])
                if want != got:
                    rl = [want + ln[len(got) :] if ln.startswith(got) else ln for ln in rl]
        if i >= 0:
            lines[i : i + len(sl)] = rl
            applied += 1
    return "\n".join(lines), applied


def compile_check(path: str, src: str) -> tuple[bool, str]:
    """A ``.py`` edit must compile. The fuzzy apply can mis-splice an edit into
    syntactically-broken code; running it would error the WHOLE suite (a collection
    failure), masking a mere attempt failure as a catastrophe. Non-py → ok."""
    if not path.endswith(".py"):
        return True, ""
    try:
        compile(src, path, "exec")
    except SyntaxError as e:
        return False, f"{e.msg} at line {e.lineno}"
    return True, ""


# ---------------------------------------------------------------------------
# File selection (name heuristics only — never the task's src_files)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "to",
        "of",
        "in",
        "on",
        "with",
        "from",
        "add",
        "fix",
        "feat",
        "chore",
        "refactor",
        "test",
        "tests",
        "docs",
        "update",
        "remove",
        "support",
        "use",
        "when",
        "make",
        "allow",
        "handle",
        "bug",
        "issue",
        "pr",
    }
)
_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def _tokens(text: str) -> set[str]:
    """Lower-cased identifier parts (camelCase and snake_case split), stop words dropped."""
    out: set[str] = set()
    for w in _WORD_RE.findall(text):
        for part in re.split(r"(?<=[a-z])(?=[A-Z])|_", w):
            p = part.lower()
            if len(p) >= 3 and p not in _STOP:
                out.add(p)
    return out


def candidate_source_files(
    ws: Workspace,
    config: RepoConfig,
    *,
    subject: str,
    test_files: Sequence[str] = (),
    max_files: int = 3,
) -> list[str]:
    """Rank tracked source files by name overlap with the subject and, in sighted
    mode, by the modules the target tests import. Deterministic; capped."""
    tracked = ws.repo.run("ls-files", cwd=ws.root).lines
    sources = [f for f in tracked if config.is_src(f) and not config.is_test(f)]
    if not sources:
        sources = [
            f
            for f in tracked
            if f.endswith(config.ext) and not config.is_test(f) and ".git/" not in f
        ]
    want = _tokens(subject)
    imported: set[str] = set()
    for tf in test_files:
        want |= _tokens(Path(tf).stem.removeprefix("test_").removesuffix("_test"))
        try:
            text = ws.read(tf)
        except OSError:
            continue
        for m in _IMPORT_RE.finditer(text):
            mod = (m.group(1) or m.group(2) or "").replace(".", "/")
            if mod:
                imported.add(mod)
    scored: list[tuple[float, str]] = []
    for f in sources:
        stem = f.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        toks = _tokens(f.replace("/", " "))
        score = float(len(toks & want)) * 2.0
        if stem in want:
            score += 3.0
        base = f.rsplit(".", 1)[0]
        for mod in imported:
            if base == mod or base.startswith(mod + "/") or base == mod + "/__init__":
                score += 4.0
        if stem == "__init__":
            score -= 0.5
        scored.append((-score, f))
    scored.sort()
    return [f for s, f in scored[:max_files] if s < 0] or [f for _, f in scored[:1]]


# ---------------------------------------------------------------------------
# Prompt (the upstream shape, extended with FILE headers for multi-file edits)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior engineer reproducing a code change from its description.
Reply with ONLY SEARCH/REPLACE blocks. For each file you change, first write a line `FILE: <path>`
then one or more blocks:

<<<<<<< SEARCH
<exact lines copied verbatim from the current file>
=======
<replacement lines>
>>>>>>> REPLACE

Rules: the SEARCH text must be copied EXACTLY (including indentation) from the file as shown.
Keep edits minimal and idiomatic. Never touch test files. To create a new file, use an empty SEARCH
section with the full file body as REPLACE. No prose, no explanations."""


def build_messages(
    brief: BuildBrief,
    files: dict[str, str],
    tests: dict[str, str],
    prior_failure: str | None,
) -> list[dict[str, Any]]:
    """The chat messages: task text, the (read-only) target tests, the candidate sources,
    and the previous attempt's failure when retrying."""
    parts = [brief.task_text()]
    if tests:
        parts.append("\nThe target tests (executable spec — read-only):")
        for path, text in tests.items():
            parts.append(f"\n--- {path} ---\n{text}")
    parts.append("\nCurrent source files (edit these with SEARCH/REPLACE blocks):")
    for path, text in files.items():
        parts.append(f"\n--- {path} ---\n{text}")
    if prior_failure:
        parts.append(f"\nYOUR PREVIOUS ATTEMPT FAILED: {prior_failure}\nTry again.")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class EditBlockBuilder:
    """One-shot (with bounded retries) SEARCH/REPLACE builder."""

    name = "editblock"

    def __init__(
        self,
        *,
        model: str,
        provider: str = "",
        chat_fn: ChatFn | None = None,
        endpoint: EndpointConfig | None = None,
        max_files: int = 3,
        max_file_chars: int = 40_000,
        keep_transcript: bool = False,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.provider = provider or (endpoint.provider if endpoint else "cerebras")
        self._chat_fn = chat_fn
        self.max_files = max_files
        self.max_file_chars = max_file_chars
        self.keep_transcript = keep_transcript

    def describe(self) -> dict[str, Any]:
        """The apparatus stamp."""
        return {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "process": "one-shot search/replace, compile-only feedback",
            "max_files": self.max_files,
        }

    def _chat(self) -> ChatFn:
        """The chat callable, built lazily so construction needs no credential."""
        if self._chat_fn is not None:
            return self._chat_fn
        chat = make_chat(self.model, self.endpoint)  # needs the openai extra + credential
        self._chat_fn = chat.text
        return self._chat_fn

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome:
        """Up to ``budget.max_turns`` chat → parse → apply → compile rounds; stops on the
        first fully applied, compilable edit set or the first budget cap."""
        started = time.monotonic()
        config = brief.repo_config()
        guard = TestFileGuard(workspace.root, config, brief.test_files, mode=brief.mode)
        meter = CostMeter(price_for(self.model), model=self.model)
        tracker = BudgetTracker(budget, meter)
        transcript: list[dict[str, Any]] = []
        errors: list[str] = []
        base: dict[str, Any] = {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "mode": brief.mode,
            "budget": budget,
        }

        def finish(*, done: bool, summary: str, stop: str, attempts: int) -> BuildOutcome:
            tampered = guard.tampered(workspace)
            if tampered:
                errors.append("tamper: test files modified: " + ", ".join(tampered[:10]))
            return BuildOutcome(
                **base,
                done=done and not tampered,
                summary=summary,
                turns=tracker.turns,
                tool_calls=0,
                tokens_in=meter.tokens_in,
                tokens_out=meter.tokens_out,
                cost_usd=meter.cost_usd,
                cost_known=meter.cost_known,
                latency_s=time.monotonic() - started,
                attempts=attempts,
                stop_reason=stop,
                errors=tuple(errors),
                transcript=tuple(transcript),
            )

        try:
            chat = self._chat()
        except Exception as exc:  # missing extra / credential — a recorded non-pass
            errors.append(f"model_error: {type(exc).__name__}: {exc}")
            return finish(done=False, summary="", stop=STOP_MODEL_ERROR, attempts=0)

        chosen = candidate_source_files(
            workspace,
            config,
            subject=brief.subject,
            test_files=brief.test_files,
            max_files=self.max_files,
        )
        files = {f: workspace.read(f)[: self.max_file_chars] for f in chosen}
        tests = {t: workspace.read(t)[: self.max_file_chars] for t in brief.test_files}
        emit(on_event, "build.start", builder=self.name, model=self.model, files=chosen)

        prior: str | None = None
        attempt = 0
        while True:
            reason = tracker.exceeded()
            if reason:
                return finish(done=False, summary=prior or "", stop=reason, attempts=attempt)
            attempt += 1
            tracker.note_turn()
            # re-read files so a partial earlier write is what the model sees
            files = {f: workspace.read(f)[: self.max_file_chars] for f in files}
            messages = build_messages(brief, files, tests, prior)
            try:
                reply = chat(messages)
            except Exception as exc:
                errors.append(f"model_error: {type(exc).__name__}: {exc}")
                return finish(done=False, summary="", stop=STOP_MODEL_ERROR, attempts=attempt)
            text = reply.text if isinstance(reply, ChatReply) else str(reply)
            if isinstance(reply, ChatReply):
                meter.add(
                    reply.tokens_in,
                    reply.tokens_out,
                    cached_in=reply.cached_in,
                    cost_usd=reply.cost_usd,
                )
            else:
                meter.add(0, 0)
            default_path = chosen[0] if chosen else ""
            blocks = parse_file_edit_blocks(text, default_path=default_path)
            event: dict[str, Any] = {"kind": "attempt", "attempt": attempt, "blocks": len(blocks)}
            if self.keep_transcript:
                event["reply"] = redact_and_cap(text, max_chars=8000)
            transcript.append(event)
            emit(on_event, "build.attempt", attempt=attempt, blocks=len(blocks))

            if not blocks:
                prior = "No SEARCH/REPLACE blocks were found in your reply. Reply with blocks only."
                continue

            # Stage every edit; the attempt is atomic — all apply + compile, or none is written.
            staged: dict[str, str] = {}
            failure = ""
            for path, search, repl in blocks:
                p = path or default_path
                refused = guard.check_write(p)
                if refused:
                    failure = refused
                    break
                current = staged.get(p)
                if current is None:
                    current = workspace.read(p) if workspace.exists(p) else ""
                if not search.strip() and not workspace.exists(p):
                    new_src = repl
                    applied = 1
                else:
                    new_src, applied = apply_edit_blocks(current, [(search, repl)])
                if not applied:
                    failure = f"Your edit to {p} did not apply — copy the SEARCH lines verbatim from the file."
                    break
                ok, syntax_err = compile_check(p, new_src)
                if not ok:
                    failure = (
                        f"Your edit to {p} produced INVALID PYTHON ({syntax_err}) — fix the syntax; "
                        "copy SEARCH lines exactly."
                    )
                    break
                staged[p] = new_src
            if failure:
                prior = failure
                transcript[-1]["failure"] = redact_and_cap(failure, max_chars=500)
                continue
            try:
                for p, new_src in staged.items():
                    target = guard.resolve_write(p)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(new_src, encoding="utf-8")
            except GuardRefused as exc:  # cannot happen after check_write, kept as a belt
                errors.append(f"guard: {exc}")
                return finish(done=False, summary=str(exc), stop=STOP_MODEL_ERROR, attempts=attempt)
            summary = f"applied {len(blocks)} block(s) to {', '.join(sorted(staged))}"
            emit(on_event, "build.applied", attempt=attempt, files=sorted(staged))
            return finish(done=True, summary=summary, stop=STOP_DONE, attempts=attempt)


__all__ = [
    "SYSTEM_PROMPT",
    "EditBlockBuilder",
    "apply_edit_blocks",
    "build_messages",
    "candidate_source_files",
    "compile_check",
    "parse_edit_blocks",
    "parse_file_edit_blocks",
]
