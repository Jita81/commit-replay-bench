// exmap/src/web/components/CardMenu.tsx — the per-card menu (design §10.4): role="menu" with Confirm, Edit, Remove
// (with a confirm step) and, for an unanswered question, Accept as outstanding (with a required reason). Arrow keys
// move between items; Escape closes and the opener restores focus.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Card } from "../../core/types.js";

export interface CardMenuProps {
  card: Card;
  id: string;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => void;
  onEdit: () => void;
  onRemove: () => void;
  onAcceptOutstanding: (reason: string) => void;
}

export function CardMenu({ card, id, pending, onClose, onConfirm, onEdit, onRemove, onAcceptOutstanding }: CardMenuProps) {
  const root = useRef<HTMLDivElement | null>(null);
  const [removing, setRemoving] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => {
    const first = root.current?.querySelector<HTMLElement>('[role="menuitem"]');
    first?.focus();
  }, []);

  const items = () => Array.from(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.stopPropagation();
      e.preventDefault();
      const list = items();
      const i = list.indexOf(document.activeElement as HTMLElement);
      const next = e.key === "ArrowDown" ? list[(i + 1) % list.length] : list[(i - 1 + list.length) % list.length];
      next?.focus();
      return;
    }
    if (e.key === "Enter" || e.key === " ") {
      // let the focused menuitem's click fire; stop the board from reopening the menu
      e.stopPropagation();
    }
  };

  const canAccept = card.kind === "question" && card.answer === null && card.accepted_outstanding === null;
  const canConfirm = card.status !== "confirmed";

  return (
    <div
      ref={root}
      id={id}
      role="menu"
      aria-label={`Actions for ${card.kind}`}
      data-testid={`card-menu-${card.id}`}
      className="absolute right-0 top-full z-20 mt-1 flex w-64 flex-col rounded border border-slate-500 bg-white p-1 text-sm text-slate-900 shadow-lg"
      onKeyDown={onKeyDown}
    >
      <button type="button" role="menuitem" data-testid={`card-confirm-${card.id}`} className="rounded px-2 py-1 text-left hover:bg-slate-100 disabled:opacity-50" disabled={pending || !canConfirm} onClick={onConfirm}>
        Confirm{card.status === "confirmed" ? " (already confirmed)" : ""}
      </button>
      <button type="button" role="menuitem" data-testid={`card-edit-${card.id}`} className="rounded px-2 py-1 text-left hover:bg-slate-100" onClick={onEdit}>
        Edit
      </button>
      {removing ? (
        <div className="flex flex-col gap-1 rounded border border-red-700 bg-red-50 p-2" role="group" aria-label="Confirm removal">
          <span>Remove this {card.kind}? It stays in the history.</span>
          <div className="flex gap-2">
            <button type="button" role="menuitem" data-testid={`card-remove-confirm-${card.id}`} className="rounded border border-red-700 px-2 py-0.5" disabled={pending} onClick={onRemove}>
              Confirm remove
            </button>
            <button type="button" role="menuitem" className="rounded border border-slate-400 px-2 py-0.5" onClick={() => setRemoving(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button type="button" role="menuitem" data-testid={`card-remove-${card.id}`} className="rounded px-2 py-1 text-left hover:bg-slate-100" onClick={() => setRemoving(true)}>
          Remove…
        </button>
      )}
      {canAccept ? (
        accepting ? (
          <div className="flex flex-col gap-1 rounded border border-slate-400 p-2" role="group" aria-label="Accept as outstanding">
            <label className="flex flex-col gap-1 text-xs">
              Reason (required; the question stays unanswered)
              <input data-testid={`card-accept-reason-${card.id}`} className="rounded border border-slate-400 px-1 py-0.5" value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                role="menuitem"
                data-testid={`card-accept-confirm-${card.id}`}
                className="rounded border border-slate-600 px-2 py-0.5 disabled:opacity-50"
                disabled={pending || reason.trim().length === 0}
                onClick={() => onAcceptOutstanding(reason.trim())}
              >
                Accept as outstanding
              </button>
              <button type="button" role="menuitem" className="rounded border border-slate-400 px-2 py-0.5" onClick={() => setAccepting(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button type="button" role="menuitem" data-testid={`card-accept-outstanding-${card.id}`} className="rounded px-2 py-1 text-left hover:bg-slate-100" onClick={() => setAccepting(true)}>
            Accept as outstanding…
          </button>
        )
      ) : null}
      <button type="button" role="menuitem" className="rounded px-2 py-1 text-left text-xs text-slate-700 hover:bg-slate-100" onClick={onClose}>
        Close menu
      </button>
    </div>
  );
}
