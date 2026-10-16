// tests/unit/web/audio/LaneBadge.test.tsx — the lane badge says "no sound heard" exactly when the detector measured
// silence (design §1.3). The e2e E3 cannot reach the silent state with Chrome 141's fake device (DESIGN §17
// [VERIFY %noloop], recorded at integration), so the rendering is pinned here.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LaneBadge, laneStateText } from "../../../../src/web/audio/react/LaneBadge.jsx";
import type { LaneView } from "../../../../src/web/audio/types.js";

const live = (signal: LaneView["signal"]): LaneView => ({
  id: "me", state: "live", source: { kind: "device", deviceId: null }, error: null, stopReason: null, signal, trackLabel: "Fake Mic", segmentsClosed: 0, startedAtMs: 0,
});

describe("LaneBadge", () => {
  it("a live lane reads 'Live — no sound heard' only while the signal is silent", () => {
    expect(laneStateText(live("silent"))).toBe("Live — no sound heard");
    expect(laneStateText(live("signal"))).toBe("Live");
    expect(laneStateText(live("unknown"))).toBe("Live");
    render(<LaneBadge view={live("silent")} />);
    const badge = screen.getByTestId("lane-me-badge");
    expect(badge).toHaveTextContent("Live — no sound heard");
    expect(badge).toHaveAttribute("data-signal", "silent");
    expect(badge).toHaveAttribute("data-state", "live");
  });
});
