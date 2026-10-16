// tests/e2e/launcher.spec.ts — TEST-PLAN §8.5 (serial, `request` only): the one-command launcher (bin/exmap.mjs) starts
// the built server, answers health, a second launcher on the same port reports "already running" and exits 0, SIGTERM
// stops the first cleanly and removes server.lock, and with the stamps matching it neither installs nor builds.
// It runs after `npm run build` (npm run e2e), so dist/ and both stamps are fresh.
import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const LAUNCHER = join(ROOT, "bin", "exmap.mjs");
const LISTENING = /exmap listening on (http:\/\/127\.0\.0\.1:(\d+))/;

interface Run { child: ChildProcess; out: () => string; err: () => string; exit: Promise<number | null> }

function launch(args: string[], home: string): Run {
  const env: NodeJS.ProcessEnv = { ...process.env, EXMAP_CLASSIFIER: "rules.v1", EXMAP_NO_OPEN: "1" };
  delete env.EXMAP_PORT; // --port decides
  delete env.EXMAP_HOME; // --home decides
  const child = spawn(process.execPath, [LAUNCHER, "--no-open", ...args, "--home", home], {
    cwd: ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let out = "";
  let err = "";
  child.stdout!.on("data", (c: Buffer) => (out += c.toString()));
  child.stderr!.on("data", (c: Buffer) => (err += c.toString()));
  const exit = new Promise<number | null>((resolve) => child.once("exit", (code) => resolve(code)));
  return { child, out: () => out, err: () => err, exit };
}

async function waitForLine(run: Run, re: RegExp, timeoutMs: number): Promise<RegExpExecArray> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const m = re.exec(run.out());
    if (m) return m;
    if (run.child.exitCode !== null) throw new Error(`launcher exited ${run.child.exitCode} before printing ${re}\nstdout: ${run.out()}\nstderr: ${run.err()}`);
    if (Date.now() > deadline) throw new Error(`no ${re} within ${timeoutMs} ms\nstdout: ${run.out()}\nstderr: ${run.err()}`);
    await new Promise((r) => setTimeout(r, 50));
  }
}

test.describe.configure({ mode: "serial" });

test.describe("launcher", () => {
  let home = "";
  let home2 = "";
  let first: Run | null = null;

  test.beforeAll(async () => {
    home = await mkdtemp(join(tmpdir(), "exmap-launcher-"));
    home2 = await mkdtemp(join(tmpdir(), "exmap-launcher2-"));
  });

  test.afterAll(async () => {
    if (first && first.child.exitCode === null) {
      first.child.kill("SIGKILL");
      await first.exit;
    }
    await rm(home, { recursive: true, force: true });
    await rm(home2, { recursive: true, force: true });
  });

  test("starts, answers health, refuses to start twice on one port, stops on SIGTERM, and installs/builds nothing", async ({ request }) => {
    first = launch(["--port", "0"], home);
    const m = await waitForLine(first, LISTENING, 30_000);
    const url = m[1]!;
    const port = m[2]!;

    const health = await request.get(`${url}/api/health`);
    expect(health.status()).toBe(200);
    expect(((await health.json()) as { app: string }).app).toBe("exmap");
    expect(existsSync(join(home, "server.lock"))).toBe(true);

    // a second launcher on that port with another home finds exmap there and exits 0
    const second = launch(["--port", port], home2);
    expect(await second.exit).toBe(0);
    expect(second.out()).toContain(`exmap is already running at http://127.0.0.1:${port}`);
    expect(existsSync(join(home2, "server.lock"))).toBe(false);

    // SIGTERM: exit 0 within 5 s, server.lock removed
    const t0 = Date.now();
    first.child.kill("SIGTERM");
    const code = await Promise.race([first.exit, new Promise<"timeout">((r) => setTimeout(() => r("timeout"), 5_000))]);
    expect(code).toBe(0);
    expect(Date.now() - t0).toBeLessThan(5_000);
    expect(existsSync(join(home, "server.lock"))).toBe(false);

    // idempotency: the install and build stamps matched, so neither step ran
    for (const run of [first, second]) {
      const all = run.out() + run.err();
      expect(all).not.toMatch(/npm install|installing packages/i);
      expect(all).not.toMatch(/building/i);
    }
  });
});
