// exmap/src/web/components/ProposalTray.tsx — the proposal tray (design §10.5). Membership, newest first: every open
// clarification whatever its age; every unreviewed AI act whatever its age; applied AI proposals from the last 10
// utterances. The classifier's last error (from /api/config) is shown once as a dismissible notice.
import { useState } from "react";
import { select } from "../../core/index.js";
import type { ClassifierConfig, MapState, ProposalRecord } from "../../core/types.js";
import { useSession } from "../store/useSession.js";
import { ClarificationItem } from "./ClarificationItem.js";
import { ProposalItem } from "./ProposalItem.js";

export interface ProposalTrayProps {
  lastError?: ClassifierConfig["last_error"] | null;
}

export type TrayItem = { kind: "clarification"; id: string; order: number } | { kind: "proposal"; record: ProposalRecord; unreviewed: boolean; order: number };

export function trayItems(state: MapState): TrayItem[] {
  const order = new Map(state.proposal_order.map((id, i) => [id, i]));
  const items: TrayItem[] = [];
  const seen = new Set<string>();
  for (const c of select.openClarifications(state)) {
    items.push({ kind: "clarification", id: c.id, order: order.get(c.proposal_id) ?? -1 });
    seen.add(c.proposal_id);
  }
  for (const record of select.unreviewedActs(state)) {
    items.push({ kind: "proposal", record, unreviewed: true, order: order.get(record.proposal.id) ?? -1 });
    seen.add(record.proposal.id);
  }
  const recent = new Set(state.utterances.slice(-10).map((u) => u.id));
  for (const id of state.proposal_order) {
    const record = state.proposals[id];
    if (!record || seen.has(id)) continue;
    const p = record.proposal;
    if (p.classifier.provider === "human") continue;
    if (!(record.status === "applied" || record.status === "pending")) continue;
    if (!p.source_utterance_ids.some((u) => recent.has(u))) continue;
    items.push({ kind: "proposal", record, unreviewed: false, order: order.get(id) ?? -1 });
    seen.add(id);
  }
  return items.sort((a, b) => b.order - a.order);
}

export function ProposalTray({ lastError = null }: ProposalTrayProps) {
  const state = useSession();
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);
  const items = trayItems(state);
  const showNotice = lastError !== null && lastError.at !== dismissedAt;
  return (
    <section role="region" aria-label="Proposals" data-testid="tray" className="flex h-full min-h-0 flex-col">
      <h2 className="border-b border-slate-300 px-3 py-2 text-sm font-semibold">Proposals ({items.length})</h2>
      {showNotice ? (
        <div role="status" data-testid="classifier-notice" className="flex items-start gap-2 border-b border-amber-600 bg-amber-50 px-3 py-2 text-xs text-amber-950">
          <span className="grow">
            The model classifier failed ({lastError.code}: {lastError.message}); the offline rules classifier answered instead. Proposals carry the fallback in their provenance.
          </span>
          <button type="button" className="rounded border border-amber-700 px-1.5" onClick={() => setDismissedAt(lastError.at)} data-testid="classifier-notice-dismiss">
            Dismiss
          </button>
        </div>
      ) : null}
      <ul role="list" className="flex min-h-0 grow flex-col gap-2 overflow-y-auto p-2">
        {items.length === 0 ? <li className="text-xs text-slate-600">Nothing to review. Proposals from the last utterances appear here.</li> : null}
        {items.map((item) =>
          item.kind === "clarification" ? (
            <ClarificationItem key={`c-${item.id}`} clarification={state.clarifications[item.id]!} />
          ) : (
            <ProposalItem key={`p-${item.record.proposal.id}`} record={item.record} unreviewed={item.unreviewed} />
          ),
        )}
      </ul>
    </section>
  );
}
