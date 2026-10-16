// exmap/src/server/main.ts — startServer(opts) and the CLI entry (design §8.1). The CLI reads env (EXMAP_PORT, EXMAP_HOME,
// EXMAP_COOP, EXMAP_DEV) and prints exactly one line: `exmap listening on http://127.0.0.1:<port>`.
// Run as plain `node dist/server/server/main.js`; the launcher imports startServer from the same file.
import { fileURLToPath, pathToFileURL } from "node:url";
import type { FastifyInstance } from "fastify";
import { buildApp, type AppOptions } from "./app.js";
import { configFromEnv, findRoot } from "./config.js";
import { ensureHomeDir } from "./home.js";
import { missingOrtFiles } from "./static.js";

export type { AppOptions } from "./app.js";
export { HomeLockedError } from "./home.js";

export interface StartedServer {
  app: FastifyInstance;
  url: string;
  port: number;
  close(): Promise<void>;
}

export class OrtRuntimeMissingError extends Error {
  readonly code = "ORT_RUNTIME_MISSING";
  readonly missing: string[];
  constructor(missing: string[]) {
    super(`ORT_RUNTIME_MISSING: ${missing.join(", ")}`);
    this.name = "OrtRuntimeMissingError";
    this.missing = missing;
  }
}

/** Takes server.lock (server module), builds the app, listens on loopback and prints the listening line. */
export async function startServer(opts: AppOptions): Promise<StartedServer> {
  ensureHomeDir(opts.home);
  if (opts.ortDir) {
    const missing = missingOrtFiles(opts.ortDir);
    if (missing.length > 0) throw new OrtRuntimeMissingError(missing);
  }
  const app = await buildApp(opts);
  await app.listen({ host: opts.host ?? "127.0.0.1", port: opts.port ?? 4317 });
  const address = app.server.address();
  const port = typeof address === "object" && address !== null ? address.port : (opts.port ?? 4317);
  const url = `http://127.0.0.1:${port}`;
  console.log(`exmap listening on ${url}`);
  return { app, url, port, close: () => app.close() };
}

export async function main(env: NodeJS.ProcessEnv = process.env): Promise<void> {
  const cfg = configFromEnv(env, findRoot(fileURLToPath(import.meta.url)));
  const srv = await startServer({
    home: cfg.home,
    port: cfg.port,
    host: cfg.host,
    coop: cfg.coop,
    dev: cfg.dev,
    webDist: cfg.webDist,
    ortDir: cfg.ortDir,
    env,
  });
  let closing = false;
  const stop = (): void => {
    if (closing) process.exit(130);
    closing = true;
    srv.close().then(
      () => process.exit(0),
      () => process.exit(1),
    );
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e: unknown) => {
    console.error(e instanceof Error ? e.message : String(e));
    process.exit(1);
  });
}
