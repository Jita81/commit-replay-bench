// exmap/src/web/components/Board.tsx — the Example Map (design §10.4): four columns, the history toggle, keyboard
// operation (roving tabindex per column, arrows between columns, Enter for the menu, p for provenance, ? for help).
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Card, CardKind } from "../../core/types.js";
import { SHORTCUTS, focusCard, normalizeTabStops, resolveBoardKey } from "../keyboard/rovingFocus.js";
import { useSession } from "../store/useSession.js";
import { Column } from "./Column.js";
import { Drawer } from "./Drawer.js";

const KINDS: CardKind[] = ["story", "rule", "example", "question"];

export interface BoardProps {
  /** Controlled history toggle; uncontrolled (off) when omitted. */
  showHistory?: boolean;
  onShowHistoryChange?: (value: boolean) => void;
}

export function Board({ showHistory: controlled, onShowHistoryChange }: BoardProps) {
  const state = useSession();
  const [uncontrolled, setUncontrolled] = useState(false);
  const showHistory = controlled ?? uncontrolled;
  const setShowHistory = (v: boolean) => {
    setUncontrolled(v);
    onShowHistoryChange?.(v);
  };
  const [help, setHelp] = useState(false);
  const root = useRef<HTMLDivElement | null>(null);

  const byKind: Record<CardKind, Card[]> = { story: [], rule: [], example: [], question: [] };
  for (const id of state.card_order) {
    const card = state.cards[id];
    if (!card) continue;
    const live = card.status === "applied" || card.status === "confirmed";
    if (live || showHistory) byKind[card.kind].push(card);
  }

  useEffect(() => {
    if (root.current) normalizeTabStops(root.current);
  });

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const board = root.current;
    if (!board) return;
    const target = e.target as Element;
    // Keys typed into a form control or a dialog inside the board are theirs.
    if (target.closest("input, textarea, select, [role=dialog], [role=menu], button") && e.key !== "?") return;
    const action = resolveBoardKey(board, target, e.key);
    if (!action) return;
    if (action.kind === "help") {
      if (target.closest("input, textarea")) return;
      e.preventDefault();
      setHelp(true);
      return;
    }
    e.preventDefault();
    if (action.kind === "focus") focusCard(action.target);
    else if (action.kind === "menu") action.card.querySelector<HTMLElement>("[data-menu-button]")?.click();
    else if (action.kind === "provenance") action.card.querySelector<HTMLElement>("[data-provenance-button]")?.click();
  };

  return (
    <section className="flex h-full min-h-0 flex-col" aria-labelledby="board-heading">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-300 px-3 py-2">
        <h2 id="board-heading" className="text-sm font-semibold">
          Map
        </h2>
        <button
          type="button"
          role="switch"
          aria-checked={showHistory}
          data-testid="history-toggle"
          className="flex items-center gap-2 rounded border border-slate-500 px-2 py-0.5 text-xs"
          onClick={() => setShowHistory(!showHistory)}
        >
          <span aria-hidden="true" className={`inline-block h-3 w-6 rounded-full border border-slate-700 ${showHistory ? "bg-slate-800" : "bg-white"}`} />
          Show history (removed, rejected and superseded)
        </button>
        <button type="button" className="rounded border border-slate-400 px-2 py-0.5 text-xs" onClick={() => setHelp(true)} aria-haspopup="dialog" data-testid="board-help">
          Keyboard help (?)
        </button>
      </div>
      <div ref={root} data-testid="board" className="grid min-h-0 grow grid-cols-1 gap-2 overflow-y-auto p-2 md:grid-cols-2 xl:grid-cols-4" onKeyDown={onKeyDown}>
        {KINDS.map((kind) => (
          <Column key={kind} kind={kind} cards={byKind[kind]} showHistory={showHistory} />
        ))}
      </div>
      <Drawer open={help} title="Keyboard shortcuts" testId="help-dialog" onClose={() => setHelp(false)} variant="dialog">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {SHORTCUTS.map((s) => (
            <div key={s.keys} className="contents">
              <dt className="font-mono font-semibold">{s.keys}</dt>
              <dd>{s.does}</dd>
            </div>
          ))}
        </dl>
      </Drawer>
    </section>
  );
}
