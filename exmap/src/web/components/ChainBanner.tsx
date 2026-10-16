// exmap/src/web/components/ChainBanner.tsx — the terminal-state banner of the session store (design §10.2): a chain
// break or a failed hash check leaves the state read-only; a named close (session not found, ledger broken) is shown
// with the server's reason; reconnecting is announced politely.
import type { StoreStatus } from "../store/sessionStore.js";

export interface ChainBannerProps {
  status: StoreStatus;
  onReload: () => void;
  onBack: () => void;
}

export function ChainBanner({ status, onReload, onBack }: ChainBannerProps) {
  const { chainError, reduceError, closeReason, connection, attempt, nextRetryMs } = status;
  if (chainError || reduceError || closeReason) {
    let text: string;
    if (chainError?.code === "PREV_HASH_MISMATCH") text = `The event stream broke its chain at seq ${chainError.seq}; showing the state read-only.`;
    else if (chainError?.code === "HASH_MISMATCH") text = `An event failed its hash check (seq ${chainError.seq}); showing the state read-only.`;
    else if (chainError) text = `The event stream failed verification (${chainError.code} at seq ${chainError.seq}: ${chainError.detail}); showing the state read-only.`;
    else if (reduceError) text = `An event could not be reduced (seq ${reduceError.seq}: ${reduceError.message}); showing the state read-only.`;
    else text = `The server closed the session stream: ${closeReason!.reason}${closeReason!.detail ? ` — ${closeReason!.detail}` : ""}. Showing what was read so far, read-only.`;
    return (
      <div role="alert" data-testid="chain-banner" data-code={chainError?.code ?? closeReason?.reason ?? "REDUCE_ERROR"} className="flex flex-wrap items-center gap-3 border-b-2 border-red-700 bg-red-50 px-4 py-2 text-sm text-red-900">
        <span className="grow">{text}</span>
        <button type="button" className="rounded border border-red-700 px-2 py-1" onClick={onReload}>
          Reload
        </button>
        <button type="button" className="rounded border border-red-700 px-2 py-1" onClick={onBack}>
          Back to sessions
        </button>
      </div>
    );
  }
  if (connection === "reconnecting") {
    return (
      <div role="status" aria-live="polite" data-testid="connection-status" className="border-b border-amber-600 bg-amber-50 px-4 py-1 text-sm text-amber-900">
        Connection lost; reconnecting (attempt {attempt}{nextRetryMs !== null ? `, next try in ${nextRetryMs / 1000} s` : ""})…
      </div>
    );
  }
  if (connection === "connecting") {
    return (
      <div role="status" aria-live="polite" data-testid="connection-status" className="border-b border-slate-300 bg-slate-50 px-4 py-1 text-sm text-slate-700">
        Connecting to the session stream…
      </div>
    );
  }
  return <div role="status" aria-live="polite" data-testid="connection-status" className="sr-only">Live</div>;
}
