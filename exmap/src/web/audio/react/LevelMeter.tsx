// exmap/src/web/audio/react/LevelMeter.tsx — role="meter" fed from controller.levels on its own animation frame
// (design §7.3, §7.7): the level never goes through the React snapshot.
import { useEffect, useRef } from "react";
import type { AudioController } from "../controller.js";
import type { CaptureLaneId } from "../types.js";

export function LevelMeter({ controller, lane }: { controller: AudioController; lane: CaptureLaneId }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const barRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    let raf = 0;
    let last = -1;
    const tick = () => {
      const level = controller.levels[lane];
      if (level !== last) {
        last = level;
        const pct = Math.round(level * 100);
        if (ref.current) ref.current.setAttribute("aria-valuenow", String(pct));
        if (barRef.current) barRef.current.style.width = `${pct}%`;
      }
      raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame(tick) : 0;
    };
    tick();
    return () => {
      if (raf && typeof cancelAnimationFrame === "function") cancelAnimationFrame(raf);
    };
  }, [controller, lane]);
  return (
    <div
      ref={ref}
      data-testid={`level-${lane}`}
      role="meter"
      aria-label={lane === "remote" ? "Call level" : "Microphone level"}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={0}
      className="h-2 w-24 overflow-hidden rounded bg-slate-200"
    >
      <div ref={barRef} className="h-full bg-green-600" style={{ width: "0%" }} />
    </div>
  );
}
