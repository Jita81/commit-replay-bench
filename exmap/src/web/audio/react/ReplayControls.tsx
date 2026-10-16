// exmap/src/web/audio/react/ReplayControls.tsx — the replay panel (design §7.4, §7.7): fixture select from
// /replay/index.json, a file input for a custom fixture, speed, Play / Step / Pause / Reset and "12 / 31".
import { useEffect, useState } from "react";
import { fetchReplayFixture, fetchReplayIndex, type AudioController, type ReplayIndexEntry } from "../controller.js";
import { parseReplayFixture, REPLAY_SPEEDS } from "../providers/replay.js";
import type { ReplaySpeed, ReplayStatus } from "../types.js";
import { useAudioController } from "./useAudioController.js";

export interface ReplayControlsProps {
  controller: AudioController;
  /** Defaults to the controller's live replay status (the web module renders every audio component with { controller } alone). */
  replay?: ReplayStatus;
  fetchFn?: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }>;
}

export function ReplayControls({ controller, replay: replayProp, fetchFn }: ReplayControlsProps) {
  const state = useAudioController(controller);
  const replay = replayProp ?? state.replay;
  const [index, setIndex] = useState<ReplayIndexEntry[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [speed, setSpeed] = useState<ReplaySpeed>("instant");
  const [error, setError] = useState<string | null>(null);
  const f = fetchFn ?? ((u: string) => fetch(u));

  useEffect(() => {
    let alive = true;
    fetchReplayIndex(f)
      .then((entries) => {
        if (!alive) return;
        setIndex(entries);
        if (entries[0] && !selected) setSelected(entries[0].name);
      })
      .catch((e: unknown) => alive && setError(String((e as Error)?.message ?? e)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = async () => {
    const entry = index.find((e) => e.name === selected);
    if (!entry) return;
    try {
      const fixture = await fetchReplayFixture(entry.file, f);
      controller.loadReplay(fixture, entry.name);
      setError(null);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  };

  const loadFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      const fixture = parseReplayFixture(JSON.parse(await file.text()));
      controller.loadReplay(fixture, file.name.replace(/\.json$/i, ""));
      setError(null);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  };

  const play = () => {
    if (replay.state === "paused") controller.resumeReplay();
    else void controller.playReplay(speed).catch((e: unknown) => setError(String((e as Error)?.message ?? e)));
  };

  const loaded = replay.state !== "empty";
  return (
    <div data-testid="replay-controls" className="flex flex-wrap items-center gap-2 text-xs">
      <span className="font-medium">Replay</span>
      <label>
        Fixture{" "}
        <select data-testid="replay-select" className="rounded border px-1" value={selected} onChange={(e) => setSelected(e.target.value)}>
          {index.map((e) => (
            <option key={e.name} value={e.name}>
              {e.title} ({e.utterances})
            </option>
          ))}
        </select>
      </label>
      <button type="button" data-testid="replay-load" className="rounded border px-2" onClick={() => void load()} disabled={!selected}>
        Load
      </button>
      <label>
        <span className="sr-only">Custom fixture file</span>
        <input data-testid="replay-file" type="file" accept="application/json,.json" className="text-xs" onChange={(e) => void loadFile(e.target.files?.[0])} />
      </label>
      <label>
        Speed{" "}
        <select data-testid="replay-speed" className="rounded border px-1" value={String(speed)} onChange={(e) => setSpeed(e.target.value === "instant" ? "instant" : (Number(e.target.value) as ReplaySpeed))}>
          {REPLAY_SPEEDS.map((s) => (
            <option key={String(s)} value={String(s)}>
              {s === "instant" ? "instant" : `×${s}`}
            </option>
          ))}
        </select>
      </label>
      <button type="button" data-testid="replay-play" className="rounded border px-2" onClick={play} disabled={!loaded || replay.state === "playing" || replay.state === "done"}>
        Play
      </button>
      <button type="button" data-testid="replay-step" className="rounded border px-2" onClick={() => controller.stepReplay()} disabled={!loaded || replay.state === "playing" || replay.state === "done"}>
        Step
      </button>
      <button type="button" data-testid="replay-pause" className="rounded border px-2" onClick={() => controller.pauseReplay()} disabled={replay.state !== "playing"}>
        Pause
      </button>
      <button type="button" data-testid="replay-reset" className="rounded border px-2" onClick={() => controller.resetReplay()} disabled={!loaded}>
        Reset
      </button>
      <span data-testid="replay-status" data-state={replay.state} aria-live="polite">
        {replay.index} / {replay.total}
      </span>
      {error ? (
        <span role="alert" data-testid="replay-error" className="text-red-700">
          {error}
        </span>
      ) : null}
    </div>
  );
}
