// tests/unit/audio/guidance.test.ts — TEST-PLAN §3 cases 45–47. The inline snapshot of the three no_audio_track pages
// is the contract the README's per-OS section follows by hand.
import { describe, expect, it } from "vitest";
import { GUIDANCE_OSES, GUIDANCE_REASONS, guidanceFor } from "../../../src/web/audio/lanes/guidance.js";
import { detectOs, isChromium } from "../../../src/web/audio/os.js";
import type { LaneSource } from "../../../src/web/audio/types.js";

const SOURCES: LaneSource[] = [{ kind: "display" }, { kind: "device", deviceId: null }];

describe("guidance", () => {
  it("45. every (os, lane, reason, source) combination returns a non-empty title and steps and says which Teams it applies to", () => {
    for (const os of GUIDANCE_OSES) {
      for (const lane of ["remote", "me"] as const) {
        for (const reason of GUIDANCE_REASONS) {
          for (const source of SOURCES) {
            const g = guidanceFor(os, lane, reason, source);
            expect(g.title.length, `${os}/${lane}/${reason}/${source.kind}`).toBeGreaterThan(0);
            expect(g.steps.length, `${os}/${lane}/${reason}/${source.kind}`).toBeGreaterThan(0);
            expect(g.note, `${os}/${lane}/${reason}/${source.kind}`).toMatch(/Teams/);
            expect(g.note).toMatch(/desktop app|browser tab/);
          }
        }
      }
    }
  });

  it("46. snapshot of the Windows / macOS / Linux no_audio_track text", () => {
    const display: LaneSource = { kind: "display" };
    expect(guidanceFor("windows", "remote", "no_audio_track", display)).toMatchInlineSnapshot(`
      {
        "alternatives": [
          "Teams in a browser tab: choose **Chrome Tab**, pick the Teams tab, tick **Share tab audio**.",
        ],
        "note": "Window sharing never carries audio in Chrome or Edge. Applies to Teams in a browser tab (tab audio; every OS) and, where it says so, to the Teams desktop app (system audio or a loopback device). Teams desktop app: share the entire screen with system audio.",
        "steps": [
          "Press Start again.",
          "In the share dialog choose **Entire screen** (not a window).",
          "Tick **Share system audio** at the bottom-left, then Share.",
        ],
        "title": "The shared screen had no audio",
      }
    `);
    expect(guidanceFor("macos", "remote", "no_audio_track", display)).toMatchInlineSnapshot(`
      {
        "alternatives": [
          "Teams desktop app: install a loopback driver (BlackHole 2ch), set it as Teams' speaker in Teams → Settings → Devices (or make a Multi-Output Device in Audio MIDI Setup so you still hear the call), then set exmap's **Call source** to *Audio device* and pick *BlackHole 2ch*.",
        ],
        "note": "exmap only hears what reaches the shared tab or the loopback device. Applies to Teams in a browser tab (tab audio; every OS) and, where it says so, to the Teams desktop app (system audio or a loopback device).",
        "steps": [
          "Open Teams in a Chrome tab (teams.microsoft.com) and join the call there.",
          "Press Start, choose **Chrome Tab**, pick the Teams tab and tick **Share tab audio**.",
        ],
        "title": "Chrome on macOS cannot share system audio from the screen",
      }
    `);
    expect(guidanceFor("linux", "remote", "no_audio_track", display)).toMatchInlineSnapshot(`
      {
        "alternatives": [
          "PulseAudio/PipeWire: set exmap's **Call source** to *Audio device* and pick the *Monitor of <your output>* device (create one with \`pactl load-module module-null-sink sink_name=exmap\` if none is listed).",
        ],
        "note": "Applies to Teams in a browser tab (tab audio; every OS) and, where it says so, to the Teams desktop app (system audio or a loopback device). Teams desktop app on Linux: route its output through a monitor device.",
        "steps": [
          "Open Teams in a Chrome tab and join the call there.",
          "Press Start, choose **Chrome Tab**, pick the Teams tab and tick **Share tab audio**.",
        ],
        "title": "Screen sharing has no system audio on Linux",
      }
    `);
    expect(guidanceFor("other", "remote", "no_audio_track", display).title).toBe("The shared surface had no audio");
    expect(guidanceFor("windows", "remote", "howto", display).title).toBe("How to capture the call on Windows");
    expect(guidanceFor("macos", "me", "permission_denied", { kind: "device", deviceId: null }).steps).toContain("Also check System Settings → Privacy & Security → Microphone → Chrome.");
    expect(guidanceFor("linux", "me", "no_device", { kind: "device", deviceId: null }).steps).toContain("Check `pactl list sources short` lists an input.");
    expect(guidanceFor("windows", "remote", "silent", { kind: "device", deviceId: "x" }).steps[0]).toBe("Check Teams' speaker is set to the loopback device.");
  });

  it("47. detectOs from Windows 11 Chrome, macOS Chrome, Ubuntu Chrome UA strings, and userAgentData.platform when present", () => {
    const win = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
    const mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
    const ubuntu = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
    expect(detectOs({ userAgent: win })).toBe("windows");
    expect(detectOs({ userAgent: mac })).toBe("macos");
    expect(detectOs({ userAgent: ubuntu })).toBe("linux");
    expect(detectOs({ userAgent: ubuntu, userAgentData: { platform: "Windows" } })).toBe("windows");
    expect(detectOs({ userAgent: win, userAgentData: { platform: "macOS" } })).toBe("macos");
    expect(detectOs({ userAgent: win, userAgentData: { platform: "Linux" } })).toBe("linux");
    expect(detectOs({ userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)" })).toBe("other");
    expect(detectOs({})).toBe("other");
    expect(isChromium({ userAgent: win })).toBe(true);
    expect(isChromium({ userAgent: "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0" })).toBe(false);
    expect(isChromium({ userAgent: win, userAgentData: { brands: [{ brand: "Microsoft Edge", version: "141" }] } })).toBe(true);
  });
});
