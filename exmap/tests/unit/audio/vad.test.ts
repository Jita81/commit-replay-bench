// tests/unit/audio/vad.test.ts — TEST-PLAN §3 cases 1–8.
import { describe, expect, it } from "vitest";
import { createVadState, DEFAULT_VAD, frameRms, rmsToDb, vadStep, type VadState } from "../../../src/web/audio/dsp/vad.js";
import { FRAME_SAMPLES, tone } from "./helpers.js";

function run(state: VadState, dbs: number[]): { state: VadState; speech: boolean[] } {
  const speech: boolean[] = [];
  let s = state;
  for (const db of dbs) {
    const r = vadStep(s, db);
    s = r.state;
    speech.push(r.speech);
  }
  return { state: s, speech };
}

const seeded = (db: number) => run(createVadState(), Array(10).fill(db)).state;

describe("vad", () => {
  it("1. frameRms of zeros = 0; of a full-scale sine ≈ 0.707; rmsToDb(0) ≈ −180", () => {
    expect(frameRms(new Float32Array(FRAME_SAMPLES))).toBe(0);
    const [sine] = tone(1, 1, 1000);
    expect(frameRms(sine!)).toBeCloseTo(Math.SQRT1_2, 2);
    expect(rmsToDb(0)).toBeCloseTo(-180, 5);
  });

  it("2. seeding: −50 → floor −64; −75 → −70; −20 (speech from frame 0) → −64 and frame 11 at −20 is speech", () => {
    expect(seeded(-50).floorDb).toBe(-64);
    expect(seeded(-75).floorDb).toBe(-70);
    const loud = run(createVadState(), Array(10).fill(-20));
    expect(loud.speech[0]).toBe(true);
    expect(loud.state.floorDb).toBe(-64);
    expect(vadStep(loud.state, -20).speech).toBe(true);
  });

  it("3. the floor drops quickly (20 % per quieter frame) and rises slowly (0.5 %)", () => {
    const s = seeded(-50); // floor −64
    const down = vadStep(s, -70).state;
    expect(down.floorDb).toBeCloseTo(-64 + 0.2 * (-70 - -64), 6);
    const up = vadStep(s, -60).state; // non-speech (−60 < −55), above the floor
    expect(up.floorDb).toBeCloseTo(-64 + 0.005 * (-60 - -64), 6);
  });

  it("4. the floor does not rise during speech frames", () => {
    const s = seeded(-50);
    const r = run(s, Array(100).fill(-20));
    expect(r.speech.every(Boolean)).toBe(true);
    expect(r.state.floorDb).toBe(-64);
  });

  it("5. onset needs floor + 9; floor + 7 is silence from silence but speech from inSpeech", () => {
    const base: VadState = { ...createVadState(), frames: DEFAULT_VAD.floorInitFrames, floorDb: -60 };
    expect(vadStep({ ...base, inSpeech: false }, -53).speech).toBe(false); // floor + 7
    expect(vadStep({ ...base, inSpeech: false }, -50.9).speech).toBe(true); // floor + 9.1
    expect(vadStep({ ...base, inSpeech: true }, -53).speech).toBe(true); // hang: floor + 6
  });

  it("6. nothing below −55 dBFS is speech even with a very low floor", () => {
    const base: VadState = { ...createVadState(), frames: DEFAULT_VAD.floorInitFrames, floorDb: -70 };
    expect(vadStep(base, -56).speech).toBe(false);
    expect(vadStep({ ...base, inSpeech: true }, -56).speech).toBe(false);
    expect(vadStep(base, -54).speech).toBe(true);
  });

  it("7. the floor is clamped to [−70, −25]", () => {
    expect(seeded(-120).floorDb).toBe(-70);
    const high: VadState = { ...createVadState(), frames: DEFAULT_VAD.floorInitFrames, floorDb: -26 };
    const r = run(high, Array(2000).fill(-10)); // −10 is not speech from a −26 floor (needs −17); it pulls the floor up
    expect(r.state.floorDb).toBeLessThanOrEqual(-25);
    expect(r.state.floorDb).toBeGreaterThan(-26);
    expect(r.state.floorDb).toBeCloseTo(-25, 3);
  });

  it("8. re-seed inside long speech", () => {
    // steady −45 dB noise from frame 0 → speech from frame 1; after 3 s the floor ≈ −45 and the next frame is not speech
    const a = run(createVadState(), Array(150).fill(-45));
    expect(a.speech.slice(1).every(Boolean)).toBe(true);
    expect(a.state.floorDb).toBeCloseTo(-45, 6);
    expect(vadStep(a.state, -45).speech).toBe(false);
    // speech at −20 with every 10th frame at −40 → floor −40 and the −20 frames still speech
    const pattern = Array.from({ length: 160 }, (_, i) => (i % 10 === 9 ? -40 : -20));
    const b = run(createVadState(), pattern);
    expect(b.state.floorDb).toBeCloseTo(-40, 6);
    expect(vadStep(b.state, -20).speech).toBe(true);
    const afterQuiet = vadStep(vadStep(b.state, -40).state, -20);
    expect(afterQuiet.speech).toBe(true);
    expect(afterQuiet.state.floorDb).toBeCloseTo(-40, 1);
  });
});
