// exmap/src/server/ledger.ts — JsonlLedger: readAll(), appendBatch() (design §9). Step-zero stub.
import type { ExmapEvent } from "../core/types.js";

export interface LedgerReadError {
  code: "LEDGER_PARSE_ERROR";
  row: number;
  detail: string;
}

export interface LedgerWriteError {
  code: "LEDGER_WRITE_FAILED";
  detail: string;
  truncated_to: number;
  truncate_failed: boolean;
}

export type LedgerReadResult = { ok: true; events: ExmapEvent[] } | { ok: false; error: LedgerReadError };

export class JsonlLedger {
  readonly path: string;
  constructor(path: string) {
    this.path = path;
  }
  readAll(): LedgerReadResult {
    throw new Error("not implemented: JsonlLedger.readAll");
  }
  /** One writeSync + one fsyncSync per batch; truncates back on failure and throws LedgerWriteError. */
  appendBatch(events: readonly ExmapEvent[]): void {
    void events;
    throw new Error("not implemented: JsonlLedger.appendBatch");
  }
}
