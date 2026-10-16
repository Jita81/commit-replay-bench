// tests/unit/web/audio/CaptureControls.test.tsx — TEST-PLAN §3 case 53 (jsdom).
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fixedClock } from "../../../../src/web/audio/clock.js";
import { AudioController } from "../../../../src/web/audio/controller.js";
import { CaptureControls } from "../../../../src/web/audio/react/CaptureControls.jsx";
import { memoryStorage } from "../../../../src/web/audio/settings.js";
import { SpeakerStore } from "../../../../src/web/audio/speakers.js";
import { FakeGraph, FakeMedia, FakeSegmentProvider, FakeStream, FakeTrack, ScriptedSink } from "../../audio/fakes.js";

function controller() {
  const media = new FakeMedia();
  media.nextUser(new FakeStream([new FakeTrack("audio", "Fake Mic")]));
  const c = new AudioController({
    sink: new ScriptedSink(),
    clock: fixedClock(0),
    speakers: new SpeakerStore({ userName: "Sam" }),
    media,
    graph: new FakeGraph(),
    storage: memoryStorage(),
    isSecureContext: true,
    os: "linux",
    providers: () => new FakeSegmentProvider(),
    providerDeps: { speechRecognitionCtor: null },
  });
  return { c, media };
}

describe("CaptureControls", () => {
  it("53. both lanes render idle; meters are named with aria-valuemin/max; the provider select is disabled while a lane is live; diagnostics start with 'this page:'", async () => {
    const { c } = controller();
    render(<CaptureControls controller={c} media={null} />);
    expect(screen.getByTestId("lane-remote-badge")).toHaveTextContent("Idle");
    expect(screen.getByTestId("lane-me-badge")).toHaveTextContent("Idle");
    expect(screen.getByTestId("lane-remote-badge")).toHaveAttribute("data-state", "idle");
    const call = screen.getByRole("meter", { name: "Call level" });
    const mic = screen.getByRole("meter", { name: "Microphone level" });
    for (const m of [call, mic]) {
      expect(m).toHaveAttribute("aria-valuemin", "0");
      expect(m).toHaveAttribute("aria-valuemax", "100");
      expect(m).toHaveAttribute("aria-valuenow");
    }
    expect(screen.getByTestId("lane-remote-provider-badge")).toHaveTextContent("Whisper (local)");
    expect(screen.getByTestId("provider-select-me")).not.toBeDisabled();
    expect(screen.getByTestId("backlog-diagnostics").textContent?.startsWith("this page:")).toBe(true);
    expect(screen.getByTestId("backlog-count")).toHaveTextContent("0 waiting");

    await act(async () => {
      await c.startLane("me");
    });
    expect(screen.getByTestId("lane-me-badge")).toHaveAttribute("data-state", "live");
    expect(screen.getByTestId("provider-select-me")).toBeDisabled();
    expect(screen.getByTestId("provider-select-me")).toHaveAttribute("title", "Stop the lane to change this");
    expect(screen.getByTestId("provider-select-remote")).not.toBeDisabled();
    // without a consent flag the model notice opens and nothing was loaded
    expect(screen.getByTestId("model-notice")).toBeInTheDocument();
    expect(screen.getByTestId("model-progress")).toHaveTextContent("Waiting for your OK to download");
    await act(async () => {
      c.cancelNotice();
    });
    expect(screen.queryByTestId("model-notice")).not.toBeInTheDocument();
    expect(screen.getByTestId("lane-me-provider-badge")).toHaveTextContent("Capture only (download declined)");
    expect(screen.getByTestId("lane-me-badge")).toHaveAttribute("data-state", "live");
    await act(async () => {
      await c.stopLane("me");
    });
    expect(screen.getByTestId("lane-me-badge")).toHaveTextContent("Stopped");
    expect(screen.getByTestId("provider-select-me")).not.toBeDisabled();
    c.dispose();
  });

  it("Web Speech is offered on the me lane only, disabled with its reason when the browser has no recogniser", () => {
    const { c } = controller();
    render(<CaptureControls controller={c} media={null} />);
    const me = screen.getByTestId("provider-select-me") as HTMLSelectElement;
    const options = Array.from(me.options).map((o) => ({ value: o.value, disabled: o.disabled }));
    expect(options.find((o) => o.value === "web-speech")?.disabled).toBe(true);
    const remote = screen.getByTestId("provider-select-remote") as HTMLSelectElement;
    expect(Array.from(remote.options).map((o) => o.value)).not.toContain("web-speech");
    expect(Array.from(remote.options).map((o) => o.value)).toContain("local-whisper");
    c.dispose();
  });
});
