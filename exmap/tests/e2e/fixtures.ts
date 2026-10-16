// exmap/tests/e2e/fixtures.ts — design §13: a worker-scoped `server` fixture that spawns the built server
// (dist/server/server/main.js) on a temp EXMAP_HOME with EXMAP_PORT=0 and EXMAP_CLASSIFIER=rules.v1 (so a developer's
// key cannot change the journey), reads its listening line, and provides baseURL. Teardown: SIGTERM, wait for exit,
// assert server.lock is gone, remove the home. Plus the helpers the specs share.
import { test as base, expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const SERVER_MAIN = join(ROOT, "dist", "server", "server", "main.js");
const LISTENING = /exmap listening on (http:\/\/127\.0\.0\.1:\d+)/;

export interface ServerHandle {
  baseURL: string;
  home: string;
  child: ChildProcess;
}

export interface FixtureUtterance {
  label: string;
  atMs: number;
  lane: "remote" | "me";
  speaker: string;
  text: string;
}

export interface FixtureFile {
  version: number;
  title: string;
  story?: string;
  speakers?: Partial<Record<"remote" | "me", string>>;
  utterances: FixtureUtterance[];
  ui?: unknown[];
}

/** The parsed conversation.v1.json (the demo fixture). */
export const fixture: FixtureFile = JSON.parse(readFileSync(join(ROOT, "src", "web", "public", "replay", "conversation.v1.json"), "utf8"));

function startServer(home: string): Promise<ServerHandle> {
  return new Promise((resolve, reject) => {
    if (!existsSync(SERVER_MAIN)) {
      reject(new Error(`${SERVER_MAIN} is missing; run npm run build first`));
      return;
    }
    const child = spawn(process.execPath, [SERVER_MAIN], {
      cwd: ROOT,
      env: { ...process.env, EXMAP_HOME: home, EXMAP_PORT: "0", EXMAP_CLASSIFIER: "rules.v1", EXMAP_NO_OPEN: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`server did not print its listening line within 30 s\nstdout: ${out}\nstderr: ${err}`));
    }, 30_000);
    child.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString();
      const m = LISTENING.exec(out);
      if (m && m[1]) {
        clearTimeout(timer);
        resolve({ baseURL: m[1], home, child });
      }
    });
    child.stderr.on("data", (chunk: Buffer) => {
      err += chunk.toString();
    });
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      reject(new Error(`server exited before listening (${code ?? signal})\nstdout: ${out}\nstderr: ${err}`));
    });
  });
}

async function stopServer(handle: ServerHandle): Promise<void> {
  const { child, home } = handle;
  if (child.exitCode === null && child.signalCode === null) {
    const exited = new Promise<void>((resolve) => child.once("exit", () => resolve()));
    child.kill("SIGTERM");
    const timeout = new Promise<"timeout">((resolve) => setTimeout(() => resolve("timeout"), 10_000));
    if ((await Promise.race([exited, timeout])) === "timeout") {
      child.kill("SIGKILL");
      await exited;
    }
  }
  expect(existsSync(join(home, "server.lock")), "server.lock must be removed on close").toBe(false);
  await rm(home, { recursive: true, force: true });
}

export const test = base.extend<Record<never, never>, { server: ServerHandle }>({
  server: [
    async ({}, use) => {
      const home = await mkdtemp(join(tmpdir(), "exmap-e2e-"));
      const handle = await startServer(home);
      await use(handle);
      await stopServer(handle);
    },
    { scope: "worker" },
  ],
  baseURL: async ({ server }, use) => {
    await use(server.baseURL);
  },
});

export { expect };

/* ───── helpers ───── */

export async function setName(request: APIRequestContext, name: string): Promise<void> {
  const res = await request.put("/api/settings", { data: { user_name: name } });
  expect(res.ok(), `PUT /api/settings -> ${res.status()}`).toBeTruthy();
}

export async function createSession(request: APIRequestContext, opts: { title: string; story?: string; actor?: string }): Promise<string> {
  const res = await request.post("/api/sessions", { data: opts });
  expect(res.status(), `POST /api/sessions -> ${res.status()}`).toBe(201);
  const body = (await res.json()) as { session: { id: string } };
  return body.session.id;
}

/** Opens the session screen; always appends &testhooks=1 so window.__exmap exists. */
export async function openSession(page: Page, id: string, extraQuery = ""): Promise<void> {
  const extra = extraQuery ? `&${extraQuery.replace(/^[?&]/, "")}` : "";
  await page.goto(`/?session=${encodeURIComponent(id)}${extra}&testhooks=1`);
}

interface ExmapTestHooks {
  replay: { playUntil(label: string | number): Promise<void>; skip(label: string | number): Promise<void>; playAll(): Promise<void>; position: number };
}

export async function playUntil(page: Page, label: string): Promise<void> {
  await page.evaluate((l) => (window as unknown as { __exmap: ExmapTestHooks }).__exmap.replay.playUntil(l), label);
}

export async function skip(page: Page, label: string): Promise<void> {
  await page.evaluate((l) => (window as unknown as { __exmap: ExmapTestHooks }).__exmap.replay.skip(l), label);
}

/** A card in the kind's column located by a substring of its text, never by ordinal. */
export function cardByText(page: Page, kind: "story" | "rule" | "example" | "question", substring: string): Locator {
  return page.getByTestId(`column-${kind}`).locator('[data-testid^="card-"]', { hasText: substring }).first();
}
