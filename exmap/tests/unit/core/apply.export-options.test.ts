// TEST-PLAN §1 case 71: export options are ledgered, non-substantive, outside the sign-off.
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
    expect(isHumanVerified(second.state)).toBe(true);
    expect(select.activeSignoff(second.state)?.id).toBe(s.ids.sig1);
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
