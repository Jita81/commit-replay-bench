// tests/unit/web/helpers.tsx — states built through core's apply() (never literal), a fake SessionApi, and a render
// wrapper that puts a component under <SessionEnv> with a static state source (no WebSocket).
import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi, type Mock } from "vitest";
import { apply } from "../../../src/core/apply.js";
import { initialState } from "../../../src/core/reduce.js";
import type {
  ApplyContext, CardKind, Command, ExmapEvent, Intent, MapState, NewCard, Operation, OperationTemplate, Utterance,
} from "../../../src/core/types.js";
import type { SessionApi } from "../../../src/web/api/client.js";
import { SessionEnv, staticSource, type ToastMessage } from "../../../src/web/store/useSession.js";
import { INTENT_OF_KIND, aiProposal, clarifying, classify, humanProposal, propose, testCtx, utterance, type ClarifyingOpts, type ProposalOpts } from "../core/fixtures.js";

export const SESSION_ID = "ses_webtest_000001";
export const CONFIRMATION = "I have reviewed the complete requirement and confirm it represents the agreed intent.";

function createdId(events: readonly ExmapEvent[]): string {
  for (const e of events) {
    if (e.type === "proposal.made" || e.type === "proposal.applied") {
      const made = e.effects.find((x) => x.before === null);
      if (made) return made.card_id;
    }
  }
  throw new Error("no card created");
}

/** Runs commands through apply() with counter ids and keeps every event (valid hashes, chained from genesis). */
export class MapBuilder {
  state: MapState;
  readonly ctx: ApplyContext;
  readonly events: ExmapEvent[] = [];
  #n = 0;

  constructor(sessionId = SESSION_ID) {
    this.ctx = testCtx().ctx;
    this.state = initialState(sessionId);
  }

  run(command: Command): ExmapEvent[] {
    const r = apply(this.state, command, this.ctx);
    if (!r.ok) throw new Error(`apply refused ${r.reason}: ${r.detail}`);
    this.state = r.state;
    this.events.push(...r.events);
    return r.events;
  }

  utter(text: string, opts: Partial<Omit<Utterance, "id" | "text">> = {}): string {
    this.#n += 1;
    const id = `utt_${this.#n}`;
    this.run({ kind: "utterance.record", utterance: utterance(id, text, { t_start_ms: this.#n * 4000, ...opts }) });
    return id;
  }

  /** An utterance the classifier found nothing in. */
  chatter(text = "Right, moving on.", opts: Partial<Omit<Utterance, "id" | "text">> = {}): string {
    const id = this.utter(text, opts);
    this.run(classify(id, "none", []));
    return id;
  }

  human(op: Operation, actor = "Sam"): { pid: string; events: ExmapEvent[] } {
    const pid = this.ctx.nextId("prop");
    return { pid, events: this.run(propose(humanProposal(pid, op, actor))) };
  }

  ai(op: Operation, utt: string, opts: ProposalOpts = {}): { pid: string; events: ExmapEvent[] } {
    const pid = this.ctx.nextId("prop");
    const events = this.run(propose(aiProposal(pid, op, { utts: [utt], ...opts })));
    this.run(classify(utt, INTENT_OF_KIND[op.kind], [pid]));
    return { pid, events };
  }

  clarify(intent: Intent, utt: string, opts: ClarifyingOpts): { pid: string; cid: string } {
    const pid = this.ctx.nextId("prop");
    const events = this.run(propose(clarifying(pid, intent, { utts: [utt], ...opts })));
    this.run(classify(utt, intent, [pid]));
    const asked = events.find((e): e is Extract<ExmapEvent, { type: "clarification.asked" }> => e.type === "clarification.asked");
    if (!asked) throw new Error("no clarification asked");
    return { pid, cid: asked.clarification_id };
  }

  create(card: NewCard, utt: string | null, opts: ProposalOpts = {}): { id: string; pid: string } {
    const r = utt ? this.ai({ kind: "card.create", card }, utt, opts) : this.human({ kind: "card.create", card });
    return { id: createdId(r.events), pid: r.pid };
  }

  utteranceText(kind: CardKind, text: string): string {
    return `${kind}: ${text}`;
  }
}

export interface RichIds {
  story: string;
  rule: string;
  exGp: string;
  exNurse: string;
  q1: string;
  q2: string;
  exRemoved: string;
  pRemove: string;
  pRuleUpdate: string;
  clar: string;
  pClar: string;
  uRemove: string;
}

/**
 * A map with every state the board / tray / review tests need: a story (confirmed by click), a rule updated by the AI
 * (so examples were flagged), one flagged and one confirmed example, an unanswered and an answered question, an AI
 * removal that nobody reviewed (the removed card is history), and an open two-candidate removal clarification.
 */
export function richMap(): { b: MapBuilder; ids: RichIds } {
  const b = new MapBuilder();
  const story = b.create({ kind: "story", text: "A patient cancels an appointment online" }, null).id;
  const u1 = b.utter("A patient should be able to cancel online, but not within two hours of their appointment.");
  const rule = b.create({ kind: "rule", text: "A patient should be able to cancel online, but not within two hours of their appointment." }, u1).id;
  const u2 = b.utter("If a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused.", { speaker: "Sam", lane: "me" });
  const exGp = b.create({ kind: "example", text: "If a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused.", rule_id: rule }, u2).id;
  const u3 = b.utter("For a nurse appointment, say it is at 10am and they cancel at 8am, that one is allowed.");
  const exNurse = b.create({ kind: "example", text: "For a nurse appointment, say it is at 10am and they cancel at 8am, that one is allowed.", rule_id: rule }, u3).id;
  const u4 = b.utter("What about appointments already in progress?", { speaker: "Sam", lane: "me" });
  const q1 = b.create({ kind: "question", text: "What about appointments already in progress?", about_card_id: rule }, u4).id;
  const u5 = b.utter("Do we know if a nurse can cancel on the patient's behalf?");
  const q2 = b.create({ kind: "question", text: "Do we know if a nurse can cancel on the patient's behalf?", about_card_id: rule }, u5).id;
  b.human({ kind: "card.update", card_id: q2, patch: { answer: "Yes, a nurse may cancel on the patient's behalf." } });
  b.human({ kind: "confirm", card_ids: [story], proposal_ids: [] });
  const u6 = b.utter("Actually, make that 24 hours for nurse appointments.", { speaker: "Sam", lane: "me" });
  const pRuleUpdate = b.ai(
    { kind: "card.update", card_id: rule, patch: { text: "A patient should be able to cancel online, but not within two hours of their appointment. Make that 24 hours for nurse appointments." } },
    u6,
    { rationale: "amendment of the cancellation window", confidence: 0.83 },
  ).pid;
  b.human({ kind: "confirm", card_ids: [exGp], proposal_ids: [] });
  const u7 = b.utter("We also need an error case, when the cancellation fails because the system is down.");
  const exRemoved = b.create({ kind: "example", text: "An error case, when the cancellation fails because the system is down.", rule_id: rule }, u7).id;
  const uRemove = b.utter("Delete that example.", { speaker: "Sam", lane: "me" });
  const pRemove = b.ai({ kind: "card.remove", card_id: exRemoved }, uRemove, { confidence: 0.5, rationale: "removal of the last example" }).pid;
  const u9 = b.utter("Delete that example. It's not what I meant.", { speaker: "Sam", lane: "me" });
  const template: OperationTemplate = { kind: "card.remove" };
  const { pid: pClar, cid: clar } = b.clarify("remove", u9, {
    question: "Which example do you mean: (1) the nurse one, or (2) the GP one?",
    template,
    candidates: [
      { card_id: exNurse, label: "For a nurse appointment, say it is at 10am and they cancel… (example, Priya)" },
      { card_id: exGp, label: "If a GP appointment is at 10am and the patient tries to… (example, Sam)" },
    ],
    confidence: 0.5,
  });
  return { b, ids: { story, rule, exGp, exNurse, q1, q2, exRemoved, pRemove, pRuleUpdate, clar, pClar, uRemove } };
}

type Fn = (...args: never[]) => unknown;
export type FakeApi = { [K in keyof SessionApi]: SessionApi[K] extends Fn ? Mock<SessionApi[K]> : SessionApi[K] };

const ok = { ok: true as const, events: [] };

export function fakeApi(over: Partial<{ [K in keyof SessionApi]: SessionApi[K] }> = {}): FakeApi {
  const api: FakeApi = {
    sessionId: SESSION_ID,
    get: vi.fn(async () => {
      throw new Error("not stubbed");
    }),
    events: vi.fn(async () => ({ events: [], head: { seq: 0, hash: "" }, has_more: false })),
    postUtterance: vi.fn(async () => ({ ok: true as const, event: { id: "evt_x", seq: 1, hash: "" } })),
    acceptProposal: vi.fn(async () => ok),
    rejectProposal: vi.fn(async () => ok),
    answerClarification: vi.fn(async () => ok),
    createCard: vi.fn(async () => ok),
    confirmCard: vi.fn(async () => ok),
    removeCard: vi.fn(async () => ok),
    updateCard: vi.fn(async () => ok),
    acceptQuestion: vi.fn(async () => ok),
    undo: vi.fn(async () => ok),
    reviewChecks: vi.fn(async () => ok),
    signoff: vi.fn(async () => ok),
    putExportOptions: vi.fn(async () => ({ ok: true as const, events: [], export_options: { capability_class: "unclassified", kind: "code" as const, size_estimate: "unsized" as const, facts: [], by: "Sam", seq: 1, at: "2026-10-16T12:00:00.000Z" } })),
    exportUrl: vi.fn((file: string, draft: boolean) => `/api/sessions/${SESSION_ID}/export/${file}?draft=${draft ? "true" : "false"}`),
    exportText: vi.fn(async () => "# Preview"),
    catalogue: vi.fn(async () => ({ classes: {} })),
    config: vi.fn(async () => {
      throw new Error("not stubbed");
    }),
  } as unknown as FakeApi;
  Object.assign(api, over);
  return api;
}

export interface EnvOptions {
  state: MapState;
  api?: SessionApi;
  actor?: string;
  onNeedActor?: () => void;
  onToast?: (t: ToastMessage) => void;
  title?: string;
}

export function renderWithEnv(ui: ReactNode, opts: EnvOptions): RenderResult & { api: SessionApi; source: ReturnType<typeof staticSource> } {
  const source = staticSource(opts.state);
  const api = opts.api ?? fakeApi();
  const result = render(
    <SessionEnv source={source} api={api} actor={opts.actor ?? "Sam"} onNeedActor={opts.onNeedActor} onToast={opts.onToast} sessionTitle={opts.title ?? "Test session"}>
      {ui}
    </SessionEnv>,
  );
  return Object.assign(result, { api, source });
}
