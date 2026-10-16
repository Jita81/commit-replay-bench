// exmap/src/web/audio/dsp/levels.ts — the meter level (design §7.3): a peak-hold with 15 % decay per frame, mapped from
// [−60, 0] dBFS onto [0, 1]. Lives on controller.levels (outside the React snapshot); LevelMeter reads it per frame.
export function levelStep(prev: number, rmsDb: number): number {
  const instant = Math.min(1, Math.max(0, (rmsDb + 60) / 60));
  return Math.max(prev * 0.85, instant);
}
