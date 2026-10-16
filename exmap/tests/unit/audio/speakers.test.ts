// tests/unit/audio/speakers.test.ts — TEST-PLAN §3 case 50.
import { describe, expect, it } from "vitest";
import { memoryStorage } from "../../../src/web/audio/settings.js";
import { REMOTE_KNOWN_KEY, REMOTE_KNOWN_MAX, SpeakerStore } from "../../../src/web/audio/speakers.js";

describe("SpeakerStore", () => {
  it("50. labels are only what a person set; remoteKnown dedupes and caps at 20; manual mirrors me; userName seeds me", () => {
    const session = memoryStorage();
    const s = new SpeakerStore({ userName: null, sessionStorage: session });
    expect(s.get("remote")).toBeNull();
    expect(s.get("me")).toBeNull();
    expect(s.get("manual")).toBeNull();
    let notified = 0;
    s.subscribe(() => notified++);
    s.set("remote", "  Bob ");
    expect(s.get("remote")).toBe("Bob");
    expect(s.labels.remoteKnown).toEqual(["Bob"]);
    s.set("remote", "Bob");
    expect(s.labels.remoteKnown).toEqual(["Bob"]);
    expect(JSON.parse(session.getItem(REMOTE_KNOWN_KEY)!)).toEqual(["Bob"]);
    s.set("remote", "");
    expect(s.get("remote")).toBeNull();
    expect(s.labels.remote).toBeNull();
    expect(notified).toBe(3);
    s.set("me", "Sam");
    expect(s.get("manual")).toBe("Sam");
    expect(s.get("me")).toBe("Sam");
    for (let i = 0; i < 25; i++) s.set("remote", `Person ${i}`);
    expect(s.labels.remoteKnown).toHaveLength(REMOTE_KNOWN_MAX);
    expect(s.labels.remoteKnown[0]).toBe("Person 5");
    expect(s.labels.remoteKnown.at(-1)).toBe("Person 24");

    const seeded = new SpeakerStore({ userName: "Sam" });
    expect(seeded.get("me")).toBe("Sam");
    expect(seeded.get("manual")).toBe("Sam");
    expect(seeded.get("remote")).toBeNull();
    const unseeded = new SpeakerStore({ userName: null });
    expect(unseeded.get("me")).toBeNull();
  });

  it("the me label is remembered in localStorage and never falls back to a lane name", () => {
    const local = memoryStorage();
    const a = new SpeakerStore({ storage: local });
    a.set("me", "Sam");
    const b = new SpeakerStore({ storage: local });
    expect(b.get("me")).toBe("Sam");
    const c = new SpeakerStore({ storage: local, userName: "Alex" });
    expect(c.get("me")).toBe("Alex");
    a.set("me", null);
    expect(new SpeakerStore({ storage: local }).get("me")).toBeNull();
  });
});
