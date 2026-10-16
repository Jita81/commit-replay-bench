// exmap/src/web/components/ReviewDrawer.tsx — human-verified completion (design §10.6): the five DoD checks with
// "Mark reviewed" previews on 1, 2 and 4 and in-place Accept / Reject for check 3's unreviewed acts, outstanding
// questions accepted with a reason (never "answered"), the catching-up gate, the sign-off form and the invalidation notice.
import { useEffect, useState } from "react";
import { SIGNOFF_CONFIRMATION_TEXT, isHumanVerified, select } from "../../core/index.js";
import { describeAct } from "../../core/dod.js";
import type { DodCheck, DodCheckId, DodReport, ExmapEvent, MapState, Signoff } from "../../core/types.js";
import { ApiError } from "../api/client.js";
import { excerpt, hash8, timeOf } from "../format.js";
import { useAct, useActor, useApi, useDod, useSession, useToast } from "../store/useSession.js";
import { Drawer } from "./Drawer.js";

export interface ReviewDrawerProps {
  open: boolean;
  onClose: () => void;
  /** The audio controller's pendingWork(); 0 when there is no audio pipeline. */
  pendingWork?: () => number;
  returnFocusTo?: HTMLElement | null;
}

const MARKABLE: ReadonlySet<DodCheckId> = new Set(["story_rules_confirmed", "examples_reviewed", "questions_resolved"]);

/** The exact card list a "Mark reviewed" sends (§8.5): the list the person sees in the preview. */
export function markList(state: MapState, check: DodCheckId): string[] {
  switch (check) {
    case "story_rules_confirmed":
      return [...select.cardsByKind(state, "story"), ...select.cardsByKind(state, "rule")].filter((c) => c.status !== "confirmed").map((c) => c.id);
    case "examples_reviewed":
      return select.cardsByKind(state, "example").filter((c) => c.status !== "confirmed" || c.needs_review !== null).map((c) => c.id);
    case "questions_resolved":
      return select.cardsByKind(state, "question").filter((c) => c.answer !== null && c.status !== "confirmed").map((c) => c.id);
    default:
      return [];
  }
}

function invalidationText(state: MapState, signoff: Signoff): string {
  const inv = signoff.invalidated!;
  const by = state.revisions.find((r) => r.event_id === inv.by_event_id);
  const type = by?.cause ?? "a later event";
  return `The sign-off by ${signoff.reviewer.name} (${timeOf(signoff.at)}, revision ${hash8(signoff.revision.hash)}) was invalidated by ${type} at ${timeOf(by?.at ?? null)} (revision ${hash8(inv.to_revision.hash)}). Review the map and sign off again.`;
}

function CheckRow({ check, children }: { check: DodCheck; children?: React.ReactNode }) {
  return (
    <li data-testid={`dod-check-${check.id}`} data-pass={check.pass ? "true" : "false"} className={`rounded border p-2 ${check.pass ? "border-green-700 bg-green-50" : "border-red-700 bg-red-50"}`}>
      <div className="flex items-start gap-2">
        <span data-testid={`dod-check-status-${check.id}`} className={`rounded px-1.5 py-0.5 text-xs font-semibold ${check.pass ? "bg-green-200 text-green-950" : "bg-red-200 text-red-950"}`}>
          {check.pass ? "passes" : "fails"}
        </span>
        <span className="text-sm font-semibold">{check.title}</span>
      </div>
      {check.details.length > 0 ? (
        <ul className="mt-1 list-inside list-disc text-xs" data-testid={`dod-details-${check.id}`}>
          {check.details.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      ) : null}
      {children}
    </li>
  );
}

export function ReviewDrawer({ open, onClose, pendingWork, returnFocusTo }: ReviewDrawerProps) {
  const state = useSession();
  const dod: DodReport = useDod();
  const api = useApi();
  const act = useAct();
  const { actor } = useActor();
  const toast = useToast();
  const [preview, setPreview] = useState<{ check: DodCheckId; ids: string[] } | null>(null);
  const [reason, setReason] = useState("");
  const [backlog, setBacklog] = useState(0);
  const [anyway, setAnyway] = useState(false);
  const [reviewer, setReviewer] = useState(actor);
  const [statement, setStatement] = useState("");
  const [signErrors, setSignErrors] = useState<DodReport | { reason: string; detail: string } | null>(null);
  const [signed, setSigned] = useState<{ text: string; revision: string } | null>(null);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    if (!open) return;
    setReviewer((r) => r || actor);
    const read = () => setBacklog(pendingWork ? pendingWork() : 0);
    read();
    const handle = setInterval(read, 1000);
    return () => clearInterval(handle);
  }, [open, pendingWork, actor]);

  const revision = select.currentRevision(state);
  const verified = isHumanVerified(state);
  const last = select.lastSignoff(state);
  // the response-derived line only bridges the moment before the signoff.recorded event lands; the ledger wins after
  useEffect(() => setSigned(null), [last?.id, last?.status]);
  const active = select.activeSignoff(state);
  const check3 = dod.checks.find((c) => c.id === "changes_resolved")!;
  const openClarifications = select.openClarifications(state);
  const unreviewed = select.unreviewedActs(state);
  const questions = select.cardsByKind(state, "question");
  const outstanding = questions.filter((q) => q.answer === null && q.accepted_outstanding === null);
  const accepted = questions.filter((q) => q.accepted_outstanding !== null);
  const gateBlocked = backlog > 0 && !anyway;
  const canSubmit = reviewer.trim().length > 0 && statement.trim().length > 0 && !gateBlocked && !signing;

  const submitSignoff = async () => {
    setSigning(true);
    setSignErrors(null);
    try {
      const res = await api.signoff(reviewer.trim(), statement.trim(), revision.hash);
      const recorded = res.events.find((e): e is Extract<ExmapEvent, { type: "signoff.recorded" }> => e.type === "signoff.recorded");
      if (recorded) {
        setSigned({
          text: `Signed off by ${recorded.signoff.reviewer.name} at ${timeOf(recorded.at)} on revision ${hash8(recorded.signoff.revision.hash)} (evidence head ${recorded.signoff.evidence.head_seq})`,
          revision: recorded.signoff.revision.hash,
        });
      }
      toast("Sign-off recorded");
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.checks) setSignErrors(e.checks);
        else setSignErrors({ reason: e.reason, detail: e.detail });
      } else {
        setSignErrors({ reason: "NETWORK", detail: e instanceof Error ? e.message : String(e) });
      }
    } finally {
      setSigning(false);
    }
  };

  const statusLine = active && verified ? `Human verified by ${active.reviewer.name} at ${timeOf(active.at)}` : "Not verified";
  const signedFromState = active ? `Signed off by ${active.reviewer.name} at ${timeOf(active.at)} on revision ${hash8(active.revision.hash)} (evidence head ${active.evidence.head_seq})` : null;
  const signoffStatus = signedFromState ?? (signed && signed.revision === revision.hash ? signed.text : null);

  return (
    <Drawer open={open} title="Review and sign off" testId="review-drawer" onClose={onClose} returnFocusTo={returnFocusTo} wide>
      <p className="text-sm" data-testid="review-status">
        Revision {revision.seq} · <span className="font-mono">{hash8(revision.hash)}</span> — <span data-testid="review-verified">{statusLine}</span>
      </p>
      {last && last.status === "invalidated" ? (
        <p role="status" data-testid="signoff-invalidated" className="rounded border border-amber-700 bg-amber-50 p-2 text-sm text-amber-950">
          {invalidationText(state, last)}
        </p>
      ) : null}
      {active && !verified ? (
        <p role="status" data-testid="signoff-not-current" className="rounded border border-amber-700 bg-amber-50 p-2 text-sm text-amber-950">
          Signed off on this revision, but not currently verified: {check3.details.filter((d) => !/ is reviewed$/.test(d)).join("; ") || "a check regressed"}
        </p>
      ) : null}

      <h3 className="text-sm font-semibold">Definition of Done</h3>
      <ol className="flex flex-col gap-2" data-testid="dod-checks">
        {dod.checks.map((check) => (
          <CheckRow key={check.id} check={check}>
            {MARKABLE.has(check.id) ? (
              <div className="mt-2 flex flex-col gap-1">
                {preview?.check === check.id ? (
                  <div className="rounded border border-slate-400 bg-white p-2 text-xs" data-testid={`dod-mark-list-${check.id}`}>
                    <div className="font-semibold">This records a confirmation, as {actor || "(set your name)"}, of exactly these cards:</div>
                    <ul className="list-inside list-disc">
                      {preview.ids.map((id) => (
                        <li key={id} data-card-id={id}>
                          {state.cards[id]?.kind ?? "card"} {id}: {state.cards[id]?.text ?? "(not in the map)"}
                        </li>
                      ))}
                      {preview.ids.length === 0 ? <li>nothing to confirm</li> : null}
                    </ul>
                  </div>
                ) : null}
                <div className="flex gap-2">
                  <button
                    type="button"
                    data-testid={`dod-mark-${check.id}`}
                    className="self-start rounded border border-slate-600 bg-white px-2 py-0.5 text-xs disabled:opacity-50"
                    disabled={preview?.check === check.id && (act.pending || preview.ids.length === 0)}
                    onClick={() => {
                      if (preview?.check !== check.id) {
                        // first press: preview the exact list; the second press sends that list, not a recomputed one
                        setPreview({ check: check.id, ids: markList(state, check.id) });
                        return;
                      }
                      const ids = preview.ids;
                      void act.run((a) => api.reviewChecks(a, check.id, ids)).then((r) => {
                        if (r) setPreview(null);
                      });
                    }}
                  >
                    {preview?.check === check.id ? `Confirm these ${preview.ids.length} cards${act.pending ? " (pending…)" : ""}` : "Mark reviewed…"}
                  </button>
                  {preview?.check === check.id ? (
                    <button type="button" data-testid={`dod-mark-cancel-${check.id}`} className="rounded border border-slate-400 px-2 py-0.5 text-xs" onClick={() => setPreview(null)}>
                      Cancel
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}
            {check.id === "changes_resolved" && (openClarifications.length > 0 || unreviewed.length > 0) ? (
              <div className="mt-2 flex flex-col gap-1 text-xs">
                {openClarifications.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    data-testid={`dod-clarification-${c.id}`}
                    className="self-start rounded border border-slate-500 bg-white px-2 py-0.5 text-left underline"
                    onClick={() => {
                      onClose();
                      setTimeout(() => document.getElementById(`clarification-${c.id}`)?.focus(), 0);
                    }}
                  >
                    Open clarification in the tray: “{excerpt(c.question, 80)}”
                  </button>
                ))}
                {unreviewed.map((record) => (
                  <div key={record.proposal.id} className="flex flex-wrap items-center gap-2" data-testid={`dod-act-${record.proposal.id}`}>
                    <span>{describeAct(state, record)}</span>
                    <button type="button" data-testid={`dod-act-accept-${record.proposal.id}`} className="rounded border border-green-800 bg-green-100 px-2 py-0.5 font-semibold disabled:opacity-50" disabled={act.pending} onClick={() => void act.run((a) => api.acceptProposal(record.proposal.id, a))}>
                      Accept
                    </button>
                    <button type="button" data-testid={`dod-act-reject-${record.proposal.id}`} className="rounded border border-red-800 bg-red-100 px-2 py-0.5 font-semibold disabled:opacity-50" disabled={act.pending} onClick={() => void act.run((a) => api.rejectProposal(record.proposal.id, a))}>
                      {record.proposal.operation?.kind === "card.remove" ? "Restore" : record.proposal.operation?.kind === "undo" ? "Redo" : "Reject"}
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </CheckRow>
        ))}
      </ol>

      <h3 className="text-sm font-semibold">Outstanding questions</h3>
      {outstanding.length > 0 ? (
        <div className="flex flex-col gap-2 text-sm" data-testid="outstanding-questions">
          <label className="flex flex-col gap-1 text-xs">
            Reason for accepting a question as outstanding (required; the question stays unanswered)
            <input data-testid="question-accept-reason" className="rounded border border-slate-400 px-1.5 py-0.5" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <ul className="flex flex-col gap-1">
            {outstanding.map((q) => (
              <li key={q.id} className="flex flex-wrap items-center gap-2" data-testid={`outstanding-${q.id}`}>
                <span>{excerpt(q.text, 90)}</span>
                <button
                  type="button"
                  data-testid={`question-accept-${q.id}`}
                  className="rounded border border-slate-600 bg-white px-2 py-0.5 text-xs disabled:opacity-50"
                  disabled={act.pending || reason.trim().length === 0}
                  onClick={() => void act.run((a) => api.acceptQuestion(q.id, a, reason.trim()))}
                >
                  Accept as outstanding
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-slate-700">No open question is waiting for a decision.</p>
      )}
      {accepted.length > 0 ? (
        <ul className="text-xs" data-testid="accepted-questions">
          {accepted.map((q) => (
            <li key={q.id}>
              “{excerpt(q.text, 70)}” — accepted outstanding by {q.accepted_outstanding!.by}: {q.accepted_outstanding!.reason}
            </li>
          ))}
        </ul>
      ) : null}

      <h3 className="text-sm font-semibold">Sign-off</h3>
      {backlog > 0 ? (
        <div role="status" data-testid="review-catching-up" className="rounded border border-amber-700 bg-amber-50 p-2 text-xs text-amber-950">
          Transcription is still catching up ({backlog} segments or utterances on their way into the ledger).
          <label className="mt-1 flex items-center gap-2">
            <input type="checkbox" data-testid="signoff-anyway" checked={anyway} onChange={(e) => setAnyway(e.target.checked)} />
            Sign off anyway (the map may still change)
          </label>
        </div>
      ) : null}
      <form
        className="flex flex-col gap-2 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) void submitSignoff();
        }}
      >
        <label className="flex flex-col gap-1 text-xs">
          Reviewer (self-asserted)
          <input data-testid="signoff-reviewer" className="rounded border border-slate-400 px-1.5 py-0.5" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </label>
        <div className="flex flex-col gap-1 text-xs">
          <label htmlFor="signoff-statement-field">{SIGNOFF_CONFIRMATION_TEXT}</label>
          <div className="flex items-center gap-2">
            <span className="text-slate-700">Type the sentence above exactly, or</span>
            <button type="button" data-testid="signoff-insert" className="rounded border border-slate-500 px-1.5" onClick={() => setStatement(SIGNOFF_CONFIRMATION_TEXT)}>
              Insert sentence
            </button>
          </div>
          <textarea id="signoff-statement-field" data-testid="signoff-statement" className="min-h-16 rounded border border-slate-400 p-1.5" value={statement} onChange={(e) => setStatement(e.target.value)} />
        </div>
        <label className="flex flex-col gap-1 text-xs">
          Cited revision (read-only)
          <input data-testid="signoff-revision" readOnly className="rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono" value={`${revision.seq} · ${revision.hash}`} />
        </label>
        <button type="submit" data-testid="signoff-submit" className="self-start rounded border border-slate-700 bg-slate-800 px-3 py-1 text-white disabled:opacity-50" disabled={!canSubmit}>
          Record sign-off{signing ? " (pending…)" : ""}
        </button>
      </form>
      {signErrors ? (
        <div role="alert" data-testid="signoff-errors" className="rounded border border-red-700 bg-red-50 p-2 text-xs text-red-900">
          {"checks" in signErrors ? (
            <>
              <div className="font-semibold">The sign-off was refused: these checks fail</div>
              <ul className="list-inside list-disc">
                {signErrors.checks
                  .filter((c) => !c.pass)
                  .map((c) => (
                    <li key={c.id}>
                      {c.title}: {c.details.join("; ")}
                    </li>
                  ))}
              </ul>
            </>
          ) : (
            <div>
              {signErrors.reason}: {signErrors.detail}
            </div>
          )}
        </div>
      ) : null}
      {signoffStatus ? (
        <p role="status" data-testid="signoff-status" className="rounded border border-green-700 bg-green-50 p-2 text-sm text-green-950">
          {signoffStatus}
        </p>
      ) : null}
    </Drawer>
  );
}
