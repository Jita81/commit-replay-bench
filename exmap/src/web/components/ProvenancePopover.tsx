// exmap/src/web/components/ProvenancePopover.tsx — where a card came from (design §10.4): the proposal and utterances,
// the classifier (human / rules.v1 / claude / fallback), confidence and rationale (AI only), the version history, the
// supersedes links, a restore, and the confirmation ("by voice" is named as such; speaker identity is only what a person assigned).
import { useEffect, useRef } from "react";
import type { Card, ClassifierStamp, MapState, Provenance } from "../../core/types.js";
import { excerpt, mmss, speakerLabel } from "../format.js";
import { useSession } from "../store/useSession.js";

export interface ProvenancePopoverProps {
  card: Card;
  id: string;
  onClose: () => void;
  /** Resolves an event id to its ledger seq when the store knows it; null shows the id. */
  eventSeq?: (eventId: string) => number | null;
}

export function classifierLine(stamp: ClassifierStamp): string {
  if (stamp.provider === "human") return `human: ${stamp.actor ?? "(unnamed)"}`;
  let line: string;
  if (stamp.fallback_from) line = `${stamp.provider} — fallback from ${stamp.fallback_from}: ${stamp.error ?? "unknown error"}`;
  else if (stamp.provider === "claude") line = `claude (${stamp.model ?? "model unknown"})`;
  else line = stamp.provider;
  if (stamp.actor) line += ` · answered by ${stamp.actor}`;
  return line;
}

function eventLabel(id: string, eventSeq?: (id: string) => number | null): string {
  const seq = eventSeq?.(id);
  return seq === null || seq === undefined ? `event ${id}` : `event ${seq}`;
}

function ProvenanceBlock({ label, prov, state, eventSeq }: { label: string; prov: Provenance; state: MapState; eventSeq?: (id: string) => number | null }) {
  const record = state.proposals[prov.proposal_id];
  const utterances = prov.utterance_ids.map((id) => state.utterances.find((u) => u.id === id) ?? null);
  return (
    <div className="flex flex-col gap-0.5">
      <div>
        <span className="font-semibold">{label}</span> by proposal <code>{prov.proposal_id}</code> ({eventLabel(prov.event_id, eventSeq)})
      </div>
      {utterances.length === 0 ? <div>from no utterance (made in the UI)</div> : null}
      {utterances.map((u, i) => (
        <div key={prov.utterance_ids[i]}>
          {u ? (
            <>
              from utterance by {speakerLabel(u.speaker)} at {mmss(u.t_start_ms)}: “{excerpt(u.text, 90)}”
            </>
          ) : (
            <>from utterance {prov.utterance_ids[i]}</>
          )}
        </div>
      ))}
      <div>classifier: {record ? classifierLine(record.proposal.classifier) : prov.classifier}</div>
      {record && record.proposal.classifier.provider !== "human" ? <div>confidence: {record.proposal.confidence}</div> : null}
      {record && record.proposal.rationale ? <div>rationale: {record.proposal.rationale}</div> : null}
    </div>
  );
}

export function ProvenancePopover({ card, id, onClose, eventSeq }: ProvenancePopoverProps) {
  const state = useSession();
  const root = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    root.current?.focus();
  }, []);
  const restored = card.restored_by ? state.proposals[card.restored_by.proposal_id] : null;
  const restoredLine = card.restored_by
    ? restored?.proposal.operation?.kind === "interpretation.reject"
      ? `restored by the rejection of ${restored.proposal.operation.proposal_id} (proposal ${card.restored_by.proposal_id})`
      : `restored by undo ${card.restored_by.proposal_id}`
    : null;
  const confirmation = card.confirmation;
  const confirmedLine = confirmation
    ? confirmation.by.provider === "human"
      ? `confirmed by ${confirmation.by.actor ?? "a person (unnamed)"} (version seen v${confirmation.version})`
      : `confirmed by voice (${confirmation.by.provider}, ${confirmation.by.confidence}, speaker ${confirmation.by.actor ?? "unlabelled"}) (version seen v${confirmation.version})`
    : null;
  return (
    <div
      ref={root}
      id={id}
      role="dialog"
      aria-label={`Provenance of ${card.kind} ${card.id}`}
      data-testid={`provenance-${card.id}`}
      tabIndex={-1}
      className="absolute left-0 top-full z-20 mt-1 flex w-80 max-w-[90vw] flex-col gap-2 rounded border border-slate-500 bg-white p-3 text-xs text-slate-900 shadow-lg"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="flex items-center justify-between">
        <span className="font-semibold">Provenance — v{card.version}</span>
        <button type="button" className="rounded border border-slate-400 px-1.5" onClick={onClose} data-testid={`provenance-close-${card.id}`}>
          Close
        </button>
      </div>
      <ProvenanceBlock label="Created" prov={card.created} state={state} eventSeq={eventSeq} />
      {card.changed.event_id !== card.created.event_id ? <ProvenanceBlock label="Current content" prov={card.changed} state={state} eventSeq={eventSeq} /> : null}
      {card.history.length > 0 ? (
        <div>
          <div className="font-semibold">Version history</div>
          <ol className="list-inside list-decimal">
            {card.history.map((h) => (
              <li key={h.version} data-testid={`history-v${h.version}`}>
                v{h.version} → v{h.version + 1} replaced by {eventLabel(h.replaced_by_event_id, eventSeq)}: “{excerpt(h.record.text, 100)}”
                {h.record.kind === "question" && h.record.answer ? ` (answer: ${excerpt(h.record.answer, 60)})` : ""}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {card.supersedes ? (
        <div data-testid={`supersedes-${card.id}`}>
          supersedes <code>{card.supersedes}</code>: “{excerpt(state.cards[card.supersedes]?.text ?? "", 60)}”
        </div>
      ) : null}
      {card.superseded_by ? (
        <div data-testid={`superseded-by-${card.id}`}>
          superseded by <code>{card.superseded_by}</code>: “{excerpt(state.cards[card.superseded_by]?.text ?? "", 60)}”
        </div>
      ) : null}
      {card.rejection ? (
        <div>
          {card.rejection.kind === "removed" ? "removed" : card.rejection.kind === "undone" ? "undone" : "interpretation rejected"} by proposal <code>{card.rejection.proposal_id}</code>
        </div>
      ) : null}
      {restoredLine ? <div data-testid={`restored-by-${card.id}`}>{restoredLine}</div> : null}
      {confirmedLine ? <div data-testid={`confirmed-by-${card.id}`}>{confirmedLine}</div> : <div>not confirmed</div>}
      {card.kind === "question" && card.accepted_outstanding ? (
        <div>
          accepted outstanding by {card.accepted_outstanding.by}: {card.accepted_outstanding.reason} (the question stays unanswered)
        </div>
      ) : null}
    </div>
  );
}
