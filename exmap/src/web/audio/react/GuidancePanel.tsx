// exmap/src/web/audio/react/GuidancePanel.tsx — the per-OS setup guidance dialog (design §7.2, §7.7).
import { useEffect, useRef } from "react";
import type { AudioController } from "../controller.js";
import { guidanceFor } from "../lanes/guidance.js";
import type { CaptureLaneId, GuidanceReason, LaneSource, OsId } from "../types.js";
import { useAudioController } from "./useAudioController.js";

export interface GuidancePanelProps {
  /** With { controller } alone the panel follows state.guidance (and renders nothing while it is null). */
  controller?: AudioController;
  os?: OsId;
  lane?: CaptureLaneId;
  reason?: GuidanceReason;
  source?: LaneSource;
  onClose?(): void;
}

/** The controller-driven variant: reads guidance / source / os from the controller. */
export function GuidancePanel(props: GuidancePanelProps) {
  if (props.controller) return <ControllerGuidance controller={props.controller} {...props} />;
  if (!props.lane || !props.reason) return null;
  return <GuidancePanelView os={props.os ?? "other"} lane={props.lane} reason={props.reason} source={props.source ?? { kind: "display" }} onClose={props.onClose ?? (() => undefined)} />;
}

function ControllerGuidance({ controller, ...rest }: GuidancePanelProps & { controller: AudioController }) {
  const state = useAudioController(controller);
  const g = state.guidance;
  const lane = rest.lane ?? g?.lane;
  const reason = rest.reason ?? g?.reason;
  if (!lane || !reason) return null;
  return <GuidancePanelView os={rest.os ?? controller.os} lane={lane} reason={reason} source={rest.source ?? state.lanes[lane].source} onClose={rest.onClose ?? (() => controller.closeGuidance())} />;
}

/** Renders the **bold** markers of the guidance copy as <strong>. */
function rich(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => (p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : <span key={i}>{p}</span>));
}

export function GuidancePanelView({ os, lane, reason, source, onClose }: { os: OsId; lane: CaptureLaneId; reason: GuidanceReason; source: LaneSource; onClose(): void }) {
  const g = guidanceFor(os, lane, reason, source);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    closeRef.current?.focus();
  }, [lane, reason]);
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30" onKeyDown={(e) => e.key === "Escape" && (e.preventDefault(), onClose())}>
      <div data-testid="guidance-panel" data-os={os} data-reason={reason} data-lane={lane} role="dialog" aria-modal="true" aria-labelledby="guidance-title" className="max-w-lg rounded bg-white p-4 text-slate-900 shadow">
        <h2 id="guidance-title" className="text-base font-semibold">
          {g.title}
        </h2>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          {g.steps.map((s, i) => (
            <li key={i}>{rich(s)}</li>
          ))}
        </ol>
        {g.alternatives.length > 0 ? (
          <>
            <h3 className="mt-3 text-sm font-semibold">Alternatives</h3>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {g.alternatives.map((s, i) => (
                <li key={i}>{rich(s)}</li>
              ))}
            </ul>
          </>
        ) : null}
        {g.note ? <p className="mt-3 text-xs opacity-80">{rich(g.note)}</p> : null}
        <div className="mt-4 flex justify-end">
          <button ref={closeRef} type="button" data-testid="guidance-close" className="rounded border px-3 py-1 text-sm" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
