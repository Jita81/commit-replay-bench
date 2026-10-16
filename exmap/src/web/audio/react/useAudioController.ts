// exmap/src/web/audio/react/useAudioController.ts — the AudioState snapshot as a React external store (design §7.7).
import { useSyncExternalStore } from "react";
import type { AudioController } from "../controller.js";
import type { AudioState } from "../types.js";

export function useAudioController(c: AudioController): AudioState {
  return useSyncExternalStore(
    (fn) => c.subscribe(fn),
    () => c.getState(),
    () => c.getState(),
  );
}
