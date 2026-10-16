#!/usr/bin/env node
// exmap/scripts/clean.mjs — removes build and test output (never node_modules; `npm run clean` is safe to re-run).
import { readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
for (const dir of ["dist", "test-results", "playwright-report", "coverage", ".vite"]) rmSync(join(ROOT, dir), { recursive: true, force: true });
for (const name of readdirSync(ROOT)) if (name.endsWith(".tsbuildinfo")) rmSync(join(ROOT, name), { force: true });
console.log("clean: ok");
