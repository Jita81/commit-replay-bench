// exmap/src/web/audio/speakers.ts — SpeakerStore (design §7.6): labels a person assigned to a lane, nothing inferred.
// `me` starts as the user's name when set, else null; `remote` starts null; a committed remote name joins remoteKnown
// (deduped, max 20, kept in sessionStorage); the me label is kept in localStorage.
import type { CaptureLaneId, SpeakerLabels, SpeakerStoreLike, StorageLike, WireLane } from "./types.js";

export const REMOTE_KNOWN_KEY = "exmap.speakers.remoteKnown";
export const ME_LABEL_KEY = "exmap.speakers.me";
export const REMOTE_KNOWN_MAX = 20;

export interface SpeakerStoreDeps {
  userName?: string | null;
  storage?: StorageLike | null; // localStorage: the me label
  sessionStorage?: StorageLike | null; // sessionStorage: remoteKnown
}

function clean(label: string | null | undefined): string | null {
  if (label === null || label === undefined) return null;
  const t = String(label).trim();
  return t.length === 0 ? null : t;
}

export class SpeakerStore implements SpeakerStoreLike {
  #me: string | null;
  #remote: string | null = null;
  #remoteKnown: string[] = [];
  readonly #storage: StorageLike | null;
  readonly #session: StorageLike | null;
  readonly #subs = new Set<() => void>();
  #labels: SpeakerLabels;

  constructor(deps: SpeakerStoreDeps = {}) {
    this.#storage = deps.storage ?? null;
    this.#session = deps.sessionStorage ?? null;
    const userName = clean(deps.userName);
    let stored: string | null = null;
    try {
      stored = clean(this.#storage?.getItem(ME_LABEL_KEY));
    } catch {
      stored = null;
    }
    // A person-set name wins; a label remembered from a previous page is next; else null (never a lane name).
    this.#me = userName ?? stored;
    try {
      const raw = this.#session?.getItem(REMOTE_KNOWN_KEY);
      if (raw) {
        const arr: unknown = JSON.parse(raw);
        if (Array.isArray(arr)) this.#remoteKnown = arr.filter((x): x is string => typeof x === "string" && x.trim().length > 0).slice(0, REMOTE_KNOWN_MAX);
      }
    } catch {
      this.#remoteKnown = [];
    }
    this.#labels = this.#snapshot();
  }

  #snapshot(): SpeakerLabels {
    return { me: this.#me, remote: this.#remote, remoteKnown: [...this.#remoteKnown] };
  }

  get labels(): SpeakerLabels {
    return this.#labels;
  }

  /** 'manual' mirrors the me label; null until a person set one. */
  get(lane: WireLane): string | null {
    if (lane === "remote") return this.#remote;
    return this.#me;
  }

  set(lane: CaptureLaneId, label: string | null): void {
    const value = clean(label);
    if (lane === "me") {
      this.#me = value;
      try {
        if (value === null) this.#storage?.removeItem(ME_LABEL_KEY);
        else this.#storage?.setItem(ME_LABEL_KEY, value);
      } catch {
        /* ignore */
      }
    } else {
      this.#remote = value;
      if (value !== null && !this.#remoteKnown.includes(value)) {
        this.#remoteKnown = [...this.#remoteKnown, value].slice(-REMOTE_KNOWN_MAX);
        try {
          this.#session?.setItem(REMOTE_KNOWN_KEY, JSON.stringify(this.#remoteKnown));
        } catch {
          /* ignore */
        }
      }
    }
    this.#labels = this.#snapshot();
    for (const fn of this.#subs) fn();
  }

  subscribe(fn: () => void): () => void {
    this.#subs.add(fn);
    return () => {
      this.#subs.delete(fn);
    };
  }
}

export const SPEAKER_COPY =
  "exmap does not detect who is speaking. The label is whatever you set here, and it is recorded as such. Until you set one, utterances are recorded with no speaker.";
