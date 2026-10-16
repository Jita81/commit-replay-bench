// exmap/src/web/audio/react/ConsentNotice.tsx — the two consent gates, same shape (design §7.0.9, §7.4): the Whisper
// download and Web Speech. role="dialog", aria-modal, focus on Continue, Escape = Cancel. Nothing on the network
// starts before Continue.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { WEB_SPEECH_NOTICE } from "../providers/webSpeech.js";
import { MODEL_INFO, modelShortName } from "../settings.js";
import type { AudioNotice, AudioState, WhisperDtype, WhisperModelId } from "../types.js";

/** The controller surface the notice needs; getState/subscribe are read when no `notice` prop is given. */
export interface ConsentController {
  acceptNotice(): void;
  cancelNotice(): void;
  getState?(): AudioState;
  subscribe?(fn: () => void): () => void;
}

export interface ConsentNoticeProps {
  controller: ConsentController;
  /** Default: the controller's current notice; renders nothing while there is none. */
  notice?: AudioNotice | null;
  dtype?: WhisperDtype;
}

const noSubscribe = () => () => undefined;

export function modelNoticeText(model: WhisperModelId, dtype: WhisperDtype = "q8"): string {
  const info = MODEL_INFO[model];
  const mb = info ? info.approxMb[dtype] : 77;
  return `exmap will download ~${mb} MB (${modelShortName(model)}, approx) from huggingface.co once and keep it in the browser cache. Audio never leaves this machine.`;
}

export function ConsentNotice({ notice: noticeProp, controller, dtype: dtypeProp }: ConsentNoticeProps) {
  const subscribe = controller.subscribe ? (fn: () => void) => controller.subscribe!(fn) : noSubscribe;
  const getState = () => controller.getState?.() ?? null;
  const state = useSyncExternalStore(subscribe, getState, getState);
  const notice = noticeProp === undefined ? (state?.notice ?? null) : noticeProp;
  const dtype = dtypeProp ?? state?.settings.whisperDtype ?? "q8";
  const continueRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    continueRef.current?.focus();
  }, [notice]);
  if (!notice) return null;
  const id = notice.kind === "model" ? "model-notice" : "webspeech-notice";
  const title = notice.kind === "model" ? "Download the speech model?" : "Use Web Speech (not local)?";
  const text = notice.kind === "model" ? modelNoticeText(notice.model, dtype) : WEB_SPEECH_NOTICE;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30" onKeyDown={(e) => e.key === "Escape" && (e.preventDefault(), controller.cancelNotice())}>
      <div data-testid={id} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-text`} className="max-w-md rounded bg-white p-4 text-slate-900 shadow">
        <h2 id={`${id}-title`} className="text-base font-semibold">
          {title}
        </h2>
        <p id={`${id}-text`} className="mt-2 text-sm">
          {text}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" data-testid={`${id}-cancel`} className="rounded border px-3 py-1 text-sm" onClick={() => controller.cancelNotice()}>
            Cancel
          </button>
          <button ref={continueRef} type="button" data-testid={`${id}-continue`} className="rounded bg-slate-900 px-3 py-1 text-sm text-white" onClick={() => controller.acceptNotice()}>
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
