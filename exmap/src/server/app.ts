// exmap/src/server/app.ts — buildApp(opts): plugins, hooks, routes, static (design §8.1, §8.2).
// Loopback only: a Host guard on every request (DNS rebinding), an Origin check on WebSocket upgrades (routes/stream.ts),
// no CORS headers ever; `Cache-Control: no-store` on /api/*, COOP/COEP on everything when `coop`, `nosniff` everywhere.
// Every error body is ErrorBody.
import { fileURLToPath } from "node:url";
import fastifyWebsocket from "@fastify/websocket";
import Fastify, { type FastifyError, type FastifyInstance } from "fastify";
import { createClassifier } from "../classifier/index.js";
import type { ModelClient } from "../classifier/index.js";
import { createEngine } from "../core/index.js";
import type { ApplyContext, Classifier, IsoTimestamp } from "../core/types.js";
import { classifierSelection, findRoot, packageVersion, type ServerConfig } from "./config.js";
import { HttpError, errorBody } from "./errors.js";
import { sha256 } from "./hash.js";
import { ExmapHome, ensureHomeDir } from "./home.js";
import { nextId as defaultNextId } from "./ids.js";
import { actRoutes } from "./routes/acts.js";
import { exportRoutes } from "./routes/export.js";
import { metaRoutes } from "./routes/meta.js";
import { sessionRoutes } from "./routes/sessions.js";
import { streamRoutes } from "./routes/stream.js";
import { utteranceRoutes } from "./routes/utterances.js";
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
  /** Additive: the claude provider's model client (tests inject a fake so no network is touched). */
  modelClient?: ModelClient;
  env?: NodeJS.ProcessEnv;
  now?: () => IsoTimestamp;
  nextId?: ApplyContext["nextId"];
  logger?: boolean;
}

export interface ExmapDecoration {
  store: SessionStore;
  config: ServerConfig;
  home: ExmapHome;
  now: () => IsoTimestamp;
  nextId: ApplyContext["nextId"];
  /** The port the Host guard and Origin check accept: the bound port once listening, else opts.port. */
  port(): number;
  /** The Host header values the guard accepts. */
  allowedHosts(): string[];
  /** The WebSocket Origin values the stream accepts. */
  allowedOrigins(): string[];
}

declare module "fastify" {
  interface FastifyInstance {
    exmap: ExmapDecoration;
  }
}

export type ExmapApp = FastifyInstance & { exmap: ExmapDecoration };

const VITE_PORT = 5173;

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
  const env = opts.env ?? process.env;
  const now = opts.now ?? (() => new Date().toISOString());
  const nextId = opts.nextId ?? defaultNextId;
  const classifierConfig = classifierSelection(env);
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
    classifier: classifierConfig,
  };
  let classifier: Classifier;
  if (opts.classifier) {
    classifier = opts.classifier;
    if (classifier.provider !== classifierConfig.provider) {
      classifierConfig.provider = classifier.provider;
      classifierConfig.reason = "a classifier was injected by the caller";
      classifierConfig.model = null;
    }
  } else {
    classifier = createClassifier({
      env,
      ...(opts.modelClient ? { client: opts.modelClient } : {}),
      onError: (e) => {
        classifierConfig.last_error = { code: e.code, message: e.message, at: now() };
      },
    });
  }

  ensureHomeDir(opts.home);
  const home = new ExmapHome(opts.home);
  const engine = createEngine({ sha256, now, nextId });
  const store = new SessionStore({
    home: opts.home,
    engine,
    classifier,
    now,
    nextId,
    onClassified: (stamp) => {
      if (stamp.provider === "claude" && stamp.fallback_from === null) classifierConfig.last_error = null;
    },
  });

  const app = Fastify({ logger: opts.logger ?? false, bodyLimit: 1024 * 1024, trustProxy: false });
  app.removeContentTypeParser("text/plain"); // JSON body parser only

  const boundPort = (): number => {
    const address = app.server.address();
    return typeof address === "object" && address !== null ? address.port : config.port;
  };
  const allowedHosts = (): string[] => {
    const p = boundPort();
    const hosts = [`127.0.0.1:${p}`, `localhost:${p}`, `[::1]:${p}`];
    if (config.dev) hosts.push(`127.0.0.1:${VITE_PORT}`, `localhost:${VITE_PORT}`);
    return hosts;
  };
  const allowedOrigins = (): string[] => {
    const p = boundPort();
    const origins = [`http://127.0.0.1:${p}`, `http://localhost:${p}`, `http://[::1]:${p}`];
    if (config.dev) origins.push(`http://127.0.0.1:${VITE_PORT}`, `http://localhost:${VITE_PORT}`);
    return origins;
  };
  app.decorate("exmap", { store, config, home, now, nextId, port: boundPort, allowedHosts, allowedOrigins });

  // DNS-rebinding guard: the Host must name this loopback server
  app.addHook("onRequest", async (req, reply) => {
    const host = (req.headers.host ?? "").toLowerCase();
    if (!allowedHosts().includes(host)) {
      reply.code(403).header("content-type", "application/json; charset=utf-8");
      return reply.send(errorBody("FORBIDDEN_HOST", `requests must name this server's loopback address (Host ${JSON.stringify(host)} is not accepted)`));
    }
    return undefined;
  });

  app.addHook("onSend", async (req, reply, payload) => {
    const path = req.url.split("?")[0] ?? "";
    if (path.startsWith("/api/")) reply.header("cache-control", "no-store");
    if (config.coop) {
      reply.header("cross-origin-opener-policy", "same-origin");
      reply.header("cross-origin-embedder-policy", "require-corp");
    }
    reply.header("x-content-type-options", "nosniff");
    if (path.startsWith("/ort/") && path.endsWith(".mjs")) reply.header("content-type", "text/javascript; charset=utf-8");
    return payload;
  });

  app.setErrorHandler((err: FastifyError | HttpError | Error, req, reply) => {
    if (err instanceof HttpError) return reply.code(err.status).send(err.body);
    const status = "statusCode" in err && typeof err.statusCode === "number" ? err.statusCode : 500;
    if (status >= 400 && status < 500) return reply.code(status).send(errorBody("BAD_REQUEST", err.message));
    req.log.error(err);
    return reply.code(500).send(errorBody("INTERNAL", err.message));
  });
  app.setNotFoundHandler((req, reply) => reply.code(404).send(errorBody("NOT_FOUND", `no route for ${req.method} ${req.url.split("?")[0] ?? ""}`)));

  await app.register(fastifyWebsocket, {
    options: { maxPayload: 64 * 1024 },
    // close(): every WebSocket client gets 1001 (design §8.8)
    preClose(done) {
      for (const client of app.websocketServer.clients) client.close(1001, "server shutting down");
      app.websocketServer.close(() => done());
    },
  });
  app.addHook("onClose", async () => {
    await store.closeAll();
  });

  await app.register(metaRoutes);
  await app.register(sessionRoutes);
  await app.register(utteranceRoutes);
  await app.register(actRoutes);
  await app.register(exportRoutes);
  await app.register(streamRoutes);
  await registerStatic(app, { webDist: config.webDist, ortDir: config.ortDir });
  return app as ExmapApp;
}
