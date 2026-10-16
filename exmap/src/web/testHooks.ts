// exmap/src/web/testHooks.ts — window.__exmap (design §7.7, §10.9): present only in dev builds or with ?testhooks=1,
// so a production page without the flag exposes nothing.
import type { AudioState } from "./audio/types.js";
import type { ReplayDriver } from "./replay/driver.js";

export interface ExmapTestHooks {
  audio: {
    state(): AudioState | null;
    postQueueIdle(): Promise<void>;
    segmentsClosed(): { me: number; remote: number };
    pendingWork(): number;
  };
  replay: {
    playUntil(label: string | number): Promise<void>;
    skip(label: string | number): Promise<void>;
    playAll(): Promise<void>;
    readonly position: number;
  };
  store?: { state(): unknown; status(): unknown };
}

declare global {
  interface Window {
    __exmap?: ExmapTestHooks;
  }
}

export function testHooksEnabled(search: string = typeof location === "undefined" ? "" : location.search): boolean {
  if (new URLSearchParams(search).get("testhooks") === "1") return true;
  const meta = import.meta as unknown as { env?: { DEV?: boolean } };
  return Boolean(meta.env?.DEV);
}

export function replayHooks(driver: ReplayDriver): ExmapTestHooks["replay"] {
  return {
    playUntil: (label) => driver.playUntil(label),
    skip: (label) => driver.skip(label),
    playAll: () => driver.playAll(),
    get position() {
      return driver.position;
    },
  };
}

export function installTestHooks(hooks: ExmapTestHooks): void {
  window.__exmap = hooks;
}

export function removeTestHooks(): void {
  delete window.__exmap;
}
