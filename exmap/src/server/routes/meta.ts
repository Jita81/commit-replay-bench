// exmap/src/server/routes/meta.ts — /api/health, /api/config, /api/settings, /api/catalogue (design §8.3).
import { readFileSync } from "node:fs";
import type { FastifyInstance } from "fastify";
import type { ConfigResponse } from "../../core/types.js";
import { badRequest } from "../errors.js";

/** The vendored catalogue file (src/export/ under tsx, dist/server/export/ after tsc copies it), served byte for byte. */
const CATALOGUE_URL = new URL("../../export/crb-catalogue.json", import.meta.url);
let catalogueBytes: Buffer | null = null;

export const USER_NAME_MAX = 80;

export async function metaRoutes(app: FastifyInstance): Promise<void> {
  // the launcher's reuse probe (it reads only `app`); INTEGRATION-NOTES step zero #1: { app, version, ok, pid }
  app.get("/api/health", async () => ({ app: "exmap", version: app.exmap.config.version, ok: true, pid: process.pid }));

  app.get("/api/config", async (): Promise<ConfigResponse> => {
    const c = app.exmap.config;
    return {
      app: "exmap",
      version: c.version,
      port: app.exmap.port(),
      home: c.home,
      loopback: true,
      coop: c.coop,
      // built from booleans by classifierSelection(); never a credential's value
      classifier: { ...c.classifier, last_error: c.classifier.last_error ? { ...c.classifier.last_error } : null },
    };
  });

  app.get("/api/settings", async () => ({ user_name: app.exmap.home.readSettings().user_name }));

  app.put("/api/settings", async (req) => {
    const body = req.body as { user_name?: unknown } | null | undefined;
    if (!body || typeof body !== "object" || Array.isArray(body) || typeof body.user_name !== "string") {
      throw badRequest("the body must be { user_name: string }");
    }
    const user_name = body.user_name.trim();
    if (user_name.length > USER_NAME_MAX) throw badRequest(`user_name is ${user_name.length} characters; at most ${USER_NAME_MAX} are allowed`);
    app.exmap.home.writeSettings({ user_name });
    return { user_name };
  });

  // the vendored crb catalogue, verbatim
  app.get("/api/catalogue", async (_req, reply) => {
    catalogueBytes ??= readFileSync(CATALOGUE_URL);
    return reply.type("application/json; charset=utf-8").send(catalogueBytes);
  });
}
