// tests/unit/export/fixtures.ts — literal MapState / Signoff fixtures for the export mappers (design §12, TEST-PLAN §5).
// Built by hand, never through apply(): a verified map (every live card confirmed, one answered question, two accepted
// outstanding, a removed example, an active sign-off on the current revision), plus the unverified variants the gate
// distinguishes (none / invalidated / active_but_stale / active_but_dod_failed) and a draft map with unattached examples.
import { createHash } from "node:crypto";
import { SIGNOFF_CONFIRMATION_TEXT, canonicalJson, canonicalState, dodReport } from "../../../src/core/index.js";
import type {
  Card, CardRecord, CardStatus, Clarification, Confirmation, Definition, ExampleCard, ExportInput, ExportOptions, ExportSession,
  MapState, Provenance, QuestionCard, Revision, RuleCard, Signoff, StoryCard,
} from "../../../src/core/types.js";

export const sha256 = (utf8: string): string => createHash("sha256").update(utf8, "utf8").digest("hex");

export const NOW = "2026-10-16T12:30:00.000Z";
export const SIGNED_AT = "2026-10-16T12:20:00.000Z";
export const SESSION: ExportSession = { id: "sess_export_fixture", title: "Appointment cancellation", created_at: "2026-10-16T12:00:00.000Z" };

export const STORY_TEXT = "A patient can cancel an appointment online, but not within two hours.";
export const RULE_24H = "A patient cannot cancel within 24 hours of a nurse appointment. Keep two hours for GPs.";
export const RULE_OVERRIDE = "A receptionist must not be able to override the cancellation window.";
export const EX_GWT = "Given a nurse appointment at 10am, when the patient cancels at 9am, then it is refused.";
export const EX_IF_THEN = "If a GP appointment is at 10am and they cancel at 7am then it is allowed.";
export const EX_FREE = "For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused under the 24-hour rule.";
export const EX_MULTILINE = "Given a receptionist opens a booking inside the window,\nwhen they try to cancel it,\nthen the system refuses and shows the rule.";
export const EX_REMOVED = "An error case: the cancellation service is down.";
export const Q_DENTIST = "What about dentist appointments?";
export const Q_MESSAGE = "Does the refusal message name the rule?";
export const Q_TWICE = "Should the window apply to appointments booked twice a day?";
export const ACCEPT_REASON = "To be settled with the practice manager";
export const ACCEPT_REASON_2 = "Parked until the practice manager confirms the booking policy";
export const ANSWER_MESSAGE = "Yes, it names the 24-hour rule.";

export const OPTIONS: ExportOptions = {
  capability_class: "backend.route.edit",
  kind: "code",
  size_estimate: "M",
  facts: [{ slot: "route_identity", text: "PUT /appointments/{id}/cancel" }],
  by: "Sam",
  seq: 1,
  at: "2026-10-16T12:25:00.000Z",
};

export const OPTIONS_2: ExportOptions = { ...OPTIONS, size_estimate: "S", facts: [...OPTIONS.facts, { slot: "behaviour_change", text: "The GP window becomes three hours." }], seq: 2, at: "2026-10-16T12:26:00.000Z" };

/* ───────────── card builders ───────────── */

export function provenance(n: number): Provenance {
  return { proposal_id: `prop_${n}`, event_id: `evt_${n}`, utterance_ids: [`utt_${n}`], classifier: "rules.v1" };
}

export function confirmedBySam(n: number, version = 1): Confirmation {
  return { proposal_id: `prop_c${n}`, event_id: `evt_c${n}`, version, by: { provider: "human", actor: "Sam", confidence: 1 } };
}

export interface CardOpts {
  status?: CardStatus;
  definitions?: Definition[];
  confirmed?: boolean;
}

function common(id: string, n: number, text: string, opts: CardOpts) {
  const confirmed = opts.confirmed ?? true;
  const status: CardStatus = opts.status ?? (confirmed ? "confirmed" : "applied");
  return {
    id,
    text,
    definitions: opts.definitions ?? [],
    status,
    version: 1,
    history: [],
    supersedes: null,
    superseded_by: null,
    rejection: null,
    confirmation: status === "confirmed" ? confirmedBySam(n) : null,
    created: provenance(n),
    changed: provenance(n),
    restored_by: null,
  };
}

export function story(id: string, n: number, text: string, opts: CardOpts = {}): StoryCard {
  return { kind: "story", ...common(id, n, text, opts) };
}

export function rule(id: string, n: number, text: string, opts: CardOpts = {}): RuleCard {
  return { kind: "rule", ...common(id, n, text, opts) };
}

export function example(id: string, n: number, text: string, rule_id: string | null, opts: CardOpts = {}): ExampleCard {
  return { kind: "example", ...common(id, n, text, opts), rule_id, needs_review: null };
}

export function question(
  id: string,
  n: number,
  text: string,
  about_card_id: string | null,
  resolution: { answer?: string; accepted?: { by: string; reason: string } } = {},
  opts: CardOpts = {},
): QuestionCard {
  const answered = resolution.answer !== undefined;
  const confirmed = opts.confirmed ?? answered;
  return {
    kind: "question",
    ...common(id, n, text, { ...opts, confirmed }),
    about_card_id,
    answer: resolution.answer ?? null,
    accepted_outstanding: resolution.accepted ? { by: resolution.accepted.by, reason: resolution.accepted.reason, event_id: `evt_acc_${n}` } : null,
  };
}

export function removedExample(id: string, n: number, text: string, rule_id: string | null): ExampleCard {
  return {
    ...example(id, n, text, rule_id, { status: "rejected" }),
    rejection: { kind: "removed", proposal_id: `prop_rm_${n}`, event_id: `evt_rm_${n}` },
  };
}

/* ───────────── state builders ───────────── */

export function record(card: Card): CardRecord {
  const { history: _history, ...rest } = card;
  return rest;
}

export function revisionHashOf(cards: readonly Card[]): string {
  return sha256(canonicalJson(canonicalState(cards.map(record))));
}

export interface StateOpts {
  headSeq?: number;
  options?: ExportOptions[];
  revisions?: number; // how many non-genesis revisions to synthesise with these cards (default 1)
}

/** A MapState whose current revision is sha256 of the given cards' canonical state and whose snapshot holds every card. */
export function buildState(cards: readonly Card[], opts: StateOpts = {}): MapState {
  const headSeq = opts.headSeq ?? 40;
  const snapshot: Record<string, CardRecord> = {};
  for (const card of cards) snapshot[card.id] = record(card);
  const hash = revisionHashOf(cards);
  const genesis: Revision = {
    seq: 0, hash: "8e97e07bb7573b0849c4f8894c845ce76472f2c9f0eda7a7db37004bc269f675", event_id: null, at: null, cause: "genesis",
    batch_id: null, source_utterance_ids: [], snapshot: {},
  };
  const revisions: Revision[] = [genesis];
  const count = opts.revisions ?? 1;
  for (let seq = 1; seq <= count; seq++) {
    revisions.push({
      seq,
      hash: seq === count ? hash : sha256(`earlier-revision-${seq}`),
      event_id: `evt_rev_${seq}`,
      at: "2026-10-16T12:10:00.000Z",
      cause: "proposal.applied",
      batch_id: `evt_rev_${seq}`,
      source_utterance_ids: [],
      snapshot: seq === count ? snapshot : {},
    });
  }
  const map: Record<string, Card> = {};
  for (const card of cards) map[card.id] = card;
  return {
    schema: "exmap.state.v1",
    session_id: SESSION.id,
    head: { seq: headSeq, hash: sha256(`head-${headSeq}`), event_id: `evt_${headSeq}` },
    utterances: [],
    classifications: [],
    cards: map,
    card_order: cards.map((c) => c.id),
    proposals: {},
    proposal_order: [],
    clarifications: {},
    clarification_order: [],
    revisions,
    signoffs: [],
    export_options: opts.options ?? [],
  };
}

/** An active sign-off on the state's current revision, with the DoD report the engine would have computed. */
export function signoffFor(state: MapState, n = 1): Signoff {
  const current = state.revisions[state.revisions.length - 1]!;
  return {
    id: `sig_${n}`,
    reviewer: { name: "Sam" },
    confirmation_text: SIGNOFF_CONFIRMATION_TEXT,
    revision: { seq: current.seq, hash: current.hash },
    evidence: { head_seq: state.head.seq - 1, head_hash: sha256(`head-${state.head.seq - 1}`) },
    checks: dodReport(state),
    event_id: state.head.event_id ?? `evt_${state.head.seq}`,
    at: SIGNED_AT,
    status: "active",
    invalidated: null,
  };
}

export function verifiedCards(): Card[] {
  return [
    story("card_1", 1, STORY_TEXT, { definitions: [{ term: "appointment", definition: "a booked slot, not a walk-in" }] }),
    rule("card_2", 2, RULE_24H),
    rule("card_3", 3, RULE_OVERRIDE, {
      definitions: [{ term: "cancellation window", definition: "the period before the appointment in which online cancellation is refused" }],
    }),
    example("card_4", 4, EX_GWT, "card_2"),
    example("card_5", 5, EX_IF_THEN, "card_2"),
    example("card_6", 6, EX_FREE, "card_2"),
    example("card_7", 7, EX_MULTILINE, "card_3"),
    question("card_8", 8, Q_DENTIST, "card_2", { accepted: { by: "Sam", reason: ACCEPT_REASON } }),
    question("card_9", 9, Q_MESSAGE, "card_4", { answer: ANSWER_MESSAGE }),
    question("card_10", 10, Q_TWICE, null, { accepted: { by: "Sam", reason: ACCEPT_REASON_2 } }),
    removedExample("card_11", 11, EX_REMOVED, "card_2"),
  ];
}

/** Human-verified: every live card confirmed, questions resolved or accepted, an active sign-off citing the current revision. */
export function verifiedState(opts: StateOpts = {}): MapState {
  const state = buildState(verifiedCards(), opts);
  state.signoffs = [signoffFor(state)];
  return state;
}

/** Verified, then an open clarification (DoD check 3 regresses without a revision): active_but_dod_failed. */
export function activeButDodFailedState(): MapState {
  const state = verifiedState();
  const clarification: Clarification = {
    id: "clar_1", proposal_id: "prop_90", question: "Which example do you mean?", candidates: [], template: { kind: "card.remove" },
    pending_operation: null, status: "open", asked_event_id: "evt_90", text_answers: [], answer: null, answered_event_id: null,
    resolved_by_proposal_id: null,
  };
  state.clarifications = { clar_1: clarification };
  state.clarification_order = ["clar_1"];
  state.head = { seq: 41, hash: sha256("head-41"), event_id: "evt_41" };
  return state;
}

/** Verified, then the 24-hour rule changed (revision 2): the sign-off is invalidated and the rule is no longer confirmed. */
export function invalidatedState(): MapState {
  const signed = verifiedState();
  const cards = verifiedCards().map((card): Card => {
    if (card.id !== "card_2") return card;
    return { ...card, text: `${RULE_24H} Make the GP window three hours.`, status: "applied", version: 2, confirmation: null, changed: provenance(50) };
  });
  const state = buildState(cards, { headSeq: 42, revisions: 2 });
  const current = state.revisions[state.revisions.length - 1]!;
  state.revisions[1] = { ...state.revisions[1]!, hash: signed.revisions[1]!.hash };
  const signoff = signed.signoffs[0]!;
  state.signoffs = [{
    ...signoff,
    status: "invalidated",
    invalidated: { event_id: "evt_42", by_event_id: "evt_41", to_revision: { seq: current.seq, hash: current.hash } },
  }];
  return state;
}

/** Kept for completeness: an active sign-off whose revision is not the current one (the engine never leaves a map like this). */
export function staleState(): MapState {
  const state = verifiedState();
  const signoff = state.signoffs[0]!;
  state.signoffs = [{ ...signoff, revision: { seq: 0, hash: sha256("some-earlier-revision") } }];
  return state;
}

export const DRAFT_STORY_TEXT = "A patient cancels an appointment online";
export const EX_UNATTACHED = "When the cancellation service is down, then the patient sees a retry message.";
export const EX_UNATTACHED_FREE = "Service outage during cancellation.";
export const Q_AUDIT = "Do we need an audit trail of refused cancellations?";
export const Q_RETRY = "How long should the retry message stay on screen?";

/** Unverified: nothing confirmed, two unattached examples, one unresolved question, no sign-off. */
export function draftState(opts: StateOpts = {}): MapState {
  return buildState(
    [
      story("card_1", 1, DRAFT_STORY_TEXT, { confirmed: false }),
      rule("card_2", 2, RULE_24H, { confirmed: false }),
      example("card_4", 4, EX_GWT, "card_2", { confirmed: false }),
      example("card_12", 12, EX_UNATTACHED, null, { confirmed: false }),
      example("card_13", 13, EX_UNATTACHED_FREE, "card_99", { confirmed: false }), // names a rule that does not exist
      question("card_8", 8, Q_AUDIT, "card_2", {}, { confirmed: false }),
      question("card_14", 14, Q_RETRY, "card_12", { accepted: { by: "Priya", reason: "UX to decide" } }, { confirmed: false }),
    ],
    opts,
  );
}

/** A second session with a story only (e2e §13.1 step 14). */
export function storyOnlyState(): MapState {
  return buildState([story("card_1", 1, DRAFT_STORY_TEXT, { confirmed: false })], { headSeq: 2 });
}

export function input(state: MapState, draft = false, now = NOW, session = SESSION): ExportInput {
  return { session, state, draft, now };
}
