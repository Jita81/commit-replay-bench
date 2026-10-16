// exmap/src/server/routes/stream.ts — WebSocket GET /api/sessions/:id/stream?after=<seq> (design §8.8).
// On connect: Origin and session checked (an `error` frame, then close 4003 / 4004 / 4009); `hello` first; then, in one
// synchronous tick, subscribe and send every event with after < seq ≤ the head at that tick — run() notifies subscribers
// synchronously in the tick of the append, so nothing is missed or sent twice between catch-up and live. Only ledger
// events, `hello` and `error` frames are ever sent. Keep-alive: ping every 25 s, a socket missing two is terminated.
// Backpressure: bufferedAmount > 8 MiB → close 1013 (the client resyncs).
import type { FastifyInstance } from "fastify";
import type { WebSocket } from "ws";
import type { BrokenInfo, StreamMessage } from "../../core/types.js";
import { HttpError } from "../errors.js";
import type { Session } from "../session.js";

export const PING_INTERVAL_MS = 25_000;
export const MAX_BUFFERED = 8 * 1024 * 1024;

export const CLOSE = { FORBIDDEN_ORIGIN: 4003, SESSION_NOT_FOUND: 4004, LEDGER_BROKEN: 4009, TRY_AGAIN_LATER: 1013, GOING_AWAY: 1001 } as const;

function send(socket: WebSocket, msg: StreamMessage): void {
  if (socket.readyState === socket.OPEN) socket.send(JSON.stringify(msg));
}

function fail(socket: WebSocket, code: number, reason: "SESSION_NOT_FOUND" | "LEDGER_BROKEN" | "FORBIDDEN_ORIGIN", detail: string, row?: number): void {
  send(socket, { type: "error", reason, detail, ...(row !== undefined ? { row } : {}) });
  socket.close(code, reason);
}

function parseAfter(raw: unknown): number {
  if (typeof raw !== "string" || !/^\d+$/.test(raw)) return 0;
  const n = Number(raw);
  return Number.isSafeInteger(n) ? n : 0;
}

export async function streamRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/sessions/:id/stream", { websocket: true }, (socket: WebSocket, req) => {
    const origin = req.headers.origin ?? "";
    if (!app.exmap.allowedOrigins().includes(origin)) {
      fail(socket, CLOSE.FORBIDDEN_ORIGIN, "FORBIDDEN_ORIGIN", `WebSocket connections must come from this server's own page (Origin ${JSON.stringify(origin)} is not accepted)`);
      return;
    }
    const id = (req.params as { id: string }).id;
    let session: Session;
    try {
      session = app.exmap.store.open(id);
    } catch (e) {
      if (e instanceof HttpError && (e.body.reason === "LEDGER_BROKEN" || e.body.reason === "META_INVALID")) {
        const row = (e.body as { row?: unknown }).row;
        fail(socket, CLOSE.LEDGER_BROKEN, "LEDGER_BROKEN", e.body.detail, typeof row === "number" ? row : undefined);
      } else {
        fail(socket, CLOSE.SESSION_NOT_FOUND, "SESSION_NOT_FOUND", e instanceof HttpError ? e.body.detail : `session ${id} cannot be opened`);
      }
      return;
    }
    if (session.broken) {
      fail(socket, CLOSE.LEDGER_BROKEN, "LEDGER_BROKEN", session.broken.detail, session.broken.row);
      return;
    }
    const after = parseAfter((req.query as { after?: unknown } | undefined)?.after);

    let closed = false;
    const overflow = (): boolean => {
      if (socket.bufferedAmount > MAX_BUFFERED) {
        closed = true;
        socket.close(CLOSE.TRY_AGAIN_LATER, "client too slow; resync");
        return true;
      }
      return false;
    };

    // one synchronous tick: hello, subscribe, catch up to the head as of now
    const upto = session.events.length;
    send(socket, { type: "hello", session_id: session.id, head: { seq: session.state.head.seq, hash: session.state.head.hash }, after });
    const unsubscribe = session.subscribe({
      onEvents(events) {
        if (closed) return;
        for (const event of events) {
          send(socket, { type: "event", event });
          if (overflow()) return;
        }
      },
      onBroken(info: BrokenInfo) {
        if (closed) return;
        closed = true;
        fail(socket, CLOSE.LEDGER_BROKEN, "LEDGER_BROKEN", info.detail, info.row);
      },
      onClose() {
        if (closed) return;
        closed = true;
        socket.close(CLOSE.GOING_AWAY, "server shutting down");
      },
    });
    for (const event of session.events) {
      if (event.seq > after && event.seq <= upto) {
        send(socket, { type: "event", event });
        if (overflow()) break;
      }
    }

    let missed = 0;
    const ping = setInterval(() => {
      if (missed >= 2) {
        socket.terminate();
        return;
      }
      missed++;
      try {
        socket.ping();
      } catch {
        /* closing */
      }
    }, PING_INTERVAL_MS);
    ping.unref?.();
    socket.on("pong", () => {
      missed = 0;
    });
    socket.on("close", () => {
      closed = true;
      clearInterval(ping);
      unsubscribe();
    });
  });
}
