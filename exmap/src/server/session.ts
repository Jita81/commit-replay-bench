// exmap/src/server/session.ts — Session: state, events, run(command), classify(utteranceId), subscribers, AbortController,
// broken flag (design §8.1, §8.4, §9).
//
// The server is the only writer: every change is engine.apply() → one fsynced append of the whole batch → subscribers
// notified synchronously in the same tick (so a WebSocket catch-up taken in one tick neither misses nor repeats an event).
// Writes run under the session's write mutex; classifications run one at a time on a separate serial chain, outside the
// write mutex, and take it only to append their outcome.
import { ClassifierError } from "../classifier/types.js";
import type { Engine } from "../core/index.js";
import type {
  ApplyContext, ApplyResult, BrokenInfo, ClassificationSummary, Classifier, ClassifierErrorInfo, ClassifierInput, ClassifierProposal,
  ClassifierStamp, Command, EventId, ExmapEvent, Intent, IsoTimestamp, MapState, Operation, Proposal, ProposalId, RefusedOperation,
  SessionMeta, Utterance, UtteranceId,
} from "../core/types.js";
import { bridgeProposal, buildClassifierInput, intentOf, voiceActor } from "./classifier-bridge.js";
import { HttpError, httpError } from "./errors.js";
import { JsonlLedger, LedgerWriteError } from "./ledger.js";
import { Mutex } from "./mutex.js";

/** A human act as a proposal (design §8.5): provider "human", the actor stamped, confidence 1, no source utterance. */
export function humanProposal(id: ProposalId, operation: Operation, actor: string, rationale: string): Proposal {
  return {
    id,
    intent: intentOf(operation.kind),
    operation,
    template: null,
    pending_operation: null,
    candidates: [],
    confidence: 1,
    needs_clarification: false,
    question: null,
    source_utterance_ids: [],
    classifier: { provider: "human", model: null, prompt_version: null, fallback_from: null, error: null, actor },
    resolves_clarification_id: null,
    rationale,
  };
}

export interface SessionSubscriber {
  /** Called synchronously after every append, with the whole batch. */
  onEvents(events: readonly ExmapEvent[]): void;
  /** The ledger could not be written; the session is broken (WebSocket: error frame + close 4009). */
  onBroken?(info: BrokenInfo): void;
  /** The session closed (server shutdown; WebSocket: close 1001). */
  onClose?(): void;
}

/** What one classification job did; `summary` is the ClassificationSummary of design §4 (for ?wait=1). */
export interface ClassificationOutcome {
  summary: ClassificationSummary;
  events: ExmapEvent[];
  proposal_ids: ProposalId[];
}

export interface SessionDeps {
  meta: SessionMeta;
  dir: string;
  ledger: JsonlLedger;
  engine: Engine;
  classifier: Classifier;
  now: () => IsoTimestamp;
  nextId: ApplyContext["nextId"];
  events: ExmapEvent[];
  state: MapState;
  /** After every ledgered classification (the app clears the claude provider's last_error on a non-fallback one). */
  onClassified?: (stamp: ClassifierStamp) => void;
  /** After a failed append (the store stops serving the session as open). */
  onBroken?: (session: Session, info: BrokenInfo) => void;
  /** A classification job failed unexpectedly (a bug, not a classifier outcome); the app logs it. */
  onJobError?: (e: unknown) => void;
}

function errorInfo(e: unknown): ClassifierErrorInfo {
  if (e instanceof ClassifierError) return { code: e.code, message: e.message };
  if (e instanceof Error && e.name === "AbortError") return { code: "aborted", message: e.message };
  return { code: "E_CLASSIFIER_FAILED", message: e instanceof Error ? e.message : String(e) };
}

const round2 = (n: number): number => Math.min(1, Math.max(0, Math.round(n * 100) / 100));

/** The events of `batch` that belong to proposal `pid` (made, its outcome, its clarification). */
function eventsOfProposal(events: readonly ExmapEvent[], pid: ProposalId): ExmapEvent[] {
  return events.filter((e) => {
    switch (e.type) {
      case "proposal.made":
        return e.proposal.id === pid;
      case "proposal.applied":
      case "proposal.rejected":
      case "proposal.confirmed":
      case "undo.applied":
      case "clarification.asked":
        return e.proposal_id === pid;
      default:
        return false;
    }
  });
}

export class Session {
  readonly id: string;
  readonly meta: SessionMeta;
  readonly dir: string;
  readonly ledger: JsonlLedger;
  readonly writeMutex = new Mutex();
  readonly #chain = new Mutex();
  readonly #deps: SessionDeps;
  readonly #abort = new AbortController();
  readonly #subs = new Set<SessionSubscriber>();
  readonly #seqOf = new Map<EventId, number>();
  #state: MapState;
  #events: ExmapEvent[];
  #closed = false;
  #broken: BrokenInfo | null = null;

  constructor(deps: SessionDeps) {
    this.#deps = deps;
    this.id = deps.meta.id;
    this.meta = deps.meta;
    this.dir = deps.dir;
    this.ledger = deps.ledger;
    this.#state = deps.state;
    this.#events = deps.events;
    for (const e of deps.events) this.#seqOf.set(e.id, e.seq);
  }

  get state(): MapState {
    return this.#state;
  }
  get events(): readonly ExmapEvent[] {
    return this.#events;
  }
  get broken(): BrokenInfo | null {
    return this.#broken;
  }
  get closed(): boolean {
    return this.#closed;
  }
  /** Aborted by close(); passed to every classify() call. */
  get signal(): AbortSignal {
    return this.#abort.signal;
  }
  seqOfEvent(id: EventId): number {
    return this.#seqOf.get(id) ?? 0;
  }
  now(): IsoTimestamp {
    return this.#deps.now();
  }
  nextId(prefix: Parameters<ApplyContext["nextId"]>[0]): string {
    return this.#deps.nextId(prefix);
  }
  /** Integer ms since the session's created_at (the audio clock's origin). */
  sessionMs(): number {
    const ms = Date.parse(this.#deps.now()) - Date.parse(this.meta.created_at);
    return Number.isFinite(ms) && ms > 0 ? Math.floor(ms) : 0;
  }

  /** Runs fn under the write mutex. Everything that appends goes through here. */
  exclusive<T>(fn: () => Promise<T> | T): Promise<T> {
    return this.writeMutex.run(fn);
  }

  /**
   * apply → append → notify, for a caller that already holds the write mutex. A refusal is returned; a broken session
   * throws 409 LEDGER_BROKEN; a failed append marks the session broken and throws 500 LEDGER_WRITE_FAILED with the
   * in-memory state untouched.
   */
  applyLocked(command: Command): ApplyResult {
    if (this.#broken) throw this.brokenError();
    const r = this.#deps.engine.apply(this.#state, command);
    if (!r.ok) return r;
    try {
      this.ledger.appendBatch(r.events);
    } catch (e) {
      const detail = e instanceof LedgerWriteError ? e.detail : e instanceof Error ? e.message : String(e);
      this.#markBroken({ code: "LEDGER_WRITE_FAILED", row: this.#events.length + 1, seq: this.#state.head.seq + 1, detail });
      throw httpError("LEDGER_WRITE_FAILED", detail);
    }
    this.#state = r.state;
    for (const e of r.events) {
      this.#events.push(e);
      this.#seqOf.set(e.id, e.seq);
    }
    for (const sub of [...this.#subs]) {
      try {
        sub.onEvents(r.events);
      } catch {
        /* a subscriber's failure never affects the append */
      }
    }
    return r;
  }

  /** run(command) under the write mutex (design §9). */
  run(command: Command): Promise<ApplyResult> {
    return this.exclusive(() => this.applyLocked(command));
  }

  brokenError(): HttpError {
    const b = this.#broken!;
    return httpError("LEDGER_BROKEN", b.detail, { row: b.row, seq: b.seq, code: b.code });
  }

  #markBroken(info: BrokenInfo): void {
    this.#broken = info;
    for (const sub of [...this.#subs]) {
      try {
        sub.onBroken?.(info);
      } catch {
        /* ignore */
      }
    }
    this.#deps.onBroken?.(this, info);
  }

  subscribe(sub: SessionSubscriber | ((events: readonly ExmapEvent[]) => void)): () => void {
    const s: SessionSubscriber = typeof sub === "function" ? { onEvents: sub } : sub;
    this.#subs.add(s);
    return () => {
      this.#subs.delete(s);
    };
  }

  get subscriberCount(): number {
    return this.#subs.size;
  }

  /**
   * Enqueues the classification of a recorded utterance on the serial chain (synchronously, so a caller holding the write
   * mutex fixes the order). The promise never rejects; it resolves null when nothing was ledgered (session closed or
   * broken, or the utterance unknown).
   */
  classify(utteranceId: UtteranceId): Promise<ClassificationOutcome | null> {
    return this.#chain.run(() => this.#classifyJob(utteranceId)).catch((e: unknown) => {
      this.#deps.onJobError?.(e);
      return null;
    });
  }

  /** Resolves once every classification queued so far has finished. */
  classificationsIdle(): Promise<void> {
    return this.#chain.idle();
  }

  /** Builds the input and calls the classifier; a throw from either is an error outcome, never a lost utterance. */
  async #callClassifier(build: () => ClassifierInput): Promise<{ p: ClassifierProposal | null; error: ClassifierErrorInfo | null }> {
    try {
      return { p: await this.#deps.classifier.classify(build(), { signal: this.#abort.signal }), error: null };
    } catch (e) {
      return { p: null, error: errorInfo(e) };
    }
  }

  #resolvesOpen(p: ClassifierProposal): boolean {
    const r = p.resolves;
    if (!r) return true;
    return this.#state.clarification_order.some((id) => {
      const c = this.#state.clarifications[id];
      return c !== undefined && c.status === "open" && c.proposal_id === r.proposal_id;
    });
  }

  async #classifyJob(utteranceId: UtteranceId): Promise<ClassificationOutcome | null> {
    if (this.#closed || this.#broken) return null;
    const utterance = this.#state.utterances.find((u) => u.id === utteranceId);
    if (!utterance) return null;
    let { p, error } = await this.#callClassifier(() => buildClassifierInput(this, utterance));
    let reran = false;
    for (;;) {
      if (this.#closed || this.#abort.signal.aborted) return null;
      const result = await this.exclusive((): { stale: true } | { outcome: ClassificationOutcome | null } => {
        if (this.#closed || this.#broken) return { outcome: null };
        // stale-answer guard (design §8.4 step 4c): the clarification this answers was resolved or dismissed meanwhile
        if (p && !reran && !this.#resolvesOpen(p)) return { stale: true };
        return { outcome: this.#ledgerOutcome(utterance, p, error) };
      }).catch((e: unknown) => {
        if (e instanceof HttpError) return { outcome: null }; // the session broke while appending
        throw e;
      });
      if ("outcome" in result) return result.outcome;
      reran = true;
      ({ p, error } = await this.#callClassifier(() => ({ ...buildClassifierInput(this, utterance), pending_clarification: null })));
    }
  }

  /** Under the write mutex: the bridge's commands in order (refusals collected), then one classification.record. */
  #ledgerOutcome(utterance: Utterance, p: ClassifierProposal | null, error: ClassifierErrorInfo | null): ClassificationOutcome | null {
    const refused: RefusedOperation[] = [];
    const proposalIds: ProposalId[] = [];
    const runEvents: ExmapEvent[] = [];
    if (p) {
      let bridged: ReturnType<typeof bridgeProposal>;
      try {
        bridged = bridgeProposal(p, this.#state, utterance, { nextId: this.#deps.nextId, actorForVoice: voiceActor });
      } catch (e) {
        // a bridge failure is a bug, but the utterance is still classified — as an error, never silently
        error = { code: "E_BRIDGE_FAILED", message: e instanceof Error ? e.message : String(e) };
        bridged = { commands: [], refused: [] };
      }
      refused.push(...bridged.refused);
      for (const command of bridged.commands) {
        if (command.kind === "proposal.propose") {
          this.#proposeWithRetry(command.proposals, refused, proposalIds, runEvents);
          continue;
        }
        const r = this.applyLocked(command);
        if (r.ok) runEvents.push(...r.events);
        else refused.push({ operation: "unknown", reason: r.reason, detail: `${command.kind}: ${r.detail}` });
      }
    }
    const stamp: ClassifierStamp = p
      ? { ...p.classifier, actor: null }
      : { provider: this.#deps.classifier.provider, model: null, prompt_version: null, fallback_from: null, error: null, actor: null };
    const cited = proposalIds.filter((id) => this.#state.proposals[id]?.proposal.source_utterance_ids.includes(utterance.id));
    const intent: Intent | "none" = p ? p.intent : "none";
    const record: Extract<Command, { kind: "classification.record" }> = {
      kind: "classification.record",
      utterance_id: utterance.id,
      intent,
      heard_intent: p && intent === "none" ? p.heard_intent : null,
      classifier: stamp,
      confidence: p ? round2(p.confidence) : 0,
      rationale: p && !error ? p.rationale : `The classifier failed (${error?.code ?? "unknown"}); nothing was proposed.`,
      proposal_ids: error ? [] : cited,
      refused,
      error,
    };
    let r = this.applyLocked(record);
    if (!r.ok) {
      // the classifier's own figures were refused by core (a malformed stamp or confidence): ledger that as the error
      const fallback: Extract<Command, { kind: "classification.record" }> = {
        ...record,
        intent: "none",
        heard_intent: null,
        classifier: { provider: this.#deps.classifier.provider, model: null, prompt_version: null, fallback_from: null, error: null, actor: null },
        confidence: 0,
        rationale: "The classifier's result could not be recorded; nothing was proposed.",
        proposal_ids: [],
        error: { code: "E_CLASSIFICATION_REFUSED", message: `${r.reason}: ${r.detail}` },
      };
      r = this.applyLocked(fallback);
      if (!r.ok) return null;
      Object.assign(record, fallback);
    }
    runEvents.push(...r.events);
    this.#deps.onClassified?.(record.classifier);
    const classified = r.events[r.events.length - 1]!;
    return {
      events: runEvents,
      proposal_ids: record.proposal_ids,
      summary: {
        event: { id: classified.id, seq: classified.seq },
        intent: record.intent,
        heard_intent: record.heard_intent,
        classifier: record.classifier,
        confidence: record.confidence,
        rationale: record.rationale,
        proposals: record.proposal_ids.map((pid) => {
          const mine = eventsOfProposal(runEvents, pid);
          const asked = mine.find((e): e is Extract<ExmapEvent, { type: "clarification.asked" }> => e.type === "clarification.asked");
          return {
            proposal_id: pid,
            status: this.#state.proposals[pid]?.status ?? "pending",
            clarification_id: asked?.clarification_id ?? null,
            events: mine.map((e) => ({ id: e.id, seq: e.seq, type: e.type })),
          };
        }),
        refused,
        error: record.error,
      },
    };
  }

  /**
   * proposal.propose is all or nothing; when one proposal of several is refused, it is recorded in `refused` and the rest
   * are proposed again as one batch (a refused prefix never takes the main operation down with it). If the dropped
   * proposal was the one resolving a clarification, the next one carries the resolution.
   */
  #proposeWithRetry(proposals: Proposal[], refused: RefusedOperation[], ids: ProposalId[], out: ExmapEvent[]): void {
    let batch = [...proposals];
    while (batch.length > 0) {
      const r = this.applyLocked({ kind: "proposal.propose", proposals: batch });
      if (r.ok) {
        ids.push(...batch.map((x) => x.id));
        out.push(...r.events);
        return;
      }
      const m = /^proposal (\d+) of (\d+): /.exec(r.detail);
      const index = m && batch.length > 1 ? Number(m[1]) - 1 : 0;
      const failed = batch[index]!;
      refused.push({ operation: failed.operation?.kind ?? failed.template?.kind ?? failed.pending_operation?.kind ?? "unknown", reason: r.reason, detail: r.detail });
      if (!m || batch.length === 1) {
        // a refusal not tied to one proposal: every remaining proposal is refused with it
        for (const other of batch) {
          if (other === failed) continue;
          refused.push({ operation: other.operation?.kind ?? other.template?.kind ?? other.pending_operation?.kind ?? "unknown", reason: r.reason, detail: r.detail });
        }
        return;
      }
      const rest = batch.filter((_, i) => i !== index);
      if (failed.resolves_clarification_id !== null && rest[0] && rest[0].resolves_clarification_id === null && index === 0) {
        rest[0] = { ...rest[0], resolves_clarification_id: failed.resolves_clarification_id };
      }
      batch = rest;
    }
  }

  /** Stops classification (aborts the in-flight call; queued jobs never run), waits for in-flight appends, tells subscribers. */
  async close(): Promise<void> {
    if (this.#closed) return;
    this.#closed = true;
    this.#abort.abort();
    await this.writeMutex.idle();
    for (const sub of [...this.#subs]) {
      try {
        sub.onClose?.();
      } catch {
        /* ignore */
      }
    }
    this.#subs.clear();
  }
}
