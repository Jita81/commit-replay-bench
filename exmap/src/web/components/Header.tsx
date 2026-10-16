// exmap/src/web/components/Header.tsx — title, revision chip, verified badge, chain head, counts, the Undo / Review /
// Export / Settings buttons and the classifier chip (design §10.1). Every number comes from select.counts(state).
import { isHumanVerified, select } from "../../core/index.js";
import type { ConfigResponse } from "../../core/types.js";
import { hash8 } from "../format.js";
import type { StoreStatus } from "../store/sessionStore.js";
import { useAct, useApi, useCounts, useSession, useSessionTitle } from "../store/useSession.js";

export interface HeaderProps {
  status: StoreStatus | null;
  config: ConfigResponse | null;
  onReview: () => void;
  onExport: () => void;
  onSettings: () => void;
}

/** `<provider>` + `· <model>` + `(offline)` for rules.v1, or `<provider> → rules.v1 (fallback: <code>)` — no model literal here. */
export function classifierChipText(config: ConfigResponse | null): string {
  if (!config) return "classifier: unknown (config not loaded)";
  const c = config.classifier;
  if (c.provider === "rules.v1") return `${c.provider} (offline)`;
  if (c.last_error) return `${c.provider} → rules.v1 (fallback: ${c.last_error.code})`;
  return c.model ? `${c.provider} · ${c.model}` : c.provider;
}

export function Header({ status, config, onReview, onExport, onSettings }: HeaderProps) {
  const state = useSession();
  const counts = useCounts();
  const title = useSessionTitle();
  const api = useApi();
  const undo = useAct();
  const revision = select.currentRevision(state);
  const verified = isHumanVerified(state);
  const canUndo = select.undoTarget(state, 1) !== null;

  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-300 bg-white px-4 py-2 text-slate-900" data-testid="header">
      <h1 className="text-lg font-semibold" data-testid="session-title">
        {title || "Example Map Live"}
      </h1>
      <span className="rounded border border-slate-400 px-2 py-0.5 font-mono text-xs" data-testid="revision-chip" data-hash={revision.hash} data-seq={revision.seq} title={revision.hash}>
        rev {revision.seq} · {hash8(revision.hash)}
      </span>
      <span
        className={`rounded px-2 py-0.5 text-xs font-semibold ${verified ? "bg-green-200 text-green-950" : "bg-slate-200 text-slate-900"}`}
        data-testid="verified-badge"
        data-verified={verified ? "true" : "false"}
      >
        {verified ? "Human verified" : "Not verified"}
      </span>
      <span className="text-xs" data-testid="events-count">
        {counts.events} events
      </span>
      <span className="text-xs text-slate-700" data-testid="counts">
        <span data-testid="header-utterance-count">{counts.utterances}</span> utterances · {counts.cards_live} live cards · {counts.needs_review} needs review ·{" "}
        {counts.open_questions} open questions · {counts.open_clarifications} clarifications · {counts.unreviewed_acts} unreviewed acts
      </span>
      {status && status.connection !== "live" ? (
        <span className="text-xs text-amber-900" data-testid="header-connection">
          {status.connection}
        </span>
      ) : null}
      <span className="grow" />
      <span className="rounded border border-slate-300 px-2 py-0.5 text-xs" data-testid="classifier-chip">
        {classifierChipText(config)}
      </span>
      <button
        type="button"
        data-testid="undo-button"
        className="rounded border border-slate-500 px-2 py-1 text-sm disabled:opacity-50"
        disabled={!canUndo || undo.pending}
        onClick={() => void undo.run((actor) => api.undo(actor, null))}
      >
        Undo{undo.pending ? " (pending…)" : ""}
      </button>
      <button type="button" data-testid="review-open" className="rounded border border-slate-500 px-2 py-1 text-sm" onClick={onReview}>
        Review
      </button>
      <button type="button" data-testid="export-open" className="rounded border border-slate-500 px-2 py-1 text-sm" onClick={onExport}>
        Export
      </button>
      <button type="button" data-testid="settings-open" className="rounded border border-slate-500 px-2 py-1 text-sm" onClick={onSettings}>
        Settings
      </button>
    </header>
  );
}
