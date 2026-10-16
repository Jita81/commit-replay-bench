// TEST-PLAN §5.5 — evidence.test.ts: evidence.json (design §12.5).
import { describe, expect, it } from "vitest";
import { canonicalJson, canonicalState, dodReport } from "../../../src/core/index.js";
import type { Evidence } from "../../../src/core/types.js";
import { DRAFT_WATERMARK, buildExportContext, evidence, exportFile } from "../../../src/export/index.js";
import type { ExportContext } from "../../../src/export/index.js";
import { NOW, OPTIONS, OPTIONS_2, SESSION, draftState, input, invalidatedState, sha256, verifiedState } from "./fixtures.js";

function ctxOf(state = verifiedState({ options: [OPTIONS] }), draft = false): ExportContext {
  const result = buildExportContext(input(state, draft));
  if (!result.ok) throw new Error(`fixture not exportable: ${result.signoff.status}`);
  return result.ctx;
}

describe("evidence.json", () => {
  it("canonical_state hashes to requirement_revision.hash and holds only live cards sorted by id", () => {
    const state = verifiedState();
    const ev = evidence(ctxOf(state));
    expect(sha256(canonicalJson(ev.canonical_state))).toBe(ev.requirement_revision.hash);
    expect(ev.requirement_revision).toEqual({ seq: 1, hash: state.revisions[1]!.hash });
    expect(ev.canonical_state.schema).toBe("exmap.revision.v1");
    expect(ev.canonical_state.cards.map((c) => c.id)).toEqual(["card_1", "card_10", "card_2", "card_3", "card_4", "card_5", "card_6", "card_7", "card_8", "card_9"]);
    expect(ev.canonical_state).toEqual(canonicalState(state.cards));
    const q = ev.canonical_state.cards.find((c) => c.id === "card_9")!;
    expect(q.kind === "question" && q.answer).toBe("Yes, it names the 24-hour rule.");
    expect(JSON.stringify(ev.canonical_state)).not.toContain("accepted_outstanding"); // review decisions are not canonical
  });

  it("verified: signoff is the active one on the same revision; draft false; watermark null", () => {
    const state = verifiedState();
    const ev = evidence(ctxOf(state));
    expect(ev.schema).toBe("exmap.evidence.v1");
    expect(ev.exported_at).toBe(NOW);
    expect(ev.draft).toBe(false);
    expect(ev.verified).toBe(true);
    expect(ev.watermark).toBeNull();
    expect(ev.session).toEqual(SESSION);
    expect(ev.signoff?.status).toBe("active");
    expect(ev.signoff?.id).toBe("sig_1");
    expect(ev.signoff?.reviewer).toEqual({ name: "Sam" });
    expect(ev.signoff?.revision.hash).toBe(ev.requirement_revision.hash);
    expect(ev.signoff?.revision).toEqual(ev.requirement_revision);
    expect(ev.signoff?.evidence).toEqual({ head_seq: 39, head_hash: sha256("head-39") });
    expect(ev.signoff?.checks.pass).toBe(true);
    expect(ev.signoff?.at).toBe("2026-10-16T12:20:00.000Z");
    expect(ev.signoff?.event_id).toBe("evt_40");
    expect(ev.signoff?.invalidated).toBeNull();
    expect(ev.chain_head).toEqual({ seq: 40, hash: sha256("head-40"), event_id: "evt_40" });
    expect(ev.dod).toEqual(dodReport(state));
    expect(ev.dod.pass).toBe(true);
  });

  it("draft after invalidation: verified false, the last sign-off shown as invalidated (never current), watermark set", () => {
    const state = invalidatedState();
    const ev = evidence(ctxOf(state, true));
    expect(ev.draft).toBe(true);
    expect(ev.verified).toBe(false);
    expect(ev.watermark).toBe(DRAFT_WATERMARK);
    expect(ev.signoff?.status).toBe("invalidated");
    expect(ev.signoff?.invalidated).toEqual({ event_id: "evt_42", by_event_id: "evt_41", to_revision: { seq: 2, hash: state.revisions[2]!.hash } });
    expect(ev.signoff?.revision.hash).not.toBe(ev.requirement_revision.hash);
    expect(ev.requirement_revision).toEqual({ seq: 2, hash: state.revisions[2]!.hash });
    expect(sha256(canonicalJson(ev.canonical_state))).toBe(ev.requirement_revision.hash);
    expect(ev.dod.pass).toBe(false);
    expect(ev.dod.checks.find((c) => c.id === "story_rules_confirmed")!.pass).toBe(false);
  });

  it("draft without any sign-off: signoff null", () => {
    const ev = evidence(ctxOf(draftState(), true));
    expect(ev.signoff).toBeNull();
    expect(ev.verified).toBe(false);
    expect(ev.watermark).toBe(DRAFT_WATERMARK);
  });

  it("a draft of a verified map keeps verified true and the active sign-off but is watermarked", () => {
    const ev = evidence(ctxOf(verifiedState(), true));
    expect(ev.draft).toBe(true);
    expect(ev.verified).toBe(true);
    expect(ev.signoff?.status).toBe("active");
    expect(ev.watermark).toBe(DRAFT_WATERMARK);
  });

  it("export_options and export_options_history are carried verbatim from state", () => {
    const ev = evidence(ctxOf(verifiedState({ options: [OPTIONS, OPTIONS_2] })));
    expect(ev.export_options).toEqual(OPTIONS_2);
    expect(ev.export_options_history).toEqual([OPTIONS, OPTIONS_2]);
    const none = evidence(ctxOf(verifiedState()));
    expect(none.export_options).toBeNull();
    expect(none.export_options_history).toEqual([]);
    const one = evidence(ctxOf(verifiedState({ options: [OPTIONS] })));
    expect(one.export_options_history).toHaveLength(1);
  });

  it("the file body round-trips and the sign-off has exactly the designed keys", () => {
    const file = exportFile(input(verifiedState({ options: [OPTIONS] })), "evidence.json");
    if (!file.ok) throw new Error("unreachable");
    const parsed = JSON.parse(file.body) as Evidence;
    expect(parsed).toEqual(evidence(ctxOf()));
    expect(parsed.verified).toBe(true);
    expect(parsed.signoff?.reviewer.name).toBe("Sam");
    expect(parsed.export_options_history).toHaveLength(1);
    expect(Object.keys(parsed.signoff!).sort()).toEqual([
      "at", "checks", "confirmation_text", "event_id", "evidence", "id", "invalidated", "reviewer", "revision", "status",
    ]);
    expect(Object.keys(parsed).sort()).toEqual([
      "canonical_state", "chain_head", "dod", "draft", "export_options", "export_options_history", "exported_at", "requirement_revision", "schema",
      "session", "signoff", "verified", "watermark",
    ]);
  });
});
