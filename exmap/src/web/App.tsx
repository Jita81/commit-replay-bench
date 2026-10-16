// exmap/src/web/App.tsx — one screen, no router (design §10.1). `?session=<id>` opens the session screen; without it the
// SessionPicker. `?replay=<name>` without a session creates one first (title "Replay — <fixture title>", the fixture's
// story when a name is set) and rewrites the URL, keeping ?replay/&speed/&autostart and ?testhooks.
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ConfigResponse } from "../core/types.js";
import { ApiClient, ApiError } from "./api/client.js";
import { SessionPicker } from "./components/SessionPicker.js";
import { SettingsDialog } from "./components/SettingsDialog.js";
import { parseSpeed, SessionScreen } from "./SessionScreen.js";

export interface AppProps {
  testHooks?: boolean;
  api?: ApiClient;
  /** The page's query string; defaults to location.search. */
  search?: string;
}

function replaceQuery(params: URLSearchParams): void {
  const q = params.toString();
  history.replaceState(null, "", `${location.pathname}${q ? `?${q}` : ""}`);
}

export function App({ testHooks = false, api: injected, search }: AppProps) {
  const api = useMemo(() => injected ?? new ApiClient(""), [injected]);
  const [params] = useState(() => new URLSearchParams(search ?? (typeof location === "undefined" ? "" : location.search)));
  const [sessionId, setSessionId] = useState<string | null>(params.get("session"));
  const [userName, setUserName] = useState<string>("");
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [bootError, setBootError] = useState<string | null>(null);
  const replayName = params.get("replay");
  const replay = useMemo(() => (replayName ? { name: replayName, speed: parseSpeed(params.get("speed")), autostart: params.get("autostart") === "1" } : null), [replayName, params]);

  const refreshConfig = useCallback(() => {
    api
      .config()
      .then(setConfig)
      .catch(() => {
        /* the chip then says the config is not loaded */
      });
  }, [api]);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setUserName(s.user_name ?? ""))
      .catch(() => {
        /* no name until the server answers */
      });
    refreshConfig();
    const handle = setInterval(refreshConfig, 30_000);
    return () => clearInterval(handle);
  }, [api, refreshConfig]);

  // ?replay=<name> without ?session=: create a session first, then rewrite the URL.
  const [nameKnown, setNameKnown] = useState(false);
  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setUserName(s.user_name ?? "");
        setNameKnown(true);
      })
      .catch(() => setNameKnown(true));
  }, [api]);
  useEffect(() => {
    if (sessionId || !replay || !nameKnown) return;
    let cancelled = false;
    (async () => {
      try {
        const index = (await (await fetch("/replay/index.json")).json()) as { fixtures: Array<{ name: string; file: string; title: string }> };
        const entry = index.fixtures.find((f) => f.name === replay.name);
        if (!entry) throw new Error(`no replay fixture named ${replay.name}`);
        const fixture = (await (await fetch(`/replay/${entry.file}`)).json()) as { title: string; story?: string };
        const body: { title: string; actor?: string; story?: string } = { title: `Replay — ${fixture.title}` };
        if (userName.trim() && fixture.story) {
          body.story = fixture.story;
          body.actor = userName.trim();
        }
        const r = await api.createSession(body);
        if (cancelled) return;
        params.set("session", r.session.id);
        replaceQuery(params);
        setSessionId(r.session.id);
      } catch (e) {
        if (!cancelled) setBootError(e instanceof ApiError ? `${e.reason}: ${e.detail}` : e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, replay, nameKnown, userName, api, params]);

  const saveName = useCallback(
    async (name: string) => {
      const r = await api.putSettings(name);
      setUserName(r.user_name);
    },
    [api],
  );

  const openSession = (id: string) => {
    params.set("session", id);
    replaceQuery(params);
    setSessionId(id);
  };
  const back = () => {
    params.delete("session");
    params.delete("replay");
    params.delete("autostart");
    replaceQuery(params);
    setSessionId(null);
  };

  if (sessionId) {
    return (
      <SessionScreen
        key={sessionId}
        api={api}
        sessionId={sessionId}
        userName={userName}
        onSaveName={saveName}
        config={config}
        refreshConfig={refreshConfig}
        testHooks={testHooks}
        replay={replay}
        onBack={back}
      />
    );
  }
  if (replay && !bootError) {
    return (
      <main className="p-6 text-slate-900">
        <h1 className="text-2xl font-semibold">Example Map Live</h1>
        <p className="mt-2 text-sm" role="status">
          Creating a session for the replay “{replay.name}”…
        </p>
      </main>
    );
  }
  return (
    <>
      <SessionPicker api={api} userName={userName} onOpen={openSession} onSettings={() => setSettingsOpen(true)} />
      {bootError ? (
        <p role="alert" className="mx-auto max-w-3xl px-6 text-sm text-red-800" data-testid="boot-error">
          {bootError}
        </p>
      ) : null}
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} userName={userName} onSaveName={saveName} config={config} />
    </>
  );
}

export default App;
