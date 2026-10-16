// exmap/src/server/errors.ts — HttpError, refusalStatus(), reply helpers (design §8.2). HttpError is real; the rest are stubs.
import type { ErrorBody } from "../core/types.js";

export class HttpError extends Error {
  readonly status: number;
  readonly body: ErrorBody;
  constructor(status: number, body: ErrorBody) {
    super(`${status} ${body.reason}: ${body.detail}`);
    this.name = "HttpError";
    this.status = status;
    this.body = body;
  }
}

/** The HTTP status for a reason code (the table of design §8.2); core refusal codes pass through unchanged. */
export function refusalStatus(reason: string): number {
  void reason;
  throw new Error("not implemented: refusalStatus");
}
