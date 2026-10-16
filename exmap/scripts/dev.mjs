#!/usr/bin/env node
// exmap/scripts/dev.mjs — development (design §3.2): `tsx watch src/server/main.ts` with EXMAP_DEV=1 (no web bundle;
// GET / answers 503 pointing at Vite; /ort/* still served) plus Vite on http://127.0.0.1:5173 proxying /api (ws) and
// /ort to :4317 (vite.config.ts). `--server-only` skips Vite. SIGINT/SIGTERM stop both.
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const serverOnly = process.argv.includes("--server-only");

const tsxCli = require.resolve("tsx/cli");
const viteBin = join(dirname(require.resolve("vite/package.json")), "bin", "vite.js");

const children = [];
let shuttingDown = false;

function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const c of children) if (c.exitCode === null) c.kill("SIGTERM");
  setTimeout(() => process.exit(code), 300).unref();
}

function start(label, args, extraEnv) {
  const child = spawn(process.execPath, args, { cwd: ROOT, stdio: "inherit", env: { ...process.env, ...extraEnv } });
  child.on("exit", (code, signal) => {
    if (!shuttingDown) {
      console.error(`dev: ${label} exited (${code ?? signal}); stopping`);
      shutdown(code ?? 1);
    }
  });
  children.push(child);
}

start("server", [tsxCli, "watch", "src/server/main.ts"], { EXMAP_DEV: "1" });
if (!serverOnly) start("vite", [viteBin], {});
else console.log("dev: --server-only; the Vite dev server is not started");

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
