// exmap/src/export/ticket.ts — ticket.json (crb's intake Ticket, brief §3) and ticket.md (design §12.3). `body` is a
// newline-joined string because crb's Ticket dataclass declares `body: str`. The tracker fills links / url / state /
// author; a guess here would be pretending. Points encode the chosen size so crb's points->size tiers land on the same
// value (≤1 XS, ≤3 S, ≤8 M, ≤20 L, else XL; no points -> unsized).
import type { DodCheck, SizeEstimate, Ticket } from "../core/types.js";
import { acceptanceCriteria, definitionsOf, factLine } from "./backlog-item.js";
import type { ExportContext } from "./index.js";
import { acceptedNote, answeredNote, groupQuestions } from "./questions.js";
import { DRAFT_WATERMARK, mdEscape, oneLine } from "./text.js";

export const POINTS_FOR_SIZE: Readonly<Record<SizeEstimate, number | null>> = { XS: 1, S: 3, M: 8, L: 20, XL: 21, unsized: null };

export function failingChecks(ctx: ExportContext): DodCheck[] {
  return ctx.dod.checks.filter((c) => !c.pass);
}

/** "a, b" of the failing check ids, or the honest note when a draft was requested on a verified map. */
export function failingCheckSummary(ctx: ExportContext): string {
  const failing = failingChecks(ctx);
  if (failing.length > 0) return failing.map((c) => c.id).join(", ");
  return ctx.verified ? "none (the map is human-verified; the draft flag was requested)" : "none";
}

/** Tags crb reads (`crb:class=`, `crb:kind=`) plus exmap's provenance tags. */
export function ticketTags(ctx: ExportContext): string[] {
  const tags = [
    `crb:class=${ctx.options.capability_class}`,
    `crb:kind=${ctx.options.kind}`,
    `exmap:revision=${ctx.revision.hash.slice(0, 8)}`,
    `exmap:session=${ctx.session.id}`,
  ];
  if (ctx.draft) tags.push("exmap:draft");
  return tags;
}

function sizeLine(ctx: ExportContext): string {
  const size = ctx.options.size_estimate;
  const points = POINTS_FOR_SIZE[size];
  return points === null ? "Size estimate: unsized" : `Size estimate: ${size} (story points ${points} encode this tier for crb)`;
}

function verificationLine(ctx: ExportContext): string {
  const s = ctx.verified ? ctx.signoff : null;
  if (!s) return "Verification: NOT VERIFIED";
  return `Verification: reviewed by ${s.reviewer.name} at ${s.at}; requirement revision ${ctx.revision.hash}; evidence head ${s.evidence.head_seq}/${s.evidence.head_hash.slice(0, 8)}`;
}

export function ticket(ctx: ExportContext): Ticket {
  const lines: string[] = [];
  if (ctx.draft) lines.push(`${DRAFT_WATERMARK} — failing checks: ${failingCheckSummary(ctx)}`);
  lines.push(ctx.story ? ctx.story.text : "No story card is recorded in this session.");
  lines.push("");
  if (ctx.rules.length > 0) {
    lines.push("Rules:");
    for (const rule of ctx.rules) lines.push(`- ${oneLine(rule.text)}`);
  } else {
    lines.push("Rules: none recorded.");
  }
  const definitions = definitionsOf(ctx);
  if (definitions.length > 0) {
    lines.push("Definitions:");
    for (const d of definitions) lines.push(`- ${d.term}: ${d.definition}`);
  }
  lines.push("");
  lines.push(sizeLine(ctx));
  lines.push(verificationLine(ctx));
  if (ctx.options.seq !== 0) {
    lines.push(`Export options: supplied by ${ctx.options.by} at ${ctx.options.at} (change ${ctx.options.seq}); outside the sign-off`);
  }
  lines.push(`Source: exmap session ${ctx.session.id}`);
  return {
    key: ctx.itemId,
    title: ctx.title,
    body: lines.join("\n"),
    acceptance_criteria: acceptanceCriteria(ctx),
    type: "User Story",
    tags: ticketTags(ctx),
    points: POINTS_FOR_SIZE[ctx.options.size_estimate],
    links: [],
    url: "",
    state: "",
    author: "",
  };
}

const md = (text: string): string => mdEscape(oneLine(text));

export function ticketMarkdown(ctx: ExportContext): string {
  const out: string[] = [];
  out.push(`# ${mdEscape(ctx.title)}`);
  if (ctx.draft) {
    const banner = ctx.verified && failingChecks(ctx).length === 0
      ? `> ${DRAFT_WATERMARK} — exported as a draft at the caller's request; the map is human-verified and no check fails.`
      : `> ${DRAFT_WATERMARK} — this requirement has not passed human verification. Failing checks: ${failingCheckSummary(ctx)}.`;
    out.push(banner);
  }
  out.push("");
  out.push(`**Story.** ${ctx.story ? mdEscape(ctx.story.text) : "_No story card is recorded in this session._"}`);
  out.push("");
  out.push("## Rules");
  if (ctx.rules.length > 0) for (const rule of ctx.rules) out.push(`- ${md(rule.text)}`);
  else out.push("_No rules recorded._");

  const definitions = definitionsOf(ctx);
  if (definitions.length > 0) {
    out.push("", "## Definitions");
    for (const d of definitions) out.push(`- **${md(d.term)}** — ${md(d.definition)}`);
  }

  out.push("", "## Acceptance criteria");
  const criteria = acceptanceCriteria(ctx);
  if (criteria.length > 0) for (const line of criteria) out.push(`- ${mdEscape(line)}`);
  else out.push("_No examples or facts recorded._");

  if (ctx.options.facts.length > 0) {
    out.push("", "## Structural facts (crb)");
    for (const fact of ctx.options.facts) out.push(`- \`${factLine(fact).replace(/`/g, "'")}\``);
    out.push("", `_Supplied at export by ${md(ctx.options.by)} at ${ctx.options.at} (change ${ctx.options.seq} of ${ctx.optionsHistory.length}); outside the sign-off._`);
  }

  const groups = groupQuestions(ctx.questions);
  if (groups.accepted.length > 0) {
    out.push("", "## Open questions explicitly accepted as outstanding");
    for (const q of groups.accepted) out.push(`- ${md(q.text)} — ${mdEscape(acceptedNote(q))}`);
  }
  if (groups.answered.length > 0) {
    out.push("", "## Answered questions");
    for (const q of groups.answered) out.push(`- ${md(q.text)} — ${mdEscape(answeredNote(q))}`);
  }
  if (groups.unresolved.length > 0) {
    out.push("", "## Unresolved questions");
    for (const q of groups.unresolved) out.push(`- ${md(q.text)}`);
  }

  out.push("", "## Verification");
  const s = ctx.verified ? ctx.signoff : null;
  if (s) {
    out.push(
      `Reviewed by **${md(s.reviewer.name)}** at ${s.at}. Requirement revision \`${ctx.revision.hash}\`. ` +
        `Evidence head \`${s.evidence.head_seq}\` / \`${s.evidence.head_hash}\`. exmap session \`${ctx.session.id}\`.`,
    );
  } else {
    const failing = failingChecks(ctx);
    if (failing.length === 0) {
      out.push(`**NOT VERIFIED.** No check fails, but no active sign-off cites revision \`${ctx.revision.hash}\`.`);
    } else {
      out.push("**NOT VERIFIED.** Failing checks:");
      for (const check of failing) out.push(`- \`${check.id}\` — ${check.details.map((d) => mdEscape(d)).join("; ")}`);
    }
  }
  out.push("");
  out.push(`Tags: ${ticketTags(ctx).map((t) => `\`${t}\``).join(" ")}`);
  return out.join("\n") + "\n";
}
