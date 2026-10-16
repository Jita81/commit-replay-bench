// exmap/src/core/replay.ts — design §5.3. Step-zero stub: signature only; the core module implements the body.
import type { ExmapEvent, ReplayResult, Sha256Fn } from "./types.js";

/** verifyChain -> initialState -> fold reduce, checking every revision hash. */
export function replay(events: readonly ExmapEvent[], sha256: Sha256Fn): ReplayResult {
  void events;
  void sha256;
  throw new Error("not implemented: replay");
}
