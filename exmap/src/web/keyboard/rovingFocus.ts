// exmap/src/web/keyboard/rovingFocus.ts — keyboard operation of the board (design §10.4, §10.8): a roving tabindex per
// column (ArrowDown/ArrowUp, Home/End), ArrowRight/ArrowLeft to the neighbouring column's active card, Enter/Space for
// the card menu, `p` for provenance, `?` for the shortcut list. Pure DOM functions so the logic is testable.

export const CARD_SELECTOR = '[data-testid^="card-"][data-card]';
export const COLUMN_SELECTOR = '[data-testid^="column-"][data-column]';

export type BoardAction = { kind: "focus"; target: HTMLElement } | { kind: "menu"; card: HTMLElement } | { kind: "provenance"; card: HTMLElement } | { kind: "help" } | null;

export function cardsOf(column: Element): HTMLElement[] {
  return Array.from(column.querySelectorAll<HTMLElement>(CARD_SELECTOR));
}

export function columnsOf(board: Element): HTMLElement[] {
  return Array.from(board.querySelectorAll<HTMLElement>(COLUMN_SELECTOR));
}

/** The column's active card: the one with tabindex 0, else its first card. */
export function activeCardOf(column: Element): HTMLElement | null {
  const cards = cardsOf(column);
  return cards.find((c) => c.tabIndex === 0) ?? cards[0] ?? null;
}

/** Makes `card` the only tab stop of its column. */
export function setActive(column: Element, card: HTMLElement): void {
  for (const c of cardsOf(column)) c.tabIndex = c === card ? 0 : -1;
}

/** Ensures every column has exactly one tab stop (after a render added or removed cards). */
export function normalizeTabStops(board: Element): void {
  for (const column of columnsOf(board)) {
    const cards = cardsOf(column);
    if (cards.length === 0) continue;
    const active = cards.find((c) => c.tabIndex === 0) ?? cards[0]!;
    setActive(column, active);
  }
}

/** Resolves a keydown on a card into an action; the caller performs it (focus, open menu, …). */
export function resolveBoardKey(board: Element, target: Element, key: string): BoardAction {
  if (key === "?") return { kind: "help" };
  const card = target.closest<HTMLElement>(CARD_SELECTOR);
  if (!card) return null;
  const column = card.closest<HTMLElement>(COLUMN_SELECTOR);
  if (!column) return null;
  const cards = cardsOf(column);
  const index = cards.indexOf(card);
  switch (key) {
    case "ArrowDown":
      return cards[index + 1] ? { kind: "focus", target: cards[index + 1]! } : null;
    case "ArrowUp":
      return cards[index - 1] ? { kind: "focus", target: cards[index - 1]! } : null;
    case "Home":
      return cards[0] && cards[0] !== card ? { kind: "focus", target: cards[0] } : null;
    case "End": {
      const last = cards[cards.length - 1];
      return last && last !== card ? { kind: "focus", target: last } : null;
    }
    case "ArrowRight":
    case "ArrowLeft": {
      const columns = columnsOf(board);
      const ci = columns.indexOf(column);
      const step = key === "ArrowRight" ? 1 : -1;
      for (let j = ci + step; j >= 0 && j < columns.length; j += step) {
        const next = activeCardOf(columns[j]!);
        if (next) return { kind: "focus", target: next };
      }
      return null;
    }
    case "Enter":
    case " ":
      return { kind: "menu", card };
    case "p":
    case "P":
      return { kind: "provenance", card };
    default:
      return null;
  }
}

/** Focuses a card and makes it its column's tab stop. */
export function focusCard(card: HTMLElement): void {
  const column = card.closest<HTMLElement>(COLUMN_SELECTOR);
  if (column) setActive(column, card);
  card.focus();
}

export const SHORTCUTS: ReadonlyArray<{ keys: string; does: string }> = [
  { keys: "↓ / ↑", does: "next / previous card in the column" },
  { keys: "Home / End", does: "first / last card in the column" },
  { keys: "→ / ←", does: "the neighbouring column's active card" },
  { keys: "Enter / Space", does: "open the card menu" },
  { keys: "p", does: "open the card's provenance" },
  { keys: "Esc", does: "close a menu, popover or dialog" },
  { keys: "?", does: "this list" },
];
