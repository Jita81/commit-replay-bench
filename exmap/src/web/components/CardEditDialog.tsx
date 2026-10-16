// exmap/src/web/components/CardEditDialog.tsx — a UI edit is a human card.update (design §10.4): the text, a rule
// select for examples (how an unattached example is linked), an answer field for questions (how one is answered by hand).
import { useState } from "react";
import { select } from "../../core/index.js";
import type { Card, CardPatch } from "../../core/types.js";
import { excerpt } from "../format.js";
import { useSession } from "../store/useSession.js";
import { Drawer } from "./Drawer.js";

export interface CardEditDialogProps {
  card: Card;
  open: boolean;
  pending: boolean;
  onClose: () => void;
  onSave: (patch: CardPatch) => void;
}

export function CardEditDialog({ card, open, pending, onClose, onSave }: CardEditDialogProps) {
  const state = useSession();
  const [text, setText] = useState(card.text);
  const [ruleId, setRuleId] = useState<string>(card.kind === "example" ? (card.rule_id ?? "") : "");
  const [about, setAbout] = useState<string>(card.kind === "question" ? (card.about_card_id ?? "") : "");
  const [answer, setAnswer] = useState<string>(card.kind === "question" ? (card.answer ?? "") : "");
  const rules = select.cardsByKind(state, "rule");
  const live = select.liveCards(state).filter((c) => c.id !== card.id);

  const patch = (): CardPatch => {
    const p: CardPatch = {};
    if (text.trim() !== card.text) p.text = text.trim();
    if (card.kind === "example" && (ruleId || null) !== card.rule_id) p.rule_id = ruleId || null;
    if (card.kind === "question") {
      if ((about || null) !== card.about_card_id) p.about_card_id = about || null;
      if ((answer.trim() || null) !== card.answer) p.answer = answer.trim() || null;
    }
    return p;
  };
  const changed = Object.keys(patch()).length > 0;

  return (
    <Drawer open={open} title={`Edit ${card.kind}`} testId="card-edit-dialog" onClose={onClose} variant="dialog">
      <label className="flex flex-col gap-1 text-sm">
        Text
        <textarea data-testid="card-edit-text" className="min-h-24 rounded border border-slate-400 p-2" value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      {card.kind === "example" ? (
        <label className="flex flex-col gap-1 text-sm">
          For rule
          <select data-testid="card-edit-rule" className="rounded border border-slate-400 p-1" value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
            <option value="">(not attached to a rule)</option>
            {rules.map((r) => (
              <option key={r.id} value={r.id}>
                {excerpt(r.text, 70)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {card.kind === "question" ? (
        <>
          <label className="flex flex-col gap-1 text-sm">
            About
            <select data-testid="card-edit-about" className="rounded border border-slate-400 p-1" value={about} onChange={(e) => setAbout(e.target.value)}>
              <option value="">(not about a particular card)</option>
              {live.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.kind}: {excerpt(c.text, 60)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Answer (leave empty to keep the question open)
            <textarea data-testid="card-edit-answer" className="min-h-16 rounded border border-slate-400 p-2" value={answer} onChange={(e) => setAnswer(e.target.value)} />
          </label>
        </>
      ) : null}
      <div className="flex gap-2">
        <button type="button" data-testid="card-edit-save" className="rounded border border-slate-700 bg-slate-800 px-3 py-1 text-white disabled:opacity-50" disabled={!changed || pending || text.trim().length === 0} onClick={() => onSave(patch())}>
          Save{pending ? " (pending…)" : ""}
        </button>
        <button type="button" className="rounded border border-slate-400 px-3 py-1" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Drawer>
  );
}
