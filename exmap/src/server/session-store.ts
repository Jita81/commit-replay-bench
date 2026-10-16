// exmap/src/server/session-store.ts — SessionStore: create / list / open (cached) / summaryOf; broken-ledger reporting
// (design §8.1, §9). Open = read meta.json, read events.jsonl, replay and verify the whole chain; a broken chain refuses to
// open with the row it broke at, is never cached as open and never written to; its summary is computed from the readable
// prefix. A session whose append failed stays broken (409 LEDGER_BROKEN) until the server restarts and re-reads the file.
import fs from "node:fs";
import { join } from "node:path";
import { createRulesClassifier } from "../classifier/rules-v1.js";
import { createEngine, initialState, isHumanVerified, select, type Engine } from "../core/index.js";
import type {
  ApplyContext, BrokenInfo, Classifier, ClassifierStamp, ExmapEvent, IsoTimestamp, MapState, ReplayError, SessionMeta, SessionSummary,
} from "../core/types.js";
import { httpError, refusalError } from "./errors.js";
import { sha256 } from "./hash.js";
import { ensureHomeDir, writeFileAtomic } from "./home.js";
import { isSessionId, newSessionId, nextId as defaultNextId } from "./ids.js";
import { JsonlLedger } from "./ledger.js";
import { Session, humanProposal } from "./session.js";

export const META_SCHEMA = "exmap.session-meta.v1";

export interface SessionStoreOptions {
  home: string;
  engine?: Engine;
  classifier?: Classifier;
  now?: () => IsoTimestamp;
  nextId?: ApplyContext["nextId"];
  onClassified?: (stamp: ClassifierStamp) => void;
  /** A classification job failed unexpectedly (a bug); default: printed on stderr. */
  onJobError?: (e: unknown) => void;
}

type Loaded =
  | { ok: true; meta: SessionMeta; events: ExmapEvent[]; state: MapState }
  | { ok: false; status: "not_found" }
  | { ok: false; status: "meta_invalid"; detail: string }
  | { ok: false; status: "broken"; meta: SessionMeta; broken: BrokenInfo; prefix: MapState };

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function describeReplayError(error: ReplayError): string {
  switch (error.code) {
    case "REVISION_MISMATCH":
      return `revision mismatch at seq ${error.seq}: the ledger records ${error.expected}, the cards hash to ${error.actual}`;
    case "EMPTY_LEDGER":
      return "the ledger is empty";
    default:
      return error.detail;
  }
}

export class SessionStore {
  readonly home: string;
  readonly engine: Engine;
  readonly classifier: Classifier;
  readonly #now: () => IsoTimestamp;
  readonly #nextId: ApplyContext["nextId"];
  readonly #onClassified: ((stamp: ClassifierStamp) => void) | undefined;
  readonly #onJobError: (e: unknown) => void;
  readonly #open = new Map<string, Session>();
  /** Sessions whose append failed: kept (state as before the failed write) to answer 409 and to be listed with `broken`. */
  readonly #failed = new Map<string, Session>();
  #closed = false;

  constructor(opts: SessionStoreOptions) {
    this.home = opts.home;
    this.#now = opts.now ?? (() => new Date().toISOString());
    this.#nextId = opts.nextId ?? defaultNextId;
    this.engine = opts.engine ?? createEngine({ sha256, now: this.#now, nextId: this.#nextId });
    this.classifier = opts.classifier ?? createRulesClassifier();
    this.#onClassified = opts.onClassified;
    this.#onJobError = opts.onJobError ?? ((e) => console.error(`exmap: a classification job failed: ${e instanceof Error ? (e.stack ?? e.message) : String(e)}`));
  }

  get sessionsDir(): string {
    return join(this.home, "sessions");
  }
  dirOf(id: string): string {
    return join(this.sessionsDir, id);
  }

  /** Every session directory, newest first; a broken one is listed with `broken` and a summary of its readable prefix. */
  list(): SessionSummary[] {
    let names: string[];
    try {
      names = fs.readdirSync(this.sessionsDir);
    } catch {
      return [];
    }
    const out: SessionSummary[] = [];
    for (const name of names) {
      if (!isSessionId(name)) continue;
      const s = this.#summaryOrNull(name);
      if (s) out.push(s);
    }
    return out.sort((a, b) => (a.created_at === b.created_at ? (a.id < b.id ? 1 : -1) : a.created_at < b.created_at ? 1 : -1));
  }

  /** Creates sessions/<id>/ with meta.json and an empty events.jsonl; with `story`, one human card.create is applied. */
  create(input: { title: string; story?: string; actor?: string }): Session {
    const created_at = this.#now();
    const parsed = Date.parse(created_at);
    let id = newSessionId(Number.isFinite(parsed) ? parsed : Date.now());
    while (fs.existsSync(this.dirOf(id))) id = newSessionId(Number.isFinite(parsed) ? parsed : Date.now());
    const meta: SessionMeta = { schema: META_SCHEMA, id, title: input.title, created_at };
    let state = initialState(id);
    let events: ExmapEvent[] = [];
    if (input.story !== undefined) {
      const actor = input.actor ?? "";
      const r = this.engine.apply(state, {
        kind: "proposal.propose",
        proposals: [humanProposal(this.#nextId("prop"), { kind: "card.create", card: { kind: "story", text: input.story } }, actor, `story set by ${actor} at session creation`)],
      });
      if (!r.ok) throw refusalError(r);
      state = r.state;
      events = r.events;
    }
    ensureHomeDir(this.home);
    const dir = this.dirOf(id);
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    writeFileAtomic(join(dir, "meta.json"), JSON.stringify(meta, null, 2) + "\n");
    fs.closeSync(fs.openSync(join(dir, "events.jsonl"), "wx", 0o600));
    const ledger = new JsonlLedger(join(dir, "events.jsonl"));
    ledger.appendBatch(events);
    const session = this.#makeSession(meta, dir, ledger, events, state);
    this.#open.set(id, session);
    return session;
  }

  /** The cached session, or a cold open that verifies the whole chain. Throws HttpError 400 / 404 / 409. */
  open(id: string): Session {
    if (!isSessionId(id)) throw httpError("INVALID_SESSION_ID", `not a session id: ${JSON.stringify(id.slice(0, 80))}`);
    const cached = this.#open.get(id);
    if (cached) return cached;
    const failed = this.#failed.get(id);
    if (failed) throw failed.brokenError();
    const loaded = this.#load(id);
    if (!loaded.ok) {
      if (loaded.status === "not_found") throw httpError("SESSION_NOT_FOUND", `session ${id} does not exist`);
      if (loaded.status === "meta_invalid") throw httpError("META_INVALID", loaded.detail);
      const b = loaded.broken;
      throw httpError("LEDGER_BROKEN", `session ${id}: the ledger is broken at row ${b.row} (${b.code}): ${b.detail}`, { row: b.row, seq: b.seq, code: b.code });
    }
    return this.#adopt(loaded);
  }

  /** A verified load becomes the cached open session (so a list does not replay it again). */
  #adopt(loaded: Extract<Loaded, { ok: true }>): Session {
    const dir = this.dirOf(loaded.meta.id);
    const session = this.#makeSession(loaded.meta, dir, new JsonlLedger(join(dir, "events.jsonl")), loaded.events, loaded.state);
    if (this.#closed) void session.close();
    else this.#open.set(loaded.meta.id, session);
    return session;
  }

  /** The summary of a session; throws HttpError 400 / 404 / 409 META_INVALID; a broken ledger is reported in `broken`. */
  summaryOf(id: string): SessionSummary {
    if (!isSessionId(id)) throw httpError("INVALID_SESSION_ID", `not a session id: ${JSON.stringify(id.slice(0, 80))}`);
    const cached = this.#open.get(id) ?? this.#failed.get(id);
    if (cached) return summarize(cached.meta, cached.state, cached.broken);
    const loaded = this.#load(id);
    if (loaded.ok) {
      const session = this.#adopt(loaded);
      return summarize(session.meta, session.state, null);
    }
    if (loaded.status === "not_found") throw httpError("SESSION_NOT_FOUND", `session ${id} does not exist`);
    if (loaded.status === "meta_invalid") throw httpError("META_INVALID", loaded.detail);
    return summarize(loaded.meta, loaded.prefix, loaded.broken);
  }

  #summaryOrNull(id: string): SessionSummary | null {
    try {
      return this.summaryOf(id);
    } catch {
      return null; // a directory without a readable meta.json is not a session we can list
    }
  }

  async closeAll(): Promise<void> {
    this.#closed = true;
    const all = [...this.#open.values(), ...this.#failed.values()];
    this.#open.clear();
    this.#failed.clear();
    await Promise.all(all.map((s) => s.close()));
  }

  /** Every open session (for shutdown and tests). */
  openSessions(): Session[] {
    return [...this.#open.values()];
  }

  #makeSession(meta: SessionMeta, dir: string, ledger: JsonlLedger, events: ExmapEvent[], state: MapState): Session {
    return new Session({
      meta,
      dir,
      ledger,
      engine: this.engine,
      classifier: this.classifier,
      now: this.#now,
      nextId: this.#nextId,
      events,
      state,
      ...(this.#onClassified ? { onClassified: this.#onClassified } : {}),
      onJobError: this.#onJobError,
      onBroken: (session) => {
        this.#open.delete(session.id);
        this.#failed.set(session.id, session);
      },
    });
  }

  #readMeta(id: string): { ok: true; meta: SessionMeta } | { ok: false; status: "not_found" } | { ok: false; status: "meta_invalid"; detail: string } {
    const dir = this.dirOf(id);
    if (!fs.existsSync(dir)) return { ok: false, status: "not_found" };
    let raw: unknown;
    try {
      raw = JSON.parse(fs.readFileSync(join(dir, "meta.json"), "utf8"));
    } catch (e) {
      return { ok: false, status: "meta_invalid", detail: `session ${id}: meta.json is missing or not JSON: ${messageOf(e)}` };
    }
    const m = raw as Partial<SessionMeta>;
    if (m === null || typeof m !== "object" || m.schema !== META_SCHEMA || m.id !== id || typeof m.title !== "string" || typeof m.created_at !== "string") {
      return { ok: false, status: "meta_invalid", detail: `session ${id}: meta.json is not a ${META_SCHEMA} record for this session` };
    }
    return { ok: true, meta: { schema: META_SCHEMA, id: m.id, title: m.title, created_at: m.created_at } };
  }

  #load(id: string): Loaded {
    const meta = this.#readMeta(id);
    if (!meta.ok) return meta;
    const read = new JsonlLedger(join(this.dirOf(id), "events.jsonl")).readAll();
    if (!read.ok) {
      const prefix = this.#replayPrefix(id, read.events);
      // the rows before the unreadable one may end inside a batch too: point at that batch's first row
      const torn = read.events.length > 0 ? this.engine.replay(read.events) : null;
      const tornAt = torn && !torn.ok && torn.error.code === "INCOMPLETE_BATCH" ? failingIndex(this.engine, read.events, torn.error) : -1;
      const hint = tornAt >= 0 ? `; the readable rows before it end inside an unfinished batch, so truncate before row ${read.rows[tornAt] ?? tornAt + 1} (that batch's first row)` : "";
      return { ok: false, status: "broken", meta: meta.meta, prefix, broken: { code: read.error.code, row: read.error.row, seq: null, detail: `${read.error.detail}${hint}` } };
    }
    const { events, rows } = read;
    if (events.length === 0) return { ok: true, meta: meta.meta, events, state: initialState(id) };
    const foreign = events.findIndex((e) => e.session_id !== id);
    if (foreign === 0) {
      return {
        ok: false, status: "broken", meta: meta.meta, prefix: initialState(id),
        broken: { code: "SESSION_MISMATCH", row: rows[0] ?? 1, seq: events[0]!.seq, detail: `event ${events[0]!.id} belongs to session ${events[0]!.session_id}, not ${id}` },
      };
    }
    const r = this.engine.replay(events);
    if (r.ok) return { ok: true, meta: meta.meta, events, state: r.state };
    const at = failingIndex(this.engine, events, r.error);
    const prefix = this.#replayPrefix(id, r.error.code === "INCOMPLETE_BATCH" ? events : events.slice(0, at));
    const seq = "seq" in r.error ? r.error.seq : null;
    const row = rows[at] ?? at + 1;
    const detail = r.error.code === "INCOMPLETE_BATCH" ? `${describeReplayError(r.error)}; truncate before row ${row} to drop the partial batch` : describeReplayError(r.error);
    return {
      ok: false, status: "broken", meta: meta.meta, prefix,
      broken: { code: r.error.code, row, seq, detail },
    };
  }

  /** The state of the longest prefix of `events` that replays cleanly. */
  #replayPrefix(id: string, events: ExmapEvent[]): MapState {
    let slice = events;
    for (let guard = 0; guard < 4 && slice.length > 0; guard++) {
      const r = this.engine.replay(slice, { requireComplete: false });
      if (r.ok) return r.state;
      slice = slice.slice(0, failingIndex(this.engine, slice, r.error));
    }
    return initialState(id);
  }
}

/** The index of the event a replay error names (the first index whose prefix fails the chain walk). */
function failingIndex(engine: Engine, events: readonly ExmapEvent[], error: ReplayError): number {
  if (error.code === "EMPTY_LEDGER") return 0;
  if (error.code === "REVISION_MISMATCH" || error.code === "INCOMPLETE_BATCH") {
    const i = events.findIndex((e) => e.seq === error.seq);
    return i >= 0 ? i : 0;
  }
  for (let i = 0; i < events.length; i++) {
    if (events[i]!.id !== error.event_id) continue;
    if (engine.verifyChain(events.slice(0, i)).ok && !engine.verifyChain(events.slice(0, i + 1)).ok) return i;
  }
  return Math.max(0, Math.min(events.length, error.seq - 1));
}

/** SessionSummary (design §4 §13): every number from select.counts(state). */
export function summarize(meta: SessionMeta, state: MapState, broken: BrokenInfo | null): SessionSummary {
  const current = select.currentRevision(state);
  return {
    id: meta.id,
    title: meta.title,
    created_at: meta.created_at,
    head: { seq: state.head.seq, hash: state.head.hash },
    revision: { seq: current.seq, hash: current.hash },
    counts: select.counts(state),
    human_verified: isHumanVerified(state),
    broken,
  };
}
