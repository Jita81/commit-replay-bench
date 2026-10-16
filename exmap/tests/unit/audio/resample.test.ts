// tests/unit/audio/resample.test.ts — TEST-PLAN §3 case 51.
import { describe, expect, it } from "vitest";
import { resampleTo16k } from "../../../src/web/audio/dsp/resample.js";
import { frameRms, rmsToDb } from "../../../src/web/audio/dsp/vad.js";

describe("resampleTo16k", () => {
  it("51. 48 000 → 16 000 gives length/3 (±1) and a 1 kHz tone keeps its RMS within 1 dB", () => {
    const n = 48000;
    const input = new Float32Array(n);
    for (let i = 0; i < n; i++) input[i] = 0.5 * Math.sin((2 * Math.PI * 1000 * i) / 48000);
    const out = resampleTo16k(input, 48000);
    expect(Math.abs(out.length - n / 3)).toBeLessThanOrEqual(1);
    const inDb = rmsToDb(frameRms(input));
    const outDb = rmsToDb(frameRms(out));
    expect(Math.abs(inDb - outDb)).toBeLessThan(1);
  });

  it("returns the input untouched at 16 kHz and handles an empty frame", () => {
    const a = new Float32Array([0.1, 0.2]);
    expect(resampleTo16k(a, 16000)).toBe(a);
    expect(resampleTo16k(new Float32Array(0), 48000).length).toBe(0);
  });
});
