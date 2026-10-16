// tests/unit/audio/hallucination.test.ts — TEST-PLAN §3 cases 19–24.
import { describe, expect, it } from "vitest";
import { isLikelyHallucination, normalizeTranscript } from "../../../src/web/audio/providers/hallucination.js";

const at = (durationMs: number, peakRmsDb: number) => ({ durationMs, peakRmsDb });

describe("hallucination gate", () => {
  it("19. \"Thank you.\" is dropped only when short AND quiet", () => {
    expect(isLikelyHallucination("Thank you.", at(700, -50))).toBe(true);
    expect(isLikelyHallucination("Thank you.", at(700, -20))).toBe(false);
    expect(isLikelyHallucination("Thank you.", at(1500, -50))).toBe(false);
  });

  it("20. single words are never dropped", () => {
    expect(isLikelyHallucination("Okay.", at(500, -20))).toBe(false);
    expect(isLikelyHallucination("Okay.", at(500, -50))).toBe(false);
    for (const w of ["Yes.", "Bye.", "you"]) {
      expect(isLikelyHallucination(w, at(300, -70))).toBe(false);
      expect(isLikelyHallucination(w, at(5000, -5))).toBe(false);
    }
  });

  it("21. empty, punctuation-only and bracket-only transcripts are dropped regardless of energy", () => {
    for (const t of ["", "...", ".", "[BLANK_AUDIO]", "(music)", "♪"]) {
      expect(isLikelyHallucination(t, at(5000, -5))).toBe(true);
      expect(isLikelyHallucination(t, at(100, -80))).toBe(true);
    }
  });

  it("22. a single token repeated ≥ 5 times with nothing else is dropped; a varied sentence is kept unchanged", () => {
    expect(isLikelyHallucination("you you you you you you", at(3000, -10))).toBe(true);
    const text = "go go go go go go now";
    expect(isLikelyHallucination(text, at(3000, -10))).toBe(false);
    expect(text).toBe("go go go go go go now");
  });

  it("23. a real sentence at any energy is kept, text unchanged", () => {
    const text = "A patient should be able to cancel online, but not within two hours.";
    expect(isLikelyHallucination(text, at(200, -80))).toBe(false);
    expect(isLikelyHallucination(text, at(14000, -3))).toBe(false);
    expect(text).toBe("A patient should be able to cancel online, but not within two hours.");
  });

  it("24. normalisation matches the table across punctuation, spacing and case", () => {
    for (const t of ["Thank you!!", " thank  you ", "THANK YOU."]) {
      expect(normalizeTranscript(t)).toBe("thank you");
      expect(isLikelyHallucination(t, at(500, -50))).toBe(true);
    }
  });
});
