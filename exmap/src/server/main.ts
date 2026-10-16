// exmap/src/server/main.ts — startServer(opts) and the CLI entry (design §8.1, §9, §11 step 8). The CLI reads env
// (EXMAP_PORT, EXMAP_HOME, EXMAP_COOP, EXMAP_DEV) and prints exactly one stdout line:
// `exmap listening on http://127.0.0.1:<port>`; the classifier line of design §6.2 goes to stderr.
// Run as plain `node dist/server/server/main.js`; the launcher imports startServer from the same file.
import { fileURLToPath, pathToFileURL } from "node:url";
import type { FastifyInstance } from "fastify";
import { buildApp, type AppOptions } from "./app.js";
import { classifierStartupLine, configFromEnv, findRoot, packageVersion } from "./config.js";
import { ExmapHome, ensureHomeDir } from "./home.js";
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

/**
 * Takes server.lock (before listen; HomeLockedError when another live exmap owns the home), builds the app, listens on
 * loopback, completes the lock with the bound port and prints the listening line. close(): stop listening, close
 * WebSocket clients with 1001, abort classification and drop queued jobs, wait for in-flight appends, remove the lock.
 */
export async function startServer(opts: AppOptions): Promise<StartedServer> {
  ensureHomeDir(opts.home);
  if (opts.ortDir) {
    const missing = missingOrtFiles(opts.ortDir);
    if (missing.length > 0) throw new OrtRuntimeMissingError(missing);
  }
  const home = new ExmapHome(opts.home);
  await home.acquireLock(packageVersion(findRoot(fileURLToPath(import.meta.url))));
  const releaseOnExit = (): void => home.releaseLock();
  process.on("exit", releaseOnExit);
  let app: FastifyInstance;
  try {
    app = await buildApp(opts);
    await app.listen({ host: opts.host ?? "127.0.0.1", port: opts.port ?? 4317 });
  } catch (e) {
    process.removeListener("exit", releaseOnExit);
    home.releaseLock();
    throw e;
  }
  const address = app.server.address();
  const port = typeof address === "object" && address !== null ? address.port : (opts.port ?? 4317);
  home.completeLock(port);
  const url = `http://127.0.0.1:${port}`;
  console.log(`exmap listening on ${url}`);
  console.error(classifierStartupLine(app.exmap.config.classifier));
  let closing: Promise<void> | null = null;
  const close = (): Promise<void> => {
    closing ??= app.close().finally(() => {
      process.removeListener("exit", releaseOnExit);
      home.releaseLock();
    });
    return closing;
  };
  return { app, url, port, close };
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
    process.exit(e instanceof Error && e.name === "HomeLockedError" ? 6 : 1);
  });
}
