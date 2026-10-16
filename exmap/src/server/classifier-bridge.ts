// exmap/src/server/classifier-bridge.ts — the seam between ClassifierProposal and core's Proposal (design §8.7).
// A pure, tested mapping in one file. Step-zero stubs.
import type {
  ApplyContext, ClassifierInput, ClassifierProposal, Command, EventId, Intent, MapState, OperationKind, Utterance,
} from "../core/types.js";

export function buildClassifierInput(s: { state: MapState; seqOfEvent: (id: EventId) => number }, utterance: Utterance): ClassifierInput {
  void s;
  void utterance;
  throw new Error("not implemented: buildClassifierInput");
}

export function toCoreCommands(
  p: ClassifierProposal,
  state: MapState,
  utterance: Utterance,
  ctx: { nextId: ApplyContext["nextId"]; actorForVoice: (u: Utterance) => string },
): Command[] {
  void p;
  void state;
  void utterance;
  void ctx;
  throw new Error("not implemented: toCoreCommands");
}

export function intentOf(kind: OperationKind): Intent {
  void kind;
  throw new Error("not implemented: intentOf");
}
