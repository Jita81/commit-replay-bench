// exmap/src/server/routes/sessions.ts — the session routes of design §8.3: list, create, detail, events page, state.
import type { FastifyInstance } from "fastify";
import { dodReport, select } from "../../core/index.js";
import type { MapState } from "../../core/types.js";
import { badRequest } from "../errors.js";
import { summarize } from "../session-store.js";
import { actorOf, bodyOf, sessionOf, stringField } from "./common.js";

export const TITLE_MAX = 120;
export const EVENTS_LIMIT_DEFAULT = 2000;
export const EVENTS_LIMIT_CAP = 5000;

function intParam(raw: unknown, name: string, fallback: number, min: number): number {
  if (raw === undefined || raw === "") return fallback;
  const n = typeof raw === "string" && /^\d+$/.test(raw) ? Number(raw) : NaN;
  if (!Number.isSafeInteger(n) || n < min) throw badRequest(`${name} must be an integer ≥ ${min}`);
  return n;
}

/** MapState with every revision's snapshot left out (tooling; the UI reduces events itself). */
export function stateWithoutSnapshots(state: MapState): Omit<MapState, "revisions"> & { revisions: ReturnType<typeof select.revisions> } {
  return { ...state, revisions: select.revisions(state) };
}

export async function sessionRoutes(app: FastifyInstance): Promise<void> {
  const store = app.exmap.store;

  app.get("/api/sessions", async () => ({ sessions: store.list() }));

  app.post("/api/sessions", async (req, reply) => {
    const body = bodyOf(req);
    const title = typeof body["title"] === "string" ? body["title"].trim() : "";
    if (title.length < 1 || title.length > TITLE_MAX) throw badRequest(`title must be 1–${TITLE_MAX} characters`);
    const story = body["story"] === undefined || body["story"] === null ? undefined : stringField(body, "story");
    let actor: string | undefined;
    if (story !== undefined) actor = actorOf(body);
    else if (body["actor"] !== undefined && body["actor"] !== null) actor = actorOf(body);
    const session = store.create({ title, ...(story !== undefined ? { story } : {}), ...(actor !== undefined ? { actor } : {}) });
    return reply.code(201).send({ session: summarize(session.meta, session.state, null) });
  });

  app.get("/api/sessions/:id", async (req) => {
    const session = sessionOf(app, req);
    const state = session.state;
    return {
      session: summarize(session.meta, state, session.broken),
      dod: dodReport(state),
      signoff: select.lastSignoff(state),
      export_options: select.exportOptions(state),
    };
  });

  app.get("/api/sessions/:id/events", async (req) => {
    const session = sessionOf(app, req);
    const q = (req.query ?? {}) as { after?: unknown; limit?: unknown };
    const after = intParam(q.after, "after", 0, 0);
    const limit = Math.min(intParam(q.limit, "limit", EVENTS_LIMIT_DEFAULT, 1), EVENTS_LIMIT_CAP);
    const all = session.events;
    const events = all.filter((e) => e.seq > after);
    const page = events.slice(0, limit);
    return { events: page, head: { seq: session.state.head.seq, hash: session.state.head.hash }, has_more: events.length > page.length };
  });

  app.get("/api/sessions/:id/state", async (req) => ({ state: stateWithoutSnapshots(sessionOf(app, req).state) }));
}
