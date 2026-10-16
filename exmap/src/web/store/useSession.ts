// exmap/src/web/store/useSession.ts — useSession(), useDod(), useCounts(), useActor() (design §10.1) plus the contexts
// that carry the session's store, API and actor to the components. A test renders a component inside
// <SessionEnv source={staticSource(state)} api={fake} actor="Sam"> with no WebSocket at all.
import { createContext, createElement, useCallback, useContext, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { dodReport, select } from "../../core/index.js";
import type { Counts, DodReport, MapState } from "../../core/types.js";
import { ApiError, type SessionApi } from "../api/client.js";

/** What useSession() reads: the SessionStore, or a static snapshot in tests. */
export interface StateSource {
  getState(): MapState;
  subscribe(fn: () => void): () => void;
  /** The ledger seq of an event id when known (the SessionStore indexes every event it reduced). */
  eventSeq?(eventId: string): number | null;
}

export function staticSource(state: MapState): StateSource & { set(next: MapState): void } {
  let current = state;
  const subs = new Set<() => void>();
  return {
    getState: () => current,
    subscribe: (fn) => {
      subs.add(fn);
      return () => {
        subs.delete(fn);
      };
    },
    set: (next) => {
      current = next;
      for (const fn of [...subs]) fn();
    },
  };
}

export interface ToastMessage {
  id: number;
  kind: "info" | "error";
  text: string;
}

export interface ActorApi {
  /** settings.user_name; "" until set. */
  actor: string;
  /** The actor, or null after opening the settings dialog with "Set your name so the record says who did this". */
  requireActor(): string | null;
}

export interface SessionEnvValue {
  source: StateSource;
  api: SessionApi;
  actorApi: ActorApi;
  toast(text: string, kind?: ToastMessage["kind"]): void;
  sessionTitle: string;
}

const SessionEnvContext = createContext<SessionEnvValue | null>(null);

export interface SessionEnvProps {
  source: StateSource;
  api: SessionApi;
  actor: string;
  /** Opens the settings dialog with the "set your name" prompt; the default does nothing. */
  onNeedActor?: () => void;
  onToast?: (toast: ToastMessage) => void;
  sessionTitle?: string;
  children?: ReactNode;
}

let toastSeq = 0;

export function SessionEnv(props: SessionEnvProps): ReactNode {
  const { source, api, actor, onNeedActor, onToast, sessionTitle = "" } = props;
  const value = useMemo<SessionEnvValue>(
    () => ({
      source,
      api,
      sessionTitle,
      actorApi: {
        actor,
        requireActor: () => {
          if (actor.trim().length > 0) return actor;
          onNeedActor?.();
          return null;
        },
      },
      toast: (text, kind = "info") => onToast?.({ id: ++toastSeq, kind, text }),
    }),
    [source, api, actor, onNeedActor, onToast, sessionTitle],
  );
  return createElement(SessionEnvContext.Provider, { value }, props.children);
}

function env(): SessionEnvValue {
  const v = useContext(SessionEnvContext);
  if (!v) throw new Error("useSession() needs a <SessionEnv> above it");
  return v;
}

export function useSession(): MapState {
  const { source } = env();
  return useSyncExternalStore(source.subscribe, source.getState, source.getState);
}

export function useDod(): DodReport {
  const state = useSession();
  return useMemo(() => dodReport(state), [state]);
}

export function useCounts(): Counts {
  const state = useSession();
  return useMemo(() => select.counts(state), [state]);
}

export function useActor(): ActorApi {
  return env().actorApi;
}

/** event id → ledger seq; falls back to the revisions the state carries, else null (the UI then shows the id). */
export function useEventSeq(): (eventId: string) => number | null {
  const { source } = env();
  const state = useSession();
  return useCallback(
    (eventId: string) => {
      const known = source.eventSeq?.(eventId);
      if (known !== null && known !== undefined) return known;
      for (const r of state.revisions) if (r.event_id === eventId) return r.seq;
      return null;
    },
    [source, state],
  );
}

export function useApi(): SessionApi {
  return env().api;
}

export function useToast(): SessionEnvValue["toast"] {
  return env().toast;
}

export function useSessionTitle(): string {
  return env().sessionTitle;
}

/**
 * One human act: refuses without a name (opens settings), shows "pending…" on the clicked control until the server
 * answers, and turns a refusal into a toast naming the server's reason. Returns the response or null.
 */
export function useAct(): {
  pending: boolean;
  error: ApiError | null;
  run<T>(fn: (actor: string) => Promise<T>, opts?: { quiet?: boolean }): Promise<T | null>;
  clearError(): void;
} {
  const { actorApi, toast } = env();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const run = useCallback(
    async <T,>(fn: (actor: string) => Promise<T>, opts?: { quiet?: boolean }): Promise<T | null> => {
      const actor = actorApi.requireActor();
      if (actor === null) return null;
      setPending(true);
      setError(null);
      try {
        return await fn(actor);
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, { reason: "NETWORK", detail: e instanceof Error ? e.message : String(e) });
        setError(err);
        if (!opts?.quiet) toast(`${err.reason}: ${err.detail}`, "error");
        return null;
      } finally {
        setPending(false);
      }
    },
    [actorApi, toast],
  );
  const clearError = useCallback(() => setError(null), []);
  return { pending, error, run, clearError };
}
