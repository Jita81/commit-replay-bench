// exmap/tests/unit/web/setup.ts — the jsdom project's setup (design §13): jest-dom matchers; stubs for WebSocket,
// matchMedia and crypto.randomUUID, which jsdom lacks or implements partially.
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { randomUUID } from "node:crypto";

type Listener = (ev: unknown) => void;

/** A WebSocket that never connects; tests that need traffic replace it with their own fake. */
export class StubWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: StubWebSocket[] = [];
  readonly url: string;
  readyState = StubWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: Listener | null = null;
  onmessage: Listener | null = null;
  onclose: Listener | null = null;
  onerror: Listener | null = null;
  private listeners = new Map<string, Set<Listener>>();
  constructor(url: string | URL) {
    this.url = String(url);
    StubWebSocket.instances.push(this);
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.readyState = StubWebSocket.CLOSED;
  }
  addEventListener(type: string, fn: Listener): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(fn);
  }
  removeEventListener(type: string, fn: Listener): void {
    this.listeners.get(type)?.delete(fn);
  }
  dispatchEvent(ev: { type: string }): boolean {
    for (const fn of this.listeners.get(ev.type) ?? []) fn(ev);
    return true;
  }
}

vi.stubGlobal("WebSocket", StubWebSocket);

if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

if (typeof globalThis.crypto?.randomUUID !== "function") {
  Object.defineProperty(globalThis.crypto, "randomUUID", { value: () => randomUUID(), configurable: true });
}

afterEach(() => {
  cleanup();
  StubWebSocket.instances = [];
});
