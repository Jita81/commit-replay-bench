// exmap/src/server/session.ts — Session: state, events, run(command), classify(utteranceId), subscribers, AbortController,
// broken flag (design §8.1, §9). Step-zero stub.
import type { ApplyResult, Command, ExmapEvent, MapState, UtteranceId } from "../core/types.js";

export class Session {
  readonly id: string;
  constructor(id: string) {
    this.id = id;
  }
  get state(): MapState {
    throw new Error("not implemented: Session.state");
  }
  get events(): readonly ExmapEvent[] {
    throw new Error("not implemented: Session.events");
  }
  run(command: Command): Promise<ApplyResult> {
    void command;
    throw new Error("not implemented: Session.run");
  }
  classify(utteranceId: UtteranceId): Promise<void> {
    void utteranceId;
    throw new Error("not implemented: Session.classify");
  }
  subscribe(fn: (events: readonly ExmapEvent[]) => void): () => void {
    void fn;
    throw new Error("not implemented: Session.subscribe");
  }
  close(): Promise<void> {
    throw new Error("not implemented: Session.close");
  }
}
