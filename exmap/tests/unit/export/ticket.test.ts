// TEST-PLAN §5.3 — ticket.test.ts: crb's intake Ticket (brief §3) and ticket.md (design §12.3).
import { describe, expect, it } from "vitest";
import type { SizeEstimate, Ticket } from "../../../src/core/types.js";
import { POINTS_FOR_SIZE, backlogItem, buildExportContext, exportFile, ticket, ticketMarkdown } from "../../../src/export/index.js";
import type { ExportContext } from "../../../src/export/index.js";
import {
  ACCEPT_REASON, ACCEPT_REASON_2, ANSWER_MESSAGE, EX_FREE, OPTIONS, OPTIONS_2, Q_AUDIT, Q_DENTIST, Q_MESSAGE, Q_RETRY, Q_TWICE, RULE_24H,
  RULE_OVERRIDE, SESSION, STORY_TEXT, buildState, draftState, input, invalidatedState, question, rule, story, verifiedState,
} from "./fixtures.js";

function ctxOf(state = verifiedState({ options: [OPTIONS] }), draft = false): ExportContext {
  const result = buildExportContext(input(state, draft));
  if (!result.ok) throw new Error(`fixture not exportable: ${result.signoff.status}`);
  return result.ctx;
}

const ACCEPTED_HEADING = "## Open questions explicitly accepted as outstanding";

function section(md: string, heading: string): string | null {
  const start = md.indexOf(`${heading}\n`);
  if (start === -1) return null;
  const rest = md.slice(start + heading.length + 1);
  const next = rest.search(/\n## /);
  return next === -1 ? rest : rest.slice(0, next);
}

describe("ticket.json", () => {
  it("body is a newline-joined string with the story, rules, definitions, size, verification, options and source", () => {
    const ctx = ctxOf();
    const t = ticket(ctx);
    expect(typeof t.body).toBe("string");
    expect(t.body).toContain("\n");
    const lines = t.body.split("\n");
    expect(lines[0]).toBe(STORY_TEXT);
    expect(lines[1]).toBe("");
    expect(lines.slice(2, 5)).toEqual(["Rules:", `- ${RULE_24H}`, `- ${RULE_OVERRIDE}`]);
    expect(lines).toContain("Definitions:");
    expect(lines).toContain("- appointment: a booked slot, not a walk-in");
    expect(lines).toContain("Size estimate: M (story points 8 encode this tier for crb)");
    expect(lines).toContain(
      `Verification: reviewed by Sam at 2026-10-16T12:20:00.000Z; requirement revision ${ctx.revision.hash}; evidence head 39/${ctx.signoff!.evidence.head_hash.slice(0, 8)}`,
    );
    expect(lines).toContain("Export options: supplied by Sam at 2026-10-16T12:25:00.000Z (change 1); outside the sign-off");
    expect(lines[lines.length - 1]).toBe(`Source: exmap session ${SESSION.id}`);
    expect(t.body.startsWith("DRAFT")).toBe(false);
  });

  it("key, title, type and acceptance criteria match the backlog item", () => {
    const ctx = ctxOf();
    const t = ticket(ctx);
    const item = backlogItem(ctx);
    expect(t.key).toBe(item.id);
    expect(t.title).toBe(item.title);
    expect(t.type).toBe("User Story");
    expect(t.acceptance_criteria).toEqual(item.acceptance_criteria);
    expect(t.acceptance_criteria).toContain(`Example: ${EX_FREE}`);
    expect(t.acceptance_criteria).toContain("route_identity: PUT /appointments/{id}/cancel");
  });

  it("tags include crb:class= and crb:kind=, the revision and the session; exmap:draft only on drafts", () => {
    const ctx = ctxOf();
    expect(ticket(ctx).tags).toEqual([
      "crb:class=backend.route.edit", "crb:kind=code", `exmap:revision=${ctx.revision.hash.slice(0, 8)}`, `exmap:session=${SESSION.id}`,
    ]);
    const draft = ticket(ctxOf(verifiedState(), true));
    expect(draft.tags).toContain("exmap:draft");
    expect(draft.tags).toContain("crb:class=unclassified");
    expect(draft.tags).toContain("crb:kind=code");
  });

  it("points encode the size so crb's tiers agree: XS 1, S 3, M 8, L 20, XL 21, unsized null", () => {
    expect(POINTS_FOR_SIZE).toEqual({ XS: 1, S: 3, M: 8, L: 20, XL: 21, unsized: null });
    const sizes: SizeEstimate[] = ["XS", "S", "M", "L", "XL", "unsized"];
    for (const size of sizes) {
      const t = ticket(ctxOf(verifiedState({ options: [{ ...OPTIONS, size_estimate: size }] })));
      expect(t.points).toBe(POINTS_FOR_SIZE[size]);
      const crbTier = t.points === null ? "unsized" : t.points <= 1 ? "XS" : t.points <= 3 ? "S" : t.points <= 8 ? "M" : t.points <= 20 ? "L" : "XL";
      expect(crbTier).toBe(size);
      expect(t.body).toContain(size === "unsized" ? "Size estimate: unsized" : `Size estimate: ${size} (story points ${t.points} encode this tier for crb)`);
    }
  });

  it("author, url, state are empty and links [] (the tracker fills them)", () => {
    const t = ticket(ctxOf());
    expect(t.author).toBe("");
    expect(t.url).toBe("");
    expect(t.state).toBe("");
    expect(t.links).toEqual([]);
    expect(Object.keys(t).sort()).toEqual(["acceptance_criteria", "author", "body", "key", "links", "points", "state", "tags", "title", "type", "url"]);
  });

  it("a draft body opens with the banner and names the failing checks; no export-options line at seq 0", () => {
    const t = ticket(ctxOf(draftState(), true));
    const lines = t.body.split("\n");
    expect(lines[0]).toBe("DRAFT / NOT VERIFIED — failing checks: story_rules_confirmed, examples_reviewed, changes_resolved, questions_resolved");
    expect(lines).toContain("Verification: NOT VERIFIED");
    expect(lines).toContain("Size estimate: unsized");
    expect(lines.some((l) => l.startsWith("Export options:"))).toBe(false);
    expect(t.points).toBeNull();
  });

  it("the file body round-trips the ticket", () => {
    const file = exportFile(input(verifiedState({ options: [OPTIONS] })), "ticket.json");
    if (!file.ok) throw new Error("unreachable");
    expect(JSON.parse(file.body) as Ticket).toEqual(ticket(ctxOf()));
  });
});

describe("ticket.md", () => {
  it("has the title, story, rules, definitions, acceptance criteria and structural facts sections", () => {
    const md = ticketMarkdown(ctxOf(verifiedState({ options: [OPTIONS, OPTIONS_2] })));
    expect(md.startsWith("# A patient can cancel an appointment online, but not within two hours\n")).toBe(true);
    expect(md).toContain(`**Story.** ${STORY_TEXT}`);
    expect(section(md, "## Rules")).toContain(`- ${RULE_24H}\n- ${RULE_OVERRIDE}`);
    expect(section(md, "## Definitions")).toContain("- **appointment** — a booked slot, not a walk-in");
    expect(section(md, "## Acceptance criteria")).toContain(`- Example: ${EX_FREE}`);
    expect(section(md, "## Acceptance criteria")).toContain("- route_identity: PUT /appointments/{id}/cancel");
    const facts = section(md, "## Structural facts (crb)")!;
    expect(facts).toContain("- `route_identity: PUT /appointments/{id}/cancel`");
    expect(facts).toContain("- `behaviour_change: The GP window becomes three hours.`");
    expect(facts).toContain("_Supplied at export by Sam at 2026-10-16T12:26:00.000Z (change 2 of 2); outside the sign-off._");
    expect(md.endsWith("\n")).toBe(true);
    expect(md.endsWith("\n\n")).toBe(false);
  });

  it("omits the structural-facts section and says so for rules when there are none", () => {
    const md = ticketMarkdown(ctxOf(buildState([story("card_1", 1, "A story")]), true));
    expect(md).not.toContain("## Structural facts");
    expect(md).not.toContain("## Definitions");
    expect(section(md, "## Rules")).toContain("_No rules recorded._");
    expect(section(md, "## Acceptance criteria")).toContain("_No examples or facts recorded._");
  });

  it("contains the accepted-outstanding section iff a question is accepted, and never says 'answered' there", () => {
    const md = ticketMarkdown(ctxOf());
    expect(md).toContain(ACCEPTED_HEADING);
    const accepted = section(md, ACCEPTED_HEADING)!;
    expect(accepted).toContain(`- ${Q_DENTIST} — accepted as outstanding by Sam: ${ACCEPT_REASON} (no answer recorded)`);
    expect(accepted).toContain(`- ${Q_TWICE} — accepted as outstanding by Sam: ${ACCEPT_REASON_2} (no answer recorded)`);
    expect(accepted).toContain("practice manager");
    expect(accepted.toLowerCase()).not.toContain("answered");
    expect(accepted).not.toContain(Q_MESSAGE);
    const answered = section(md, "## Answered questions")!;
    expect(answered).toContain(`- ${Q_MESSAGE} — ${ANSWER_MESSAGE}`);
    expect(answered).not.toContain("not confirmed");

    const none = ticketMarkdown(ctxOf(buildState([story("card_1", 1, "A story"), rule("card_2", 2, "A rule"), question("card_8", 8, "Open?", "card_2")]), true));
    expect(none).not.toContain(ACCEPTED_HEADING);
    expect(none).not.toContain("## Answered questions");
  });

  it("an accepted question that also carries an unconfirmed answer stays in the accepted section without 'answered'", () => {
    const state = buildState([
      story("card_1", 1, "A story"),
      question("card_8", 8, "Which window?", null, { answer: "Two hours", accepted: { by: "Sam", reason: "The classifier's answer was not checked" } }, { confirmed: false }),
    ]);
    const md = ticketMarkdown(ctxOf(state, true));
    const accepted = section(md, ACCEPTED_HEADING)!;
    expect(accepted).toContain("- Which window? — accepted as outstanding by Sam: The classifier's answer was not checked (an unconfirmed answer is recorded: Two hours)");
    expect(accepted.toLowerCase()).not.toContain("answered");
    expect(md).not.toContain("## Answered questions");
  });

  it("shows the draft banner iff draft, with the failing checks (or the honest note on a verified map)", () => {
    const draft = ticketMarkdown(ctxOf(draftState(), true));
    expect(draft.split("\n")[1]).toBe(
      "> DRAFT / NOT VERIFIED — this requirement has not passed human verification. Failing checks: story_rules_confirmed, examples_reviewed, changes_resolved, questions_resolved.",
    );
    expect(draft).toContain("# [DRAFT / NOT VERIFIED] A patient cancels an appointment online");
    const verified = ticketMarkdown(ctxOf());
    expect(verified).not.toContain("> DRAFT");
    expect(verified).not.toContain("NOT VERIFIED");
    const draftOfVerified = ticketMarkdown(ctxOf(verifiedState(), true));
    expect(draftOfVerified.split("\n")[1]).toBe("> DRAFT / NOT VERIFIED — exported as a draft at the caller's request; the map is human-verified and no check fails.");
  });

  it("lists unresolved questions only on drafts", () => {
    const draft = ticketMarkdown(ctxOf(draftState(), true));
    expect(section(draft, "## Unresolved questions")).toContain(`- ${Q_AUDIT}`);
    expect(section(draft, ACCEPTED_HEADING)).toContain(`- ${Q_RETRY} — accepted as outstanding by Priya: UX to decide (no answer recorded)`);
    expect(ticketMarkdown(ctxOf())).not.toContain("## Unresolved questions");
    expect(ticketMarkdown(ctxOf(verifiedState(), true))).not.toContain("## Unresolved questions");
  });

  it("the verification paragraph names the reviewer, the revision and the evidence head; drafts say NOT VERIFIED with the details", () => {
    const ctx = ctxOf();
    const md = ticketMarkdown(ctx);
    const verification = section(md, "## Verification")!;
    expect(verification).toContain(
      `Reviewed by **Sam** at 2026-10-16T12:20:00.000Z. Requirement revision \`${ctx.revision.hash}\`. Evidence head \`39\` / \`${ctx.signoff!.evidence.head_hash}\`. exmap session \`${SESSION.id}\`.`,
    );
    expect(verification).toContain("Tags: `crb:class=backend.route.edit` `crb:kind=code` `exmap:revision=");

    const draft = section(ticketMarkdown(ctxOf(draftState(), true)), "## Verification")!;
    expect(draft).toContain("**NOT VERIFIED.** Failing checks:");
    expect(draft).toContain("- `story_rules_confirmed` — story card_1 is applied, not confirmed; rule card_2 is applied, not confirmed");
    expect(draft).toContain("- `questions_resolved` — ");
    expect(draft).toContain("`exmap:draft`");

    const invalidated = section(ticketMarkdown(ctxOf(invalidatedState(), true)), "## Verification")!;
    expect(invalidated).toContain("**NOT VERIFIED.**");
    expect(invalidated).not.toContain("Reviewed by");
  });

  it("escapes a leading #, > or - and backticks in card text", () => {
    const state = buildState([
      story("card_1", 1, "# not a heading\n> not a quote"),
      rule("card_2", 2, "- not a list item with `code`"),
    ]);
    const md = ticketMarkdown(ctxOf(state, true));
    expect(md).toContain("**Story.** \\# not a heading\n\\> not a quote");
    expect(section(md, "## Rules")).toContain("- \\- not a list item with \\`code\\`");
  });

  it("the ticket.md file body equals ticketMarkdown and is text/markdown", () => {
    const file = exportFile(input(verifiedState({ options: [OPTIONS] })), "ticket.md");
    if (!file.ok) throw new Error("unreachable");
    expect(file.content_type).toBe("text/markdown; charset=utf-8");
    expect(file.body).toBe(ticketMarkdown(ctxOf()));
  });
});
