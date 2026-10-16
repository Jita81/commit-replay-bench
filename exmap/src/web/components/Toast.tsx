// exmap/src/web/components/Toast.tsx — a polite status region for request outcomes (design §10.2, §10.8).
import { useEffect } from "react";
import type { ToastMessage } from "../store/useSession.js";

export interface ToastProps {
  toasts: ToastMessage[];
  onDismiss: (id: number) => void;
  /** Auto-dismiss after this many ms (0 = never). */
  ttlMs?: number;
}

export function Toast({ toasts, onDismiss, ttlMs = 8000 }: ToastProps) {
  useEffect(() => {
    if (ttlMs <= 0 || toasts.length === 0) return;
    const newest = toasts[toasts.length - 1]!;
    const handle = setTimeout(() => onDismiss(newest.id), ttlMs);
    return () => clearTimeout(handle);
  }, [toasts, onDismiss, ttlMs]);
  return (
    <div role="status" aria-live="polite" data-testid="toasts" className="fixed bottom-4 left-1/2 z-50 flex w-full max-w-md -translate-x-1/2 flex-col gap-2 px-4">
      {toasts.map((t) => (
        <div
          key={t.id}
          data-testid={`toast-${t.kind}`}
          className={`flex items-start gap-3 rounded border px-3 py-2 text-sm shadow ${t.kind === "error" ? "border-red-700 bg-red-50 text-red-900" : "border-slate-400 bg-white text-slate-900"}`}
        >
          <span className="grow">{t.text}</span>
          <button type="button" className="rounded px-1 text-xs underline" onClick={() => onDismiss(t.id)} aria-label={`Dismiss: ${t.text}`}>
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
