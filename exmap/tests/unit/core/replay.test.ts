// TEST-PLAN §1 case 19: replay equals folding reduce; reduce.ts imports neither chain.ts nor revision.ts.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { initialState, reduce } from "../../../src/core/reduce.js";
import { replay } from "../../../src/core/replay.js";
import { sha256 } from "../../../src/server/hash.js";
import { scenario } from "./fixtures.js";

describe("replay", () => {
  it("19. replay of the scenario equals folding reduce; reduce.ts imports neither chain.ts nor revision.ts", () => {
    const s = scenario();
    const result = replay(s.events, sha256);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    let folded = initialState(s.session_id);
    for (const event of s.events) folded = reduce(folded, event);
    expect(result.state).toEqual(folded);
    expect(result.state).toEqual(s.state); // and equals what apply() returned step by step
    expect(result.state.revisions.length).toBe(s.state.revisions.length);
    // snapshots are in-memory only but must agree too
    expect(result.state.revisions[result.state.revisions.length - 1]!.snapshot).toEqual(s.state.revisions[s.state.revisions.length - 1]!.snapshot);
    // every step's state equals the replay of its prefix
    for (const step of s.steps) {
      const prefix = replay(s.eventsUpTo(step.label), sha256);
      expect(prefix.ok).toBe(true);
      if (prefix.ok) expect(prefix.state).toEqual(step.state);
    }
    const source = readFileSync(fileURLToPath(new URL("../../../src/core/reduce.ts", import.meta.url)), "utf8");
    const imports = [...source.matchAll(/from\s+"([^"]+)"/g)].map((m) => m[1]);
    expect(imports).not.toContain("./chain.js");
    expect(imports).not.toContain("./revision.js");
    expect(imports.every((i) => i!.startsWith("./"))).toBe(true);
  });
});
