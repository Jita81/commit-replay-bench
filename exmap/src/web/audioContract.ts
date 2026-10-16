// exmap/src/web/audioContract.ts — the web module's view of the audio module (design §7.7), as a structural contract.
// CaptureControls renders the consent notice and the guidance panel itself (INTEGRATION-NOTES, audio §12), so the
// session screen mounts three components: CaptureControls, ReplayControls and ManualInput, each with { controller }.
// Types come from src/web/audio/types.ts (real at step zero); the runtime module is loaded lazily by loadAudioModule()
// so the session screen compiles against the documented API while the audio module lands, and names what is missing.
import type { ComponentType } from "react";
import type {
  AudioSettings, AudioState, CaptureLaneId, GuidanceReason, ReplayFixture, ReplaySpeed, SessionClock, SpeakerStoreLike, StorageLike,
  UtteranceSink, WireLane,
} from "./audio/types.js";

export interface AudioControllerLike {
  getState(): AudioState;
  subscribe(fn: () => void): () => void;
  startLane(lane: CaptureLaneId): Promise<void> | void;
  stopLane(lane: CaptureLaneId): Promise<void> | void;
  updateSettings(patch: Partial<AudioSettings>): void;
  setSpeaker(lane: CaptureLaneId, label: string | null): void;
  acceptNotice(): void;
  cancelNotice(): void;
  submitManual(text: string, lane: WireLane, speaker: string | null): void;
  loadReplay(fixture: ReplayFixture, name: string): void;
  playReplay(speed: ReplaySpeed, opts?: { until?: number | string }): Promise<void>;
  stepReplay(): void;
  skipReplay(until: number | string): void;
  pauseReplay(): void;
  resetReplay(): void;
  openGuidance(lane: CaptureLaneId, reason: GuidanceReason): void;
  closeGuidance(): void;
  retryFailedSegments(): void;
  pendingWork(): number;
  idle(): Promise<void>;
  dispose(): void;
}

export interface AudioControllerDeps {
  sink: UtteranceSink;
  clock: SessionClock;
  speakers: SpeakerStoreLike;
  storage?: StorageLike | null;
  autostartRequested?: boolean;
}
export type AudioControllerCtor = new (deps: AudioControllerDeps) => AudioControllerLike;

/** Every audio React component is rendered with exactly this prop (recorded in INTEGRATION-NOTES). */
export interface AudioComponentProps {
  controller: AudioControllerLike;
}

export interface AudioModule {
  AudioController: AudioControllerCtor | null;
  useAudioController: ((c: AudioControllerLike) => AudioState) | null;
  CaptureControls: ComponentType<AudioComponentProps> | null;
  ReplayControls: ComponentType<AudioComponentProps> | null;
  ManualInput: ComponentType<AudioComponentProps> | null;
  /** Names of the exports that were not found (shown in the UI instead of a silent blank strip). */
  missing: string[];
}

type Loose = Record<string, unknown>;

function pick<T>(mod: Loose, name: string, missing: string[]): T | null {
  const v = mod[name];
  if (typeof v === "function") return v as T;
  missing.push(name);
  return null;
}

/** Loads the audio module's runtime exports; a missing export is reported, never thrown. */
export async function loadAudioModule(): Promise<AudioModule> {
  const missing: string[] = [];
  const safe = async (load: () => Promise<unknown>, label: string): Promise<Loose> => {
    try {
      return (await load()) as Loose;
    } catch (e) {
      missing.push(`${label} (${e instanceof Error ? e.message : String(e)})`);
      return {};
    }
  };
  const controller = await safe(() => import("./audio/controller.js"), "controller");
  const hook = await safe(() => import("./audio/react/useAudioController.js"), "useAudioController");
  const capture = await safe(() => import("./audio/react/CaptureControls.js"), "CaptureControls");
  const replay = await safe(() => import("./audio/react/ReplayControls.js"), "ReplayControls");
  const manual = await safe(() => import("./audio/react/ManualInput.js"), "ManualInput");
  return {
    AudioController: pick<AudioControllerCtor>(controller, "AudioController", missing),
    useAudioController: pick<(c: AudioControllerLike) => AudioState>(hook, "useAudioController", missing),
    CaptureControls: pick<ComponentType<AudioComponentProps>>(capture, "CaptureControls", missing),
    ReplayControls: pick<ComponentType<AudioComponentProps>>(replay, "ReplayControls", missing),
    ManualInput: pick<ComponentType<AudioComponentProps>>(manual, "ManualInput", missing),
    missing,
  };
}
