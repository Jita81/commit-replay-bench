// exmap/src/web/api/client.ts — ApiClient (every route of design §8) and ApiError. Step zero: ApiError is real;
// ApiClient carries only its base URL; the web module adds the methods.
import type { DodReport, ExportRefusal } from "../../core/types.js";

export class ApiError extends Error {
  readonly status: number;
  readonly reason: string;
  readonly detail: string;
  readonly checks?: DodReport;
  readonly signoff?: ExportRefusal["signoff"];
  constructor(status: number, body: { reason: string; detail: string; checks?: DodReport; signoff?: ExportRefusal["signoff"] }) {
    super(`${status} ${body.reason}: ${body.detail}`);
    this.name = "ApiError";
    this.status = status;
    this.reason = body.reason;
    this.detail = body.detail;
    if (body.checks) this.checks = body.checks;
    if (body.signoff) this.signoff = body.signoff;
  }
}

export class ApiClient {
  readonly baseUrl: string;
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }
}
