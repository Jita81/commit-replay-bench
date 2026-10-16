// exmap/src/server/errors.ts — HttpError, refusalStatus(), reply helpers (design §8.2). The error body is always ErrorBody;
// core refusal codes pass through unchanged (reason = ApplyResult.reason, detail verbatim).
import type { ApplyResult, ErrorBody, RefusalCode } from "../core/types.js";

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

/** Every core refusal code with its HTTP status (design §8.2). Typed over RefusalCode so a new code cannot be missed. */
const CORE_STATUS: { readonly [K in RefusalCode]: number } = {
  BAD_SHAPE: 422,
  DUPLICATE_ID: 409,
  EMPTY_TEXT: 422,
  INVALID_TIMING: 422,
  INVALID_ENUM: 422,
  INVALID_CONFIDENCE: 422,
  INVALID_DEFINITION: 422,
  INTENT_OPERATION_MISMATCH: 422,
  UTTERANCE_UNKNOWN: 404,
  CARD_NOT_FOUND: 404,
  CARD_NOT_LIVE: 409,
  KIND_MISMATCH: 422,
  LINK_KIND_MISMATCH: 422,
  STORY_ALREADY_EXISTS: 409,
  PATCH_EMPTY: 422,
  PATCH_FIELD_NOT_ALLOWED: 422,
  NO_CHANGE: 409,
  EMPTY_TARGET: 422,
  REPLACEMENT_INVALID: 409,
  NOTHING_TO_CONFIRM: 409,
  PROPOSAL_NOT_CONFIRMABLE: 409,
  PROPOSAL_NOT_FOUND: 404,
  PROPOSAL_NOT_REJECTABLE: 409,
  PROPOSAL_KIND_NOT_REJECTABLE: 409,
  REJECT_NOT_LATEST: 409,
  UNDO_NO_EARLIER_REVISION: 409,
  UNDO_TARGET_OUT_OF_RANGE: 409,
  UNDO_TARGET_IS_CURRENT: 409,
  CLARIFICATION_QUESTION_REQUIRED: 422,
  CLARIFICATION_SHAPE: 422,
  CLARIFICATION_NOT_FOUND: 404,
  CLARIFICATION_NOT_ANSWERABLE: 409,
  CLARIFICATION_NOT_AWAITING_PROPOSAL: 409,
  CLARIFICATION_NO_TEMPLATE: 409,
  CLARIFICATION_NO_OPERATION: 409,
  CLASSIFICATION_PROPOSAL_MISMATCH: 422,
  ACTOR_REQUIRED: 400,
  REASON_REQUIRED: 400,
  QUESTION_ALREADY_RESOLVED: 409,
  SIGNOFF_REVIEWER_REQUIRED: 400,
  SIGNOFF_CONFIRMATION_TEXT_MISMATCH: 400,
  SIGNOFF_STALE_REVISION: 409,
  SIGNOFF_ALREADY_ACTIVE: 409,
  SIGNOFF_DOD_FAILED: 422,
};

/** The server's own reasons (design §8.2). */
export type ServerReason =
  | "BAD_REQUEST" | "INVALID_SESSION_ID" | "CHECK_NOT_MARKABLE" | "CLASS_UNKNOWN" | "EXPORT_FILE_UNKNOWN"
  | "FORBIDDEN_HOST" | "FORBIDDEN_ORIGIN" | "SESSION_NOT_FOUND" | "NOT_FOUND"
  | "LEDGER_BROKEN" | "META_INVALID" | "NOT_HUMAN_VERIFIED"
  | "LEDGER_WRITE_FAILED" | "INTERNAL" | "ORT_RUNTIME_MISSING";

const SERVER_STATUS: { readonly [K in ServerReason]: number } = {
  BAD_REQUEST: 400,
  INVALID_SESSION_ID: 400,
  CHECK_NOT_MARKABLE: 400,
  CLASS_UNKNOWN: 400,
  EXPORT_FILE_UNKNOWN: 400,
  FORBIDDEN_HOST: 403,
  FORBIDDEN_ORIGIN: 403,
  SESSION_NOT_FOUND: 404,
  NOT_FOUND: 404,
  LEDGER_BROKEN: 409,
  META_INVALID: 409,
  NOT_HUMAN_VERIFIED: 422,
  LEDGER_WRITE_FAILED: 500,
  INTERNAL: 500,
  ORT_RUNTIME_MISSING: 500,
};

/** The HTTP status for a reason code (the table of design §8.2); an unknown reason is 500. */
export function refusalStatus(reason: string): number {
  if (Object.hasOwn(CORE_STATUS, reason)) return CORE_STATUS[reason as RefusalCode];
  if (Object.hasOwn(SERVER_STATUS, reason)) return SERVER_STATUS[reason as ServerReason];
  return 500;
}

export type ErrorExtras = Omit<ErrorBody, "ok" | "reason" | "detail"> & Record<string, unknown>;

export function errorBody(reason: string, detail: string, extras: ErrorExtras = {}): ErrorBody {
  return { ok: false, reason, detail, ...extras } as ErrorBody;
}

/** An HttpError whose status comes from refusalStatus(reason) unless `status` is given. */
export function httpError(reason: string, detail: string, extras: ErrorExtras = {}, status?: number): HttpError {
  return new HttpError(status ?? refusalStatus(reason), errorBody(reason, detail, extras));
}

/** A core refusal as an HttpError: reason and detail verbatim, `checks` carried for SIGNOFF_DOD_FAILED. */
export function refusalError(r: Extract<ApplyResult, { ok: false }>, status?: number): HttpError {
  return httpError(r.reason, r.detail, r.checks ? { checks: r.checks } : {}, status);
}

/** 400 BAD_REQUEST with zod-style issues (422 on the utterance route, design §8.4). */
export function badRequest(detail: string, issues?: unknown[], status = 400): HttpError {
  return httpError("BAD_REQUEST", detail, issues ? { issues } : {}, status);
}
