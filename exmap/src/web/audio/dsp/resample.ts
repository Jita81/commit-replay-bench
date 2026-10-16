// exmap/src/web/audio/dsp/resample.ts — fallback resampler for an AudioContext that refused 16 kHz (design §7.3):
// one-pole low-pass at 7 kHz then linear interpolation. Used only on that path; Chromium normally resamples for us.
export const TARGET_RATE = 16000;
const CUTOFF_HZ = 7000;

/** Mono float PCM at `fromRate` → 16 kHz. Returns the input untouched when the rate already matches. */
export function resampleTo16k(pcm: Float32Array, fromRate: number): Float32Array {
  if (fromRate === TARGET_RATE || pcm.length === 0) return pcm;
  const ratio = fromRate / TARGET_RATE;
  const outLen = Math.round(pcm.length / ratio);
  // one-pole low-pass (only meaningful when downsampling)
  let src = pcm;
  if (fromRate > TARGET_RATE) {
    const rc = 1 / (2 * Math.PI * CUTOFF_HZ);
    const dt = 1 / fromRate;
    const alpha = dt / (rc + dt);
    const filtered = new Float32Array(pcm.length);
    let y = 0;
    for (let i = 0; i < pcm.length; i++) {
      y += alpha * ((pcm[i] ?? 0) - y);
      filtered[i] = y;
    }
    src = filtered;
  }
  const out = new Float32Array(outLen);
  const last = src.length - 1;
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const i0 = Math.min(last, Math.floor(pos));
    const i1 = Math.min(last, i0 + 1);
    const frac = pos - i0;
    out[i] = (src[i0] ?? 0) * (1 - frac) + (src[i1] ?? 0) * frac;
  }
  return out;
}
