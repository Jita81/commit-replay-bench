// exmap/src/server/routes/meta.ts — /api/health, /api/config, /api/settings, /api/catalogue (design §8.3).
// Step zero: GET /api/health is real (the launcher's reuse probe); the others are added by the server module.
import type { FastifyInstance } from "fastify";

export async function metaRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/health", async () => ({ app: "exmap", version: app.exmap.config.version, ok: true, pid: process.pid }));
}
