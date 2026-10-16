// exmap/src/server/config.ts — ServerConfig from env + opts; classifierSelection() for /api/config (design §8.1, §8.3).
// classifierSelection() is built from booleans over the environment: it names which variable chose the provider and never
// carries a credential's value.
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { CLAUDE_MODEL, selectProvider } from "../classifier/index.js";
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
  /** What GET /api/config reports; `last_error` is kept here in memory (set by the claude provider's onError). */
  classifier: ClassifierConfig;
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
    classifier: classifierSelection(env),
  };
}

const nonEmpty = (v: string | undefined): boolean => v !== undefined && v.trim() !== "";

/**
 * provider / reason / model / credentials / last_error for GET /api/config; never the key. Throws the classifier's
 * E_CLASSIFIER_UNKNOWN_PROVIDER for an EXMAP_CLASSIFIER value that names no provider (the server refuses to start).
 */
export function classifierSelection(env: NodeJS.ProcessEnv): ClassifierConfig {
  const provider = selectProvider(env);
  const explicit = (env["EXMAP_CLASSIFIER"] ?? "").trim() !== "";
  const hasKey = nonEmpty(env["ANTHROPIC_API_KEY"]);
  const hasToken = nonEmpty(env["ANTHROPIC_AUTH_TOKEN"]);
  let reason: string;
  if (explicit) reason = provider === "claude" ? "EXMAP_CLASSIFIER=claude" : "EXMAP_CLASSIFIER=rules.v1";
  else if (hasKey) reason = "ANTHROPIC_API_KEY is set";
  else if (hasToken) reason = "ANTHROPIC_AUTH_TOKEN is set";
  else reason = "no model configured; using the offline rules classifier";
  const credentials: ClassifierConfig["credentials"] = hasKey ? "api_key" : hasToken ? "auth_token" : provider === "claude" ? "profile_or_none" : "none";
  return { provider, reason, model: provider === "claude" ? CLAUDE_MODEL : null, credentials, last_error: null };
}

/** The startup line of design §6.2 (printed on stderr so stdout stays the single listening line). */
export function classifierStartupLine(c: ClassifierConfig): string {
  return c.provider === "claude" ? `classifier: claude (${c.model ?? CLAUDE_MODEL})` : "classifier: rules.v1 (offline)";
}
