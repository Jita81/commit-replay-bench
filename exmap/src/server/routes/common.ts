// exmap/src/server/routes/common.ts — helpers the route files share: the session behind `:id`, the body as an object, the
// actor rule of design §8.2 (1–80 characters after trim, else 400 ACTOR_REQUIRED), `?wait=1`.
import type { FastifyInstance, FastifyRequest } from "fastify";
import type { ApplyResult, Command } from "../../core/types.js";
import { badRequest, httpError, refusalError } from "../errors.js";
import type { Session } from "../session.js";

export const ACTOR_MAX = 80;

export type Body = Record<string, unknown>;

/** The session named by the `:id` route parameter (400 INVALID_SESSION_ID / 404 / 409 from the store). */
export function sessionOf(app: FastifyInstance, req: FastifyRequest): Session {
  const id = (req.params as { id?: string }).id ?? "";
  return app.exmap.store.open(id);
}

/** The JSON body as a plain object, else 400 BAD_REQUEST. */
export function bodyOf(req: FastifyRequest): Body {
  const b = req.body;
  if (b === null || typeof b !== "object" || Array.isArray(b)) throw badRequest("the request body must be a JSON object");
  return b as Body;
}

/** `actor`: a string of 1–80 characters after trim, else 400 ACTOR_REQUIRED. */
export function actorOf(body: Body): string {
  const raw = body["actor"];
  const actor = typeof raw === "string" ? raw.trim() : "";
  if (actor === "" || actor.length > ACTOR_MAX) {
    throw httpError("ACTOR_REQUIRED", `every act must name who performs it: actor must be 1–${ACTOR_MAX} characters`);
  }
  return actor;
}

/** An optional string field: absent → `fallback`; present but not a string → 400 BAD_REQUEST. */
export function stringField(body: Body, key: string, fallback = ""): string {
  const v = body[key];
  if (v === undefined || v === null) return fallback;
  if (typeof v !== "string") throw badRequest(`${key} must be a string`);
  return v;
}

export function wantWait(req: FastifyRequest): boolean {
  const w = (req.query as { wait?: unknown } | undefined)?.wait;
  return w === "1" || w === "true";
}

/** apply under the write mutex; a refusal becomes its HttpError. */
export async function runOrThrow(session: Session, build: () => Command): Promise<Extract<ApplyResult, { ok: true }>> {
  return session.exclusive(() => {
    const r = session.applyLocked(build());
    if (!r.ok) throw refusalError(r);
    return r;
  });
}
