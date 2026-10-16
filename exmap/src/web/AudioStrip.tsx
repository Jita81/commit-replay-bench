// exmap/src/web/AudioStrip.tsx — where the audio module's React components are mounted (design §10.1): the capture
// and replay controls in the collapsible strip and ManualInput docked under the transcript (CaptureControls renders the
// consent notice and the guidance panel itself). A missing export is named on screen, never a silent blank.
import type { AudioModule } from "./audioContract.js";
import type { AudioControllerLike } from "./audioContract.js";

export interface AudioStripProps {
  mod: AudioModule | null;
  controller: AudioControllerLike | null;
  loadError: string | null;
}

function Unavailable({ what, mod, loadError }: { what: string; mod: AudioModule | null; loadError: string | null }) {
  return (
    <p className="rounded border border-dashed border-slate-400 p-2 text-xs text-slate-700" data-testid={`audio-unavailable-${what}`}>
      {loadError ? `Audio pipeline not loaded: ${loadError}` : mod ? `${what} is not available in this build (missing: ${mod.missing.join(", ") || "unknown"}).` : "Loading the audio pipeline…"}
    </p>
  );
}

export function CaptureStrip({ mod, controller, loadError }: AudioStripProps) {
  if (!mod || !controller) return <Unavailable what="CaptureControls" mod={mod} loadError={loadError} />;
  const Capture = mod.CaptureControls;
  const Replay = mod.ReplayControls;
  return (
    <div className="flex flex-col gap-2 md:flex-row md:items-start" data-testid="capture-strip">
      <div className="min-w-0 grow">{Capture ? <Capture controller={controller} /> : <Unavailable what="CaptureControls" mod={mod} loadError={loadError} />}</div>
      <div className="min-w-0 md:w-96">{Replay ? <Replay controller={controller} /> : <Unavailable what="ReplayControls" mod={mod} loadError={loadError} />}</div>
    </div>
  );
}

export function ManualDock({ mod, controller, loadError }: AudioStripProps) {
  if (!mod || !controller) return <Unavailable what="ManualInput" mod={mod} loadError={loadError} />;
  const Manual = mod.ManualInput;
  return Manual ? <Manual controller={controller} /> : <Unavailable what="ManualInput" mod={mod} loadError={loadError} />;
}
