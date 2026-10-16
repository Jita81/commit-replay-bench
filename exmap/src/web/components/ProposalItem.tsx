// exmap/src/web/components/ProposalItem.tsx — one AI proposal in the tray (design §10.5): intent, rationale, the
// operation as a diff, classifier + confidence as a number, a fallback notice, the source utterance excerpt, the
// "AI act — needs a person's Accept or Reject" line, and Accept / Reject (Restore / Redo) buttons.
import { select } from "../../core/index.js";
import type { MapState, ProposalRecord, Revision } from "../../core/types.js";
import { cardText, describeOperation, excerpt, mmss, speakerLabel } from "../format.js";
import { useAct, useApi, useSession } from "../store/useSession.js";
import { proposalClassifierLine } from "./ProvenancePopover.js";

export interface ProposalItemProps {
  record: ProposalRecord;
  unreviewed: boolean;
}

function revisionsOfUndo(state: MapState, record: ProposalRecord): { from: Revision; to: Revision } | null {
  const i = state.revisions.findIndex((r) => r.event_id === record.outcome_event_id);
  if (i < 1) return null;
  return { from: state.revisions[i - 1]!, to: state.revisions[i]! };
}

export function proposalDiff(state: MapState, record: ProposalRecord): { label: string; before: string | null; after: string | null } {
  const op = record.proposal.operation;
  if (!op) return { label: record.proposal.question ?? "clarification", before: null, after: null };
  const effect = record.effects[0];
  switch (op.kind) {
    case "card.create":
      return { label: `create ${op.card.kind}`, before: null, after: op.card.text };
    case "card.update": {
      const before = effect?.before?.text ?? state.cards[op.card_id]?.history.at(-1)?.record.text ?? null;
      const after = effect?.after.text ?? op.patch.text ?? null;
      if (op.patch.answer !== undefined) return { label: `answer ${cardText(state, op.card_id)}`, before: effect?.before?.kind === "question" ? effect.before.answer : null, after: op.patch.answer };
      return { label: `update ${state.cards[op.card_id]?.kind ?? "card"}`, before, after };
    }
    case "card.remove":
      return { label: `remove ${state.cards[op.card_id]?.kind ?? "card"}`, before: state.cards[op.card_id]?.text ?? op.card_id, after: null };
    case "card.replace": {
      const replacement = "replacement" in op ? op.replacement.text : (state.cards[op.replacement_card_id]?.text ?? op.replacement_card_id);
      return { label: `replace ${state.cards[op.card_id]?.kind ?? "card"}`, before: state.cards[op.card_id]?.text ?? op.card_id, after: replacement };
    }
    case "definition.refine":
      return { label: `refine ${cardText(state, op.card_id)}`, before: null, after: `${op.term}: ${op.definition}` };
    case "undo": {
      const revs = revisionsOfUndo(state, record);
      return { label: revs ? `undo: rev ${revs.from.seq} → rev ${revs.to.seq}` : describeOperation(state, op), before: null, after: null };
    }
    case "interpretation.reject": {
      const target = state.proposals[op.proposal_id];
      return { label: `reject proposal ${op.proposal_id}`, before: null, after: target?.proposal.operation ? describeOperation(state, target.proposal.operation) : target?.proposal.rationale ?? null };
    }
    case "confirm":
      return { label: describeOperation(state, op), before: null, after: null };
  }
}

export function rejectLabel(record: ProposalRecord): string {
  const kind = record.proposal.operation?.kind;
  if (kind === "card.remove") return "Restore";
  if (kind === "undo") return "Redo";
  return "Reject";
}

export function ProposalItem({ record, unreviewed }: ProposalItemProps) {
  const state = useSession();
  const api = useApi();
  const act = useAct();
  const p = record.proposal;
  const op = p.operation;
  const diff = proposalDiff(state, record);
  const isAct = op !== null && select.ACT_KINDS.includes(op.kind);
  const liveAffected = record.affected_card_ids.filter((id) => {
    const c = state.cards[id];
    return c !== undefined && (c.status === "applied" || c.status === "confirmed");
  });
  const showAccept = op !== null && op.kind !== "confirm" && record.status === "applied" && (isAct || liveAffected.length > 0);
  const showReject = select.isRejectable(state, p.id);
  const utterances = p.source_utterance_ids.map((id) => state.utterances.find((u) => u.id === id)).filter((u) => u !== undefined);

  return (
    <li
      id={`proposal-${p.id}`}
      data-testid={`proposal-${p.id}`}
      data-status={record.status}
      tabIndex={-1}
      className="flex flex-col gap-1 rounded border border-slate-400 bg-white p-2 text-sm text-slate-900 focus-visible:ring-2 focus-visible:ring-slate-900"
      aria-label={`${p.intent} proposal ${p.id}`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-slate-800 px-1.5 py-0.5 font-semibold text-white" data-testid={`proposal-intent-${p.id}`}>
          {p.intent}
        </span>
        <span className="rounded border border-slate-400 px-1.5 py-0.5" data-testid={`proposal-status-${p.id}`}>
          {record.status}
        </span>
        <span className="rounded border border-slate-300 px-1.5 py-0.5" data-testid={`proposal-classifier-${p.id}`}>
          {proposalClassifierLine(p)} · confidence <span data-testid={`proposal-confidence-${p.id}`}>{p.confidence}</span>
        </span>
      </div>
      {p.classifier.fallback_from ? (
        <div className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-950" data-testid={`proposal-fallback-${p.id}`}>
          {p.classifier.provider} answered because {p.classifier.fallback_from} failed: {p.classifier.error ?? "unknown error"}
        </div>
      ) : null}
      <div data-testid={`proposal-rationale-${p.id}`}>{p.rationale || "(no rationale given)"}</div>
      <div className="rounded border border-slate-200 bg-slate-50 p-1.5 text-xs" data-testid={`proposal-diff-${p.id}`}>
        <div className="font-semibold">{diff.label}</div>
        {diff.before !== null ? (
          <div>
            <span className="text-slate-600">old:</span> <del>{diff.before}</del>
          </div>
        ) : null}
        {diff.after !== null ? (
          <div>
            <span className="text-slate-600">{diff.before !== null ? "new:" : ""}</span> <ins className="no-underline">{diff.after}</ins>
          </div>
        ) : null}
      </div>
      {utterances.map((u) => (
        <div key={u.id} className="text-xs text-slate-700" data-testid={`proposal-source-${p.id}`}>
          from {speakerLabel(u.speaker)} at {mmss(u.t_start_ms)}: “{excerpt(u.text, 90)}”
        </div>
      ))}
      {unreviewed ? (
        <div className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-950" data-testid={`proposal-unreviewed-${p.id}`}>
          AI act — needs a person's Accept or Reject
        </div>
      ) : null}
      {act.error ? (
        <div className="text-xs text-red-800" role="alert" data-testid={`proposal-error-${p.id}`}>
          {act.error.reason}: {act.error.detail}
        </div>
      ) : null}
      <div className="flex gap-2">
        {showAccept ? (
          <button type="button" data-testid={`proposal-accept-${p.id}`} className="rounded border border-green-800 bg-green-100 px-2 py-0.5 text-xs font-semibold disabled:opacity-50" disabled={act.pending} onClick={() => void act.run((actor) => api.acceptProposal(p.id, actor))}>
            Accept{act.pending ? " (pending…)" : ""}
          </button>
        ) : null}
        {showReject ? (
          <button type="button" data-testid={`proposal-reject-${p.id}`} className="rounded border border-red-800 bg-red-100 px-2 py-0.5 text-xs font-semibold disabled:opacity-50" disabled={act.pending} onClick={() => void act.run((actor) => api.rejectProposal(p.id, actor))}>
            {rejectLabel(record)}
            {act.pending ? " (pending…)" : ""}
          </button>
        ) : null}
      </div>
    </li>
  );
}
