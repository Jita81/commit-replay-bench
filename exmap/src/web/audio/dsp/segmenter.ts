// exmap/src/web/audio/dsp/segmenter.ts — turns VAD-labelled 20 ms frames into Segments (design §7.3). Pure: every
// function returns a new state; the caller keeps it. Pre-roll 200 ms, trailing silence 600 ms closes, hard cap 15 s.
import type { CaptureLaneId, Segment } from "../types.js";
import { DEFAULT_VAD, FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE, createVadState, frameRms, rmsToDb, vadStep, type VadConfig, type VadState } from "./vad.js";

export interface SegmenterConfig {
  trailingSilenceMs: number;
  hardCapMs: number;
  minSegmentMs: number;
  preRollMs: number;
  keepTailMs: number;
}

export const DEFAULT_SEGMENTER: SegmenterConfig = {
  trailingSilenceMs: 600,
  hardCapMs: 15000,
  minSegmentMs: 200,
  preRollMs: 200,
  keepTailMs: 200,
};

export interface SegmenterState {
  lane: CaptureLaneId;
  seq: number; // segments emitted so far
  phase: "silence" | "speech";
  vad: VadState;
  preRoll: Float32Array[]; // ring of the last preRollMs / FRAME_MS silence frames
  frames: Float32Array[]; // the current segment's frames (pre-roll included)
  startedAt: number;
  onsetAt: number;
  lastSpeechAt: number;
  peakRmsDb: number;
}

export interface SegmenterStepResult {
  state: SegmenterState;
  segment: Segment | null;
  speech: boolean;
  rmsDb: number;
}

export function createSegmenter(lane: CaptureLaneId, vadCfg: VadConfig = DEFAULT_VAD): SegmenterState {
  return {
    lane,
    seq: 0,
    phase: "silence",
    vad: createVadState(vadCfg),
    preRoll: [],
    frames: [],
    startedAt: 0,
    onsetAt: 0,
    lastSpeechAt: 0,
    peakRmsDb: Number.NEGATIVE_INFINITY,
  };
}

function concat(frames: Float32Array[]): Float32Array {
  let n = 0;
  for (const f of frames) n += f.length;
  const out = new Float32Array(n);
  let o = 0;
  for (const f of frames) {
    out.set(f, o);
    o += f.length;
  }
  return out;
}

function emit(s: SegmerCloseInput, endedAt: number, speechMs: number, frames: Float32Array[], speaker: string | null, capped: boolean): Segment {
  return {
    lane: s.lane,
    seq: s.seq,
    startedAt: s.startedAt,
    onsetAt: s.onsetAt,
    endedAt,
    speechMs,
    pcm: concat(frames),
    sampleRate: SAMPLE_RATE,
    peakRmsDb: s.peakRmsDb,
    cappedAt15s: capped,
    speaker,
  };
}

interface SegmerCloseInput {
  lane: CaptureLaneId;
  seq: number;
  startedAt: number;
  onsetAt: number;
  peakRmsDb: number;
}

/** Rule 3: close on trailing silence — trim the silence beyond keepTailMs; discard under minSegmentMs. */
function closeOnSilence(s: SegmenterState, speaker: string | null, cfg: SegmenterConfig): { state: SegmenterState; segment: Segment | null } {
  const speechMs = s.lastSpeechAt + FRAME_MS - s.onsetAt;
  const next: SegmenterState = { ...s, phase: "silence", frames: [], preRoll: [], peakRmsDb: Number.NEGATIVE_INFINITY };
  if (speechMs < cfg.minSegmentMs) return { state: next, segment: null };
  const endedAt = s.lastSpeechAt + FRAME_MS + cfg.keepTailMs;
  const keepFrames = Math.round((endedAt - s.startedAt) / FRAME_MS);
  const frames = s.frames.slice(0, keepFrames);
  next.seq = s.seq + 1;
  const segment = emit({ ...s, seq: next.seq }, endedAt, speechMs, frames, speaker, false);
  return { state: next, segment };
}

/**
 * One frame at session time tMs (its start). `speaker` is the lane's label at this moment; it is stamped on a segment
 * closed by this frame. Frames are 320 samples of mono 16 kHz PCM.
 */
export function segmenterStep(
  prev: SegmenterState,
  pcm: Float32Array,
  tMs: number,
  speaker: string | null,
  cfg: SegmenterConfig = DEFAULT_SEGMENTER,
  vadCfg: VadConfig = DEFAULT_VAD,
): SegmenterStepResult {
  const rmsDb = rmsToDb(frameRms(pcm));
  const v = vadStep(prev.vad, rmsDb, vadCfg);
  const s: SegmenterState = { ...prev, vad: v.state };
  const preRollFrames = Math.round(cfg.preRollMs / FRAME_MS);

  if (s.phase === "silence") {
    if (!v.speech) {
      const ring = s.preRoll.length >= preRollFrames ? s.preRoll.slice(s.preRoll.length - preRollFrames + 1) : s.preRoll.slice();
      ring.push(pcm);
      s.preRoll = ring;
      return { state: s, segment: null, speech: false, rmsDb };
    }
    // onset
    s.phase = "speech";
    s.frames = [...s.preRoll, pcm];
    s.onsetAt = tMs;
    s.startedAt = tMs - FRAME_MS * s.preRoll.length;
    s.lastSpeechAt = tMs;
    s.peakRmsDb = rmsDb;
    s.preRoll = [];
    return { state: s, segment: null, speech: true, rmsDb };
  }

  // in speech
  s.frames = [...s.frames, pcm];
  if (v.speech) {
    s.lastSpeechAt = tMs;
    if (rmsDb > s.peakRmsDb) s.peakRmsDb = rmsDb;
  }
  // rule 4: hard cap — emit and stay in speech with fresh buffers (no sample lost or duplicated)
  if (tMs + FRAME_MS - s.startedAt >= cfg.hardCapMs) {
    const endedAt = tMs + FRAME_MS;
    const seq = s.seq + 1;
    const segment = emit({ ...s, seq }, endedAt, s.lastSpeechAt + FRAME_MS - s.onsetAt, s.frames, speaker, true);
    const next: SegmenterState = {
      ...s,
      seq,
      frames: [],
      startedAt: endedAt,
      onsetAt: endedAt,
      lastSpeechAt: v.speech ? tMs : s.lastSpeechAt,
      peakRmsDb: Number.NEGATIVE_INFINITY,
    };
    return { state: next, segment, speech: v.speech, rmsDb };
  }
  // rule 3: trailing silence
  if (!v.speech && tMs + FRAME_MS - s.lastSpeechAt >= cfg.trailingSilenceMs) {
    const closed = closeOnSilence(s, speaker, cfg);
    return { state: closed.state, segment: closed.segment, speech: false, rmsDb };
  }
  return { state: s, segment: null, speech: v.speech, rmsDb };
}

/** Rule 5: closes an in-speech phase as rule 3 would; in silence returns null. */
export function segmenterFlush(prev: SegmenterState, _tMs: number, speaker: string | null, cfg: SegmenterConfig = DEFAULT_SEGMENTER): { state: SegmenterState; segment: Segment | null } {
  if (prev.phase !== "speech") return { state: prev, segment: null };
  return closeOnSilence(prev, speaker, cfg);
}

export { FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE };
