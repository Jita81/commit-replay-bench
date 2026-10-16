// exmap/src/server/ledger.ts — JsonlLedger: readAll(), appendBatch() (design §9). crb's ledger discipline in Node: one
// canonical-JSON line per event, append-only, one write + one fsync per batch, truncation back to the pre-write length on
// any failure, and a parse error (never a silent repair) for a line that is not a complete event.
// `fs` is used through its default export so tests can spy on writeSync / fsyncSync / ftruncateSync.
import fs from "node:fs";
import { canonicalJson } from "../core/index.js";
import type { ExmapEvent } from "../core/types.js";

export interface LedgerReadError {
  code: "LEDGER_PARSE_ERROR";
  row: number; // 1-based line number in events.jsonl
  detail: string;
}

/** Thrown by appendBatch; the file has been truncated back to `truncated_to` unless `truncate_failed`. */
export class LedgerWriteError extends Error {
  readonly code = "LEDGER_WRITE_FAILED" as const;
  readonly detail: string;
  readonly truncated_to: number;
  readonly truncate_failed: boolean;
  constructor(info: { detail: string; truncated_to: number; truncate_failed: boolean }) {
    super(`LEDGER_WRITE_FAILED: ${info.detail}`);
    this.name = "LedgerWriteError";
    this.detail = info.detail;
    this.truncated_to = info.truncated_to;
    this.truncate_failed = info.truncate_failed;
  }
}

/**
 * `rows[i]` is the 1-based file line of `events[i]` (blank lines are skipped but counted). On a parse error `events`/`rows`
 * hold the readable prefix before the bad row, so a summary can be computed from it.
 */
export type LedgerReadResult =
  | { ok: true; events: ExmapEvent[]; rows: number[] }
  | { ok: false; error: LedgerReadError; events: ExmapEvent[]; rows: number[] };

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export class JsonlLedger {
  readonly path: string;
  constructor(path: string) {
    this.path = path;
  }

  /** Every event in file order. A missing file reads as empty (create() always writes one). */
  readAll(): LedgerReadResult {
    let text: string;
    try {
      text = fs.readFileSync(this.path, "utf8");
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code === "ENOENT") return { ok: true, events: [], rows: [] };
      throw e;
    }
    const events: ExmapEvent[] = [];
    const rows: number[] = [];
    const lines = text.split("\n");
    const terminated = text.endsWith("\n") || text === "";
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]!;
      const row = i + 1;
      const isLast = i === lines.length - 1;
      if (isLast && terminated) break; // the empty string after the final newline
      if (line.trim() === "") continue;
      const fail = (detail: string): LedgerReadResult => ({ ok: false, error: { code: "LEDGER_PARSE_ERROR", row, detail }, events, rows });
      if (isLast && !terminated) {
        return fail(`row ${row} is not terminated by a newline (an interrupted write?); inspect events.jsonl and, as your own act, truncate it`);
      }
      let value: unknown;
      try {
        value = JSON.parse(line);
      } catch (e) {
        return fail(`row ${row} is not valid JSON: ${messageOf(e)}`);
      }
      if (value === null || typeof value !== "object" || Array.isArray(value)) return fail(`row ${row} is not a JSON object`);
      const rec = value as Record<string, unknown>;
      if (typeof rec["hash"] !== "string" || typeof rec["seq"] !== "number") return fail(`row ${row} lacks hash/seq`);
      events.push(value as ExmapEvent);
      rows.push(row);
    }
    return { ok: true, events, rows };
  }

  /** One write + one fsync per batch; on any failure truncates back to the pre-write length and throws LedgerWriteError. */
  appendBatch(events: readonly ExmapEvent[]): void {
    if (events.length === 0) return;
    const data = Buffer.from(events.map((e) => canonicalJson(e) + "\n").join(""), "utf8");
    let fd: number;
    try {
      fd = fs.openSync(this.path, "a");
    } catch (e) {
      throw new LedgerWriteError({ detail: `cannot open ${this.path}: ${messageOf(e)}`, truncated_to: -1, truncate_failed: false });
    }
    let pre = 0;
    try {
      pre = fs.fstatSync(fd).size;
      let offset = 0;
      while (offset < data.length) {
        const n = fs.writeSync(fd, data, offset, data.length - offset);
        if (!Number.isInteger(n) || n <= 0) throw new Error(`short write: ${offset} of ${data.length} bytes written`);
        offset += n;
      }
      fs.fsyncSync(fd);
    } catch (e) {
      let truncateFailed = false;
      try {
        fs.ftruncateSync(fd, pre);
        fs.fsyncSync(fd);
      } catch {
        truncateFailed = true;
      }
      throw new LedgerWriteError({
        detail: `append of ${events.length} event(s) to ${this.path} failed: ${messageOf(e)}${truncateFailed ? "; truncating back also failed" : `; truncated back to ${pre} bytes`}`,
        truncated_to: pre,
        truncate_failed: truncateFailed,
      });
    } finally {
      try {
        fs.closeSync(fd);
      } catch {
        /* the write outcome is already decided */
      }
    }
  }
}
