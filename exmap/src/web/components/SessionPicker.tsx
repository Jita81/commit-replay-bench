// exmap/src/web/components/SessionPicker.tsx — the landing screen (design §10.1): the sessions the server knows, newest
// first (a broken ledger is listed, named, and cannot be opened), a create form, and the same settings-open control as
// the header so a name can be set before any session exists.
import { useEffect, useState } from "react";
import type { SessionSummary } from "../../core/types.js";
import { ApiError, type ApiClient } from "../api/client.js";
import { hash8, timeOf } from "../format.js";

export interface SessionPickerProps {
  api: ApiClient;
  userName: string;
  onOpen: (id: string) => void;
  onSettings: () => void;
}

export function SessionPicker({ api, userName, onOpen, onSettings }: SessionPickerProps) {
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [story, setStory] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => {
    api
      .listSessions()
      .then((r) => {
        setSessions(r.sessions);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? `${e.reason}: ${e.detail}` : `Could not reach the server: ${e instanceof Error ? e.message : String(e)}`));
  };
  useEffect(load, [api]);

  const create = async () => {
    const t = title.trim();
    if (!t) return;
    setCreating(true);
    try {
      const body: { title: string; actor?: string; story?: string } = { title: t };
      if (story.trim() && userName.trim()) {
        body.story = story.trim();
        body.actor = userName.trim();
      }
      const r = await api.createSession(body);
      onOpen(r.session.id);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.reason}: ${e.detail}` : String(e));
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-6 text-slate-900" data-testid="session-picker">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Example Map Live</h1>
          <p className="mt-1 text-sm text-slate-700">A local-first, voice-driven requirements modeller with human verification.</p>
        </div>
        <button type="button" data-testid="settings-open" className="rounded border border-slate-500 px-2 py-1 text-sm" onClick={onSettings}>
          Settings{userName ? ` (${userName})` : " (no name set)"}
        </button>
      </header>
      <section aria-labelledby="new-session-heading" className="flex flex-col gap-2 rounded border border-slate-300 p-4">
        <h2 id="new-session-heading" className="text-lg font-semibold">
          New session
        </h2>
        <form
          className="flex flex-col gap-2 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <label className="flex flex-col gap-1">
            Title
            <input data-testid="new-session-title" className="rounded border border-slate-400 px-2 py-1" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            Story (optional; recorded as your first card{userName ? "" : " — set your name first"})
            <input data-testid="new-session-story" className="rounded border border-slate-400 px-2 py-1" value={story} onChange={(e) => setStory(e.target.value)} disabled={!userName} />
          </label>
          <button type="submit" data-testid="new-session-create" className="self-start rounded border border-slate-700 bg-slate-800 px-3 py-1 text-white disabled:opacity-50" disabled={creating || title.trim().length === 0}>
            Create and open
          </button>
        </form>
      </section>
      <section aria-labelledby="sessions-heading" className="flex flex-col gap-2">
        <h2 id="sessions-heading" className="text-lg font-semibold">
          Sessions
        </h2>
        {error ? (
          <p role="alert" className="text-sm text-red-800" data-testid="sessions-error">
            {error}{" "}
            <button type="button" className="underline" onClick={load}>
              Retry
            </button>
          </p>
        ) : null}
        {sessions === null && !error ? <p className="text-sm text-slate-700">Loading…</p> : null}
        {sessions && sessions.length === 0 ? <p className="text-sm text-slate-700">No sessions yet.</p> : null}
        <ul className="flex flex-col gap-2" data-testid="sessions-list">
          {(sessions ?? []).map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 rounded border border-slate-300 p-3 text-sm" data-testid={`session-${s.id}`}>
              <div className="flex grow flex-col">
                <span className="font-semibold">{s.title}</span>
                <span className="text-xs text-slate-700">
                  {timeOf(s.created_at)} · rev {s.revision.seq} · {hash8(s.revision.hash)} · {s.counts.utterances} utterances · {s.counts.cards_live} live cards ·{" "}
                  {s.human_verified ? "human verified" : "not verified"}
                </span>
                {s.broken ? (
                  <span className="text-xs text-red-800" data-testid={`session-broken-${s.id}`}>
                    Ledger broken at row {s.broken.row} ({s.broken.code}): {s.broken.detail}. Shown from the readable prefix; cannot be opened.
                  </span>
                ) : null}
              </div>
              {!s.broken ? (
                <button type="button" data-testid={`session-open-${s.id}`} className="rounded border border-slate-600 px-2 py-1" onClick={() => onOpen(s.id)}>
                  Open
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
