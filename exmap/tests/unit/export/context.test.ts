// TEST-PLAN §5.1 — context.test.ts: the gate's refusal shapes, draft on a verified map, option defaults, the context itself.
import { describe, expect, it } from "vitest";
import { isHumanVerified } from "../../../src/core/index.js";
import { CONTENT_TYPES, DRAFT_WATERMARK, EXPORT_FILES, REFUSAL_DETAIL, buildExportContext, exportFile } from "../../../src/export/index.js";
import {
  NOW, OPTIONS, OPTIONS_2, SESSION, activeButDodFailedState, draftState, input, invalidatedState, staleState, storyOnlyState, verifiedState,
} from "./fixtures.js";

describe("buildExportContext — the gate", () => {
  it("the verified fixture passes core's gate (sanity for every other test)", () => {
    expect(isHumanVerified(verifiedState())).toBe(true);
    expect(isHumanVerified(draftState())).toBe(false);
  });

  it("refuses an unverified map with NOT_HUMAN_VERIFIED, the checks and signoff.status none", () => {
    const result = buildExportContext(input(draftState()));
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.reason).toBe("NOT_HUMAN_VERIFIED");
    expect(result.detail).toBe(REFUSAL_DETAIL);
    expect(result.checks.pass).toBe(false);
    expect(result.checks.checks.map((c) => c.id)).toEqual([
      "story_rules_confirmed", "examples_reviewed", "changes_resolved", "questions_resolved", "final_version_recorded",
    ]);
    expect(result.checks.checks.filter((c) => !c.pass).map((c) => c.id)).toEqual([
      "story_rules_confirmed", "examples_reviewed", "changes_resolved", "questions_resolved",
    ]);
    expect(result.signoff).toEqual({ status: "none" });
  });

  it("names an invalidated sign-off with its id, revision and invalidated_by_event_id", () => {
    const state = invalidatedState();
    expect(isHumanVerified(state)).toBe(false);
    const result = buildExportContext(input(state));
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.signoff.status).toBe("invalidated");
    expect(result.signoff.id).toBe("sig_1");
    expect(result.signoff.revision).toEqual(state.signoffs[0]!.revision);
    expect(result.signoff.invalidated_by_event_id).toBe("evt_41");
    expect(result.checks.checks.find((c) => c.id === "story_rules_confirmed")!.pass).toBe(false);
  });

  it("reports active_but_dod_failed when the sign-off is on the current revision but check 3 regressed", () => {
    const state = activeButDodFailedState();
    expect(isHumanVerified(state)).toBe(false);
    const result = buildExportContext(input(state));
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.signoff).toEqual({ status: "active_but_dod_failed", id: "sig_1", revision: state.signoffs[0]!.revision });
    const check3 = result.checks.checks.find((c) => c.id === "changes_resolved")!;
    expect(check3.pass).toBe(false);
    expect(check3.details.join("\n")).toContain("clarification clar_1 is open");
  });

  it("reports active_but_stale when an active sign-off cites another revision (kept for completeness)", () => {
    const result = buildExportContext(input(staleState()));
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.signoff.status).toBe("active_but_stale");
    expect(result.signoff.id).toBe("sig_1");
  });

  it("exportFile passes the refusal through unchanged for every file", () => {
    for (const file of EXPORT_FILES) {
      const result = exportFile(input(storyOnlyState()), file);
      expect(result.ok).toBe(false);
      if (result.ok) throw new Error("unreachable");
      expect(result.reason).toBe("NOT_HUMAN_VERIFIED");
      expect(result.checks.checks).toHaveLength(5);
      expect(result.signoff.status).toBe("none");
    }
  });
});

describe("buildExportContext — drafts", () => {
  it("a draft of an unverified map is allowed and watermarked", () => {
    const result = buildExportContext(input(storyOnlyState(), true));
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.draft).toBe(true);
    expect(result.ctx.verified).toBe(false);
    expect(result.ctx.signoff).toBeNull();
    expect(result.ctx.title).toBe(`[${DRAFT_WATERMARK}] A patient cancels an appointment online`);
    expect(result.ctx.itemId).toMatch(/^a-patient-cancels-an-appointment-online-draft-[0-9a-f]{8}$/);
    const file = exportFile(input(storyOnlyState(), true), "ticket.json");
    expect(file.ok).toBe(true);
    if (!file.ok) throw new Error("unreachable");
    expect(file.filename).toBe("DRAFT-ticket.json");
    expect((JSON.parse(file.body) as { title: string }).title.startsWith(`[${DRAFT_WATERMARK}]`)).toBe(true);
  });

  it("a draft on a verified map still watermarks (verified stays true, the sign-off is carried)", () => {
    const result = buildExportContext(input(verifiedState(), true));
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.verified).toBe(true);
    expect(result.ctx.draft).toBe(true);
    expect(result.ctx.signoff?.status).toBe("active");
    expect(result.ctx.title.startsWith(`[${DRAFT_WATERMARK}] `)).toBe(true);
    expect(result.ctx.itemId).toContain("-draft-");
    const ev = exportFile(input(verifiedState(), true), "evidence.json");
    if (!ev.ok) throw new Error("unreachable");
    expect(ev.filename).toBe("DRAFT-evidence.json");
    const body = JSON.parse(ev.body) as { watermark: string | null; verified: boolean; draft: boolean };
    expect(body).toMatchObject({ watermark: DRAFT_WATERMARK, verified: true, draft: true });
  });

  it("a draft of an invalidated map carries the invalidated sign-off, never as current", () => {
    const result = buildExportContext(input(invalidatedState(), true));
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.verified).toBe(false);
    expect(result.ctx.signoff?.status).toBe("invalidated");
    expect(result.ctx.signoff?.invalidated?.by_event_id).toBe("evt_41");
  });
});

describe("buildExportContext — the context", () => {
  it("defaults the export options to unclassified / code / unsized with seq 0 and `at` = now", () => {
    const result = buildExportContext(input(verifiedState()));
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.options).toEqual({ capability_class: "unclassified", kind: "code", size_estimate: "unsized", facts: [], by: "", seq: 0, at: NOW });
    expect(result.ctx.optionsHistory).toEqual([]);
  });

  it("carries the current options and the whole history from state", () => {
    const result = buildExportContext(input(verifiedState({ options: [OPTIONS, OPTIONS_2] })));
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.options).toEqual(OPTIONS_2);
    expect(result.ctx.optionsHistory).toEqual([OPTIONS, OPTIONS_2]);
  });

  it("lists live cards in card_order, groups examples by rule and excludes non-live cards", () => {
    const state = verifiedState();
    const result = buildExportContext(input(state));
    if (!result.ok) throw new Error("unreachable");
    const ctx = result.ctx;
    expect(ctx.session).toEqual(SESSION);
    expect(ctx.now).toBe(NOW);
    expect(ctx.verified).toBe(true);
    expect(ctx.story?.id).toBe("card_1");
    expect(ctx.rules.map((r) => r.id)).toEqual(["card_2", "card_3"]);
    expect(ctx.examples.map((e) => e.id)).toEqual(["card_4", "card_5", "card_6", "card_7"]); // card_11 is removed
    expect(ctx.questions.map((q) => q.id)).toEqual(["card_8", "card_9", "card_10"]);
    expect([...ctx.examplesByRule.keys()]).toEqual(["card_2", "card_3"]);
    expect(ctx.examplesByRule.get("card_2")!.map((e) => e.id)).toEqual(["card_4", "card_5", "card_6"]);
    expect(ctx.examplesByRule.get("card_3")!.map((e) => e.id)).toEqual(["card_7"]);
    expect(ctx.unattachedExamples).toEqual([]);
    expect(ctx.revision).toEqual({ seq: 1, hash: state.revisions[1]!.hash });
    expect(ctx.head).toEqual(state.head);
    expect(ctx.signoff?.id).toBe("sig_1");
    expect(ctx.dod.pass).toBe(true);
    expect(ctx.title).toBe("A patient can cancel an appointment online, but not within two hours");
    expect(ctx.itemId).toBe(`a-patient-can-cancel-an-appointment-online-but-n-${state.revisions[1]!.hash.slice(0, 8)}`);
  });

  it("puts examples with no rule, or a rule that is not live, under unattachedExamples", () => {
    const result = buildExportContext(input(draftState(), true));
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.unattachedExamples.map((e) => e.id)).toEqual(["card_12", "card_13"]);
    expect(result.ctx.examplesByRule.get("card_2")!.map((e) => e.id)).toEqual(["card_4"]);
  });

  it("falls back to the session title (or a named placeholder) when there is no story", () => {
    const state = draftState();
    state.cards = Object.fromEntries(Object.entries(state.cards).filter(([id]) => id !== "card_1"));
    state.card_order = state.card_order.filter((id) => id !== "card_1");
    const result = buildExportContext(input(state, true));
    if (!result.ok) throw new Error("unreachable");
    expect(result.ctx.story).toBeNull();
    expect(result.ctx.title).toBe(`[${DRAFT_WATERMARK}] Appointment cancellation`);
    expect(result.ctx.itemId).toMatch(/^appointment-cancellation-draft-[0-9a-f]{8}$/);
    const untitled = buildExportContext(input(state, true, NOW, { ...SESSION, title: "  " }));
    if (!untitled.ok) throw new Error("unreachable");
    expect(untitled.ctx.title).toBe(`[${DRAFT_WATERMARK}] Untitled requirement`);
  });
});

describe("exportFile", () => {
  it("produces every file with its content type, plain filename and a trailing newline", () => {
    for (const file of EXPORT_FILES) {
      const result = exportFile(input(verifiedState({ options: [OPTIONS] })), file);
      expect(result.ok).toBe(true);
      if (!result.ok) throw new Error("unreachable");
      expect(result.filename).toBe(file);
      expect(result.content_type).toBe(CONTENT_TYPES[file]);
      expect(result.body.endsWith("\n")).toBe(true);
      if (file.endsWith(".json")) expect(() => JSON.parse(result.body)).not.toThrow();
    }
    expect(CONTENT_TYPES["ticket.md"]).toBe("text/markdown; charset=utf-8");
    expect(CONTENT_TYPES["requirement.feature"]).toBe("text/plain; charset=utf-8");
    expect(CONTENT_TYPES["evidence.json"]).toBe("application/json");
  });

  it("is deterministic: the same input gives byte-identical bodies", () => {
    for (const file of EXPORT_FILES) {
      const a = exportFile(input(verifiedState({ options: [OPTIONS] })), file);
      const b = exportFile(input(verifiedState({ options: [OPTIONS] })), file);
      if (!a.ok || !b.ok) throw new Error("unreachable");
      expect(a.body).toBe(b.body);
    }
  });
});
