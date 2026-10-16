// exmap/src/core/apply.ts — design §5.4. Step-zero stub: signature only; the core module implements the body.
import type { ApplyContext, ApplyResult, Command, MapState } from "./types.js";

export function apply(state: MapState, command: Command, ctx: ApplyContext): ApplyResult {
  void state;
  void command;
  void ctx;
  throw new Error("not implemented: apply");
}
