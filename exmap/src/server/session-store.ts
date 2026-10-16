// exmap/src/server/session-store.ts — SessionStore: create / list / open (cached) / summaryOf; broken-ledger reporting
// (design §8.1, §9). Step-zero stub: the constructor is callable (buildApp needs an instance); the methods throw.
import type { SessionSummary } from "../core/types.js";
import type { Session } from "./session.js";

export interface SessionStoreOptions {
  home: string;
}

export class SessionStore {
  readonly home: string;
  constructor(opts: SessionStoreOptions) {
    this.home = opts.home;
  }
  list(): SessionSummary[] {
    throw new Error("not implemented: SessionStore.list");
  }
  create(input: { title: string; story?: string; actor?: string }): Session {
    void input;
    throw new Error("not implemented: SessionStore.create");
  }
  open(id: string): Session {
    void id;
    throw new Error("not implemented: SessionStore.open");
  }
  summaryOf(id: string): SessionSummary {
    void id;
    throw new Error("not implemented: SessionStore.summaryOf");
  }
  closeAll(): Promise<void> {
    return Promise.resolve();
  }
}
