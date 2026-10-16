// exmap/src/web/audio/react/LaneBadge.tsx — the lane state badge and the provider badge (design §7.7).
import { LANE_ERROR_TEXT } from "../errors.js";
import { providerLabelFor } from "../providers/registry.js";
import type { CaptureLaneId, LaneView, ProviderId } from "../types.js";

export const LANE_NAME: Record<CaptureLaneId, string> = { remote: "Call", me: "Me" };

export function laneStateText(view: LaneView): string {
  switch (view.state) {
    case "idle":
      return "Idle";
    case "requesting":
      return "Requesting…";
    case "live":
      return view.signal === "silent" ? "Live — no sound heard" : "Live";
    case "stopped":
      if (view.stopReason === "ended_by_browser") return "Stopped — sharing ended from the browser bar";
      if (view.stopReason === "device_lost") return "Stopped — device lost";
      return "Stopped";
    case "error":
      return `Error: ${view.error ? LANE_ERROR_TEXT[view.error.code] : "unknown"}`;
  }
}

export function LaneBadge({ view }: { view: LaneView }) {
  const name = LANE_NAME[view.id];
  return (
    <span className="inline-flex flex-col gap-0.5">
      <span
        data-testid={`lane-${view.id}-badge`}
        data-state={view.state}
        data-error-code={view.error?.code ?? undefined}
        data-signal={view.signal}
        aria-live="polite"
        aria-label={`${name} lane status`}
        className={
          "rounded px-2 py-0.5 text-xs font-medium " +
          (view.state === "live" ? "bg-green-100 text-slate-900" : view.state === "error" ? "bg-red-100 text-slate-900" : "bg-slate-100 text-slate-900")
        }
      >
        {laneStateText(view)}
      </span>
      {view.error ? (
        <details className="text-xs">
          <summary className="cursor-pointer opacity-70">details</summary>
          <code data-testid={`lane-${view.id}-error-detail`}>
            {view.error.domName ?? "(no DOMException name)"}: {view.error.message}
          </code>
        </details>
      ) : null}
    </span>
  );
}

export function ProviderBadge({ lane, provider, declined }: { lane: CaptureLaneId; provider: ProviderId | null; declined: boolean }) {
  return (
    <span data-testid={`lane-${lane}-provider-badge`} aria-live="polite" aria-label={`${LANE_NAME[lane]} lane transcription provider`} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-900">
      {providerLabelFor(provider, declined)}
    </span>
  );
}
