// exmap/src/server/routes/export.ts — GET /api/sessions/:id/export/:file?draft=true|false (design §8.6).
// Refused with 422 NOT_HUMAN_VERIFIED (+ the DoD checks and the sign-off gate status) unless the map is human-verified,
// except an explicit ?draft=true whose files are watermarked.
import type { FastifyInstance } from "fastify";
import type { ExportFile } from "../../core/types.js";
import { EXPORT_FILES, exportFile } from "../../export/index.js";
import { HttpError, errorBody, httpError } from "../errors.js";
import { sessionOf } from "./common.js";

export async function exportRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/sessions/:id/export/:file", async (req, reply) => {
    const file = (req.params as { file: string }).file;
    if (!(EXPORT_FILES as readonly string[]).includes(file)) {
      throw httpError("EXPORT_FILE_UNKNOWN", `unknown export file ${JSON.stringify(file)}; one of ${EXPORT_FILES.join(", ")}`);
    }
    const session = sessionOf(app, req);
    const draft = (req.query as { draft?: unknown } | undefined)?.draft === "true";
    const result = exportFile(
      { session: { id: session.meta.id, title: session.meta.title, created_at: session.meta.created_at }, state: session.state, draft, now: app.exmap.now() },
      file as ExportFile,
    );
    if (!result.ok) {
      throw new HttpError(422, errorBody(result.reason, result.detail, { checks: result.checks, signoff: result.signoff }));
    }
    return reply
      .code(200)
      .type(result.content_type)
      .header("content-disposition", `attachment; filename="${result.filename}"`)
      .send(Buffer.from(result.body, "utf8")); // a Buffer keeps the export module's content type exactly (no added charset)
  });
}
