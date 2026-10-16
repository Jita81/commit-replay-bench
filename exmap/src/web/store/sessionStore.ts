// exmap/src/web/store/sessionStore.ts — SessionStore: the WebSocket pump plus core.reduce (design §10.2). The browser
// reduces exactly what the server appended and verifies every pushed event before reducing it: a duplicate is ignored,
// a gap resyncs, a broken prev_hash / wrong hash / foreign session is terminal (the state stays, read-only).
import { eventHash, initialState, reduce } from "../../core/index.js";
import type { ChainError, EventBody, ExmapEvent, MapState, Sha256Fn, Sha256Hex, StreamMessage } from "../../core/types.js";

export type Connection = "connecting" | "live" | "reconnecting" | "closed";

export interface StoreStatus {
  connection: Connection;
  head: { seq: number; hash: Sha256Hex | "" };
  chainError: ChainError | null;
  /** A terminal close named by the server (SESSION_NOT_FOUND / LEDGER_BROKEN / FORBIDDEN_ORIGIN) with its detail. */
  closeReason: { reason: string; detail: string; code: number | null } | null;
  /** A reducer failure (the event was well-formed and chained but core refused to reduce it); terminal like a chain error. */
  reduceError: { seq: number; message: string } | null;
  attempt: number;
  nextRetryMs: number | null;
}

export interface WebSocketLike {
  readyState: number;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}
export type WebSocketCtor = new (url: string) => WebSocketLike;

export interface Timers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface SessionStoreOptions {
  sessionId: string;
  wsUrl: (after: number) => string;
  sha256: Sha256Fn;
  /** Accepted for parity with §10.2; mutations go through the components' SessionApi, never through the store. */
  api?: unknown;
  WebSocketCtor?: WebSocketCtor;
  timers?: Timers;
}

export const BACKOFF_MS: readonly number[] = [500, 1000, 2000, 4000, 8000];

const TERMINAL_CLOSE: Record<number, string> = { 4003: "FORBIDDEN_ORIGIN", 4004: "SESSION_NOT_FOUND", 4009: "LEDGER_BROKEN" };

export class SessionStore {
  readonly sessionId: string;
  #state: MapState;
  #status: StoreStatus;
  #socket: WebSocketLike | null = null;
  #disposed = false;
  #retry: unknown = null;
  #pendingError: { reason: string; detail: string } | null = null;
  readonly #eventSeq = new Map<string, number>();
  readonly #subs = new Set<() => void>();
  readonly #wsUrl: (after: number) => string;
  readonly #sha256: Sha256Fn;
  readonly #Ctor: WebSocketCtor;
  readonly #timers: Timers;

  constructor(opts: SessionStoreOptions) {
    this.sessionId = opts.sessionId;
    this.#wsUrl = opts.wsUrl;
    this.#sha256 = opts.sha256;
    this.#Ctor = opts.WebSocketCtor ?? (globalThis.WebSocket as unknown as WebSocketCtor);
    this.#timers = opts.timers ?? {
      setTimeout: (fn, ms) => setTimeout(fn, ms),
      clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    };
    this.#state = initialState(opts.sessionId);
    this.#status = {
      connection: "connecting",
      head: { seq: 0, hash: "" },
      chainError: null,
      closeReason: null,
      reduceError: null,
      attempt: 0,
      nextRetryMs: null,
    };
  }

  getState = (): MapState => this.#state;
  getStatus = (): StoreStatus => this.#status;
  eventSeq = (eventId: string): number | null => this.#eventSeq.get(eventId) ?? null;

  subscribe = (fn: () => void): (() => void) => {
    this.#subs.add(fn);
    return () => {
      this.#subs.delete(fn);
    };
  };

  /** True once a chain error, reducer error or terminal close stopped the pump; the state is then read-only. */
  get terminal(): boolean {
    return this.#status.chainError !== null || this.#status.reduceError !== null || this.#status.closeReason !== null;
  }

  /** Opens the stream (`after = head.seq`). Also after dispose(): React may unmount and remount the same store. */
  connect(): void {
    if (this.#socket || this.terminal) return;
    if (this.#disposed) {
      this.#disposed = false;
      this.#setStatus({ connection: "connecting", nextRetryMs: null });
    }
    this.#open();
  }

  /** Reopens with `after = head.seq` at once (a gap, or a caller that knows the socket is stale). */
  resync(): void {
    if (this.#disposed || this.terminal) return;
    this.#closeSocket();
    this.#open();
  }

  dispose(): void {
    this.#disposed = true;
    if (this.#retry !== null) {
      this.#timers.clearTimeout(this.#retry);
      this.#retry = null;
    }
    this.#closeSocket();
    this.#setStatus({ connection: "closed", nextRetryMs: null });
  }

  #closeSocket(): void {
    const s = this.#socket;
    if (!s) return;
    this.#socket = null;
    s.onopen = s.onmessage = s.onclose = s.onerror = null;
    try {
      s.close(1000, "resync");
    } catch {
      /* already closed */
    }
  }

  #open(): void {
    const socket = new this.#Ctor(this.#wsUrl(this.#state.head.seq));
    this.#socket = socket;
    this.#pendingError = null;
    socket.onopen = () => {
      /* the hello frame confirms liveness */
    };
    socket.onmessage = (ev) => this.#onMessage(ev.data);
    socket.onclose = (ev) => {
      if (this.#socket !== socket) return;
      this.#socket = null;
      this.#onClose(ev.code ?? null, ev.reason ?? "");
    };
    socket.onerror = () => {
      /* onclose follows */
    };
  }

  #onMessage(data: unknown): void {
    if (this.terminal) return;
    let frame: StreamMessage;
    try {
      frame = JSON.parse(typeof data === "string" ? data : String(data)) as StreamMessage;
    } catch {
      return;
    }
    if (!frame || typeof frame !== "object" || typeof frame.type !== "string") return;
    switch (frame.type) {
      case "hello":
        this.#setStatus({ connection: "live", attempt: 0, nextRetryMs: null });
        return;
      case "error":
        this.#pendingError = { reason: frame.reason, detail: frame.detail };
        return;
      case "event":
        this.#onEvent(frame.event);
        return;
      default:
        return;
    }
  }

  #onEvent(event: ExmapEvent): void {
    const head = this.#state.head;
    if (typeof event?.seq !== "number") return;
    if (event.seq <= head.seq) return; // duplicate
    if (event.seq > head.seq + 1) {
      this.resync(); // gap
      return;
    }
    if (event.prev_hash !== head.hash) {
      this.#fail({ code: "PREV_HASH_MISMATCH", seq: event.seq, event_id: event.id, detail: `event ${event.id} at seq ${event.seq} cites prev_hash ${event.prev_hash.slice(0, 8)}, the head is ${head.hash.slice(0, 8) || "(genesis)"}` });
      return;
    }
    if (event.session_id !== this.sessionId) {
      this.#fail({ code: "SESSION_MISMATCH", seq: event.seq, event_id: event.id, detail: `event ${event.id} belongs to session ${event.session_id}, not ${this.sessionId}` });
      return;
    }
    const { hash, ...body } = event;
    const expected = eventHash(body as EventBody, this.#sha256);
    if (expected !== hash) {
      this.#fail({ code: "HASH_MISMATCH", seq: event.seq, event_id: event.id, detail: `event ${event.id} at seq ${event.seq} failed its hash check` });
      return;
    }
    try {
      this.#state = reduce(this.#state, event);
      this.#eventSeq.set(event.id, event.seq);
    } catch (e) {
      this.#setStatus({ reduceError: { seq: event.seq, message: e instanceof Error ? e.message : String(e) }, connection: "closed" });
      this.#closeSocket();
      return;
    }
    this.#setStatus({ head: { seq: this.#state.head.seq, hash: this.#state.head.hash } });
  }

  #fail(error: ChainError): void {
    this.#closeSocket();
    this.#setStatus({ chainError: error, connection: "closed", nextRetryMs: null });
  }

  #onClose(code: number | null, reason: string): void {
    if (this.#disposed || this.terminal) {
      this.#setStatus({ connection: "closed", nextRetryMs: null });
      return;
    }
    const terminal = code !== null ? TERMINAL_CLOSE[code] : undefined;
    if (terminal || this.#pendingError) {
      const named = this.#pendingError ?? { reason: terminal ?? "CLOSED", detail: reason };
      this.#setStatus({ connection: "closed", closeReason: { ...named, code }, nextRetryMs: null });
      return;
    }
    const attempt = this.#status.attempt + 1;
    const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length) - 1]!;
    this.#setStatus({ connection: "reconnecting", attempt, nextRetryMs: delay });
    this.#retry = this.#timers.setTimeout(() => {
      this.#retry = null;
      if (this.#disposed || this.terminal) return;
      this.#open();
    }, delay);
  }

  #setStatus(patch: Partial<StoreStatus>): void {
    this.#status = { ...this.#status, ...patch };
    this.#emit();
  }

  #emit(): void {
    for (const fn of [...this.#subs]) fn();
  }
}
