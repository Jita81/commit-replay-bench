// exmap/src/web/SessionScreen.tsx — the session screen (design §10.1): header, chain banner, the capture/replay strip,
// the three panes (tabs below 1024 px), the drawers, settings, toasts; the SessionStore, the audio controller, the
// replay driver and the window.__exmap hooks are created here, once per session id.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { select } from "../core/index.js";
import type { ConfigResponse, SessionSummary } from "../core/types.js";
import { ApiClient, ApiError } from "./api/client.js";
import { createSessionClock } from "./audio/clock.js";
import { HttpUtteranceSink } from "./audio/pipeline/sink.js";
import { parseReplayFixture } from "./audio/providers/replay.js";
import { SpeakerStore } from "./audio/speakers.js";
import { browserStorage } from "./audio/settings.js";
import type { ReplaySpeed } from "./audio/types.js";
import { loadAudioModule, type AudioControllerLike, type AudioModule } from "./audioContract.js";
import { CaptureStrip, ManualDock } from "./AudioStrip.js";
import { Board } from "./components/Board.js";
import { ChainBanner } from "./components/ChainBanner.js";
import { ExportDrawer } from "./components/ExportDrawer.js";
import { Header } from "./components/Header.js";
import { ProposalTray } from "./components/ProposalTray.js";
import { ReviewDrawer } from "./components/ReviewDrawer.js";
import { SettingsDialog } from "./components/SettingsDialog.js";
import { Toast } from "./components/Toast.js";
import { Transcript } from "./components/Transcript.js";
import { sha256 } from "./hash.js";
import { RecordingSink, ReplayDriver, ledgerSettled } from "./replay/driver.js";
import { SessionStore } from "./store/sessionStore.js";
import { SessionEnv, type ToastMessage } from "./store/useSession.js";
import { installTestHooks, removeTestHooks, replayHooks } from "./testHooks.js";

export interface SessionScreenProps {
  api: ApiClient;
  sessionId: string;
  userName: string;
  /** False until GET /api/settings answered: the SpeakerStore takes the user's name as the microphone's default label. */
  settingsLoaded?: boolean;
  onSaveName: (name: string) => Promise<void>;
  config: ConfigResponse | null;
  refreshConfig: () => void;
  testHooks: boolean;
  replay: { name: string; speed: ReplaySpeed; autostart: boolean } | null;
  onBack: () => void;
}

export function parseSpeed(raw: string | null): ReplaySpeed {
  if (raw === "instant") return "instant";
  const n = Number(raw);
  return n === 0.5 || n === 2 || n === 4 ? n : 1;
}

function useMediaQuery(query: string): boolean {
  const get = () => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query).matches : true);
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const on = () => setMatches(mql.matches);
    on();
    mql.addEventListener?.("change", on);
    return () => mql.removeEventListener?.("change", on);
  }, [query]);
  return matches;
}

export function SessionScreen(props: SessionScreenProps) {
  const { api, sessionId, userName, settingsLoaded = true, onSaveName, config, refreshConfig, testHooks, replay, onBack } = props;
  const sessionApi = useMemo(() => api.session(sessionId), [api, sessionId]);
  const store = useMemo(
    () =>
      new SessionStore({
        sessionId,
        sha256,
        wsUrl: (after) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/sessions/${encodeURIComponent(sessionId)}/stream?after=${after}`,
      }),
    [sessionId],
  );
  const status = useSyncExternalStore(store.subscribe, store.getStatus, store.getStatus);
  const [meta, setMeta] = useState<SessionSummary | null>(null);
  const [metaError, setMetaError] = useState<ApiError | null>(null);
  const [audio, setAudio] = useState<{ mod: AudioModule; controller: AudioControllerLike } | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [drawer, setDrawer] = useState<"review" | "export" | "settings" | null>(null);
  const [settingsPrompt, setSettingsPrompt] = useState<string | null>(null);
  const [tab, setTab] = useState<"transcript" | "map" | "proposals">("map");
  const wide = useMediaQuery("(min-width: 1024px)");
  const opener = useRef<HTMLElement | null>(null);
  const pendingWork = useCallback(() => audio?.controller.pendingWork() ?? 0, [audio]);

  // 1. the store
  useEffect(() => {
    store.connect();
    return () => store.dispose();
  }, [store]);

  // 2. the session meta (title, created_at for the audio clock)
  useEffect(() => {
    let cancelled = false;
    sessionApi
      .get()
      .then((d) => {
        if (!cancelled) setMeta(d.session);
      })
      .catch((e: unknown) => {
        if (!cancelled) setMetaError(e instanceof ApiError ? e : new ApiError(0, { reason: "NETWORK", detail: e instanceof Error ? e.message : String(e) }));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionApi]);

  // 3. the audio controller, replay driver and test hooks, once the meta (the session clock) and the settings (the
  //    microphone's default speaker label) are known. With ?replay= the fixture is loaded before the hooks appear.
  useEffect(() => {
    if (!meta || !settingsLoaded) return;
    let cancelled = false;
    let controller: AudioControllerLike | null = null;
    (async () => {
      const mod = await loadAudioModule();
      if (cancelled) return;
      if (!mod.AudioController) {
        setAudioError(`the audio controller is not available (missing: ${mod.missing.join(", ")})`);
        return;
      }
      const sink = new RecordingSink(new HttpUtteranceSink({ baseUrl: "", sessionId }));
      try {
        controller = new mod.AudioController({
          sink,
          clock: createSessionClock(meta.created_at),
          speakers: new SpeakerStore({ userName: userName.trim() || null, storage: browserStorage("local"), sessionStorage: browserStorage("session") }),
          storage: browserStorage("local"),
          autostartRequested: replay?.autostart ?? false,
        });
      } catch (e) {
        setAudioError(`the audio controller failed to start: ${e instanceof Error ? e.message : String(e)}`);
        return;
      }
      const ctrl = controller;
      setAudio({ mod, controller: ctrl });
      const ready = replay ? loadFixture(ctrl, replay.name) : Promise.resolve(true);
      const driver = new ReplayDriver({
        controller: ctrl,
        postQueueIdle: () => ctrl.idle(),
        settled: ledgerSettled(store, sink),
        ready: ready.then(() => undefined),
      });
      const loaded = await ready;
      if (cancelled) return;
      if (testHooks) {
        installTestHooks({
          audio: {
            state: () => ctrl.getState(),
            postQueueIdle: () => ctrl.idle(),
            segmentsClosed: () => {
              const st = ctrl.getState();
              return { me: st.lanes.me.segmentsClosed, remote: st.lanes.remote.segmentsClosed };
            },
            pendingWork: () => ctrl.pendingWork(),
          },
          replay: replayHooks(driver),
          store: { state: () => store.getState(), status: () => store.getStatus(), settled: ledgerSettled(store, sink) },
        });
      }
      if (replay && loaded && replay.autostart) void ctrl.playReplay(replay.speed);
    })();
    return () => {
      cancelled = true;
      if (testHooks) removeTestHooks();
      controller?.dispose();
    };

    async function loadFixture(ctrl: AudioControllerLike, name: string): Promise<boolean> {
      try {
        const index = (await (await fetch("/replay/index.json")).json()) as { fixtures: Array<{ name: string; file: string }> };
        const entry = index.fixtures.find((f) => f.name === name);
        if (!entry) throw new Error(`no replay fixture named ${name} in /replay/index.json`);
        const fixture = parseReplayFixture(await (await fetch(`/replay/${entry.file}`)).json());
        if (cancelled) return false;
        ctrl.loadReplay(fixture, name);
        return true;
      } catch (e) {
        setToasts((t) => [...t, { id: Date.now(), kind: "error", text: `Replay fixture not loaded: ${e instanceof Error ? e.message : String(e)}` }]);
        return false;
      }
    }
    // userName is read once at controller creation (the SpeakerStore's initial label); later changes go through
    // effect 3b below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta, settingsLoaded, sessionId, store, testHooks, replay]);

  // 3b. a name set after the controller exists becomes the microphone's label when the person has not assigned one
  useEffect(() => {
    const c = audio?.controller;
    const name = userName.trim();
    if (!c || !name) return;
    if (c.getState().speakers.me === null) c.setSpeaker("me", name);
  }, [audio, userName]);

  // 4. a fallback classification refreshes /api/config so the chip and the notice follow it
  const fallbacks = select.counts(store.getState()).fallbacks;
  useEffect(() => {
    if (fallbacks > 0) refreshConfig();
  }, [fallbacks, refreshConfig]);

  const onToast = useCallback((t: ToastMessage) => setToasts((prev) => [...prev.slice(-4), t]), []);
  const onNeedActor = useCallback(() => {
    setSettingsPrompt("Set your name so the record says who did this");
    setDrawer("settings");
  }, []);
  const dismissToast = useCallback((id: number) => setToasts((prev) => prev.filter((t) => t.id !== id)), []);
  const openDrawer = (which: "review" | "export" | "settings") => {
    opener.current = document.activeElement as HTMLElement | null;
    if (which !== "settings") setSettingsPrompt(null);
    setDrawer(which);
  };
  const closeDrawer = () => {
    setDrawer(null);
    setSettingsPrompt(null);
  };

  if (metaError) {
    return (
      <main className="p-6 text-slate-900" data-testid="session-error">
        <h1 className="text-xl font-semibold">Example Map Live</h1>
        <p role="alert" className="mt-2 text-sm text-red-800">
          Session {sessionId}: {metaError.reason} — {metaError.detail}
        </p>
        <button type="button" className="mt-3 rounded border border-slate-600 px-2 py-1 text-sm" onClick={onBack}>
          Back to sessions
        </button>
      </main>
    );
  }

  const controller = audio?.controller ?? null;
  const audioState = controller ? controller.getState() : null;
  const panes = {
    transcript: (
      <div className="flex h-full min-h-0 flex-col">
        <div className="min-h-0 grow">
          <Transcript />
        </div>
        <div className="border-t border-slate-300 p-2" data-testid="manual-dock">
          <ManualDock mod={audio?.mod ?? null} controller={controller} loadError={audioError} />
        </div>
      </div>
    ),
    map: <Board />,
    proposals: <ProposalTray lastError={config?.classifier.last_error ?? null} />,
  };

  return (
    <SessionEnv source={store} api={sessionApi} actor={userName} onNeedActor={onNeedActor} onToast={onToast} sessionTitle={meta?.title ?? ""}>
      <div className="flex h-screen flex-col bg-slate-50 text-slate-900">
        <Header status={status} config={config} onReview={() => openDrawer("review")} onExport={() => openDrawer("export")} onSettings={() => openDrawer("settings")} />
        <ChainBanner status={status} onReload={() => location.reload()} onBack={onBack} />
        <section aria-label="Capture and replay" className="border-b border-slate-300 bg-white px-4 py-1">
          <details open data-testid="capture-details">
            <summary className="cursor-pointer text-sm font-semibold">Capture and replay</summary>
            <div className="py-2">
              <CaptureStrip mod={audio?.mod ?? null} controller={controller} loadError={audioError} />
            </div>
          </details>
        </section>
        <main className="flex min-h-0 grow flex-col" aria-label="Session">
        {wide ? (
          <div className="grid min-h-0 grow grid-cols-[minmax(18rem,1fr)_minmax(0,2fr)_minmax(18rem,1fr)] gap-0 divide-x divide-slate-300">
            <div className="min-h-0 bg-white">{panes.transcript}</div>
            <div className="min-h-0">{panes.map}</div>
            <div className="min-h-0 bg-white">{panes.proposals}</div>
          </div>
        ) : (
          <div className="flex min-h-0 grow flex-col">
            <div role="tablist" aria-label="Panes" className="flex border-b border-slate-300 bg-white">
              {(["transcript", "map", "proposals"] as const).map((t) => (
                <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls={`pane-${t}`} className={`px-3 py-2 text-sm ${tab === t ? "border-b-2 border-slate-900 font-semibold" : ""}`} onClick={() => setTab(t)}>
                  {t === "transcript" ? "Transcript" : t === "map" ? "Map" : "Proposals"}
                </button>
              ))}
            </div>
            <div role="tabpanel" id={`pane-${tab}`} aria-labelledby={`tab-${tab}`} className="min-h-0 grow bg-white">
              {panes[tab]}
            </div>
          </div>
        )}
        </main>
        <ReviewDrawer open={drawer === "review"} onClose={closeDrawer} pendingWork={pendingWork} returnFocusTo={opener.current} />
        <ExportDrawer open={drawer === "export"} onClose={closeDrawer} returnFocusTo={opener.current} />
        <SettingsDialog
          open={drawer === "settings"}
          onClose={closeDrawer}
          userName={userName}
          onSaveName={async (name) => {
            await onSaveName(name);
            setSettingsPrompt(null);
          }}
          config={config}
          prompt={settingsPrompt}
          audio={
            controller && audioState
              ? {
                  settings: audioState.settings,
                  update: (patch) => controller.updateSettings(patch),
                  locked: Object.values(audioState.lanes).some((l) => l.state === "live" || l.state === "requesting"),
                }
              : null
          }
          returnFocusTo={opener.current}
        />
        <Toast toasts={toasts} onDismiss={dismissToast} />
      </div>
    </SessionEnv>
  );
}
