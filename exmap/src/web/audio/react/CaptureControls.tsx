// exmap/src/web/audio/react/CaptureControls.tsx — the capture strip (design §7.7): per lane the badges, Start/Stop,
// provider select, call-source toggle, device picker, level meter and speaker picker; below, the model selects, the
// download progress, the backlog line, the page diagnostics and Setup help. The consent notice and the guidance panel
// render here too, so mounting this one component gives the whole audio UI. Test ids are the e2e contract.
import type { AudioController } from "../controller.js";
import { PROVIDERS } from "../providers/registry.js";
import { MODEL_INFO, WHISPER_DTYPES, WHISPER_MODELS } from "../settings.js";
import type { AudioSettings, AudioState, CaptureLaneId, MediaDevicesLike, ProviderId, WhisperDtype, WhisperModelId } from "../types.js";
import { ConsentNotice } from "./ConsentNotice.jsx";
import { DevicePicker } from "./DevicePicker.jsx";
import { GuidancePanelView } from "./GuidancePanel.jsx";
import { LANE_NAME, LaneBadge, ProviderBadge } from "./LaneBadge.jsx";
import { LevelMeter } from "./LevelMeter.jsx";
import { ModelProgress } from "./ModelProgress.jsx";
import { SpeakerPicker } from "./SpeakerPicker.jsx";
import { useAudioController } from "./useAudioController.js";

export interface CaptureControlsProps {
  controller: AudioController;
  media?: MediaDevicesLike | null;
}

const CAPTURE_ONLY = "__capture_only__";

function providerOptions(lane: CaptureLaneId, state: AudioState): Array<{ value: string; label: string; disabled: boolean; title?: string }> {
  const out: Array<{ value: string; label: string; disabled: boolean; title?: string }> = [];
  for (const [id, info] of Object.entries(PROVIDERS) as Array<[ProviderId, (typeof PROVIDERS)[ProviderId]]>) {
    if (!info.lanes.includes(lane) || id === "replay") continue;
    const unsupported = id === "web-speech" && !state.webSpeechAvailable;
    out.push({ value: id, label: unsupported ? `${info.label} — ${state.webSpeechReason ?? "unavailable"}` : info.label, disabled: unsupported, ...(unsupported && state.webSpeechReason ? { title: state.webSpeechReason } : {}) });
  }
  out.push({ value: CAPTURE_ONLY, label: "Capture only (test audio)", disabled: false });
  return out;
}

export function backlogText(b: AudioState["backlog"]): string {
  if (b.segmentsWaiting === 0 && b.segmentInFlight === 0 && b.utterancesUnsent === 0 && b.failed === 0) return "0 waiting";
  const parts = [`${b.segmentsWaiting} waiting`];
  if (b.segmentInFlight > 0) parts.push(`${b.segmentInFlight} transcribing`);
  if (b.utterancesUnsent > 0) parts.push(`${b.utterancesUnsent} unsent`);
  if (b.failed > 0) parts.push(`${b.failed} could not be transcribed`);
  return parts.join(" · ");
}

function LaneRow({ lane, state, controller, media }: { lane: CaptureLaneId; state: AudioState; controller: AudioController; media: MediaDevicesLike | null }) {
  const view = state.lanes[lane];
  const busy = view.state === "requesting" || view.state === "live";
  const provider = state.settings.provider[lane];
  const declined = state.modelDeclined && provider === "local-whisper";
  return (
    <div data-testid={`lane-${lane}`} className="flex flex-wrap items-center gap-2 rounded border p-2">
      <span className="w-10 text-sm font-semibold">{LANE_NAME[lane]}</span>
      <LaneBadge view={view} />
      <ProviderBadge lane={lane} provider={provider} declined={declined} />
      {busy ? (
        <button type="button" data-testid={`lane-${lane}-stop`} className="rounded border px-2 py-0.5 text-xs" onClick={() => void controller.stopLane(lane)}>
          Stop
        </button>
      ) : (
        <button type="button" data-testid={`lane-${lane}-start`} className="rounded bg-slate-900 px-2 py-0.5 text-xs text-white" onClick={() => void controller.startLane(lane)}>
          Start
        </button>
      )}
      <label className="text-xs">
        <span className="sr-only">{LANE_NAME[lane]} lane transcription provider</span>
        <select
          data-testid={`provider-select-${lane}`}
          className="rounded border px-1 py-0.5 text-xs"
          disabled={busy}
          title={busy ? "Stop the lane to change this" : undefined}
          value={provider ?? CAPTURE_ONLY}
          onChange={(e) => {
            const v = e.target.value === CAPTURE_ONLY ? null : (e.target.value as AudioSettings["provider"]["me"]);
            controller.updateSettings({ provider: { ...state.settings.provider, [lane]: v } });
          }}
        >
          {providerOptions(lane, state).map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled} title={o.title}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {lane === "remote" ? (
        <label className="text-xs">
          Call source{" "}
          <select
            data-testid="remote-source"
            className="rounded border px-1 py-0.5 text-xs"
            disabled={busy}
            title={busy ? "Stop the lane to change this" : undefined}
            value={state.settings.remoteSource.kind}
            onChange={(e) => controller.updateSettings({ remoteSource: e.target.value === "device" ? { kind: "device", deviceId: state.settings.deviceId.remote } : { kind: "display" } })}
          >
            <option value="display">Share screen / tab</option>
            <option value="device">Audio device (loopback)</option>
          </select>
        </label>
      ) : null}
      {lane === "me" || state.settings.remoteSource.kind === "device" ? <DevicePicker controller={controller} lane={lane} media={media} disabled={busy} value={state.settings.deviceId[lane]} /> : null}
      <LevelMeter controller={controller} lane={lane} />
      <SpeakerPicker controller={controller} lane={lane} speakers={state.speakers} />
      {lane === "me" && state.interim.me ? (
        <span data-testid="interim-me" className="text-xs italic opacity-70" aria-live="polite">
          {state.interim.me}
        </span>
      ) : null}
    </div>
  );
}

export function CaptureControls({ controller, media }: CaptureControlsProps) {
  const state = useAudioController(controller);
  const mediaDevices = media === undefined ? (typeof navigator !== "undefined" ? ((navigator.mediaDevices as unknown as MediaDevicesLike | undefined) ?? null) : null) : media;
  const anyLive = state.lanes.remote.state === "live" || state.lanes.me.state === "live" || state.lanes.remote.state === "requesting" || state.lanes.me.state === "requesting";
  const b = state.backlog;
  const behind = b.segmentsWaiting >= 3;
  return (
    <section data-testid="capture-controls" aria-label="Audio capture" className="flex flex-col gap-2 text-slate-900">
      <LaneRow lane="remote" state={state} controller={controller} media={mediaDevices} />
      <LaneRow lane="me" state={state} controller={controller} media={mediaDevices} />
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label>
          Model{" "}
          <select
            data-testid="model-select"
            className="rounded border px-1 py-0.5"
            value={state.settings.whisperModel}
            disabled={anyLive && state.model.state === "loading"}
            onChange={(e) => controller.updateSettings({ whisperModel: e.target.value as WhisperModelId })}
          >
            {WHISPER_MODELS.map((m) => (
              <option key={m} value={m}>
                {MODEL_INFO[m].short} (≈{MODEL_INFO[m].approxMb[state.settings.whisperDtype]} MB approx)
              </option>
            ))}
          </select>
        </label>
        <label>
          Precision{" "}
          <select data-testid="dtype-select" className="rounded border px-1 py-0.5" value={state.settings.whisperDtype} onChange={(e) => controller.updateSettings({ whisperDtype: e.target.value as WhisperDtype })}>
            {WHISPER_DTYPES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <ModelProgress model={state.model} />
        <button type="button" data-testid="model-clear" className="underline" onClick={() => void controller.clearDownloadedModels()}>
          Clear downloaded models
        </button>
        <button type="button" data-testid="guidance-open" className="underline" onClick={() => controller.openGuidance("remote", "howto")}>
          Setup help
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span data-testid="backlog-count" aria-live="polite">
          {backlogText(b)}
          {b.failed > 0 ? (
            <>
              {" "}
              <button type="button" data-testid="backlog-retry" className="underline" onClick={() => controller.retryFailedSegments()}>
                Retry
              </button>
            </>
          ) : null}
        </span>
        {behind ? (
          <span data-testid="backlog-behind" role="status">
            Transcription is {b.segmentsWaiting} segments (≈ {Math.round(b.speechWaitingMs / 1000)} s of speech) behind
            {b.segmentsWaiting >= 10 && state.settings.whisperModel !== "onnx-community/whisper-tiny.en" ? " — consider the tiny.en model" : ""}
          </span>
        ) : null}
        <span data-testid="backlog-diagnostics" className="opacity-70">
          this page: {b.droppedAsHallucination} dropped as likely hallucination · {b.postRetries} post retries · {state.refused.length} refused by the server
        </span>
        {state.lastError ? (
          <span data-testid="audio-last-error" role="status" className="text-red-700">
            {state.lastError.scope}: {state.lastError.code} — {state.lastError.message}
          </span>
        ) : null}
      </div>
      {state.refused.length > 0 ? (
        <ul data-testid="refused-list" className="text-xs text-red-700">
          {state.refused.map((r) => (
            <li key={r.id}>
              refused ({r.reason}): “{r.text.slice(0, 60)}” — {r.detail}
            </li>
          ))}
        </ul>
      ) : null}
      {state.notice ? <ConsentNotice notice={state.notice} controller={controller} dtype={state.settings.whisperDtype} /> : null}
      {state.guidance ? (
        <GuidancePanelView
          os={controller.os}
          lane={state.guidance.lane}
          reason={state.guidance.reason}
          source={state.lanes[state.guidance.lane].source}
          onClose={() => controller.closeGuidance()}
        />
      ) : null}
    </section>
  );
}
