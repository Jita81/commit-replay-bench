// exmap/src/server/routes/utterances.ts — POST /api/sessions/:id/utterances[?wait=1] (design §8.4).
// Recorded first (under the write mutex, with the classification enqueued before the mutex is released, so two posts are
// classified in recorded order), answered at once with 201, classified second; ?wait=1 waits for the outcome.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { ExmapEvent, Utterance, UtterancePostResponse } from "../../core/types.js";
import { badRequest, httpError, refusalError } from "../errors.js";
import type { ClassificationOutcome } from "../session.js";
import { sessionOf, wantWait } from "./common.js";

export const UtteranceWireSchema = z
  .object({
    id: z.string().regex(/^utt_[0-9a-f-]{8,40}$/),
    text: z.string(),
    lane: z.enum(["remote", "me", "manual"]),
    speaker: z.string().nullable(),
    provider: z.enum(["local-whisper", "web-speech", "manual", "replay"]),
    model: z.string().nullable(),
    t_start_ms: z.number().int().nonnegative(),
    t_end_ms: z.number().int().nonnegative(),
    is_local: z.boolean(),
    confidence: z.number().min(0).max(1).nullable(),
  })
  .strict();

export async function utteranceRoutes(app: FastifyInstance): Promise<void> {
  app.post("/api/sessions/:id/utterances", async (req, reply) => {
    const session = sessionOf(app, req);
    const parsed = UtteranceWireSchema.safeParse(req.body);
    if (!parsed.success) {
      const issues = parsed.error.issues.map((i) => ({ path: i.path, code: i.code, message: i.message }));
      throw badRequest(`the utterance is malformed: ${parsed.error.issues.map((i) => `${i.path.join(".") || "(body)"}: ${i.message}`).join("; ")}`, issues, 422);
    }
    const utterance: Utterance = parsed.data;
    let job: Promise<ClassificationOutcome | null> | null = null;
    const response = await session.exclusive((): UtterancePostResponse => {
      const r = session.applyLocked({ kind: "utterance.record", utterance });
      if (!r.ok) {
        if (r.reason === "DUPLICATE_ID") {
          const existing = session.events.find(
            (e): e is Extract<ExmapEvent, { type: "utterance.recorded" }> => e.type === "utterance.recorded" && e.utterance.id === utterance.id,
          );
          throw httpError("DUPLICATE_ID", r.detail, existing ? { event: { id: existing.id, seq: existing.seq, hash: existing.hash } } : {});
        }
        throw refusalError(r, 422);
      }
      job = session.classify(utterance.id); // enqueued before the mutex is released
      const e = r.events[0]!;
      return { ok: true, event: { id: e.id, seq: e.seq, hash: e.hash } };
    });
    if (wantWait(req) && job) {
      const outcome = await (job as Promise<ClassificationOutcome | null>);
      if (outcome) response.classification = outcome.summary;
    }
    return reply.code(201).send(response);
  });
}
