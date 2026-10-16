// tests/unit/audio/segmenter.test.ts — TEST-PLAN §3 cases 9–18.
import { describe, expect, it } from "vitest";
import { createSegmenter, DEFAULT_SEGMENTER, segmenterFlush } from "../../../src/web/audio/dsp/segmenter.js";
import { DEFAULT_VAD, rmsToDb, frameRms } from "../../../src/web/audio/dsp/vad.js";
import { concatFrames, feed, FRAME_MS, FRAME_SAMPLES, framesAtDb, noise, silence } from "./helpers.js";

const NO_RESEED = { ...DEFAULT_VAD, floorReseedMs: Number.POSITIVE_INFINITY };

describe("segmenter", () => {
  it("9. 1 s silence, 1 s −20 dB speech, 1 s silence → one segment with the designed bounds", () => {
    const frames = [...silence(50), ...framesAtDb(50, -20), ...silence(50)];
    const { segments } = feed(createSegmenter("me"), frames, 0);
    expect(segments).toHaveLength(1);
    const s = segments[0]!;
    expect(s.startedAt).toBe(800);
    expect(s.onsetAt).toBe(1000);
    expect(s.speechMs).toBe(1000);
    const lastSpeechAt = 1000 + 49 * FRAME_MS;
    expect(s.endedAt).toBe(lastSpeechAt + FRAME_MS + DEFAULT_SEGMENTER.keepTailMs);
    expect(s.pcm.length).toBe((s.endedAt - s.startedAt) * 16);
    expect(s.seq).toBe(1);
    expect(s.cappedAt15s).toBe(false);
    expect(s.sampleRate).toBe(16000);
    expect(s.lane).toBe("me");
  });

  it("10. the pre-roll holds exactly the 10 frames before the onset frame, byte-for-byte, then the onset frame", () => {
    const quiet = noise(30, Math.pow(10, -70 / 20), 7); // −70 dB noise frames, each different
    const loud = framesAtDb(30, -20);
    const frames = [...quiet, ...loud, ...silence(40)];
    const { segments } = feed(createSegmenter("remote"), frames, 0);
    expect(segments).toHaveLength(1);
    const pcm = segments[0]!.pcm;
    for (let i = 0; i < 10; i++) {
      const expected = quiet[20 + i]!;
      expect(Array.from(pcm.subarray(i * FRAME_SAMPLES, (i + 1) * FRAME_SAMPLES))).toEqual(Array.from(expected));
    }
    expect(Array.from(pcm.subarray(10 * FRAME_SAMPLES, 11 * FRAME_SAMPLES))).toEqual(Array.from(loud[0]!));
  });

  it("11. onset at frame 3 → startedAt = onsetAt − 60", () => {
    const frames = [...silence(3), ...framesAtDb(30, -20), ...silence(40)];
    const { segments } = feed(createSegmenter("me"), frames, 0);
    expect(segments).toHaveLength(1);
    expect(segments[0]!.onsetAt).toBe(60);
    expect(segments[0]!.startedAt).toBe(0);
  });

  it("12. a 150 ms blip → null, back in silence; a 300 ms \"Yes.\" → a segment with speechMs 300", () => {
    const blip = feed(createSegmenter("me"), [...silence(20), ...framesAtDb(7, -20), ...silence(40)], 0);
    expect(blip.segments).toHaveLength(0);
    expect(blip.state.phase).toBe("silence");
    const yes = feed(createSegmenter("me"), [...silence(20), ...framesAtDb(15, -20), ...silence(40)], 0);
    expect(yes.segments).toHaveLength(1);
    expect(yes.segments[0]!.speechMs).toBe(300);
  });

  it("13. a 500 ms gap inside speech does not close; 600 ms does", () => {
    const base = [...silence(20), ...framesAtDb(50, -20)];
    const short = feed(createSegmenter("me"), [...base, ...silence(25), ...framesAtDb(50, -20), ...silence(40)], 0);
    expect(short.segments).toHaveLength(1);
    expect(short.segments[0]!.speechMs).toBe((50 + 25 + 50) * FRAME_MS);
    const long = feed(createSegmenter("me"), [...base, ...silence(30), ...framesAtDb(50, -20), ...silence(40)], 0);
    expect(long.segments).toHaveLength(2);
    expect(long.segments[0]!.speechMs).toBe(1000);
  });

  it("14. 1 s silence then 20 s continuous speech → the hard cap at exactly 15 000 ms, then a fresh segment; nothing lost", () => {
    const speech = framesAtDb(1000, -20, 333);
    const frames = [...silence(50), ...speech];
    const fed = feed(createSegmenter("me"), frames, 0, { vad: NO_RESEED });
    expect(fed.segments).toHaveLength(1);
    const first = fed.segments[0]!;
    expect(first.startedAt).toBe(800);
    expect(first.endedAt - first.startedAt).toBe(15000);
    expect(first.cappedAt15s).toBe(true);
    expect(first.pcm.length).toBe(15000 * 16);
    const flushed = segmenterFlush(fed.state, fed.tMs, null);
    expect(flushed.segment).not.toBeNull();
    const second = flushed.segment!;
    expect(second.startedAt).toBe(first.endedAt);
    expect(second.onsetAt).toBe(first.endedAt);
    expect(second.seq).toBe(2);
    const joined = new Float32Array(first.pcm.length + second.pcm.length);
    joined.set(first.pcm, 0);
    joined.set(second.pcm, first.pcm.length);
    expect(Array.from(joined)).toEqual(Array.from(concatFrames(frames.slice(40))));
  });

  it("15. start mid-speech: continuous −20 dB from frame 0 → one segment with onsetAt 0", () => {
    const fed = feed(createSegmenter("me"), framesAtDb(100, -20), 0);
    expect(fed.segments).toHaveLength(0);
    const { segment } = segmenterFlush(fed.state, fed.tMs, null);
    expect(segment).not.toBeNull();
    expect(segment!.onsetAt).toBe(0);
    expect(segment!.startedAt).toBe(0);
    expect(segment!.speechMs).toBe(2000);
  });

  it("16. segmenterFlush in speech emits; in silence returns null; < 200 ms speech returns null", () => {
    const inSpeech = feed(createSegmenter("me"), [...silence(20), ...framesAtDb(30, -20)], 0);
    expect(segmenterFlush(inSpeech.state, inSpeech.tMs, null).segment).not.toBeNull();
    const inSilence = feed(createSegmenter("me"), silence(20), 0);
    expect(segmenterFlush(inSilence.state, inSilence.tMs, null).segment).toBeNull();
    const tooShort = feed(createSegmenter("me"), [...silence(20), ...framesAtDb(5, -20)], 0);
    expect(segmenterFlush(tooShort.state, tooShort.tMs, null).segment).toBeNull();
  });

  it("17. speaker is stamped at close time; a change before the close frame is reflected, after it is not; null as null", () => {
    const frames = [...silence(20), ...framesAtDb(30, -20), ...silence(40)];
    // the close frame is the 29th silence frame after the last speech frame (tMs + 20 − lastSpeechAt ≥ 600)
    const closeIndex = 20 + 30 + 29;
    const before = feed(createSegmenter("me"), frames, 0, { speaker: (i) => (i >= closeIndex - 1 ? "Bob" : "Alice") });
    expect(before.segments[0]!.speaker).toBe("Bob");
    const after = feed(createSegmenter("me"), frames, 0, { speaker: (i) => (i > closeIndex ? "Bob" : "Alice") });
    expect(after.segments[0]!.speaker).toBe("Alice");
    const none = feed(createSegmenter("me"), frames, 0, { speaker: null });
    expect(none.segments[0]!.speaker).toBeNull();
  });

  it("18. peakRmsDb equals the loudest frame's dB", () => {
    const loudest = framesAtDb(1, -12)[0]!;
    const frames = [...silence(20), ...framesAtDb(10, -30), loudest, ...framesAtDb(10, -25), ...silence(40)];
    const { segments } = feed(createSegmenter("me"), frames, 0);
    expect(segments[0]!.peakRmsDb).toBeCloseTo(rmsToDb(frameRms(loudest)), 9);
  });
});
