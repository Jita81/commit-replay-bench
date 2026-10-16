// exmap/src/core/dod.ts — design §5.6. Constants are real; the functions are step-zero stubs.
import type { DodOptions, DodReport, MapState } from "./types.js";

export const SIGNOFF_CONFIRMATION_TEXT = "I have reviewed the complete requirement and confirm it represents the agreed intent.";
export const DOD_OPTIONS: DodOptions = { requireHumanConfirm: false }; // voice confirmations count, labelled as such

export function dodReport(state: MapState, opts: DodOptions = DOD_OPTIONS): DodReport {
  void state;
  void opts;
  throw new Error("not implemented: dodReport");
}

export function isHumanVerified(state: MapState): boolean {
  void state;
  throw new Error("not implemented: isHumanVerified");
}
