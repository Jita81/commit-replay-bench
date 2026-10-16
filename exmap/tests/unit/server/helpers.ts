// exmap/tests/unit/server/helpers.ts — TEST-PLAN §4 setup: buildApp({ home: mkdtemp, port: 4317, classifier: fake,
// webDist: null, ortDir: null, now: fixedClock, nextId: counterIds }), app.inject with Host 127.0.0.1:4317.
// fakeClassifier(script), postUtterance(), createSession(), readLedger(), awaitClassified(), and proposal builders.
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { LightMyRequestResponse } from "fastify";
import { afterEach } from "vitest";
import { buildApp, type AppOptions, type ExmapApp } from "../../../src/server/app.js";
import type {
  ApplyContext, Classifier, ClassifierInput, ClassifierOperation, ClassifierProposal, ClassifierProvenance, ExmapEvent, IdPrefix,
  IsoTimestamp, Lane, SessionSummary,
} from "../../../src/core/types.js";

export const PORT = 4317;
export const HOST = `127.0.0.1:${PORT}`;

/* ───────────── clock, ids, homes ───────────── */

/** A fixed clock stepping 1 s per call. */
export function fixedClock(start = "2026-10-16T12:00:00.000Z"): () => IsoTimestamp {
  let t = Date.parse(start);
  return () => {
    const at = new Date(t).toISOString();
    t += 1000;
    return at;
  };
}

/** Counter ids `evt_1`, `card_1`, … per prefix. */
export function counterIds(): ApplyContext["nextId"] {
  const counters = new Map<IdPrefix, number>();
  return (prefix) => {
    const n = (counters.get(prefix) ?? 0) + 1;
    counters.set(prefix, n);
    return `${prefix}_${n}`;
  };
}

const homes: string[] = [];
export function tempHome(): string {
  const dir = mkdtempSync(join(tmpdir(), "exmap-server-test-"));
  homes.push(dir);
  return dir;
}
const apps: ExmapApp[] = [];
afterEach(async () => {
  for (const app of apps.splice(0)) await app.close().catch(() => undefined);
  for (const dir of homes.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/* ───────────── fake classifier ───────────── */

export type Step = ClassifierProposal | Error | ((input: ClassifierInput, signal?: AbortSignal) => ClassifierProposal | Promise<ClassifierProposal>);

export interface FakeClassifier extends Classifier {
  calls: ClassifierInput[];
  signals: Array<AbortSignal | undefined>;
  /** Steps consumed in order; when they run out, `fallback` answers. */
  push(...steps: Step[]): void;
}

/** A classifier that answers from a script (in call order), else with `fallback` (default: "none"). */
export function fakeClassifier(script: Step[] = [], fallback?: Step, provider: "rules.v1" | "claude" = "rules.v1"): FakeClassifier {
  const queue = [...script];
  const calls: ClassifierInput[] = [];
  const signals: Array<AbortSignal | undefined> = [];
  return {
    provider,
    calls,
    signals,
    push: (...steps) => {
      queue.push(...steps);
    },
    async classify(input, opts) {
      calls.push(structuredClone(input));
      signals.push(opts?.signal);
      const step = queue.length > 0 ? queue.shift()! : (fallback ?? ((i: ClassifierInput) => none(i)));
      if (step instanceof Error) throw step;
      if (typeof step === "function") return step(input, opts?.signal);
      return step;
    },
  };
}

export function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void } {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/* ───────────── proposal builders (what a classifier returns) ───────────── */

export const RULES: ClassifierProvenance = { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null };

export function proposal(input: ClassifierInput, over: Partial<ClassifierProposal> & Pick<ClassifierProposal, "intent">): ClassifierProposal {
  return {
    operations: [],
    target_card_ids: [],
    confidence: 0.8,
    needs_clarification: false,
    clarification: null,
    resolves: null,
    rationale: `test: ${over.intent}`,
    heard_intent: null,
    classifier: RULES,
    source_utterance_ids: [input.utterance.id],
    ...over,
  };
}

export function none(input: ClassifierInput, heard: ClassifierProposal["heard_intent"] = null): ClassifierProposal {
  return proposal(input, { intent: "none", heard_intent: heard, confidence: heard ? 0.5 : 0, rationale: "No map-changing cue found." });
}

export function ops(intent: ClassifierProposal["intent"], operations: ClassifierOperation[], over: Partial<ClassifierProposal> = {}): Step {
  return (input) => proposal(input, { intent, operations, ...over });
}

export const op = {
  create(kind: "story" | "rule" | "example" | "question", text: string, links: { rule_id?: string | null; about_card_id?: string | null } = {}): ClassifierOperation {
    return { kind: "card.create", card: { kind, text, rule_id: links.rule_id ?? null, about_card_id: links.about_card_id ?? null } };
  },
  update(card_id: string, patch: Partial<Extract<ClassifierOperation, { kind: "card.update" }>["patch"]>, amendment: Extract<ClassifierOperation, { kind: "card.update" }>["amendment"] = null): ClassifierOperation {
    return { kind: "card.update", card_id, patch: { text: null, text_append: null, answer: null, rule_id: null, about_card_id: null, ...patch }, amendment };
  },
  remove(card_id: string, reason = ""): ClassifierOperation {
    return { kind: "card.remove", card_id, reason };
  },
  confirm(card_ids: string[]): ClassifierOperation {
    return { kind: "confirm", card_ids };
  },
  reject(proposal_id: string): ClassifierOperation {
    return { kind: "interpretation.reject", proposal_id };
  },
  undo(steps = 1): ClassifierOperation {
    return { kind: "undo", steps };
  },
};

/* ───────────── app + requests ───────────── */

export interface TestApp {
  app: ExmapApp;
  home: string;
  classifier: FakeClassifier;
}

export async function makeApp(over: Partial<AppOptions> & { classifier?: FakeClassifier } = {}): Promise<TestApp> {
  const home = over.home ?? tempHome();
  const classifier = over.classifier ?? fakeClassifier();
  const app = await buildApp({
    home,
    port: PORT,
    webDist: null,
    ortDir: null,
    now: fixedClock(),
    nextId: counterIds(),
    env: {},
    ...over,
    classifier,
  });
  apps.push(app);
  return { app, home, classifier };
}

/** Registers an app built elsewhere so the suite closes it. */
export function track(app: ExmapApp): ExmapApp {
  apps.push(app);
  return app;
}

type Method = "GET" | "POST" | "PUT";
export async function call(app: ExmapApp, method: Method, url: string, body?: unknown, headers: Record<string, string> = {}): Promise<LightMyRequestResponse> {
  return app.inject({
    method,
    url,
    headers: { host: `127.0.0.1:${app.exmap.port()}`, ...(body !== undefined ? { "content-type": "application/json" } : {}), ...headers },
    ...(body !== undefined ? { payload: JSON.stringify(body) } : {}),
  });
}

export const json = <T = Record<string, unknown>>(res: LightMyRequestResponse): T => res.json() as T;

export async function createSession(app: ExmapApp, opts: { story?: string; title?: string; actor?: string } = {}): Promise<SessionSummary> {
  const body: Record<string, unknown> = { title: opts.title ?? "Online cancellation" };
  if (opts.story !== undefined) {
    body["story"] = opts.story;
    body["actor"] = opts.actor ?? "Sam";
  } else if (opts.actor !== undefined) body["actor"] = opts.actor;
  const res = await call(app, "POST", "/api/sessions", body);
  if (res.statusCode !== 201) throw new Error(`createSession: ${res.statusCode} ${res.body}`);
  return json<{ session: SessionSummary }>(res).session;
}

let uttCounter = 0;
/** A wire-valid utterance id (`utt_` + 12 hex). */
export function uttId(n?: number): string {
  const v = n ?? ++uttCounter;
  return `utt_${v.toString(16).padStart(12, "0")}`;
}

export function wireUtterance(id: string, text: string, opts: { lane?: Lane; speaker?: string | null; t?: number } = {}): Record<string, unknown> {
  const t = opts.t ?? 1000;
  return {
    id, text, lane: opts.lane ?? "remote", speaker: opts.speaker === undefined ? "Priya" : opts.speaker, provider: "replay", model: null,
    t_start_ms: t, t_end_ms: t + 2000, is_local: true, confidence: null,
  };
}

export async function postUtterance(
  app: ExmapApp, sid: string, id: string, text: string, opts: { wait?: boolean; lane?: Lane; speaker?: string | null } = {},
): Promise<LightMyRequestResponse> {
  const wait = opts.wait ?? true;
  return call(app, "POST", `/api/sessions/${sid}/utterances${wait ? "?wait=1" : ""}`, wireUtterance(id, text, opts));
}

/** Every event of events.jsonl, parsed. */
export function readLedger(home: string, sid: string): ExmapEvent[] {
  const text = readFileSync(join(home, "sessions", sid, "events.jsonl"), "utf8");
  return text.split("\n").filter((l) => l !== "").map((l) => JSON.parse(l) as ExmapEvent);
}

export function ledgerText(home: string, sid: string): string {
  return readFileSync(join(home, "sessions", sid, "events.jsonl"), "utf8");
}

/** Waits until the session's classification chain is idle and returns the utterance.classified event for `utteranceId`. */
export async function awaitClassified(app: ExmapApp, sid: string, utteranceId: string): Promise<Extract<ExmapEvent, { type: "utterance.classified" }>> {
  const session = app.exmap.store.open(sid);
  for (let i = 0; i < 50; i++) {
    await session.classificationsIdle();
    const e = session.events.find((x): x is Extract<ExmapEvent, { type: "utterance.classified" }> => x.type === "utterance.classified" && x.utterance_id === utteranceId);
    if (e) return e;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error(`utterance ${utteranceId} was never classified`);
}

export function eventsOf(app: ExmapApp, sid: string): readonly ExmapEvent[] {
  return app.exmap.store.open(sid).events;
}

export function types(events: readonly ExmapEvent[]): string[] {
  return events.map((e) => e.type);
}

/** The card id a batch created (the first `before: null` effect of a proposal.made). */
export function createdCard(events: readonly ExmapEvent[]): string {
  for (const e of events) {
    if (e.type === "proposal.made") for (const f of e.effects) if (f.before === null) return f.card_id;
  }
  throw new Error("no card created in this batch");
}
