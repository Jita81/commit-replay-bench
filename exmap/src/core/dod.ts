// exmap/src/core/dod.ts — design §5.6. The five Definition of Done checks, computed from the ledger state; every detail
// names the id and the status it saw. `isHumanVerified` is the completion gate: the last sign-off is active, on the
// current revision, and the report still passes (check 3 can regress without a revision).
import { canonicalJson } from "./canonical.js";
import { canonicalState } from "./revision.js";
import * as select from "./select.js";
import type {
  Card, ConfirmedBy, DodCheck, DodCheckId, DodOptions, DodReport, ExampleCard, MapState, NeedsReview, ProposalRecord,
} from "./types.js";

export const SIGNOFF_CONFIRMATION_TEXT = "I have reviewed the complete requirement and confirm it represents the agreed intent.";
export const DOD_OPTIONS: DodOptions = { requireHumanConfirm: false }; // voice confirmations count, labelled as such

const TITLES: Record<DodCheckId, string> = {
  story_rules_confirmed: "Story and business rules accurately represent the agreed intent",
  examples_reviewed: "Examples and acceptance criteria have been reviewed",
  changes_resolved: "Changes, deletions and disputed interpretations are resolved",
  questions_resolved: "Open questions are resolved or explicitly accepted as outstanding",
  final_version_recorded: "The final version and its evidence are recorded",
};

function describeBy(by: ConfirmedBy): string {
  if (by.provider === "human") return by.actor ?? "a person (unnamed)";
  return `voice (${by.provider}, ${by.confidence}, speaker ${by.actor ?? "unlabelled"})`;
}

function isConfirmed(card: Card, opts: DodOptions): boolean {
  if (card.status !== "confirmed" || card.confirmation === null) return false;
  return !opts.requireHumanConfirm || card.confirmation.by.provider === "human";
}

/** `<kind> <id> confirmed by …` / `<kind> <id> is applied, not confirmed` (+ the human-only note when a voice confirm does not count). */
function confirmationLine(card: Card, opts: DodOptions): { ok: boolean; line: string } {
  if (card.status === "confirmed" && card.confirmation !== null) {
    const line = `${card.kind} ${card.id} confirmed by ${describeBy(card.confirmation.by)}`;
    if (isConfirmed(card, opts)) return { ok: true, line };
    return { ok: false, line: `${line}; a person's confirmation is required` };
  }
  return { ok: false, line: `${card.kind} ${card.id} is ${select.statusLabel(card)}, not confirmed` };
}

function reviewReason(flag: NeedsReview): string {
  switch (flag.reason) {
    case "rule_changed":
      return "rule changed";
    case "rule_removed":
      return "rule removed";
    case "rule_replaced":
      return "rule replaced";
  }
}

function cardLabel(state: MapState, id: string): string {
  const card = state.cards[id];
  return card ? `${card.kind} ${card.id}` : `card ${id}`;
}

/** `removal prop_14 of example card_9 (rules.v1, 0.5)` · `undo prop_21 to revision 6 (claude, 0.8)` · `rejection prop_17 of proposal prop_16 (…)`. */
export function describeAct(state: MapState, record: ProposalRecord): string {
  const p = record.proposal;
  const stamp = `(${p.classifier.provider}, ${p.confidence})`;
  const op = p.operation;
  if (op === null) return `proposal ${p.id} ${stamp}`;
  switch (op.kind) {
    case "card.remove":
      return `removal ${p.id} of ${cardLabel(state, op.card_id)} ${stamp}`;
    case "undo":
      return op.to_revision_seq === null ? `undo ${p.id} (one step back) ${stamp}` : `undo ${p.id} to revision ${op.to_revision_seq} ${stamp}`;
    case "interpretation.reject":
      return `rejection ${p.id} of proposal ${op.proposal_id} ${stamp}`;
    default:
      return `${op.kind} ${p.id} ${stamp}`;
  }
}

function check(id: DodCheckId, pass: boolean, details: string[]): DodCheck {
  return { id, title: TITLES[id], pass, details };
}

function storyRulesConfirmed(state: MapState, opts: DodOptions): DodCheck {
  const stories = select.cardsByKind(state, "story");
  const rules = select.cardsByKind(state, "rule");
  const details: string[] = [];
  let pass = stories.length === 1;
  if (stories.length === 0) details.push("no live story");
  for (const card of [...stories, ...rules]) {
    const result = confirmationLine(card, opts);
    details.push(result.line);
    if (!result.ok) pass = false;
  }
  return check("story_rules_confirmed", pass, details);
}

function examplesReviewed(state: MapState, opts: DodOptions): DodCheck {
  const details: string[] = [];
  let pass = true;
  for (const example of select.cardsByKind(state, "example")) {
    if (example.needs_review !== null) {
      details.push(`example ${example.id} needs review: ${reviewReason(example.needs_review)} (event ${example.needs_review.event_id})`);
      pass = false;
      continue;
    }
    const result = confirmationLine(example, opts);
    details.push(result.line);
    if (!result.ok) pass = false;
  }
  return check("examples_reviewed", pass, details);
}

function liveRuleStatus(state: MapState, example: ExampleCard): string | null {
  if (example.rule_id === null) return `example ${example.id} is not attached to a rule`;
  const rule = state.cards[example.rule_id];
  if (!rule) return `example ${example.id} is attached to rule ${example.rule_id}, which does not exist`;
  if (rule.status !== "applied" && rule.status !== "confirmed") {
    return `example ${example.id} is attached to rule ${rule.id}, which is ${select.statusLabel(rule)}`;
  }
  return null;
}

function changesResolved(state: MapState): DodCheck {
  const details: string[] = [];
  let pass = true;
  for (const id of state.proposal_order) {
    const record = state.proposals[id];
    if (record && (record.status === "pending" || record.status === "clarifying")) {
      details.push(`proposal ${id} is ${record.status}`);
      pass = false;
    }
  }
  for (const clarification of select.openClarifications(state)) {
    details.push(`clarification ${clarification.id} is open: "${clarification.question}"`);
    pass = false;
  }
  for (const id of state.proposal_order) {
    const record = state.proposals[id];
    if (!record || record.proposal.classifier.actor !== null || record.proposal.operation === null) continue;
    if (!select.ACT_KINDS.includes(record.proposal.operation.kind)) continue;
    if (record.status === "applied") {
      details.push(`${describeAct(state, record)} is not reviewed`);
      pass = false;
    } else if (record.status === "confirmed") {
      details.push(`${describeAct(state, record)} is reviewed`);
    }
  }
  for (const example of select.cardsByKind(state, "example")) {
    const problem = liveRuleStatus(state, example);
    if (problem) {
      details.push(problem);
      pass = false;
    }
  }
  for (const question of select.cardsByKind(state, "question")) {
    if (question.about_card_id === null) continue;
    const about = state.cards[question.about_card_id];
    if (!about) {
      details.push(`question ${question.id} is about card ${question.about_card_id}, which does not exist`);
      pass = false;
    } else if (about.status !== "applied" && about.status !== "confirmed") {
      details.push(`question ${question.id} is about ${about.kind} ${about.id}, which is ${select.statusLabel(about)}`);
      pass = false;
    }
  }
  return check("changes_resolved", pass, details);
}

function questionsResolved(state: MapState, opts: DodOptions): DodCheck {
  const details: string[] = [];
  let pass = true;
  for (const question of select.cardsByKind(state, "question")) {
    if (question.answer !== null) {
      if (isConfirmed(question, opts)) {
        details.push(`question ${question.id} answered and confirmed by ${describeBy(question.confirmation!.by)}`);
        continue;
      }
      if (question.accepted_outstanding !== null) {
        details.push(`question ${question.id} accepted outstanding by ${question.accepted_outstanding.by}: ${question.accepted_outstanding.reason}`);
        continue;
      }
      const status = question.status === "confirmed" ? "confirmed by voice; a person's confirmation is required" : `${select.statusLabel(question)}, not confirmed`;
      details.push(`question ${question.id} is answered but ${status}`);
      pass = false;
      continue;
    }
    if (question.accepted_outstanding !== null) {
      details.push(`question ${question.id} accepted outstanding by ${question.accepted_outstanding.by}: ${question.accepted_outstanding.reason}`);
      continue;
    }
    details.push(`question ${question.id} is unanswered`);
    pass = false;
  }
  return check("questions_resolved", pass, details);
}

function finalVersionRecorded(state: MapState): DodCheck {
  const current = select.currentRevision(state);
  const details: string[] = [];
  let pass = true;
  if (current.seq < 1 || current.event_id === null) {
    details.push("no revision has been recorded yet");
    pass = false;
  }
  if (state.head.hash === "") {
    details.push("the chain head is empty");
    pass = false;
  }
  // dodReport has no hasher (its signature is fixed by §5.6); the hash itself is re-checked by replay() on every load,
  // so this check compares the recorded snapshot's canonical form with the live cards structurally.
  if (canonicalJson(canonicalState(current.snapshot)) !== canonicalJson(canonicalState(state.cards))) {
    details.push(`revision ${current.seq} snapshot does not match the live cards`);
    pass = false;
  }
  if (pass) {
    details.push(`revision ${current.seq} (${current.hash}) recorded by event ${current.event_id}; chain head ${state.head.seq} (${state.head.hash})`);
  }
  return check("final_version_recorded", pass, details);
}

export function dodReport(state: MapState, opts: DodOptions = DOD_OPTIONS): DodReport {
  const checks: DodCheck[] = [
    storyRulesConfirmed(state, opts),
    examplesReviewed(state, opts),
    changesResolved(state),
    questionsResolved(state, opts),
    finalVersionRecorded(state),
  ];
  return { pass: checks.every((c) => c.pass), checks };
}

/** The gate: the last sign-off exists, is active, cites the current revision, and the report still passes. */
export function isHumanVerified(state: MapState): boolean {
  const signoff = select.lastSignoff(state);
  if (!signoff || signoff.status !== "active") return false;
  if (signoff.revision.hash !== select.currentRevision(state).hash) return false;
  return dodReport(state).pass;
}
