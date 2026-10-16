// exmap/src/web/audio/lanes/guidance.ts — per-OS setup guidance (design §7.2). The snapshot test is the contract; the
// README's per-OS section is kept in step by hand. Every page says whether it applies to the Teams desktop app or to
// Teams in a browser tab.
import { OS_LABEL } from "../os.js";
import type { CaptureLaneId, GuidanceReason, LaneSource, OsId } from "../types.js";

export interface Guidance {
  title: string;
  steps: string[];
  alternatives: string[];
  note: string;
}

const TAB_NOTE = "Applies to Teams in a browser tab (tab audio; every OS) and, where it says so, to the Teams desktop app (system audio or a loopback device).";

function noAudioTrack(os: OsId): Guidance {
  switch (os) {
    case "windows":
      return {
        title: "The shared screen had no audio",
        steps: ["Press Start again.", "In the share dialog choose **Entire screen** (not a window).", "Tick **Share system audio** at the bottom-left, then Share."],
        alternatives: ["Teams in a browser tab: choose **Chrome Tab**, pick the Teams tab, tick **Share tab audio**."],
        note: `Window sharing never carries audio in Chrome or Edge. ${TAB_NOTE} Teams desktop app: share the entire screen with system audio.`,
      };
    case "macos":
      return {
        title: "Chrome on macOS cannot share system audio from the screen",
        steps: [
          "Open Teams in a Chrome tab (teams.microsoft.com) and join the call there.",
          "Press Start, choose **Chrome Tab**, pick the Teams tab and tick **Share tab audio**.",
        ],
        alternatives: [
          "Teams desktop app: install a loopback driver (BlackHole 2ch), set it as Teams' speaker in Teams → Settings → Devices (or make a Multi-Output Device in Audio MIDI Setup so you still hear the call), then set exmap's **Call source** to *Audio device* and pick *BlackHole 2ch*.",
        ],
        note: `exmap only hears what reaches the shared tab or the loopback device. ${TAB_NOTE}`,
      };
    case "linux":
      return linuxNoAudio("Screen sharing has no system audio on Linux");
    default:
      return linuxNoAudio("The shared surface had no audio");
  }
}

function linuxNoAudio(title: string): Guidance {
  return {
    title,
    steps: ["Open Teams in a Chrome tab and join the call there.", "Press Start, choose **Chrome Tab**, pick the Teams tab and tick **Share tab audio**."],
    alternatives: [
      "PulseAudio/PipeWire: set exmap's **Call source** to *Audio device* and pick the *Monitor of <your output>* device (create one with `pactl load-module module-null-sink sink_name=exmap` if none is listed).",
    ],
    note: `${TAB_NOTE} Teams desktop app on Linux: route its output through a monitor device.`,
  };
}

function remoteDeviceNoAudio(os: OsId): Guidance {
  const base = noAudioTrack(os);
  return {
    title: "The selected audio device carried no audio",
    steps: ["Check the loopback / monitor device is the one Teams plays into.", "Press Start again."],
    alternatives: base.alternatives,
    note: `Applies to the Teams desktop app routed through a loopback device. ${base.note}`,
  };
}

export function guidanceFor(os: OsId, lane: CaptureLaneId, reason: GuidanceReason, source: LaneSource): Guidance {
  const osName = OS_LABEL[os];
  if (lane === "remote") {
    switch (reason) {
      case "no_audio_track":
        return source.kind === "device" ? remoteDeviceNoAudio(os) : noAudioTrack(os);
      case "howto":
        return { ...noAudioTrack(os), title: `How to capture the call on ${osName}` };
      case "permission_denied":
        return {
          title: "Sharing was cancelled or blocked",
          steps: ["Press Start and choose a surface in the dialog.", "If no dialog appears, click the camera/screen icon in the address bar and allow screen capture for 127.0.0.1."],
          alternatives: [],
          note: `Applies to Teams in a browser tab and to the Teams desktop app alike. ${TAB_NOTE}`,
        };
      case "silent":
        return {
          title: "Live, but no sound for 10 s",
          steps:
            source.kind === "device"
              ? ["Check Teams' speaker is set to the loopback device.", "Check Teams is not muted and the other side is talking."]
              : ["Check the shared tab is the one playing the call.", "Check Teams is not muted and the other side is talking."],
          alternatives: [],
          note: source.kind === "device" ? "Applies to the Teams desktop app routed through a loopback device." : "Applies to Teams in a browser tab (tab audio) or a shared screen with system audio.",
        };
      case "unsupported":
        return {
          title: "This browser cannot share tab or system audio",
          steps: ["Use Chrome or Edge: Firefox and Safari cannot share system or tab audio.", "Open http://127.0.0.1:4317 there and press Start."],
          alternatives: noAudioTrack(os).alternatives,
          note: `Applies to Teams in a browser tab and to the Teams desktop app alike. ${TAB_NOTE}`,
        };
      case "no_device":
        return {
          title: "No audio device found for the call source",
          steps: ["Set **Call source** back to *Share screen / tab*, or plug in / create the loopback device, then press Start."],
          alternatives: noAudioTrack(os).alternatives,
          note: "Applies to the Teams desktop app routed through a loopback device.",
        };
    }
  }
  // me lane
  switch (reason) {
    case "permission_denied": {
      const steps = ["Click the microphone icon in the address bar, allow it for 127.0.0.1, then press Start."];
      if (os === "macos") steps.push("Also check System Settings → Privacy & Security → Microphone → Chrome.");
      if (os === "windows") steps.push("Also check Settings → Privacy & security → Microphone.");
      return { title: "Microphone access was denied", steps, alternatives: [], note: "Your microphone is captured by exmap directly; it does not depend on Teams (desktop app or browser tab)." };
    }
    case "no_device": {
      const steps = ["Plug in or enable a microphone, then press Start."];
      if (os === "linux") steps.push("Check `pactl list sources short` lists an input.");
      return { title: "No microphone found", steps, alternatives: [], note: "Your microphone is captured by exmap directly; it does not depend on Teams (desktop app or browser tab)." };
    }
    case "silent":
      return {
        title: "Live, but no sound for 10 s",
        steps: ["Check the right microphone is selected.", "Check it is not muted in the OS."],
        alternatives: [],
        note: "Your microphone is captured by exmap directly; it does not depend on Teams (desktop app or browser tab).",
      };
    case "unsupported":
      return {
        title: "This browser cannot capture the microphone",
        steps: ["Use Chrome or Edge: Firefox and Safari cannot share system or tab audio.", "Open http://127.0.0.1:4317 there and press Start."],
        alternatives: [],
        note: "Your microphone is captured by exmap directly; it does not depend on Teams (desktop app or browser tab).",
      };
    case "no_audio_track":
      return {
        title: "The microphone stream had no audio track",
        steps: ["Pick another microphone in the device list, then press Start."],
        alternatives: [],
        note: "Your microphone is captured by exmap directly; it does not depend on Teams (desktop app or browser tab).",
      };
    case "howto":
    default:
      return {
        title: `How to capture your own voice on ${osName}`,
        steps: ["Press Start on the Me lane and allow the microphone.", "Set your name in Settings so your utterances carry a speaker label.", "Wear headphones so the call does not feed back into your microphone."],
        alternatives: [],
        note: "Your microphone is captured by exmap directly; it does not depend on Teams (desktop app or browser tab).",
      };
  }
}

export const GUIDANCE_REASONS: readonly GuidanceReason[] = ["no_audio_track", "permission_denied", "unsupported", "silent", "no_device", "howto"] as const;
export const GUIDANCE_OSES: readonly OsId[] = ["windows", "macos", "linux", "other"] as const;
