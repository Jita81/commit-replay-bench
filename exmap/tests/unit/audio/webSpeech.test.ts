// tests/unit/audio/webSpeech.test.ts — TEST-PLAN §3 cases 48–49.
import { beforeEach, describe, expect, it } from "vitest";
import { fixedClock } from "../../../src/web/audio/clock.js";
import { ProviderError } from "../../../src/web/audio/errors.js";
import { WebSpeechProvider } from "../../../src/web/audio/providers/webSpeech.js";
import { SpeakerStore } from "../../../src/web/audio/speakers.js";
import type { ProviderContext, UtteranceDraft } from "../../../src/web/audio/types.js";
import { FakeRecognition, fakeTimers } from "./fakes.js";

function setup(consent = true) {
  const timers = fakeTimers();
  const errors: ProviderError[] = [];
  const emitted: UtteranceDraft[] = [];
  const interim: Array<string | null> = [];
  const clock = fixedClock(10_000);
  const speakers = new SpeakerStore({ userName: "Sam" });
  const ctx: ProviderContext = { emit: (d) => emitted.push(d), onInterim: (_l, t) => interim.push(t), clock, speakers, signal: new AbortController().signal };
  const p = new WebSpeechProvider({ ctor: FakeRecognition, lang: "en-GB", consentGiven: () => consent, timers, onError: (e) => errors.push(e) });
  return { p, timers, errors, emitted, interim, clock, ctx };
}

describe("WebSpeechProvider", () => {
  beforeEach(() => {
    FakeRecognition.instances = [];
  });

  it("48. interim results go to onInterim and are never emitted; a final emits with tStartMs from the first interim; confidence 0 → null; a restart resets", async () => {
    const { p, emitted, interim, clock, ctx } = setup();
    await p.start(ctx);
    const rec = FakeRecognition.instances[0]!;
    expect(rec.continuous).toBe(true);
    expect(rec.interimResults).toBe(true);
    expect(rec.maxAlternatives).toBe(1);
    expect(rec.lang).toBe("en-GB");
    expect(rec.startCalls).toBe(1);
    expect(p.label).toContain("not local");
    expect(p.isLocal).toBe(false);
    rec.result(0, "we also", false);
    clock.set(11_500);
    rec.result(0, "we also need", false);
    expect(emitted).toHaveLength(0);
    expect(interim).toEqual(["we also", "we also need"]);
    clock.set(12_000);
    rec.result(0, "We also need an error case.", true, 0.83);
    expect(emitted).toHaveLength(1);
    expect(emitted[0]).toMatchObject({ text: "We also need an error case.", lane: "me", speaker: "Sam", provider: "web-speech", model: null, isLocal: false, confidence: 0.83, tStartMs: 10_000, tEndMs: 12_000 });
    expect(interim.at(-1)).toBeNull();
    // confidence 0 → null; a final without interims starts 1 s before now
    clock.set(20_000);
    rec.result(1, "Yes.", true, 0);
    expect(emitted[1]).toMatchObject({ confidence: null, tStartMs: 19_000, tEndMs: 20_000 });
    // after an onend restart a new interim at index 0 gets a fresh tStartMs
    rec.end();
    const { timers } = setup();
    void timers; // the provider's own timers were used above
    await p.stop();
  });

  it("48b. restart bookkeeping: after onend a new recogniser's index 0 starts fresh", async () => {
    const { p, timers, emitted, clock, ctx } = setup();
    await p.start(ctx);
    const first = FakeRecognition.instances[0]!;
    clock.set(10_000);
    first.result(0, "first", false);
    first.end();
    timers.advance(250);
    const second = FakeRecognition.instances[1]!;
    expect(second).toBeDefined();
    expect(second.startCalls).toBe(1);
    clock.set(30_000);
    second.result(0, "again", false);
    clock.set(31_000);
    second.result(0, "Again.", true, 0.5);
    expect(emitted[0]!.tStartMs).toBe(30_000);
    await p.stop();
  });

  it("49. onend restarts while started; network surfaces once and backs off; not-allowed stops with WEB_SPEECH_DENIED; no consent rejects", async () => {
    const { p, timers, errors, ctx } = setup();
    await p.start(ctx);
    const a = FakeRecognition.instances[0]!;
    a.end();
    expect(FakeRecognition.instances).toHaveLength(1);
    timers.advance(250);
    expect(FakeRecognition.instances).toHaveLength(2);
    const b = FakeRecognition.instances[1]!;
    b.error("network", "offline");
    b.end();
    expect(errors.map((e) => e.code)).toEqual(["WEB_SPEECH_NETWORK"]);
    timers.advance(999);
    expect(FakeRecognition.instances).toHaveLength(2);
    timers.advance(1);
    expect(FakeRecognition.instances).toHaveLength(3);
    const c = FakeRecognition.instances[2]!;
    c.error("network");
    c.end();
    expect(errors).toHaveLength(1); // surfaced once
    timers.advance(1999);
    expect(FakeRecognition.instances).toHaveLength(3);
    timers.advance(1);
    expect(FakeRecognition.instances).toHaveLength(4);
    const d = FakeRecognition.instances[3]!;
    d.error("no-speech");
    d.end();
    timers.advance(4000); // the network backoff is still in force (4 s now)
    expect(FakeRecognition.instances).toHaveLength(5);
    const e = FakeRecognition.instances[4]!;
    e.error("not-allowed", "denied by the user");
    expect(errors.map((x) => x.code)).toEqual(["WEB_SPEECH_NETWORK", "WEB_SPEECH_DENIED"]);
    expect(p.started).toBe(false);
    e.end();
    timers.advance(60_000);
    expect(FakeRecognition.instances).toHaveLength(5); // no restart after a denial
    await p.stop();

    const noConsent = setup(false);
    await expect(noConsent.p.start(noConsent.ctx)).rejects.toMatchObject({ code: "WEB_SPEECH_DENIED", detail: "consent not given" });
    expect(FakeRecognition.instances).toHaveLength(5); // no recogniser was constructed

    const unsupported = new WebSpeechProvider({ ctor: null, lang: "en-US", consentGiven: () => true });
    await expect(unsupported.start(ctx)).rejects.toMatchObject({ code: "WEB_SPEECH_UNSUPPORTED" });

    const capture = setup();
    await capture.p.start(capture.ctx);
    FakeRecognition.instances.at(-1)!.error("audio-capture");
    expect(capture.errors[0]).toMatchObject({ code: "WEB_SPEECH_DENIED", detail: "no microphone" });
  });
});
