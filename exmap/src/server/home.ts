// exmap/src/server/home.ts — ExmapHome: paths, settings.json (atomic write), server.lock acquire/complete/release (design §9).
// Step-zero: ensureHomeDir() and HomeLockedError are real; ExmapHome is a stub.
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/** Thrown by acquireHomeLock when another live exmap owns the home; the launcher maps it to exit 6. */
export class HomeLockedError extends Error {
  readonly pid: number;
  readonly port: number | null;
  readonly url: string | null;
  constructor(info: { pid: number; port: number | null }) {
    super(info.port ? `another exmap is already using this home at http://127.0.0.1:${info.port}` : "another exmap is starting on this home");
    this.name = "HomeLockedError";
    this.pid = info.pid;
    this.port = info.port;
    this.url = info.port ? `http://127.0.0.1:${info.port}` : null;
  }
}

/** Creates EXMAP_HOME (0o700) and its sessions/ directory; idempotent. */
export function ensureHomeDir(home: string): void {
  mkdirSync(home, { recursive: true, mode: 0o700 });
  mkdirSync(join(home, "sessions"), { recursive: true, mode: 0o700 });
}

export class ExmapHome {
  readonly root: string;
  constructor(root: string) {
    this.root = root;
  }
  get settingsPath(): string {
    return join(this.root, "settings.json");
  }
  get lockPath(): string {
    return join(this.root, "server.lock");
  }
  sessionDir(id: string): string {
    return join(this.root, "sessions", id);
  }
  readSettings(): { user_name: string } {
    throw new Error("not implemented: ExmapHome.readSettings");
  }
  writeSettings(settings: { user_name: string }): void {
    void settings;
    throw new Error("not implemented: ExmapHome.writeSettings");
  }
  acquireLock(version: string): void {
    void version;
    throw new Error("not implemented: ExmapHome.acquireLock");
  }
  completeLock(port: number): void {
    void port;
    throw new Error("not implemented: ExmapHome.completeLock");
  }
  releaseLock(): void {
    throw new Error("not implemented: ExmapHome.releaseLock");
  }
}
