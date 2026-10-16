// exmap/src/web/audio/pipeline/sink.ts — the HTTP utterance sink (design §7.5). Outcomes are classified by the body's
// `reason`, never by status alone: 201 → ok; 409 DUPLICATE_ID → ok + duplicate (a retry after a timeout); every other
// 4xx except 408/429 → refused (never retried); 408, 429, 5xx, a non-JSON 2xx, a network error, an abort → transient.
import type { PostOutcome, UtteranceSink, UtteranceWire } from "../types.js";

export type FetchLike = (input: string, init: { method: string; headers: Record<string, string>; body: string; signal: AbortSignal }) => Promise<{
  status: number;
  ok: boolean;
  text(): Promise<string>;
}>;

export interface HttpSinkOptions {
  baseUrl: string;
  sessionId: string;
  fetch?: FetchLike;
  timeoutMs?: number;
}

export const DEFAULT_POST_TIMEOUT_MS = 15_000;

export class HttpUtteranceSink implements UtteranceSink {
  readonly baseUrl: string;
  readonly sessionId: string;
  readonly timeoutMs: number;
  readonly #fetch: FetchLike;

  constructor(opts: HttpSinkOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.sessionId = opts.sessionId;
    this.timeoutMs = opts.timeoutMs ?? DEFAULT_POST_TIMEOUT_MS;
    this.#fetch = opts.fetch ?? ((input, init) => fetch(input, init));
  }

  get url(): string {
    return `${this.baseUrl}/api/sessions/${encodeURIComponent(this.sessionId)}/utterances`;
  }

  async post(u: UtteranceWire): Promise<PostOutcome> {
    let res: Awaited<ReturnType<FetchLike>>;
    try {
      res = await this.#fetch(this.url, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify(u),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (e) {
      return { ok: false, kind: "transient", status: null, message: isAbort(e) ? "timeout" : messageOf(e) };
    }
    let text = "";
    try {
      text = await res.text();
    } catch (e) {
      return { ok: false, kind: "transient", status: res.status, message: messageOf(e) };
    }
    let body: Record<string, unknown> | null = null;
    try {
      body = text.length > 0 ? (JSON.parse(text) as Record<string, unknown>) : null;
    } catch {
      body = null;
    }
    return classifyResponse(res.status, body);
  }
}

export function classifyResponse(status: number, body: Record<string, unknown> | null): PostOutcome {
  const reason = typeof body?.["reason"] === "string" ? (body["reason"] as string) : null;
  const detail = typeof body?.["detail"] === "string" ? (body["detail"] as string) : "";
  const event = body?.["event"];
  const eventId = typeof event === "object" && event !== null && typeof (event as { id?: unknown }).id === "string" ? (event as { id: string }).id : null;

  if (status >= 200 && status < 300) {
    if (body && eventId) return { ok: true, eventId, duplicate: false };
    return { ok: false, kind: "transient", status, message: "the server answered 2xx without a JSON event body" };
  }
  if (status === 409 && reason === "DUPLICATE_ID") {
    return { ok: true, eventId: eventId ?? "", duplicate: true };
  }
  if (status === 408 || status === 429 || status >= 500) {
    return { ok: false, kind: "transient", status, message: reason ? `${reason}: ${detail}` : `HTTP ${status}` };
  }
  if (status >= 400) {
    return { ok: false, kind: "refused", status, reason: reason ?? `HTTP_${status}`, detail };
  }
  return { ok: false, kind: "transient", status, message: `unexpected HTTP ${status}` };
}

function isAbort(e: unknown): boolean {
  return typeof e === "object" && e !== null && ((e as { name?: unknown }).name === "AbortError" || (e as { name?: unknown }).name === "TimeoutError");
}

function messageOf(e: unknown): string {
  if (typeof e === "object" && e !== null && "message" in e) return String((e as { message: unknown }).message);
  return String(e);
}

/** A sink that keeps everything in memory (tests and the controller's own unit test). */
export class MemorySink implements UtteranceSink {
  readonly posted: UtteranceWire[] = [];
  #seq = 0;
  async post(u: UtteranceWire): Promise<PostOutcome> {
    this.posted.push(u);
    this.#seq++;
    return { ok: true, eventId: `evt_${this.#seq}`, duplicate: false };
  }
}
