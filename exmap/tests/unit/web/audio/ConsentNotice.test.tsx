// tests/unit/web/audio/ConsentNotice.test.tsx — TEST-PLAN §3 case 54 (jsdom).
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConsentNotice, modelNoticeText } from "../../../../src/web/audio/react/ConsentNotice.jsx";

function fakeController() {
  const calls: string[] = [];
  return { calls, acceptNotice: () => calls.push("accept"), cancelNotice: () => calls.push("cancel") };
}

describe("ConsentNotice", () => {
  it("54. Continue / Cancel call the controller; role=dialog; focus on Continue; Escape cancels", () => {
    const controller = fakeController();
    render(<ConsentNotice notice={{ kind: "model", model: "onnx-community/whisper-base.en", lane: "me" }} controller={controller} />);
    const dialog = screen.getByTestId("model-notice");
    expect(dialog).toHaveAttribute("role", "dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent("~77 MB");
    expect(dialog).toHaveTextContent("Audio never leaves this machine.");
    const cont = screen.getByTestId("model-notice-continue");
    expect(document.activeElement).toBe(cont);
    fireEvent.click(cont);
    fireEvent.click(screen.getByTestId("model-notice-cancel"));
    expect(controller.calls).toEqual(["accept", "cancel"]);
    fireEvent.keyDown(cont, { key: "Escape" });
    expect(controller.calls).toEqual(["accept", "cancel", "cancel"]);
  });

  it("the Web Speech notice uses its own ids and says the audio leaves the machine", () => {
    const controller = fakeController();
    render(<ConsentNotice notice={{ kind: "webspeech", previous: "local-whisper" }} controller={controller} />);
    expect(screen.getByTestId("webspeech-notice")).toHaveTextContent("the audio does leave this machine");
    fireEvent.click(screen.getByTestId("webspeech-notice-continue"));
    expect(controller.calls).toEqual(["accept"]);
    expect(modelNoticeText("onnx-community/whisper-tiny.en")).toContain("~44 MB");
    expect(modelNoticeText("onnx-community/whisper-base.en", "q4")).toContain("~143 MB");
  });

  it("with { controller } alone it follows the controller's notice and renders nothing while there is none", () => {
    const listeners = new Set<() => void>();
    type State = ReturnType<NonNullable<Parameters<typeof ConsentNotice>[0]["controller"]["getState"]>>;
    // a stable snapshot per change, as the real controller provides (useSyncExternalStore requires it)
    let snapshot = { notice: null, settings: { whisperDtype: "q4" } } as unknown as State;
    const controller = {
      calls: [] as string[],
      acceptNotice() {
        this.calls.push("accept");
      },
      cancelNotice() {
        this.calls.push("cancel");
      },
      getState: () => snapshot,
      subscribe: (fn: () => void) => {
        listeners.add(fn);
        return () => listeners.delete(fn);
      },
    };
    render(<ConsentNotice controller={controller} />);
    expect(screen.queryByTestId("model-notice")).not.toBeInTheDocument();
    snapshot = { ...snapshot, notice: { kind: "model", model: "onnx-community/whisper-base.en", lane: "remote" } };
    act(() => {
      for (const fn of listeners) fn();
    });
    expect(screen.getByTestId("model-notice")).toHaveTextContent("~143 MB"); // q4 from the controller's settings
    fireEvent.click(screen.getByTestId("model-notice-continue"));
    expect(controller.calls).toEqual(["accept"]);
  });
});
