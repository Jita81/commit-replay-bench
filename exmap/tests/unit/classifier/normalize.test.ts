// exmap/tests/unit/classifier/normalize.test.ts — TEST-PLAN §2 normalize rows 1–3.
import { describe, expect, it } from "vitest";
import { contentTokens, normalizeText, originalSpan, splitSentences, stripDiscourse, tokenMatch } from "../../../src/classifier/normalize.js";

function sentences(raw: string): string[] {
  return splitSentences(normalizeText(raw)).map((s) => s.text);
}

function stripped(raw: string): Array<string | null> {
  return splitSentences(normalizeText(raw)).map((s) => stripDiscourse(s)?.text ?? null);
}

describe("normalize", () => {
  it("1. number words, contractions, hyphens keep their original spans; sentences split on . ? ; :", () => {
    const n = normalizeText("twenty-four hours");
    expect(n.text).toBe("24 hours");
    expect(originalSpan(n, 0, 2)).toBe("twenty-four");
    expect(originalSpan(n, 0, 8)).toBe("twenty-four hours");
    expect(normalizeText("We don't need that").text).toBe("we do not need that");
    expect(normalizeText("that's right").text).toBe("that is right");
    const w = normalizeText("a booked slot, not a walk-in.");
    expect(w.text).toBe("a booked slot, not a walk in");
    const idx = w.text.indexOf("walk in");
    expect(originalSpan(w, idx, idx + "walk in".length)).toBe("walk-in");
    expect(sentences("Alpha. Beta? Gamma; delta: epsilon")).toEqual(["alpha", "beta?", "gamma", "delta", "epsilon"]);
    expect(normalizeText("One more example: a GP appointment at 10am.").text).toBe("one more example | a gp appointment at 10am");
    expect(normalizeText("Undo the last two changes.").text).toBe("undo the last 2 changes");
    expect(normalizeText("one more example").text).toBe("one more example");
    expect(normalizeText("half an hour, an hour, a couple of days").text).toBe("30 minutes, 1 hour, 2 days");
    expect(normalizeText("I'm not sure, let's leave that open.").text).toBe("i am not sure, let us leave that open");
    expect(normalizeText("the 24-hour rule").text).toBe("the 24 hour rule");
  });

  it("2. stripDiscourse removes leading markers (at most three), drops marker-only sentences, keeps a bare Okay / Right / Yes", () => {
    expect(stripped("Right, so is the two-hour window the same for dentists?")).toEqual(["is the 2 hour window the same for dentists?"]);
    expect(stripped("Right.")).toEqual(["right"]);
    expect(stripped("Yes, that's exactly right.")).toEqual(["yes, that is exactly right"]);
    expect(stripped("Got it. So for example, if a GP appointment is at 10am then it is refused.")).toEqual([null, "for example, if a gp appointment is at 10am then it is refused"]);
    expect(stripped("Okay, right, so, well, we need an error case.")).toEqual(["well, we need an error case"]);
    expect(stripped("Okay.")).toEqual(["okay"]);
    expect(stripped("And for a nurse appointment, say it is at 10am.")).toEqual(["for a nurse appointment, say it is at 10am"]);
    const s = splitSentences(normalizeText("And for a nurse appointment, say it is at 10am."))[0]!;
    expect(stripDiscourse(s)?.lead).toBe("and");
    // the raw span of the stripped sentence starts after the marker
    const r = stripDiscourse(splitSentences(normalizeText("Right, so is the two-hour window the same for dentists?"))[0]!)!;
    expect(r.norm.raw.slice(r.rawStart, r.rawEnd)).toBe("is the two-hour window the same for dentists?");
  });

  it("3. contentTokens / tokenMatch: cancellation ~ cancel, GPs ~ gp, appointments ~ appointment", () => {
    expect(tokenMatch("cancellation", "cancel")).toBe(true);
    expect(tokenMatch("GPs", "gp")).toBe(true);
    expect(tokenMatch("appointments", "appointment")).toBe(true);
    expect(tokenMatch("nurses", "nurse")).toBe(true);
    expect(tokenMatch("nurse", "patient")).toBe(false);
    expect(tokenMatch("gp", "gap")).toBe(false);
    expect(contentTokens("the patient's appointment is at 10am, not a walk-in")).toEqual(["patient", "appointment", "10am", "walk"]);
    expect(contentTokens("Delete the example about nurses")).toEqual(["delete", "example", "nurse"]);
  });
});
