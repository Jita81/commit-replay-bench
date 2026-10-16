// exmap/src/core/reduce.ts — design §5.3. Step-zero stub: signatures only; the core module implements the bodies.
import type { ExmapEvent, MapState } from "./types.js";

export function initialState(session_id: string): MapState {
  void session_id;
  throw new Error("not implemented: initialState");
}

/** Pure, total over ExmapEvent, never mutates its input, never hashes. */
export function reduce(state: MapState, event: ExmapEvent): MapState {
  void state;
  void event;
  throw new Error("not implemented: reduce");
}
