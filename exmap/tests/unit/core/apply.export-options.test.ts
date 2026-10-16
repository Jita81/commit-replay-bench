// TEST-PLAN §1 case 71: export options are ledgered and create no revision; a change by anyone but the signing reviewer invalidates the sign-off.
import { describe, expect, it } from "vitest";
import { isHumanVerified } from "../../../src/core/dod.js";
import * as select from "../../../src/core/select.js";
import type { Command, ExmapEvent, ExportOptionsInput } from "../../../src/core/types.js";
import { refused, run, scenario } from "./fixtures.js";

const options = (patch: Partial<ExportOptionsInput> = {}): Command => ({
  kind: "export.options_set",
  options: { capability_class: "backend.route.edit", kind: "code", size_estimate: "M", facts: [{ slot: "route_identity", text: "PUT /appointments/{id}/cancel" }], by: "Sam", ...patch },
});

describe("export.options_set", () => {
  it("71. appends one event with seq 1 then 2, at from the clock, by from the input; exportOptions is the last; not substantive; refusals", () => {
    const s = scenario();
    const { ctx } = s;
    const signed = s.stateAfter("signoff");
    expect(select.exportOptions(signed)?.seq).toBe(1);
    const first = s.step("export_options");
    const event = first.events[0] as Extract<ExmapEvent, { type: "export.options_set" }>;
    expect(first.events.length).toBe(1);
    expect(event.options).toEqual({ capability_class: "backend.route.edit", kind: "code", size_estimate: "M", facts: [{ slot: "route_identity", text: "PUT /appointments/{id}/cancel" }], by: "Sam", seq: 1, at: event.at });
    expect(select.exportOptions(first.state)).toEqual(event.options);
    const second = run(signed, options({ size_estimate: "L", by: "Priya" }), ctx);
    const e2 = second.events[0] as Extract<ExmapEvent, { type: "export.options_set" }>;
    expect(e2.options.seq).toBe(2);
    expect(e2.options.by).toBe("Priya");
    expect(e2.options.at).toBe(e2.at);
    expect(select.exportOptions(second.state)?.size_estimate).toBe("L");
    expect(second.state.export_options.length).toBe(2);
    expect(second.state.export_options.map((o) => o.seq)).toEqual([1, 2]);
    expect(second.state.revisions.length).toBe(signed.revisions.length);
    // 2026-10-16 review fix (INTEGRATION-NOTES): still no revision, but Priya changing the facts Sam signed off on
    // invalidates Sam's sign-off; the reviewer's own change keeps it (next describe block).
    expect(second.events.map((e) => e.type)).toEqual(["export.options_set", "signoff.invalidated"]);
    expect(isHumanVerified(second.state)).toBe(false);
    expect(select.lastSignoff(second.state)?.id).toBe(s.ids.sig1);
    expect(select.lastSignoff(second.state)?.status).toBe("invalidated");
    expect(select.exportOptions(s.stateBefore("export_options"))).toBeNull();
    expect(refused(signed, options({ kind: "ops" as never }), ctx).reason).toBe("INVALID_ENUM");
    expect(refused(signed, options({ size_estimate: "huge" as never }), ctx).reason).toBe("INVALID_ENUM");
    const badSlot = refused(signed, options({ facts: [{ slot: "1bad", text: "x" }] }), ctx);
    expect(badSlot.reason).toBe("BAD_SHAPE");
    expect(badSlot.detail).toContain("facts[0].slot");
    expect(refused(signed, options({ facts: [{ slot: "ok", text: "  " }] }), ctx).reason).toBe("EMPTY_TEXT");
    expect(refused(signed, options({ facts: Array.from({ length: 41 }, (_, i) => ({ slot: `s${i}`, text: "t" })) }), ctx).reason).toBe("BAD_SHAPE");
    expect(run(signed, options({ facts: Array.from({ length: 40 }, (_, i) => ({ slot: `s${i}`, text: "t" })) }), ctx).events.length).toBe(1);
    expect(refused(signed, options({ by: " " }), ctx).reason).toBe("ACTOR_REQUIRED");
    expect(refused(signed, options({ capability_class: "" }), ctx).reason).toBe("EMPTY_TEXT");
    expect(refused(signed, options({ capability_class: "x".repeat(81) }), ctx).reason).toBe("EMPTY_TEXT");
    expect(run(signed, options({ capability_class: "unclassified" }), ctx).events.length).toBe(1); // core is catalogue-agnostic
    expect(refused(signed, { ...options(), extra: true } as never, ctx).reason).toBe("BAD_SHAPE");
  });
});

describe("export.options_set after a sign-off (review finding: unreviewed facts exported as verified)", () => {
  it("a changed value set by anyone but the active sign-off's reviewer invalidates it in the same batch", () => {
    const s = scenario();
    const signed = s.stateAfter("signoff");
    expect(isHumanVerified(signed)).toBe(true);
    const r = run(signed, options({ facts: [{ slot: "error_contract", text: "409 when within two hours; admins bypass the window entirely" }], by: "Mallory" }), s.ctx);
    expect(r.events.map((e) => e.type)).toEqual(["export.options_set", "signoff.invalidated"]);
    const inv = r.events[1] as Extract<ExmapEvent, { type: "signoff.invalidated" }>;
    expect(inv.by_event_id).toBe(r.events[0]!.id);
    expect(inv.signoff_id).toBe(s.ids.sig1);
    expect(inv.to_revision).toEqual(inv.from_revision); // the meaning did not change; the export annotations did
    expect(r.state.revisions.length).toBe(signed.revisions.length);
    expect(select.activeSignoff(r.state)).toBeNull();
    expect(isHumanVerified(r.state)).toBe(false);
  });

  it("the reviewer's own change, or a re-save of the same value by anyone, keeps the sign-off", () => {
    const s = scenario();
    const signed = s.stateAfter("signoff");
    const own = run(signed, options({ size_estimate: "L", by: "Sam" }), s.ctx);
    expect(own.events.map((e) => e.type)).toEqual(["export.options_set"]);
    expect(isHumanVerified(own.state)).toBe(true);
    const current = select.exportOptions(signed)!;
    const same = run(signed, { kind: "export.options_set", options: { capability_class: current.capability_class, kind: current.kind, size_estimate: current.size_estimate, facts: current.facts, by: "Mallory" } }, s.ctx);
    expect(same.events.map((e) => e.type)).toEqual(["export.options_set"]);
    expect(isHumanVerified(same.state)).toBe(true);
  });
});
