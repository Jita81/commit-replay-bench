// exmap/src/server/app.ts — buildApp(opts): plugins, hooks, routes, static (design §8.1). Step zero registers only
// GET /api/health (routes/meta.ts) and the static roots; the server module adds the hooks and the other routes.
import { fileURLToPath } from "node:url";
import Fastify, { type FastifyInstance } from "fastify";
import type { ApplyContext, Classifier, IsoTimestamp } from "../core/types.js";
import { findRoot, packageVersion, type ServerConfig } from "./config.js";
import { metaRoutes } from "./routes/meta.js";
import { SessionStore } from "./session-store.js";
import { registerStatic, resolveOrtDir } from "./static.js";

export interface AppOptions {
  home: string;
  port?: number;
  host?: "127.0.0.1";
  coop?: boolean; // default true
  webDist?: string | null; // null = not served (tests, dev)
  ortDir?: string | null; // null = not served (tests, dev)
  dev?: boolean; // EXMAP_DEV=1: also accept the Vite origin/host
  classifier?: Classifier; // injected fake in tests; default createClassifier({ env, onError })
  env?: NodeJS.ProcessEnv;
  now?: () => IsoTimestamp;
  nextId?: ApplyContext["nextId"];
  logger?: boolean;
}

export interface ExmapDecoration {
  store: SessionStore;
  config: ServerConfig;
}

declare module "fastify" {
  interface FastifyInstance {
    exmap: ExmapDecoration;
  }
}

export type ExmapApp = FastifyInstance & { exmap: ExmapDecoration };

export async function buildApp(opts: AppOptions): Promise<ExmapApp> {
  const root = findRoot(fileURLToPath(import.meta.url));
  let ortDir: string | null = opts.ortDir ?? null;
  if (opts.ortDir === undefined) {
    try {
      ortDir = resolveOrtDir(root);
    } catch {
      ortDir = null;
    }
  }
  const config: ServerConfig = {
    root,
    version: packageVersion(root),
    home: opts.home,
    port: opts.port ?? 4317,
    host: opts.host ?? "127.0.0.1",
    coop: opts.coop ?? true,
    dev: opts.dev ?? false,
    webDist: opts.webDist ?? null,
    ortDir,
  };
  const app = Fastify({ logger: opts.logger ?? false, bodyLimit: 1024 * 1024, trustProxy: false });
  app.decorate("exmap", { store: new SessionStore({ home: opts.home }), config });
  await app.register(metaRoutes);
  await registerStatic(app, { webDist: config.webDist, ortDir: config.ortDir });
  return app as ExmapApp;
}
