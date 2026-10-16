// exmap/src/web/components/Transcript.tsx — the utterance log (design §10.3): rows by t_start_ms, lane badge, the
// speaker label a person assigned (or "— (no speaker label)"), mm:ss, the provider chip, the text, and under each row
// the chips built from the ledger only: one per proposal citing it, one per classification record, "classifying…".
import { Fragment } from "react";
import { select } from "../../core/index.js";
import type { ClassificationRecord, MapState, ProposalRecord, Utterance } from "../../core/types.js";
import { LANE_LABEL, mmss, providerChip, speakerLabel } from "../format.js";
import { useSession } from "../store/useSession.js";

export function proposalsCiting(state: MapState, utteranceId: string): ProposalRecord[] {
  const out: ProposalRecord[] = [];
  for (const id of state.proposal_order) {
    const record = state.proposals[id];
    if (record && record.proposal.source_utterance_ids.includes(utteranceId)) out.push(record);
  }
  return out;
}

export function classificationChip(record: ClassificationRecord): string {
  if (record.error) return `classifier error: ${record.error.code}`;
  if (record.classifier.fallback_from) return `fallback from ${record.classifier.fallback_from}: ${record.classifier.error ?? "unknown"}`;
  if (record.intent === "none") return `${record.heard_intent ? `heard ${record.heard_intent} — ` : ""}no map change — ${record.rationale || "nothing to propose"}`;
  if (record.refused.length > 0) return `refused: ${record.refused.map((r) => `${r.operation} ${r.reason}`).join(", ")}`;
  return "";
}

/** The tray item for a proposal (its clarification when it asked one), else the first affected card. */
export function focusTargetFor(state: MapState, record: ProposalRecord): string | null {
  const clarification = Object.values(state.clarifications).find((c) => c.proposal_id === record.proposal.id);
  if (clarification) return `clarification-${clarification.id}`;
  if (document.getElementById(`proposal-${record.proposal.id}`)) return `proposal-${record.proposal.id}`;
  const card = record.affected_card_ids[0];
  return card ? `card-${card}` : `proposal-${record.proposal.id}`;
}

function focusById(id: string): void {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView?.({ block: "nearest" });
  el.focus();
}

function Row({ u, state }: { u: Utterance; state: MapState }) {
  const proposals = proposalsCiting(state, u.id);
  const records = select.classificationsOf(state, u.id);
  // "classifying…" until the ledger holds a classification record for this utterance (design §10.3)
  const classifying = records.length === 0;
  return (
    <li data-testid={`utterance-${u.id}`} id={`utterance-${u.id}`} className="border-b border-slate-200 px-3 py-2 text-sm" data-lane={u.lane}>
      {/* the {" "} separators keep the row's text readable as text (copy, screen readers): "Call Priya 00:04 Replay …" */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-700">
        <span className="rounded bg-slate-200 px-1.5 py-0.5 font-semibold text-slate-900" data-testid="transcript-lane">
          {LANE_LABEL[u.lane]}
        </span>{" "}
        <span data-testid="transcript-speaker" className="font-semibold text-slate-900">
          {speakerLabel(u.speaker)}
        </span>{" "}
        <time data-testid="transcript-time" dateTime={`PT${Math.floor(u.t_start_ms / 1000)}S`}>
          {mmss(u.t_start_ms)}
        </time>{" "}
        <span className="rounded border border-slate-300 px-1.5 py-0.5" data-testid="transcript-provider">
          {providerChip(u)}
        </span>
        {u.confidence !== null ? <> <span>confidence {u.confidence}</span></> : null}
      </div>{" "}
      <p className="mt-1 text-slate-900" data-testid="transcript-text">
        {u.text}
      </p>{" "}
      <div className="mt-1 flex flex-wrap gap-1" data-testid={`utterance-proposals-${u.id}`}>
        {proposals.map((p) => (
          <button
            type="button"
            key={p.proposal.id}
            data-testid={`chip-proposal-${p.proposal.id}`}
            data-status={p.status}
            className="rounded border border-slate-400 bg-white px-1.5 py-0.5 text-xs hover:bg-slate-100"
            onClick={() => {
              const target = focusTargetFor(state, p);
              if (target) focusById(target);
            }}
            title={p.proposal.rationale}
          >
            {p.proposal.intent} · {p.status}
          </button>
        )).flatMap((chip, i) => (i === 0 ? [chip] : [" ", chip]))}
        {records.map((r) => {
          const text = classificationChip(r);
          return text ? (
            <Fragment key={r.event_id}>
              {" "}
              <span className="rounded border border-dashed border-slate-400 px-1.5 py-0.5 text-xs" data-testid={`chip-classification-${r.event_id}`}>
                {text}
              </span>
            </Fragment>
          ) : null;
        })}
        {classifying ? (
          <span className="rounded border border-dashed border-slate-400 px-1.5 py-0.5 text-xs italic" data-testid="chip-classifying">
            classifying…
          </span>
        ) : null}
      </div>
    </li>
  );
}

export function Transcript() {
  const state = useSession();
  const rows = state.utterances
    .map((u, i) => ({ u, i }))
    .sort((a, b) => a.u.t_start_ms - b.u.t_start_ms || a.i - b.i)
    .map((x) => x.u);
  return (
    <section className="flex h-full min-h-0 flex-col" aria-labelledby="transcript-heading">
      <h2 id="transcript-heading" className="border-b border-slate-300 px-3 py-2 text-sm font-semibold">
        Transcript ({rows.length})
      </h2>
      {/* role="log" sits on the wrapper so the rows keep a real list parent (axe: listitem) */}
      <div role="log" aria-live="polite" aria-relevant="additions" aria-labelledby="transcript-heading" data-testid="transcript" tabIndex={0} className="min-h-0 grow overflow-y-auto">
        <ol className="m-0 list-none p-0">
          {rows.length === 0 ? <li className="px-3 py-2 text-sm text-slate-600">Nothing recorded yet. Start a lane, play the replay or type below.</li> : null}
          {rows.map((u) => (
            <Row key={u.id} u={u} state={state} />
          ))}
        </ol>
      </div>
    </section>
  );
}
