// exmap/src/classifier/claude/user-message.ts — renderUserMessage(input) (design §6.4): the volatile context of one
// classification, rendered deterministically in a fixed section order with ids verbatim. No timestamps, no session id:
// everything that changes per call lives here so the frozen system block stays cacheable.
import type { CardIndexEntry, ClassifierInput, ClassifierUtterance, LastProposalRef } from "../../core/types.js";

function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** `<label> (<lane>)` when a label was assigned, the lane alone when not, `(typed)` for the manual lane regardless of label. */
export function speakerLine(u: ClassifierUtterance): string {
  if (u.lane === "manual") return "(typed)";
  return u.speaker !== null ? `${u.speaker} (${u.lane})` : `(${u.lane})`;
}

function cardLine(c: CardIndexEntry): string {
  const dash = (v: string | null): string => v ?? "-";
  return [
    c.id, c.kind, c.status, oneLine(c.text),
    `links: rule=${dash(c.links.rule_id)} about=${dash(c.links.about_card_id)}`,
    `answer=${c.answer === null ? "-" : oneLine(c.answer)}`,
    `last: ${dash(c.last_utterance_id)} by ${dash(c.last_speaker)}`,
    `made by ${dash(c.proposal_id)}`,
  ].join(" | ");
}

function refLine(r: LastProposalRef): string {
  return `${r.id} intent=${r.intent} op=${r.op} status=${r.status} cards=${r.card_ids.length ? r.card_ids.join(",") : "-"} from=${r.utterance_id} rejectable=${r.rejectable ? "yes" : "no"}`;
}

function utteranceLine(u: ClassifierUtterance): string {
  return `[${u.id}] ${speakerLine(u)}: ${oneLine(u.text)}`;
}

export function renderUserMessage(input: ClassifierInput): string {
  const lines: string[] = [];
  lines.push("## CARD INDEX");
  if (input.cards.length === 0) lines.push("(none)");
  for (const c of input.cards) lines.push(cardLine(c));
  lines.push("");
  lines.push("## LAST PROPOSAL");
  lines.push(input.last_proposal ? refLine(input.last_proposal) : "(none)");
  lines.push("## LAST REJECTABLE");
  if (!input.last_rejectable) lines.push("(none)");
  else if (input.last_proposal && input.last_rejectable.id === input.last_proposal.id) lines.push("(same as last proposal)");
  else lines.push(refLine(input.last_rejectable));
  lines.push("");
  lines.push("## PENDING CLARIFICATION");
  const pc = input.pending_clarification;
  if (!pc) lines.push("(none)");
  else {
    lines.push(`kind=${pc.kind} proposal=${pc.proposal_id} question=${JSON.stringify(pc.question)}`);
    if (pc.candidates.length > 0) lines.push(`candidates: ${pc.candidates.map((c, i) => `${i + 1}. ${c.card_id} — ${oneLine(c.label)}`).join(" | ")}`);
    lines.push(`pending_operations: ${JSON.stringify(pc.pending_operations)}`);
  }
  lines.push("");
  lines.push("## RECENT UTTERANCES (oldest first)");
  if (input.recent.length === 0) lines.push("(none)");
  for (const u of input.recent) lines.push(utteranceLine(u));
  lines.push("");
  lines.push("## NEW UTTERANCE");
  lines.push(utteranceLine(input.utterance));
  return lines.join("\n");
}
