// exmap/src/web/components/ProvenancePopover.tsx — where a card came from (design §10.4): the proposal and utterances,
// the classifier (human / rules.v1 / claude / fallback), confidence and rationale (AI only), the version history, the
// supersedes links, a restore, and the confirmation ("by voice" is named as such; speaker identity is only what a person assigned).
import { useEffect, useRef } from "react";
import { select } from "../../core/index.js";
import type { Card, ClassifierStamp, MapState, Proposal, ProposalRecord, Provenance } from "../../core/types.js";
import { excerpt, mmss, speakerLabel } from "../format.js";
import { useSession } from "../store/useSession.js";

const ACT_KINDS = select.ACT_KINDS;

export interface ProvenancePopoverProps {
  card: Card;
  id: string;
  onClose: () => void;
  /** Resolves an event id to its ledger seq when the store knows it; null shows the id. */
  eventSeq?: (eventId: string) => number | null;
}

/**
 * `rules.v1` / `claude (<model>)` / `rules.v1 — fallback from claude: <error>` / `human: <actor>` (design §10.4). An AI
 * proposal that carries an actor names it: the person who answered a clarification, or the speaker label of a voice
 * confirmation — only ever the label a person assigned.
 */
export function classifierLine(stamp: ClassifierStamp, opts: { resolves?: boolean } = {}): string {
  if (stamp.provider === "human") return `human: ${stamp.actor ?? "(unnamed)"}`;
  let line: string;
  if (stamp.fallback_from) line = `${stamp.provider} — fallback from ${stamp.fallback_from}: ${stamp.error ?? "unknown error"}`;
  else if (stamp.provider === "claude") line = `claude (${stamp.model ?? "model unknown"})`;
  else line = stamp.provider;
  if (stamp.actor) line += opts.resolves ? ` · answered by ${stamp.actor}` : ` · speaker ${stamp.actor}`;
  return line;
}

export function proposalClassifierLine(p: Proposal): string {
  return classifierLine(p.classifier, { resolves: p.resolves_clarification_id !== null });
}

/** The applied `confirm` proposal that reviewed an act (`confirm { proposal_ids: [pid] }`), newest first; null when none. */
export function confirmerOf(state: MapState, proposalId: string): ProposalRecord | null {
  for (let i = state.proposal_order.length - 1; i >= 0; i--) {
    const record = state.proposals[state.proposal_order[i]!];
    const op = record?.proposal.operation;
    if (record && op?.kind === "confirm" && op.proposal_ids.includes(proposalId) && record.status === "applied") return record;
  }
  return null;
}

/** "confirmed by <actor>" for a click; "confirmed by voice (<provider>, <confidence>, speaker <actor>)" otherwise. */
export function confirmedByText(stamp: ClassifierStamp, confidence: number): string {
  if (stamp.provider === "human") return `confirmed by ${stamp.actor ?? "a person (unnamed)"}`;
  return `confirmed by voice (${stamp.provider}, ${confidence}, speaker ${stamp.actor ?? "unlabelled"})`;
}

/** The review state of an act (removal / undo / rejection): who confirmed it, or that it still needs a person. */
export function actReviewText(state: MapState, record: ProposalRecord): string | null {
  const op = record.proposal.operation;
  if (!op || !ACT_KINDS.includes(op.kind)) return null;
  if (record.status === "confirmed") {
    const by = confirmerOf(state, record.proposal.id);
    return by ? confirmedByText(by.proposal.classifier, by.proposal.confidence) : "confirmed";
  }
  if (record.status === "applied" && record.proposal.classifier.actor === null) return "not reviewed — an AI act needs a person's Accept or Reject";
  if (record.status === "rejected") return "rejected (reverted)";
  return null;
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
      <div>classifier: {record ? proposalClassifierLine(record.proposal) : prov.classifier}</div>
      {record && record.proposal.classifier.provider !== "human" ? <div>confidence: {record.proposal.confidence}</div> : null}
      {record && record.proposal.rationale ? <div>rationale: {record.proposal.rationale}</div> : null}
    </div>
  );
}

function RejectionBlock({ card, state, eventSeq }: { card: Card; state: MapState; eventSeq?: (id: string) => number | null }) {
  const rejection = card.rejection!;
  const record = state.proposals[rejection.proposal_id];
  const what = rejection.kind === "removed" ? "removed" : rejection.kind === "undone" ? "undone" : "interpretation rejected";
  const review = record ? actReviewText(state, record) : null;
  return (
    <div className="flex flex-col gap-0.5" data-testid={`rejection-${card.id}`}>
      <div>
        <span className="font-semibold">{what}</span> by proposal <code>{rejection.proposal_id}</code> ({eventLabel(rejection.event_id, eventSeq)})
        {record ? <> — classifier: {proposalClassifierLine(record.proposal)}</> : null}
        {record && record.proposal.classifier.provider !== "human" ? <>, confidence {record.proposal.confidence}</> : null}
      </div>
      {record && record.proposal.rationale ? <div>rationale: {record.proposal.rationale}</div> : null}
      {review ? <div data-testid={`rejection-review-${card.id}`}>review: {review}</div> : null}
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
      {card.rejection ? <RejectionBlock card={card} state={state} eventSeq={eventSeq} /> : null}
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
