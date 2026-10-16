// exmap/src/web/components/Column.tsx — one Example Mapping column (design §10.4): story yellow, rules blue, examples
// green, questions red, each with text-slate-900 (status is never conveyed by colour alone), an "Add card" form, and
// a <ul role="list"> of cards.
import { useState } from "react";
import { select } from "../../core/index.js";
import type { Card, CardKind, NewCard } from "../../core/types.js";
import { KIND_LABEL, KIND_SINGULAR, excerpt } from "../format.js";
import { useAct, useApi, useSession } from "../store/useSession.js";
import { CardView } from "./CardView.js";

export const COLUMN_CLASS: Record<CardKind, string> = {
  story: "bg-yellow-100",
  rule: "bg-sky-100",
  example: "bg-green-100",
  question: "bg-red-100",
};

export interface ColumnProps {
  kind: CardKind;
  cards: Card[];
  showHistory: boolean;
}

export function Column({ kind, cards, showHistory }: ColumnProps) {
  const state = useSession();
  const api = useApi();
  const act = useAct();
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [link, setLink] = useState("");
  const live = cards.filter((c) => c.status === "applied" || c.status === "confirmed");
  const headingId = `column-${kind}-heading`;
  const hasStory = select.story(state) !== null;
  const linkOptions = kind === "example" ? select.cardsByKind(state, "rule") : kind === "question" ? select.liveCards(state) : [];

  const submit = async () => {
    const t = text.trim();
    if (!t) return;
    let card: NewCard;
    if (kind === "example") card = { kind, text: t, rule_id: link || null };
    else if (kind === "question") card = { kind, text: t, about_card_id: link || null };
    else card = { kind, text: t };
    const r = await act.run((actor) => api.createCard(actor, card));
    if (r) {
      setText("");
      setLink("");
      setAdding(false);
    }
  };

  return (
    <section
      role="region"
      aria-labelledby={headingId}
      data-testid={`column-${kind}`}
      data-column
      data-kind={kind}
      className={`flex min-h-0 flex-col rounded border border-slate-300 ${COLUMN_CLASS[kind]} text-slate-900`}
    >
      <div className="flex items-center justify-between px-2 py-1">
        <h3 id={headingId} className="text-sm font-semibold">
          {KIND_LABEL[kind]} ({live.length})
        </h3>
        {kind !== "story" || !hasStory ? (
          <button type="button" data-testid={`column-add-${kind}`} className="rounded border border-slate-500 bg-white/60 px-1.5 py-0.5 text-xs" aria-expanded={adding} onClick={() => setAdding((v) => !v)}>
            Add {KIND_SINGULAR[kind]}
          </button>
        ) : null}
      </div>
      {adding ? (
        <form
          className="mx-2 mb-2 flex flex-col gap-1 rounded border border-slate-400 bg-white/70 p-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="flex flex-col gap-1">
            New {KIND_SINGULAR[kind]} text
            <textarea data-testid={`column-add-text-${kind}`} className="min-h-16 rounded border border-slate-400 p-1" value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          {kind === "example" || kind === "question" ? (
            <label className="flex flex-col gap-1">
              {kind === "example" ? "For rule" : "About"}
              <select data-testid={`column-add-link-${kind}`} className="rounded border border-slate-400 p-1" value={link} onChange={(e) => setLink(e.target.value)}>
                <option value="">{kind === "example" ? "(not attached to a rule)" : "(no particular card)"}</option>
                {linkOptions.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.kind}: {excerpt(c.text, 60)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="flex gap-2">
            <button type="submit" data-testid={`column-add-submit-${kind}`} className="rounded border border-slate-700 bg-slate-800 px-2 py-0.5 text-white disabled:opacity-50" disabled={act.pending || text.trim().length === 0}>
              Add{act.pending ? " (pending…)" : ""}
            </button>
            <button type="button" className="rounded border border-slate-400 px-2 py-0.5" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      <ul role="list" className="flex min-h-0 grow flex-col gap-2 overflow-y-auto px-2 pb-2" data-testid={`column-list-${kind}`}>
        {cards.map((card) => (
          <CardView key={card.id} card={card} history={showHistory && card.status !== "applied" && card.status !== "confirmed"} />
        ))}
        {cards.length === 0 ? <li className="text-xs text-slate-700">No {KIND_LABEL[kind].toLowerCase()} yet.</li> : null}
      </ul>
    </section>
  );
}
