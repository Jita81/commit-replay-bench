// TEST-PLAN §5.2 — backlog-item.test.ts: crb's BacklogItem (brief §3) from the verified fixture; the id rule, title
// truncation, description, acceptance-criteria lines, structural facts, labels, registered, determinism; plus the text
// helpers the id and the AC lines rest on.
import { describe, expect, it } from "vitest";
import type { BacklogItem } from "../../../src/core/types.js";
import { backlogItem, buildExportContext, exportFile, parseGwt, slugify, storyTitle, titleOf } from "../../../src/export/index.js";
import type { ExportContext } from "../../../src/export/index.js";
import {
  ACCEPT_REASON, ANSWER_MESSAGE, EX_FREE, NOW, OPTIONS, OPTIONS_2, RULE_24H, RULE_OVERRIDE, SESSION, STORY_TEXT, buildState, input, story,
  verifiedState,
} from "./fixtures.js";

const CRB_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function ctxOf(state = verifiedState({ options: [OPTIONS] }), draft = false): ExportContext {
  const result = buildExportContext(input(state, draft));
  if (!result.ok) throw new Error(`fixture not exportable: ${result.signoff.status}`);
  return result.ctx;
}

describe("text helpers", () => {
  it("slugify: NFKD, ASCII letters/digits, lowercase, runs of other chars to '-', leading '-' removed", () => {
    expect(slugify("A patient can cancel, but not within two hours.")).toBe("a-patient-can-cancel-but-not-within-two-hours-");
    expect(slugify("  --Hello World!! ")).toBe("hello-world-");
    expect(slugify("Café déjà vu")).toBe("cafe-deja-vu");
    expect(slugify("!!!")).toBe("");
    expect(slugify("")).toBe("");
  });

  it("storyTitle: first sentence, no full stop, 120 chars at a word boundary; null without a story", () => {
    expect(storyTitle(null)).toBeNull();
    expect(storyTitle(story("card_1", 1, "First sentence. Second sentence."))).toBe("First sentence");
    expect(storyTitle(story("card_1", 1, "First line\nsecond line"))).toBe("First line");
    expect(storyTitle(story("card_1", 1, "Ends with a stop.\nMore"))).toBe("Ends with a stop");
    expect(storyTitle(story("card_1", 1, STORY_TEXT))).toBe("A patient can cancel an appointment online, but not within two hours");
    const long = "word ".repeat(40).trim(); // 199 chars, no sentence break
    const title = storyTitle(story("card_1", 1, long))!;
    expect(title.length).toBeLessThanOrEqual(120);
    expect(title.endsWith("word")).toBe(true);
    expect(long.startsWith(`${title} `)).toBe(true);
    expect(titleOf("x".repeat(130), 120)).toHaveLength(120); // no boundary at all: hard cut
    expect(titleOf("Given a thing, when it happens, then it is refused under the twenty-four hour rule of the practice", 80)).toBe(
      "Given a thing, when it happens, then it is refused under the twenty-four hour",
    );
  });

  it("parseGwt: given/when/then, if/then, when-opener, keyword cleanup; null for anything else", () => {
    expect(parseGwt("Given a nurse appointment at 10am, when the patient cancels at 9am, then it is refused.")).toEqual({
      given: "a nurse appointment at 10am", when: "the patient cancels at 9am", then: "it is refused",
    });
    expect(parseGwt("If a GP appointment is at 10am and they cancel at 7am then it is allowed.")).toEqual({
      given: "a GP appointment is at 10am and they cancel at 7am", when: null, then: "it is allowed",
    });
    expect(parseGwt("Given the service is down, and when the patient cancels, and then they see a retry message")).toEqual({
      given: "the service is down", when: "the patient cancels", then: "they see a retry message",
    });
    expect(parseGwt("GIVEN   a thing\n  WHEN it\thappens THEN it works.")).toEqual({ given: "a thing", when: "it happens", then: "it works" });
    expect(parseGwt("When the service is down, then the patient sees a retry message.")).toEqual({
      given: "the service is down", when: null, then: "the patient sees a retry message",
    });
    expect(parseGwt("Given X then Y when Z")).toEqual({ given: "X", when: null, then: "Y when Z" }); // a "when" after "then" is prose
    expect(parseGwt("For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused.")).toBeNull();
    expect(parseGwt("Given a thing happens without a consequence")).toBeNull();
    expect(parseGwt("Given, when, then.")).toBeNull();
    expect(parseGwt("Given X when then Y")).toBeNull();
    expect(parseGwt("Whenever it rains then it pours")).toBeNull();
    expect(parseGwt("")).toBeNull();
  });
});

describe("backlogItem — id and title", () => {
  it("builds the id from the story: a 48-char slug cap with no trailing '-', then -<hash8>", () => {
    const ctx = ctxOf();
    const hash8 = ctx.revision.hash.slice(0, 8);
    expect(hash8).toMatch(/^[0-9a-f]{8}$/);
    const item = backlogItem(ctx);
    expect(item.id).toBe(`a-patient-can-cancel-an-appointment-online-but-n-${hash8}`);
    expect(item.id).toMatch(CRB_ID);
    expect(item.id.length).toBeLessThanOrEqual(64);
    expect(item.title).toBe("A patient can cancel an appointment online, but not within two hours");
  });

  it("a draft id carries -draft- before the hash and still matches crb's regex within 64 chars", () => {
    const ctx = ctxOf(verifiedState(), true);
    const item = backlogItem(ctx);
    expect(item.id).toBe(`a-patient-can-cancel-an-appointment-online-but-n-draft-${ctx.revision.hash.slice(0, 8)}`);
    expect(item.id).toMatch(CRB_ID);
    expect(item.id.length).toBeLessThanOrEqual(64);
    expect(item.id).toHaveLength(63); // the worst case: 48 + "-draft" + "-" + 8
    expect(item.title.startsWith("[DRAFT / NOT VERIFIED] ")).toBe(true);
    expect(item.labels.exmap_draft).toBe("true");
  });

  it("a punctuation-only story yields exmap-<hash8>", () => {
    const state = verifiedState();
    const punctuation = { ...state.cards.card_1!, text: "!!!" };
    state.cards = { ...state.cards, card_1: punctuation };
    state.revisions[1] = { ...state.revisions[1]!, snapshot: { ...state.revisions[1]!.snapshot, card_1: { ...state.revisions[1]!.snapshot.card_1!, text: "!!!" } } };
    const result = buildExportContext(input(state, true)); // the revision hash no longer matches, so only a draft is honest
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.itemId).toMatch(/^exmap-draft-[0-9a-f]{8}$/);
    const verified = buildExportContext(input(buildState([story("card_1", 1, "...")]), true));
    if (!verified.ok) throw new Error("unreachable");
    expect(verified.ctx.itemId).toMatch(/^exmap-draft-[0-9a-f]{8}$/);
  });

  it("truncates a long story title at a word boundary", () => {
    const text = "The practice wants every online cancellation to be refused inside the window and allowed outside it for every clinician type including locums";
    const result = buildExportContext(input(buildState([story("card_1", 1, text)]), true));
    if (!result.ok) throw new Error("unreachable");
    const title = result.ctx.title.replace("[DRAFT / NOT VERIFIED] ", "");
    expect(title.length).toBeLessThanOrEqual(120);
    expect(text.startsWith(`${title} `)).toBe(true);
    expect(result.ctx.itemId).toMatch(/^the-practice-wants-every-online-cancellation-to-draft-[0-9a-f]{8}$/);
  });
});

describe("backlogItem — content", () => {
  it("description holds the story, then Rules:, then Definitions: (deduplicated, sorted)", () => {
    const item = backlogItem(ctxOf());
    expect(item.description).toBe(
      `${STORY_TEXT}\n\nRules:\n- ${RULE_24H}\n- ${RULE_OVERRIDE}\n\nDefinitions:\n- appointment: a booked slot, not a walk-in\n- cancellation window: the period before the appointment in which online cancellation is refused`,
    );
  });

  it("description omits Rules: and Definitions: when there are none", () => {
    const result = buildExportContext(input(buildState([story("card_1", 1, "Just a story")]), true));
    if (!result.ok) throw new Error("unreachable");
    expect(backlogItem(result.ctx).description).toBe("Just a story");
  });

  it("acceptance criteria: parsed examples as Given/when/then, if-then without when, free text as Example:, facts last", () => {
    const item = backlogItem(ctxOf());
    expect(item.acceptance_criteria).toEqual([
      "Given a nurse appointment at 10am, when the patient cancels at 9am, then it is refused",
      "Given a GP appointment is at 10am and they cancel at 7am, then it is allowed",
      `Example: ${EX_FREE}`,
      "Given a receptionist opens a booking inside the window, when they try to cancel it, then the system refuses and shows the rule",
      "route_identity: PUT /appointments/{id}/cancel",
    ]);
    expect(item.acceptance_criteria).toContain(
      "Example: For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused under the 24-hour rule.",
    );
  });

  it("structural_facts are the fact lines verbatim; options drive kind, class and size", () => {
    const item = backlogItem(ctxOf(verifiedState({ options: [OPTIONS, OPTIONS_2] })));
    expect(item.structural_facts).toEqual(["route_identity: PUT /appointments/{id}/cancel", "behaviour_change: The GP window becomes three hours."]);
    expect(item.acceptance_criteria.slice(-2)).toEqual(item.structural_facts);
    expect(item.kind).toBe("code");
    expect(item.capability_class).toBe("backend.route.edit");
    expect(item.size_estimate).toBe("S");
    expect(item.labels.exmap_export_options_seq).toBe("2");
  });

  it("defaults: unclassified / code / unsized, no facts, options seq 0", () => {
    const item = backlogItem(ctxOf(verifiedState()));
    expect(item.capability_class).toBe("unclassified");
    expect(item.kind).toBe("code");
    expect(item.size_estimate).toBe("unsized");
    expect(item.structural_facts).toEqual([]);
    expect(item.acceptance_criteria).toHaveLength(4);
    expect(item.labels.exmap_export_options_seq).toBe("0");
  });

  it("fixed fields and labels: depends_on [], L1, supersedes '', registered === now, session / revision / signoff / reviewer", () => {
    const ctx = ctxOf();
    const item = backlogItem(ctx);
    expect(item.depends_on).toEqual([]);
    expect(item.level).toBe("L1");
    expect(item.supersedes).toBe("");
    expect(item.registered).toBe(NOW);
    expect(item.labels).toEqual({
      exmap_session: SESSION.id,
      exmap_revision: ctx.revision.hash,
      exmap_signoff: "sig_1",
      exmap_export_options_seq: "1",
      exmap_reviewer: "Sam",
      exmap_signed_at: "2026-10-16T12:20:00.000Z",
    });
    expect(item.labels.exmap_revision).toMatch(/^[0-9a-f]{64}$/);
    expect(item.labels.exmap_signoff).not.toBe("");
  });

  it("an unverified draft has an empty exmap_signoff and no reviewer labels", () => {
    const result = buildExportContext(input(buildState([story("card_1", 1, "A story")]), true));
    if (!result.ok) throw new Error("unreachable");
    const item = backlogItem(result.ctx);
    expect(item.labels.exmap_signoff).toBe("");
    expect(item.labels.exmap_draft).toBe("true");
    expect(item.labels).not.toHaveProperty("exmap_reviewer");
    expect(item.labels).not.toHaveProperty("exmap_signed_at");
    expect(item.description).toBe("A story");
  });

  it("the shape has exactly crb's BacklogItem keys", () => {
    const item = backlogItem(ctxOf());
    expect(Object.keys(item).sort()).toEqual([
      "acceptance_criteria", "capability_class", "depends_on", "description", "id", "kind", "labels", "level", "registered", "size_estimate",
      "structural_facts", "supersedes", "title",
    ]);
  });

  it("is deterministic and the file body round-trips the item", () => {
    const a = backlogItem(ctxOf());
    const b = backlogItem(ctxOf());
    expect(a).toEqual(b);
    const file = exportFile(input(verifiedState({ options: [OPTIONS] })), "crb-backlog-item.json");
    if (!file.ok) throw new Error("unreachable");
    expect(JSON.parse(file.body) as BacklogItem).toEqual(a);
    expect(file.body.endsWith("\n")).toBe(true);
  });

  it("never says 'answered' about the accepted question anywhere in the item", () => {
    const text = JSON.stringify(backlogItem(ctxOf()));
    expect(text).not.toContain(ACCEPT_REASON); // questions are not part of the backlog item at all
    expect(text).not.toContain(ANSWER_MESSAGE);
  });
});
