// exmap/src/server/config.ts — ServerConfig from env + opts; classifierSelection() for /api/config (design §8.1, §8.3).
// Step-zero: findRoot, packageVersion and configFromEnv are real (the CLI needs them); classifierSelection is a stub.
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { ClassifierConfig } from "../core/types.js";
import { resolveOrtDir } from "./static.js";

export const DEFAULT_PORT = 4317;

export interface ServerConfig {
  root: string; // the exmap package root
  version: string;
  home: string;
  port: number;
  host: "127.0.0.1";
  coop: boolean;
  dev: boolean;
  webDist: string | null;
  ortDir: string | null;
}

/** Walks up from `from` to the directory holding exmap's package.json (works from src/ under tsx and from dist/ under node). */
export function findRoot(from: string): string {
  let dir = resolve(from);
  for (let i = 0; i < 12; i++) {
    const pkg = join(dir, "package.json");
    if (existsSync(pkg)) {
      try {
        if (JSON.parse(readFileSync(pkg, "utf8")).name === "exmap") return dir;
      } catch {
        /* keep walking */
      }
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(`exmap package root not found above ${from}`);
}

export function packageVersion(root: string): string {
  return String(JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version ?? "0.0.0");
}

export function configFromEnv(env: NodeJS.ProcessEnv, root: string): ServerConfig {
  const rawPort = env.EXMAP_PORT;
  const port = rawPort === undefined || rawPort === "" ? DEFAULT_PORT : Number(rawPort);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error(`EXMAP_PORT is not a valid port: ${rawPort}`);
  const dev = env.EXMAP_DEV === "1";
  const webDist = join(root, "dist", "web");
  let ortDir: string | null;
  try {
    ortDir = resolveOrtDir(root);
  } catch {
    ortDir = join(root, "node_modules", "onnxruntime-web", "dist"); // startServer refuses with ORT_RUNTIME_MISSING
  }
  return {
    root,
    version: packageVersion(root),
    home: env.EXMAP_HOME && env.EXMAP_HOME !== "" ? resolve(env.EXMAP_HOME) : join(homedir(), ".exmap"),
    port,
    host: "127.0.0.1",
    coop: env.EXMAP_COOP !== "0",
    dev,
    webDist: !dev && existsSync(join(webDist, "index.html")) ? webDist : null,
    ortDir,
  };
}

/** provider / reason / model / credentials / last_error for GET /api/config; never the key. */
export function classifierSelection(env: NodeJS.ProcessEnv): ClassifierConfig {
  void env;
  throw new Error("not implemented: classifierSelection");
}
