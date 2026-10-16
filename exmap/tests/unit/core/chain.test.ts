// TEST-PLAN §1 cases 4–10: the hash chain over the scenario ledger, every tamper, and the replay revision recheck.
import { describe, expect, it } from "vitest";
import { canonicalJson } from "../../../src/core/canonical.js";
import { chainEvent, eventHash, GENESIS_PREV_HASH, verifyChain } from "../../../src/core/chain.js";
import { replay } from "../../../src/core/replay.js";
import type { EventBody, ExmapEvent } from "../../../src/core/types.js";
import { sha256 } from "../../../src/server/hash.js";
import { scenario } from "./fixtures.js";

/** Recomputes hash and prev_hash from `from` onwards (what a forger who controls the file could do). */
function rechain(events: ExmapEvent[], from: number): ExmapEvent[] {
  const out = events.slice(0, from);
  for (let i = from; i < events.length; i++) {
    const { hash: _hash, prev_hash: _prev, seq: _seq, ...body } = events[i]!;
    out.push(chainEvent({ seq: out.length, hash: out[out.length - 1]?.hash ?? "" }, body as never, sha256));
  }
  return out;
}

const s = scenario();

describe("chain", () => {
  it("4. the genesis event has prev_hash \"\", seq 1, hash = sha256(canonicalJson(body sans hash)), batch_id === id", () => {
    const first = s.events[0]!;
    expect(first.prev_hash).toBe(GENESIS_PREV_HASH);
    expect(first.seq).toBe(1);
    expect(first.batch_id).toBe(first.id);
    const { hash, ...body } = first;
    expect(hash).toBe(sha256(canonicalJson(body)));
    expect(eventHash(body as EventBody, sha256)).toBe(hash);
    expect(eventHash({ ...body, hash: "ignored" } as never, sha256)).toBe(hash);
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it("5. verifyChain accepts the full scenario ledger: ok, count === events.length, head === last.hash", () => {
    // TEST-PLAN names a 60-event scenario; the §5.10 scenario as built runs to this many events (see INTEGRATION-NOTES).
    expect(s.events.length).toBeGreaterThan(60);
    const result = verifyChain(s.events, sha256);
    expect(result).toEqual({ ok: true, count: s.events.length, head: s.events[s.events.length - 1]!.hash });
    expect(verifyChain([], sha256)).toEqual({ ok: true, count: 0, head: "" });
    for (let i = 1; i < s.events.length; i++) expect(s.events[i]!.prev_hash).toBe(s.events[i - 1]!.hash);
  });

  it("6. verifyChain detects payload tampering: one card's text changed inside an event's effects -> HASH_MISMATCH at that seq", () => {
    const index = s.events.findIndex((e) => e.type === "proposal.applied");
    const target = s.events[index]! as Extract<ExmapEvent, { type: "proposal.applied" }>;
    const tampered: ExmapEvent = {
      ...target,
      effects: target.effects.map((e) => ({ ...e, after: { ...e.after, text: e.after.text + " (tampered)" } })),
    };
    const events = [...s.events.slice(0, index), tampered, ...s.events.slice(index + 1)];
    const result = verifyChain(events, sha256);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("HASH_MISMATCH");
      expect(result.error.seq).toBe(target.seq);
      expect(result.error.event_id).toBe(target.id);
    }
  });

  it("7. verifyChain detects a removed event: delete event 5 -> PREV_HASH_MISMATCH / SEQ_MISMATCH at the event after it; never repaired", () => {
    const events = s.events.filter((e) => e.seq !== 5);
    const result = verifyChain(events, sha256);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(["PREV_HASH_MISMATCH", "SEQ_MISMATCH"]).toContain(result.error.code);
      expect(result.error.seq).toBe(6);
      expect(result.error.event_id).toBe(s.events[5]!.id);
      expect(result.error.detail).toContain("position 5");
    }
    expect(events.length).toBe(s.events.length - 1); // the input is untouched
  });

  it("8. verifyChain detects reordering: swap events 3 and 4 -> failure at position 3", () => {
    const events = [...s.events];
    [events[2], events[3]] = [events[3]!, events[2]!];
    const result = verifyChain(events, sha256);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(["PREV_HASH_MISMATCH", "SEQ_MISMATCH"]).toContain(result.error.code);
      expect(result.error.event_id).toBe(s.events[3]!.id); // the event now sitting at position 3
      expect(result.error.detail).toContain("position 3");
    }
  });

  it("9. verifyChain detects a foreign session's event spliced in -> SESSION_MISMATCH", () => {
    const index = 10;
    const foreign = { ...s.events[index]!, session_id: "sess_other" };
    const events = rechain([...s.events.slice(0, index), foreign, ...s.events.slice(index + 1)], index);
    const result = verifyChain(events, sha256);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("SESSION_MISMATCH");
      expect(result.error.seq).toBe(index + 1);
    }
  });

  it("10. replay refuses a revision stamp the reducer does not reproduce (REVISION_MISMATCH), on the last and on an earlier revision", () => {
    const lastIndex = s.events.map((e) => "revision" in e).lastIndexOf(true);
    const last = s.events[lastIndex]! as Extract<ExmapEvent, { type: "proposal.applied" }>;
    const forged = rechain(
      [...s.events.slice(0, lastIndex), { ...last, revision: { ...last.revision, hash: "0".repeat(64) } }, ...s.events.slice(lastIndex + 1)],
      lastIndex,
    );
    expect(verifyChain(forged, sha256).ok).toBe(true);
    const result = replay(forged, sha256);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("REVISION_MISMATCH");
      if (result.error.code === "REVISION_MISMATCH") {
        expect(result.error.seq).toBe(last.seq);
        expect(result.error.expected).toBe("0".repeat(64));
        expect(result.error.actual).toBe(last.revision.hash);
      }
    }
    // variant: an earlier revision-creating event, every later event re-chained
    const earlyIndex = s.events.findIndex((e) => "revision" in e);
    const early = s.events[earlyIndex]! as Extract<ExmapEvent, { type: "proposal.applied" }>;
    const forgedEarly = rechain(
      [...s.events.slice(0, earlyIndex), { ...early, revision: { ...early.revision, hash: "1".repeat(64) } }, ...s.events.slice(earlyIndex + 1)],
      earlyIndex,
    );
    expect(verifyChain(forgedEarly, sha256).ok).toBe(true);
    const resultEarly = replay(forgedEarly, sha256);
    expect(resultEarly.ok).toBe(false);
    if (!resultEarly.ok && resultEarly.error.code === "REVISION_MISMATCH") expect(resultEarly.error.seq).toBe(early.seq);
    // the untouched ledger replays
    expect(replay(s.events, sha256).ok).toBe(true);
    expect(replay([], sha256)).toEqual({ ok: false, error: { code: "EMPTY_LEDGER" } });
  });
});
