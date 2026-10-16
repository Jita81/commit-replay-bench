#!/usr/bin/env node
// exmap/bin/exmap.mjs — the one command (design §11): Node check, install when the lockfile changed,
// build when stale, start the server in-process, open the browser, run until signalled.
// Plain ESM, Node built-ins only: this file runs before node_modules exists.
import { existsSync, readFileSync, writeFileSync, statSync, readdirSync, realpathSync } from "node:fs";
import { join, dirname, resolve, basename } from "node:path";
import { homedir } from "node:os";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const DEFAULT_PORT = 4317;
export const INSTALL_STAMP = "node_modules/.exmap-install-stamp";
export const BUILD_STAMP = "dist/.exmap-build-stamp";
/** What the staleness walk looks at (design §11 step 4); `**\/*.test.*` is skipped. */
export const SOURCE_ROOTS = ["src", "vite.config.ts", "tsconfig.base.json", "tsconfig.server.json", "tsconfig.web.json", "package.json"];

const USAGE = `usage: node bin/exmap.mjs [--port <n>] [--home <dir>] [--no-open] [--no-install] [--no-build]
env:   EXMAP_PORT (default ${DEFAULT_PORT}; 0 = OS-assigned)  EXMAP_HOME (default ~/.exmap)  EXMAP_NO_OPEN=1
       EXMAP_CLASSIFIER  ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN (passed through, never printed)  EXMAP_COOP=0
exit:  0 started (or already running)  1 unexpected failure  2 node < 22.12  3 port in use by another program
       4 npm install failed  5 build failed  6 EXMAP_HOME locked by another live exmap server`;

/* ───────── pure helpers (unit-tested in tests/unit/launcher) ───────── */

export function nodeVersionOk(version) {
  const m = /^v?(\d+)\.(\d+)/.exec(String(version));
  if (!m) return false;
  const major = Number(m[1]);
  const minor = Number(m[2]);
  return major > 22 || (major === 22 && minor >= 12);
}

export function sha256Hex(data) {
  return createHash("sha256").update(data).digest("hex");
}

/** sha256 of package-lock.json, or "" when there is no lockfile yet. */
export function lockHashOf(root = ROOT) {
  const p = join(root, "package-lock.json");
  return existsSync(p) ? sha256Hex(readFileSync(p)) : "";
}

export function readInstallStamp(root = ROOT) {
  try {
    return readFileSync(join(root, INSTALL_STAMP), "utf8");
  } catch {
    return "";
  }
}

export function installNeeded({ nodeModulesExists, stamp, lockHash }) {
  return !nodeModulesExists || String(stamp ?? "").trim() !== lockHash;
}

/** Newest mtime (ms) under the given entries, skipping `**\/*.test.*`; 0 when nothing exists. */
export function newestMtimeMs(root = ROOT, entries = SOURCE_ROOTS) {
  let newest = 0;
  const visit = (p) => {
    let st;
    try {
      st = statSync(p);
    } catch {
      return;
    }
    if (st.isDirectory()) {
      for (const name of readdirSync(p)) visit(join(p, name));
      return;
    }
    if (/\.test\.[^/\\]+$/.test(basename(p))) return;
    if (st.mtimeMs > newest) newest = st.mtimeMs;
  };
  for (const e of entries) visit(join(root, e));
  return newest;
}

export function readBuildStamp(root = ROOT) {
  try {
    const parsed = JSON.parse(readFileSync(join(root, BUILD_STAMP), "utf8"));
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function buildStale({ webIndexExists, serverMainExists, stamp, lockHash, newestSourceMtimeMs }) {
  if (!webIndexExists || !serverMainExists) return true;
  if (!stamp || typeof stamp !== "object") return true;
  if (stamp.lock_sha256 !== lockHash) return true;
  if (typeof stamp.newest_source_mtime_ms !== "number") return true;
  return newestSourceMtimeMs > stamp.newest_source_mtime_ms;
}

/** First executable named `name` on PATH (also `name.cmd` on Windows), or null. */
export function whichOnPath(name, env = process.env, platform = process.platform, exists = existsSync) {
  const dirs = String(env.PATH ?? env.Path ?? "").split(platform === "win32" ? ";" : ":").filter(Boolean);
  const names = platform === "win32" ? [`${name}.cmd`, `${name}.exe`, name] : [name];
  for (const dir of dirs) for (const n of names) {
    const candidate = join(dir, n);
    if (exists(candidate)) return candidate;
  }
  return null;
}

function npmCliFromBin(binPath, exists) {
  let real = binPath;
  try {
    real = realpathSync(binPath);
  } catch {
    /* keep the symlink path */
  }
  if (basename(real) === "npm-cli.js" && exists(real)) return real;
  const sibling = join(dirname(real), "npm-cli.js");
  if (exists(sibling)) return sibling;
  const underLib = join(dirname(real), "..", "lib", "node_modules", "npm", "bin", "npm-cli.js");
  if (exists(underLib)) return underLib;
  return null;
}

/**
 * Locates npm (design §11 step 3), in order: npm_execpath; <execDir>/node_modules/npm/bin/npm-cli.js (Windows);
 * <execDir>/../lib/node_modules/npm/bin/npm-cli.js (Linux/macOS tarballs, nvm); realpath(which("npm")) resolved to
 * its npm-cli.js; last, `npm` on PATH with shell: true. An npm-cli.js is run by the Node that passed the check.
 */
export function locateNpm({ execPath = process.execPath, env = process.env, exists = existsSync, which = (n) => whichOnPath(n, env) } = {}) {
  if (env.npm_execpath && exists(env.npm_execpath)) return { cmd: execPath, args: [env.npm_execpath], shell: false, label: env.npm_execpath };
  const execDir = dirname(execPath);
  for (const candidate of [
    join(execDir, "node_modules", "npm", "bin", "npm-cli.js"),
    join(execDir, "..", "lib", "node_modules", "npm", "bin", "npm-cli.js"),
  ]) {
    if (exists(candidate)) return { cmd: execPath, args: [candidate], shell: false, label: candidate };
  }
  const onPath = which("npm");
  if (onPath) {
    const cli = npmCliFromBin(onPath, exists);
    if (cli) return { cmd: execPath, args: [cli], shell: false, label: cli };
  }
  return { cmd: "npm", args: [], shell: true, label: "npm from PATH" };
}

/** [command, args] that opens `url`, or null when there is nothing sensible to run (design §11 step 7). */
export function browserCommand(platform, env, url, resolveCmd = (n) => whichOnPath(n, env, platform)) {
  if (platform === "darwin") return ["open", [url]];
  if (platform === "win32") return ["cmd.exe", ["/c", "start", "", url]];
  if (platform === "linux") {
    if (env.WSL_DISTRO_NAME && resolveCmd("cmd.exe")) return ["cmd.exe", ["/c", "start", "", url]];
    if (env.DISPLAY || env.WAYLAND_DISPLAY) return ["xdg-open", [url]];
  }
  return null;
}

/** "exmap" when an exmap server answers at url, "other" for anything else that answers, "free" when nothing does. */
export async function probePort(url, fetchImpl = globalThis.fetch, timeoutMs = 1500) {
  let res;
  try {
    res = await fetchImpl(`${url}/api/health`, { signal: AbortSignal.timeout(timeoutMs) });
  } catch {
    return "free"; // connection refused or timed out
  }
  if (res.status === 200) {
    try {
      const body = await res.json();
      if (body && body.app === "exmap") return "exmap";
    } catch {
      /* not JSON */
    }
  }
  return "other";
}

export async function waitForHealth(url, { timeoutMs = 30_000, intervalMs = 250, fetchImpl = globalThis.fetch } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if ((await probePort(url, fetchImpl)) === "exmap") return true;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}

export function openBrowser(url, { platform = process.platform, env = process.env } = {}) {
  const cmd = browserCommand(platform, env, url);
  if (!cmd) {
    console.log(`Open ${url} in Chrome or Edge`);
    return;
  }
  try {
    const child = spawn(cmd[0], cmd[1], { detached: true, stdio: "ignore" });
    child.on("error", (e) => console.log(`could not open the browser (${e.message}); open ${url} yourself`));
    child.unref();
    console.log(`Opening ${url}`);
  } catch (e) {
    console.log(`could not open the browser (${e.message}); open ${url} yourself`);
  }
}

export function parseArgs(argv) {
  const out = { port: null, home: null, open: true, install: true, build: true, help: false, unknown: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--port") out.port = Number(argv[++i]);
    else if (a.startsWith("--port=")) out.port = Number(a.slice("--port=".length));
    else if (a === "--home") out.home = argv[++i] ?? null;
    else if (a.startsWith("--home=")) out.home = a.slice("--home=".length);
    else if (a === "--no-open") out.open = false;
    else if (a === "--no-install") out.install = false;
    else if (a === "--no-build") out.build = false;
    else if (a === "-h" || a === "--help") out.help = true;
    else out.unknown = a;
  }
  return out;
}

/* ───────── the steps (design §11) ───────── */

function stepInstall(env, lockHash) {
  const npm = locateNpm({ env });
  if (npm.shell) console.log("using npm from PATH");
  console.log("exmap: installing packages (first run, or the lockfile changed)...");
  const r = spawnSync(npm.cmd, [...npm.args, "install", "--no-audit", "--no-fund"], {
    cwd: ROOT,
    stdio: "inherit",
    shell: npm.shell,
    env: { ...env, ONNXRUNTIME_NODE_INSTALL: "skip", npm_config_onnxruntime_node_install: "skip" },
  });
  if (r.status !== 0) return false;
  const lockNow = lockHashOf(ROOT) || lockHash;
  if (readInstallStamp(ROOT).trim() !== lockNow) writeFileSync(join(ROOT, INSTALL_STAMP), `${lockNow}\n`);
  return true;
}

function stepBuild(env) {
  console.log("exmap: building the web bundle and the server (first run, or sources changed)...");
  const r = spawnSync(process.execPath, [join(ROOT, "scripts", "build.mjs")], { cwd: ROOT, stdio: "inherit", env });
  return r.status === 0;
}

export async function main(argv = process.argv.slice(2), env = process.env) {
  const args = parseArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  if (args.unknown) {
    console.error(`exmap: unknown option ${args.unknown}\n${USAGE}`);
    return 1;
  }

  // 1. Node check
  if (!nodeVersionOk(process.version)) {
    console.error(`exmap needs Node 22.12 or newer (found ${process.version}). Install it from https://nodejs.org`);
    return 2;
  }

  const envPort = env.EXMAP_PORT !== undefined && env.EXMAP_PORT !== "" ? Number(env.EXMAP_PORT) : DEFAULT_PORT;
  const port = args.port ?? envPort;
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    console.error(`exmap: invalid port ${args.port ?? env.EXMAP_PORT}`);
    return 1;
  }
  const home = resolve(args.home ?? (env.EXMAP_HOME || join(homedir(), ".exmap")));
  const open = args.open && env.EXMAP_NO_OPEN !== "1";
  const coop = env.EXMAP_COOP !== "0";

  // 2. Port probe (skipped for an OS-assigned port)
  if (port !== 0) {
    const url = `http://127.0.0.1:${port}`;
    const probe = await probePort(url);
    if (probe === "exmap") {
      console.log(`exmap is already running at ${url}`);
      if (open) openBrowser(url);
      return 0;
    }
    if (probe === "other") {
      console.error(`port ${port} is in use by another program; set EXMAP_PORT or pass --port`);
      return 3;
    }
  }

  // 3. Install when needed
  const nodeModules = join(ROOT, "node_modules");
  if (args.install) {
    const lockHash = lockHashOf(ROOT);
    if (installNeeded({ nodeModulesExists: existsSync(nodeModules), stamp: readInstallStamp(ROOT), lockHash })) {
      if (!stepInstall(env, lockHash)) {
        console.error("exmap: npm install failed");
        return 4;
      }
    }
  } else if (!existsSync(nodeModules)) {
    console.error("exmap: node_modules is missing and --no-install was given");
    return 4;
  }

  // 4. Build when stale (the lockfile may have been rewritten by the install)
  const serverMain = join(ROOT, "dist", "server", "server", "main.js");
  if (args.build) {
    const stale = buildStale({
      webIndexExists: existsSync(join(ROOT, "dist", "web", "index.html")),
      serverMainExists: existsSync(serverMain),
      stamp: readBuildStamp(ROOT),
      lockHash: lockHashOf(ROOT),
      newestSourceMtimeMs: newestMtimeMs(ROOT),
    });
    if (stale && !stepBuild(env)) {
      console.error("exmap: build failed");
      return 5;
    }
  } else if (!existsSync(serverMain)) {
    console.error("exmap: dist/ is missing and --no-build was given");
    return 5;
  }

  // 5. Start the server in-process
  let startServer;
  let resolveOrtDir;
  try {
    ({ startServer } = await import(pathToFileURL(serverMain).href));
    ({ resolveOrtDir } = await import(pathToFileURL(join(ROOT, "dist", "server", "server", "static.js")).href));
  } catch (e) {
    console.error(`exmap: cannot load the server build: ${e?.message ?? e}`);
    return 1;
  }
  let srv;
  try {
    srv = await startServer({ home, port, host: "127.0.0.1", coop, webDist: join(ROOT, "dist", "web"), ortDir: resolveOrtDir(ROOT), env });
  } catch (e) {
    if (e && e.name === "HomeLockedError") {
      console.error(e.url ? `another exmap is already using ${home} at ${e.url}` : `another exmap is starting on this home (${home})`);
      return 6;
    }
    console.error(`exmap: the server failed to start: ${e?.message ?? e}`);
    return 1;
  }

  // 6. Wait for health
  if (!(await waitForHealth(srv.url))) {
    console.error(`exmap: the server did not answer at ${srv.url}/api/health within 30 s`);
    await srv.close().catch(() => {});
    return 1;
  }

  // 7. Open the browser (the URL is always printed)
  if (open) openBrowser(srv.url);
  else console.log(`Open ${srv.url} in Chrome or Edge`);

  // 8. Run until signalled
  return new Promise((resolveExit) => {
    let closing = false;
    const onSignal = (signal) => {
      if (closing) process.exit(130);
      closing = true;
      console.log(`\nexmap: ${signal} received, shutting down...`);
      srv.close().then(
        () => resolveExit(0),
        (e) => {
          console.error(`exmap: close failed: ${e?.message ?? e}`);
          resolveExit(1);
        },
      );
    };
    process.on("SIGINT", onSignal);
    process.on("SIGTERM", onSignal);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then(
    (code) => process.exit(code),
    (e) => {
      console.error(`exmap: ${e?.stack ?? e}`);
      process.exit(1);
    },
  );
}
