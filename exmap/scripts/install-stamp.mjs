#!/usr/bin/env node
// exmap/scripts/install-stamp.mjs — the postinstall script (design §3.2): writes node_modules/.exmap-install-stamp
// = hex sha256(package-lock.json) so the launcher can tell whether the lockfile changed since the last install.
// Node built-ins only; nothing here may depend on an installed package.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const lock = join(root, "package-lock.json");
if (!existsSync(lock)) process.exit(0); // nothing to stamp yet; the launcher writes it after its own install
const hash = createHash("sha256").update(readFileSync(lock)).digest("hex");
mkdirSync(join(root, "node_modules"), { recursive: true });
writeFileSync(join(root, "node_modules", ".exmap-install-stamp"), `${hash}\n`);
