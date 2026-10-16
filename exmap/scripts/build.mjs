#!/usr/bin/env node
// exmap/scripts/build.mjs — the sequential build (design §3.2; 4 CPUs, so one step at a time):
// (1) vite build -> dist/web   (2) tsc -p tsconfig.server.json -> dist/server   (3) drop the never-requested
// ort-wasm-*.wasm Vite copied into dist/web/assets (the runtime is served from /ort/, design §8.2)
// (4) write dist/.exmap-build-stamp. Any step failing exits 1 naming the step.
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { lockHashOf, newestMtimeMs, BUILD_STAMP } from "../bin/exmap.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

function run(step, args) {
  console.log(`build: ${step}`);
  const r = spawnSync(process.execPath, args, { cwd: ROOT, stdio: "inherit" });
  if (r.status !== 0) {
    console.error(`build failed at step "${step}" (exit ${r.status ?? r.signal})`);
    process.exit(1);
  }
}

// Captured before building so an edit made during the build still counts as newer than this build.
const newestSourceMtimeMs = newestMtimeMs(ROOT);

// vite 8's exports map has no "./bin/*", so the bin is located from its package.json.
const viteBin = join(dirname(require.resolve("vite/package.json")), "bin", "vite.js");
const tscBin = join(dirname(require.resolve("typescript/package.json")), "bin", "tsc");

run("vite build", [viteBin, "build"]);
run("tsc -p tsconfig.server.json", [tscBin, "-p", "tsconfig.server.json"]);

const assets = join(ROOT, "dist", "web", "assets");
if (existsSync(assets)) {
  for (const name of readdirSync(assets)) {
    if (/^ort-wasm-.*\.wasm$/.test(name)) {
      unlinkSync(join(assets, name));
      console.log(`build: removed dist/web/assets/${name} (served from /ort/ instead)`);
    }
  }
}

mkdirSync(join(ROOT, "dist"), { recursive: true });
const stamp = { lock_sha256: lockHashOf(ROOT), newest_source_mtime_ms: newestSourceMtimeMs, built_at: new Date().toISOString(), node: process.version };
writeFileSync(join(ROOT, BUILD_STAMP), `${JSON.stringify(stamp, null, 2)}\n`);
console.log("build: ok");
