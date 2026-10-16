// exmap/src/server/home.ts — ExmapHome: paths, settings.json (atomic write), server.lock acquire/complete/release (design §9).
// The lock is taken with an exclusive create and written + fsynced in the same step (the file is never empty); after
// listen it is rewritten atomically with the port. A lock whose pid is dead, or that stays unparsable for 200 ms, is stale.
import fs from "node:fs";
import { join } from "node:path";

/** Thrown by acquireLock when another live exmap owns the home; the launcher maps it to exit 6. */
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
  fs.mkdirSync(home, { recursive: true, mode: 0o700 });
  fs.mkdirSync(join(home, "sessions"), { recursive: true, mode: 0o700 });
}

export interface Settings {
  user_name: string;
}

export interface LockInfo {
  pid: number;
  started_at: string;
  version: string;
  port?: number;
}

/** Writes `path` atomically: `.tmp` + fsync + rename. */
export function writeFileAtomic(path: string, content: string): void {
  const tmp = `${path}.tmp`;
  const fd = fs.openSync(tmp, "w", 0o600);
  try {
    fs.writeFileSync(fd, content);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, path);
}

/** true when a process with this pid exists (kill(pid, 0) succeeds, or EPERM: it exists but is not ours). */
export function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return (e as NodeJS.ErrnoException).code === "EPERM";
  }
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

export class ExmapHome {
  readonly root: string;
  #lock: LockInfo | null = null;

  constructor(root: string) {
    this.root = root;
  }
  get settingsPath(): string {
    return join(this.root, "settings.json");
  }
  get lockPath(): string {
    return join(this.root, "server.lock");
  }
  get sessionsDir(): string {
    return join(this.root, "sessions");
  }
  sessionDir(id: string): string {
    return join(this.root, "sessions", id);
  }

  /** `{ user_name: "" }` until a name is set (a missing or unreadable file reads as unset). */
  readSettings(): Settings {
    try {
      const raw = JSON.parse(fs.readFileSync(this.settingsPath, "utf8")) as { user_name?: unknown };
      return { user_name: typeof raw.user_name === "string" ? raw.user_name : "" };
    } catch {
      return { user_name: "" };
    }
  }

  writeSettings(settings: Settings): void {
    ensureHomeDir(this.root);
    writeFileAtomic(this.settingsPath, JSON.stringify({ schema: "exmap.settings.v1", user_name: settings.user_name }, null, 2) + "\n");
  }

  /** The lock as written, or null when it is absent or unparsable. */
  readLock(): LockInfo | null {
    try {
      const raw = JSON.parse(fs.readFileSync(this.lockPath, "utf8")) as Partial<LockInfo>;
      if (typeof raw.pid !== "number" || !Number.isInteger(raw.pid) || raw.pid <= 0) return null;
      const info: LockInfo = { pid: raw.pid, started_at: String(raw.started_at ?? ""), version: String(raw.version ?? "") };
      if (typeof raw.port === "number") info.port = raw.port;
      return info;
    } catch {
      return null;
    }
  }

  get lockHeld(): boolean {
    return this.#lock !== null;
  }

  /**
   * Takes server.lock (design §9). A live owner → HomeLockedError { pid, port, url }. A stale lock (dead pid, or unparsable
   * twice 200 ms apart) is removed and the create retried once.
   */
  async acquireLock(version: string): Promise<void> {
    ensureHomeDir(this.root);
    for (let attempt = 0; attempt < 2; attempt++) {
      const info: LockInfo = { pid: process.pid, started_at: new Date().toISOString(), version };
      try {
        const fd = fs.openSync(this.lockPath, "wx", 0o600);
        try {
          fs.writeFileSync(fd, JSON.stringify(info) + "\n");
          fs.fsyncSync(fd);
        } finally {
          fs.closeSync(fd);
        }
        this.#lock = info;
        return;
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
      }
      let existing = this.readLock();
      if (existing === null) {
        await sleep(200);
        existing = this.readLock();
      }
      if (existing !== null && pidAlive(existing.pid)) throw new HomeLockedError({ pid: existing.pid, port: existing.port ?? null });
      if (attempt === 1) break;
      try {
        fs.unlinkSync(this.lockPath);
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      }
    }
    throw new Error(`could not take ${this.lockPath}: it was re-created while a stale lock was being removed`);
  }

  /** After listen: rewrites the lock atomically with the bound port. */
  completeLock(port: number): void {
    if (!this.#lock) return;
    this.#lock = { ...this.#lock, port };
    writeFileAtomic(this.lockPath, JSON.stringify(this.#lock) + "\n");
  }

  /** Removes the lock if it is still ours (same pid and started_at); idempotent. */
  releaseLock(): void {
    const mine = this.#lock;
    if (!mine) return;
    this.#lock = null;
    const current = this.readLock();
    if (current && (current.pid !== mine.pid || current.started_at !== mine.started_at)) return;
    try {
      fs.unlinkSync(this.lockPath);
    } catch {
      /* already gone */
    }
  }
}
