// exmap/src/web/components/ClarificationItem.tsx — an open clarification in the tray (design §10.5): the question, the
// "Will: …" line, text answers so far, one button per candidate (template) or one Yes (pending operation), always an
// "Answer in words" field and Dismiss with a reason. A refused answer shows the refusal and keeps Dismiss.
import { useState } from "react";
import type { Clarification } from "../../core/types.js";
import { KIND_SINGULAR, describeOperation, describeTemplate, excerpt } from "../format.js";
import { useAct, useApi, useSession } from "../store/useSession.js";

export interface ClarificationItemProps {
  clarification: Clarification;
}

export function ClarificationItem({ clarification: c }: ClarificationItemProps) {
  const state = useSession();
  const api = useApi();
  const act = useAct();
  const [text, setText] = useState("");
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const asking = state.proposals[c.proposal_id];
  const will = c.template ? `Will: ${describeTemplate(state, c.template, c.candidates.map((x) => x.card_id))}` : c.pending_operation ? `Will: ${describeOperation(state, c.pending_operation)}` : null;
  const headingId = `clarification-${c.id}-question`;

  return (
    <li className="list-none">
    {/* the group is inside the <li> so the tray's list keeps only listitems (axe: list) */}
    <div
      id={`clarification-${c.id}`}
      data-testid={`clarification-${c.id}`}
      data-status={c.status}
      role="group"
      aria-labelledby={headingId}
      tabIndex={-1}
      className="flex flex-col gap-1 rounded border-2 border-red-700 bg-white p-2 text-sm text-slate-900 focus-visible:ring-2 focus-visible:ring-slate-900"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-red-700 px-1.5 py-0.5 font-semibold text-white">clarification</span>
        {asking ? (
          <span className="rounded border border-slate-300 px-1.5 py-0.5">
            {asking.proposal.intent} · {asking.proposal.classifier.provider}
            {asking.proposal.classifier.fallback_from ? ` (fallback from ${asking.proposal.classifier.fallback_from})` : ""} · confidence {asking.proposal.confidence}
          </span>
        ) : null}
      </div>
      <p id={headingId} className="font-semibold" data-testid={`clarification-question-${c.id}`}>
        {c.question}
      </p>
      {will ? (
        <p className="text-xs" data-testid={`clarification-will-${c.id}`}>
          {will}
        </p>
      ) : null}
      {c.text_answers.length > 0 ? (
        <ul className="text-xs text-slate-700" data-testid={`clarification-text-answers-${c.id}`}>
          {c.text_answers.map((a) => (
            <li key={a.event_id}>
              answered in words by {a.actor}: “{a.text}” — still open
            </li>
          ))}
        </ul>
      ) : null}
      {c.template !== null && c.candidates.length > 0 ? (
        <div className="flex flex-col gap-1" role="group" aria-label="Candidates">
          {c.candidates.map((cand) => {
            const card = state.cards[cand.card_id];
            const label = card ? `${excerpt(card.text, 60)} (${KIND_SINGULAR[card.kind]})` : cand.label;
            return (
              <button
                key={cand.card_id}
                type="button"
                data-testid={`clarification-candidate-${c.id}-${cand.card_id}`}
                className="rounded border border-slate-600 bg-slate-50 px-2 py-1 text-left text-xs hover:bg-slate-100 disabled:opacity-50"
                disabled={act.pending}
                onClick={() => void act.run((actor) => api.answerClarification(c.id, actor, { kind: "candidate", card_id: cand.card_id }), { quiet: true })}
              >
                {label}
                {cand.score !== null ? ` · score ${cand.score}` : ""}
              </button>
            );
          })}
        </div>
      ) : null}
      {c.pending_operation !== null ? (
        <button
          type="button"
          data-testid={`clarification-yes-${c.id}`}
          className="rounded border border-green-800 bg-green-100 px-2 py-1 text-left text-xs font-semibold disabled:opacity-50"
          disabled={act.pending}
          onClick={() => void act.run((actor) => api.answerClarification(c.id, actor, { kind: "yes" }), { quiet: true })}
        >
          Yes — {describeOperation(state, c.pending_operation)}
        </button>
      ) : null}
      <form
        className="flex gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          const t = text.trim();
          if (!t) return;
          void act.run((actor) => api.answerClarification(c.id, actor, { kind: "text", text: t }), { quiet: true }).then((r) => {
            if (r) setText("");
          });
        }}
      >
        <label className="sr-only" htmlFor={`clarification-text-${c.id}`}>
          Answer in words
        </label>
        <input id={`clarification-text-${c.id}`} data-testid={`clarification-text-${c.id}`} className="grow rounded border border-slate-400 px-1.5 py-0.5 text-xs" placeholder="Answer in words" value={text} onChange={(e) => setText(e.target.value)} />
        <button type="submit" data-testid={`clarification-text-submit-${c.id}`} className="rounded border border-slate-600 px-2 py-0.5 text-xs disabled:opacity-50" disabled={act.pending || text.trim().length === 0}>
          Send
        </button>
      </form>
      {dismissing ? (
        <form
          className="flex flex-col gap-1 rounded border border-slate-400 p-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            const r = reason.trim();
            if (!r) return;
            void act.run((actor) => api.answerClarification(c.id, actor, { kind: "dismiss", reason: r }), { quiet: true });
          }}
        >
          <label className="flex flex-col gap-1 text-xs">
            Why dismiss this question? (required)
            <input data-testid={`clarification-dismiss-reason-${c.id}`} className="rounded border border-slate-400 px-1.5 py-0.5" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="flex gap-2">
            <button type="submit" data-testid={`clarification-dismiss-confirm-${c.id}`} className="rounded border border-slate-600 px-2 py-0.5 text-xs disabled:opacity-50" disabled={act.pending || reason.trim().length === 0}>
              Dismiss
            </button>
            <button type="button" className="rounded border border-slate-400 px-2 py-0.5 text-xs" onClick={() => setDismissing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button type="button" data-testid={`clarification-dismiss-${c.id}`} className="self-start rounded border border-slate-400 px-2 py-0.5 text-xs" onClick={() => setDismissing(true)}>
          Dismiss…
        </button>
      )}
      {act.error ? (
        <div className="text-xs text-red-800" role="alert" data-testid={`clarification-error-${c.id}`}>
          Refused — {act.error.reason}: {act.error.detail}
        </div>
      ) : null}
      {act.pending ? <div className="text-xs text-slate-600">pending…</div> : null}
    </div>
    </li>
  );
}
