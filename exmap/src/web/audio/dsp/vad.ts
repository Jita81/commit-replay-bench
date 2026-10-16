// exmap/src/web/audio/dsp/vad.ts — energy VAD over 20 ms frames with an adaptive noise floor (design §7.3). Pure.
export const FRAME_MS = 20;
export const SAMPLE_RATE = 16000;
export const FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) / 1000; // 320

export interface VadConfig {
  onsetMarginDb: number;
  hangMarginDb: number;
  absMinDb: number;
  floorInitFrames: number;
  floorDownAlpha: number;
  floorUpAlpha: number;
  floorMinDb: number;
  floorMaxDb: number;
  floorReseedMs: number;
}

export const DEFAULT_VAD: VadConfig = {
  onsetMarginDb: 9,
  hangMarginDb: 6,
  absMinDb: -55,
  floorInitFrames: 10,
  floorDownAlpha: 0.2,
  floorUpAlpha: 0.005,
  floorMinDb: -70,
  floorMaxDb: -25,
  floorReseedMs: 3000,
};

export interface VadState {
  floorDb: number;
  frames: number; // frames seen (seeding runs over the first floorInitFrames)
  seedMinDb: number; // the quietest frame seen while seeding
  inSpeech: boolean;
  speechFrames: number; // consecutive speech frames (for the re-seed rule)
  minInSpeechDb: number; // the quietest frame of the current speech run
}

export interface VadStep {
  state: VadState;
  speech: boolean;
  rmsDb: number;
}

export function createVadState(cfg: VadConfig = DEFAULT_VAD): VadState {
  return { floorDb: cfg.floorMinDb, frames: 0, seedMinDb: Number.POSITIVE_INFINITY, inSpeech: false, speechFrames: 0, minInSpeechDb: Number.POSITIVE_INFINITY };
}

export function frameRms(pcm: Float32Array): number {
  if (pcm.length === 0) return 0;
  let acc = 0;
  for (let i = 0; i < pcm.length; i++) {
    const v = pcm[i] ?? 0;
    acc += v * v;
  }
  return Math.sqrt(acc / pcm.length);
}

export function rmsToDb(rms: number): number {
  return 20 * Math.log10(rms + 1e-9);
}

function clampFloor(db: number, cfg: VadConfig): number {
  return Math.min(cfg.floorMaxDb, Math.max(cfg.floorMinDb, db));
}

/** Threshold a frame must exceed to count as speech, from the given state. */
export function speechThresholdDb(state: VadState, cfg: VadConfig = DEFAULT_VAD): number {
  return Math.max(cfg.absMinDb, state.floorDb + (state.inSpeech ? cfg.hangMarginDb : cfg.onsetMarginDb));
}

/**
 * One frame. Floor rules: (1) seeding over the first floorInitFrames never raises the floor above absMinDb − onsetMarginDb;
 * (2) after seeding the floor updates only on non-speech frames (fast down, slow up), clamped; (3) a long run of
 * "speech" whose quietest frame is still an onset above the floor re-seeds the floor to that quietest frame.
 */
export function vadStep(prev: VadState, rmsDb: number, cfg: VadConfig = DEFAULT_VAD): VadStep {
  const s: VadState = { ...prev };
  s.frames = prev.frames + 1;
  if (s.frames <= cfg.floorInitFrames) {
    s.seedMinDb = Math.min(prev.seedMinDb, rmsDb);
    s.floorDb = clampFloor(Math.min(s.seedMinDb, cfg.absMinDb - cfg.onsetMarginDb), cfg);
  }
  const threshold = speechThresholdDb(s, cfg);
  const speech = rmsDb > threshold;
  if (!speech && s.frames > cfg.floorInitFrames) {
    const alpha = rmsDb < s.floorDb ? cfg.floorDownAlpha : cfg.floorUpAlpha;
    s.floorDb = clampFloor(s.floorDb + alpha * (rmsDb - s.floorDb), cfg);
  }
  if (speech) {
    s.speechFrames = prev.speechFrames + 1;
    s.minInSpeechDb = Math.min(prev.minInSpeechDb, rmsDb);
    if (s.speechFrames * FRAME_MS >= cfg.floorReseedMs && s.minInSpeechDb > s.floorDb + cfg.onsetMarginDb) {
      s.floorDb = clampFloor(s.minInSpeechDb, cfg);
      s.speechFrames = 0;
      s.minInSpeechDb = Number.POSITIVE_INFINITY;
    }
  } else {
    s.speechFrames = 0;
    s.minInSpeechDb = Number.POSITIVE_INFINITY;
  }
  s.inSpeech = speech;
  return { state: s, speech, rmsDb };
}
