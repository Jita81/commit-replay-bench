// tests/unit/audio/helpers.ts — synthetic 20 ms frames (320 samples at 16 kHz) and a feed() over the segmenter.
import { FRAME_MS, FRAME_SAMPLES } from "../../../src/web/audio/dsp/vad.js";
import { segmenterStep, type SegmenterConfig, type SegmenterState } from "../../../src/web/audio/dsp/segmenter.js";
import type { VadConfig } from "../../../src/web/audio/dsp/vad.js";
import type { Segment } from "../../../src/web/audio/types.js";

export { FRAME_MS, FRAME_SAMPLES };

export function silence(n: number): Float32Array[] {
  return Array.from({ length: n }, () => new Float32Array(FRAME_SAMPLES));
}

/** A sine of the given amplitude; amplitude a gives RMS a/√2 (a = 1 → ≈ 0.707 → −3 dBFS). */
export function tone(n: number, amplitude: number, hz = 440, sampleRate = 16000, phaseStart = 0): Float32Array[] {
  const out: Float32Array[] = [];
  let k = phaseStart;
  for (let f = 0; f < n; f++) {
    const frame = new Float32Array(FRAME_SAMPLES);
    for (let i = 0; i < FRAME_SAMPLES; i++, k++) frame[i] = amplitude * Math.sin((2 * Math.PI * hz * k) / sampleRate);
    out.push(frame);
  }
  return out;
}

/** Deterministic pseudo-noise at the given RMS (a seeded LCG so frames are byte-for-byte reproducible). */
export function noise(n: number, rms: number, seed = 1): Float32Array[] {
  let s = seed >>> 0;
  const rnd = () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
  const out: Float32Array[] = [];
  for (let f = 0; f < n; f++) {
    const frame = new Float32Array(FRAME_SAMPLES);
    let acc = 0;
    for (let i = 0; i < FRAME_SAMPLES; i++) {
      const v = rnd() * 2 - 1;
      frame[i] = v;
      acc += v * v;
    }
    const scale = rms / Math.sqrt(acc / FRAME_SAMPLES);
    for (let i = 0; i < FRAME_SAMPLES; i++) frame[i] = (frame[i] ?? 0) * scale;
    out.push(frame);
  }
  return out;
}

/** Frames at an exact dBFS level (a tone scaled so frameRms gives that dB). */
export function framesAtDb(n: number, db: number, hz = 440): Float32Array[] {
  const rms = Math.pow(10, db / 20);
  return tone(n, rms * Math.SQRT2, hz);
}

export function dbToAmplitude(db: number): number {
  return Math.pow(10, db / 20) * Math.SQRT2;
}

export interface FeedResult {
  state: SegmenterState;
  segments: Segment[];
  /** the time of the next frame after the feed */
  tMs: number;
}

export function feed(
  segmenter: SegmenterState,
  frames: Float32Array[],
  t0: number,
  opts: { speaker?: string | null | ((i: number) => string | null); cfg?: SegmenterConfig; vad?: VadConfig } = {},
): FeedResult {
  let state = segmenter;
  const segments: Segment[] = [];
  let t = t0;
  frames.forEach((pcm, i) => {
    const speaker = typeof opts.speaker === "function" ? opts.speaker(i) : (opts.speaker ?? null);
    const r = segmenterStep(state, pcm, t, speaker, opts.cfg, opts.vad);
    state = r.state;
    if (r.segment) segments.push(r.segment);
    t += FRAME_MS;
  });
  return { state, segments, tMs: t };
}

export function concatFrames(frames: Float32Array[]): Float32Array {
  const out = new Float32Array(frames.length * FRAME_SAMPLES);
  frames.forEach((f, i) => out.set(f, i * FRAME_SAMPLES));
  return out;
}
