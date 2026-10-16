// tests/unit/launcher/launcher.test.ts — TEST-PLAN §7: the launcher's pure helpers (bin/exmap.mjs) and the postinstall
// stamp script. The launcher is plain ESM JavaScript with no declaration file, so it is imported by a computed URL and
// typed here by the shape the tests use.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const ROOT = resolve(fileURLToPath(new URL("../../../", import.meta.url)));

interface NpmCommand { cmd: string; args: string[]; shell: boolean; label: string }
interface Launcher {
  nodeVersionOk(version: string): boolean;
  installNeeded(o: { nodeModulesExists: boolean; stamp: string | null; lockHash: string }): boolean;
  buildStale(o: { webIndexExists: boolean; serverMainExists: boolean; stamp: unknown; lockHash: string; newestSourceMtimeMs: number }): boolean;
  locateNpm(o: { execPath: string; env: Record<string, string | undefined>; exists: (p: string) => boolean; which: (n: string) => string | null }): NpmCommand;
  browserCommand(platform: string, env: Record<string, string | undefined>, url: string, resolveCmd?: (n: string) => string | null): [string, string[]] | null;
  probePort(url: string, fetchImpl?: typeof fetch, timeoutMs?: number): Promise<"exmap" | "other" | "free">;
}

let L: Launcher;
beforeAll(async () => {
  L = (await import(pathToFileURL(join(ROOT, "bin", "exmap.mjs")).href)) as Launcher;
});

describe("launcher pure helpers (design §11)", () => {
  it("nodeVersionOk: the floor is 22.12", () => {
    expect(L.nodeVersionOk("22.11.0")).toBe(false);
    expect(L.nodeVersionOk("v22.11.9")).toBe(false);
    expect(L.nodeVersionOk("22.12.0")).toBe(true);
    expect(L.nodeVersionOk("v22.22.0")).toBe(true);
    expect(L.nodeVersionOk("23.1.0")).toBe(true);
    expect(L.nodeVersionOk("20.18.1")).toBe(false);
    expect(L.nodeVersionOk("not a version")).toBe(false);
  });

  it("installNeeded: no node_modules, or a stamp that is not the lockfile's hash", () => {
    const table: Array<[{ nodeModulesExists: boolean; stamp: string | null; lockHash: string }, boolean]> = [
      [{ nodeModulesExists: false, stamp: "abc", lockHash: "abc" }, true],
      [{ nodeModulesExists: true, stamp: "", lockHash: "abc" }, true],
      [{ nodeModulesExists: true, stamp: null, lockHash: "abc" }, true],
      [{ nodeModulesExists: true, stamp: "abd", lockHash: "abc" }, true],
      [{ nodeModulesExists: true, stamp: "abc", lockHash: "abc" }, false],
      [{ nodeModulesExists: true, stamp: "abc\n", lockHash: "abc" }, false],
    ];
    for (const [input, want] of table) expect(L.installNeeded(input), JSON.stringify(input)).toBe(want);
  });

  it("buildStale: the five conditions", () => {
    const fresh = { webIndexExists: true, serverMainExists: true, stamp: { lock_sha256: "L", newest_source_mtime_ms: 100 }, lockHash: "L", newestSourceMtimeMs: 100 };
    expect(L.buildStale(fresh)).toBe(false);
    expect(L.buildStale({ ...fresh, newestSourceMtimeMs: 99 })).toBe(false);
    expect(L.buildStale({ ...fresh, webIndexExists: false })).toBe(true); // 1. dist/web/index.html missing
    expect(L.buildStale({ ...fresh, serverMainExists: false })).toBe(true); // 2. dist/server/server/main.js missing
    expect(L.buildStale({ ...fresh, stamp: null })).toBe(true); // 3. stamp missing / unparsable
    expect(L.buildStale({ ...fresh, stamp: { lock_sha256: "L" } })).toBe(true); // 3. stamp without a source mtime
    expect(L.buildStale({ ...fresh, lockHash: "M" })).toBe(true); // 4. the lockfile changed
    expect(L.buildStale({ ...fresh, newestSourceMtimeMs: 101 })).toBe(true); // 5. a source is newer than the build
  });

  it("locateNpm: npm_execpath wins; the Windows layout; the ../lib/node_modules layout; PATH last", () => {
    const has = (...paths: string[]) => (p: string) => paths.includes(p);
    const none = () => null;
    const win = { execPath: join("C:", "nodejs", "node.exe") };
    const winCli = join("C:", "nodejs", "node_modules", "npm", "bin", "npm-cli.js");
    const nix = { execPath: join("/opt", "node", "bin", "node") };
    const nixCli = join("/opt", "node", "bin", "..", "lib", "node_modules", "npm", "bin", "npm-cli.js");

    const execpath = L.locateNpm({ ...nix, env: { npm_execpath: "/x/npm-cli.js" }, exists: has("/x/npm-cli.js", nixCli), which: none });
    expect(execpath).toMatchObject({ cmd: nix.execPath, args: ["/x/npm-cli.js"], shell: false });

    // npm_execpath set but missing on disk is skipped
    const stale = L.locateNpm({ ...nix, env: { npm_execpath: "/gone/npm-cli.js" }, exists: has(nixCli), which: none });
    expect(stale).toMatchObject({ cmd: nix.execPath, args: [nixCli], shell: false });

    expect(L.locateNpm({ ...win, env: {}, exists: has(winCli), which: none })).toMatchObject({ cmd: win.execPath, args: [winCli], shell: false });
    expect(L.locateNpm({ ...nix, env: {}, exists: has(nixCli), which: none })).toMatchObject({ cmd: nix.execPath, args: [nixCli], shell: false });

    // which("npm") resolved to its npm-cli.js (a sibling of the bin script here), run by the Node that passed the check
    const pathCli = join("/usr", "share", "npm", "bin", "npm-cli.js");
    const viaWhich = L.locateNpm({ ...nix, env: {}, exists: has(pathCli), which: () => join("/usr", "share", "npm", "bin", "npm") });
    expect(viaWhich).toMatchObject({ cmd: nix.execPath, args: [pathCli], shell: false });

    // nothing found: `npm` on PATH with shell: true, labelled
    expect(L.locateNpm({ ...nix, env: {}, exists: () => false, which: none })).toEqual({ cmd: "npm", args: [], shell: true, label: "npm from PATH" });
  });

  it("browserCommand: open / cmd.exe start / xdg-open / null without a display", () => {
    const url = "http://127.0.0.1:4317";
    expect(L.browserCommand("darwin", {}, url)).toEqual(["open", [url]]);
    expect(L.browserCommand("win32", {}, url)).toEqual(["cmd.exe", ["/c", "start", "", url]]);
    expect(L.browserCommand("linux", { DISPLAY: ":0" }, url, () => null)).toEqual(["xdg-open", [url]]);
    expect(L.browserCommand("linux", { WAYLAND_DISPLAY: "wayland-0" }, url, () => null)).toEqual(["xdg-open", [url]]);
    expect(L.browserCommand("linux", { WSL_DISTRO_NAME: "Ubuntu" }, url, () => "/mnt/c/Windows/System32/cmd.exe")).toEqual(["cmd.exe", ["/c", "start", "", url]]);
    expect(L.browserCommand("linux", {}, url, () => null)).toBeNull();
    expect(L.browserCommand("linux", { WSL_DISTRO_NAME: "Ubuntu" }, url, () => null)).toBeNull();
    expect(L.browserCommand("freebsd", { DISPLAY: ":0" }, url, () => null)).toBeNull();
  });

  describe("probePort", () => {
    let exmap: Server;
    let html: Server;
    const urlOf = (s: Server) => `http://127.0.0.1:${(s.address() as AddressInfo).port}`;
    beforeAll(async () => {
      exmap = createServer((_req, res) => {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ app: "exmap", version: "0.1.0", ok: true }));
      });
      html = createServer((_req, res) => {
        res.writeHead(200, { "content-type": "text/html" });
        res.end("<!doctype html><title>something else</title>");
      });
      await Promise.all([exmap, html].map((s) => new Promise<void>((r) => s.listen(0, "127.0.0.1", () => r()))));
    });
    afterAll(async () => {
      await Promise.all([exmap, html].map((s) => new Promise<void>((r) => s.close(() => r()))));
    });

    it("an exmap health body → exmap; HTML → other; a closed port → free", async () => {
      expect(await L.probePort(urlOf(exmap))).toBe("exmap");
      expect(await L.probePort(urlOf(html))).toBe("other");
      const closed = createServer();
      await new Promise<void>((r) => closed.listen(0, "127.0.0.1", () => r()));
      const closedUrl = urlOf(closed);
      await new Promise<void>((r) => closed.close(() => r()));
      expect(await L.probePort(closedUrl)).toBe("free");
    });

    it("a port held by a program that does not answer HTTP (silent, or resetting the connection) → other, and the launcher exits 3 (review finding)", async () => {
      const net = await import("node:net");
      const { spawn } = await import("node:child_process");
      const held: import("node:net").Server[] = [];
      const listen = (onConn: (s: import("node:net").Socket) => void) => new Promise<number>((r) => {
        const srv = net.createServer(onConn);
        held.push(srv);
        srv.listen(0, "127.0.0.1", () => r((srv.address() as AddressInfo).port));
      });
      const sockets: import("node:net").Socket[] = [];
      const silent = await listen((sock) => { sockets.push(sock); });
      const reset = await listen((sock) => sock.destroy());
      try {
        expect(await L.probePort(`http://127.0.0.1:${silent}`, fetch, 300)).toBe("other");
        expect(await L.probePort(`http://127.0.0.1:${reset}`)).toBe("other");
        const home = mkdtempSync(join(tmpdir(), "exmap-launcher-port-"));
        try {
          const child = spawn(process.execPath, [join(ROOT, "bin", "exmap.mjs"), "--no-install", "--no-build"], {
            env: { ...process.env, EXMAP_NO_OPEN: "1", EXMAP_HOME: home, EXMAP_PORT: String(reset) }, stdio: ["ignore", "pipe", "pipe"],
          });
          let err = "";
          child.stderr.on("data", (d: Buffer) => { err += d.toString(); });
          const code = await new Promise<number | null>((r) => child.on("exit", r));
          expect(code).toBe(3);
          expect(err).toContain(`port ${reset} is in use by another program; set EXMAP_PORT or pass --port`);
          expect(err).not.toContain("EADDRINUSE");
        } finally {
          rmSync(home, { recursive: true, force: true });
        }
      } finally {
        for (const sock of sockets) sock.destroy();
        await Promise.all(held.map((srv) => new Promise<void>((r) => srv.close(() => r()))));
      }
    }, 20_000);
  });
});

describe("scripts/install-stamp.mjs", () => {
  it("writes node_modules/.exmap-install-stamp = sha256(package-lock.json)", () => {
    const dir = mkdtempSync(join(tmpdir(), "exmap-stamp-"));
    try {
      mkdirSync(join(dir, "scripts"));
      copyFileSync(join(ROOT, "scripts", "install-stamp.mjs"), join(dir, "scripts", "install-stamp.mjs"));
      const lock = JSON.stringify({ name: "exmap", lockfileVersion: 3, packages: {} }, null, 2) + "\n";
      writeFileSync(join(dir, "package-lock.json"), lock);
      const r = spawnSync(process.execPath, [join(dir, "scripts", "install-stamp.mjs")], { cwd: dir, encoding: "utf8" });
      expect(r.status, r.stderr).toBe(0);
      const want = createHash("sha256").update(lock).digest("hex");
      expect(readFileSync(join(dir, "node_modules", ".exmap-install-stamp"), "utf8").trim()).toBe(want);
      // and the real lockfile's stamp is what the launcher compares against
      const real = createHash("sha256").update(readFileSync(join(ROOT, "package-lock.json"))).digest("hex");
      expect(readFileSync(join(ROOT, "node_modules", ".exmap-install-stamp"), "utf8").trim()).toBe(real);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
