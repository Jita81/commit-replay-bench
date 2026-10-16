// exmap/src/web/components/CardView.tsx — one card on the board (design §10.4): text, definitions, links, the status
// chip (statusLabel, never a bare "rejected"), the needs_review chip, version, provenance, and the card menu. History
// cards (removed / rejected / superseded) render struck through and offer only provenance.
import { useId, useRef, useState } from "react";
import { select } from "../../core/index.js";
import type { Card } from "../../core/types.js";
import { cardText, excerpt } from "../format.js";
import { useAct, useApi, useEventSeq, useSession } from "../store/useSession.js";
import { CardEditDialog } from "./CardEditDialog.js";
import { CardMenu } from "./CardMenu.js";
import { ProvenancePopover } from "./ProvenancePopover.js";

export interface CardViewProps {
  card: Card;
  /** True when the card is not live (shown because the history toggle is on). */
  history: boolean;
}

export function needsReviewText(card: Card, eventSeq: (id: string) => number | null): string | null {
  if (card.kind !== "example" || card.needs_review === null) return null;
  const reason = card.needs_review.reason === "rule_changed" ? "rule changed" : card.needs_review.reason === "rule_removed" ? "rule removed" : "rule replaced";
  const seq = eventSeq(card.needs_review.event_id);
  return `needs review: ${reason} (event ${seq ?? card.needs_review.event_id})`;
}

export function CardView({ card, history }: CardViewProps) {
  const state = useSession();
  const api = useApi();
  const act = useAct();
  const eventSeq = useEventSeq();
  const [menuOpen, setMenuOpen] = useState(false);
  const [provOpen, setProvOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement | null>(null);
  const provButton = useRef<HTMLButtonElement | null>(null);
  const article = useRef<HTMLElement | null>(null);
  const reactId = useId();
  const menuId = `card-menu-${card.id}-${reactId}`;
  const provId = `card-provenance-popover-${card.id}`;
  const label = select.statusLabel(card);
  const review = needsReviewText(card, eventSeq);

  const closeMenu = () => {
    setMenuOpen(false);
    (article.current ?? menuButton.current)?.focus();
  };
  const closeProv = () => {
    setProvOpen(false);
    provButton.current?.focus();
  };

  const link =
    card.kind === "example" ? (
      card.rule_id ? (
        <span data-testid={`card-link-${card.id}`}>for rule: {cardText(state, card.rule_id, 40)}</span>
      ) : (
        <span data-testid={`card-link-${card.id}`} className="rounded bg-amber-200 px-1 text-amber-950">
          not attached to a rule
        </span>
      )
    ) : card.kind === "question" ? (
      <span data-testid={`card-link-${card.id}`}>about: {card.about_card_id ? cardText(state, card.about_card_id, 40) : "(no card)"}</span>
    ) : null;

  return (
    <li className="relative list-none">
      <article
        ref={article}
        id={`card-${card.id}`}
        data-testid={`card-${card.id}`}
        data-card
        data-kind={card.kind}
        data-status={card.status}
        data-live={history ? "false" : "true"}
        tabIndex={-1}
        aria-labelledby={`card-${card.id}-text`}
        aria-describedby={`card-${card.id}-status`}
        className={`relative flex flex-col gap-1 rounded border border-slate-400 bg-white/70 p-2 text-sm text-slate-900 shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 ${history ? "opacity-60" : ""}`}
        onKeyDown={(e) => {
          // Escape anywhere in the card closes what the card has open and returns focus to it
          if (e.key !== "Escape" || (!menuOpen && !provOpen)) return;
          e.stopPropagation();
          e.preventDefault();
          if (menuOpen) closeMenu();
          if (provOpen) {
            setProvOpen(false);
            article.current?.focus();
          }
        }}
      >
        <p id={`card-${card.id}-text`} className={history ? "line-through" : ""} data-testid={`card-text-${card.id}`}>
          {card.text}
        </p>
        {card.definitions.length > 0 ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-xs" data-testid={`card-definitions-${card.id}`}>
            {card.definitions.map((d) => (
              <div key={d.term} className="contents">
                <dt className="font-semibold">{d.term}</dt>
                <dd>
                  {" — "}
                  {d.definition}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        {link ? <div className={`text-xs ${history ? "text-slate-900" : "text-slate-700"}`}>{link}</div> : null}
        {card.kind === "question" ? (
          <div className="flex flex-wrap gap-1 text-xs">
            <span data-testid={`card-answer-${card.id}`}>{card.answer === null ? "unanswered" : `answer: ${excerpt(card.answer, 80)}`}</span>
            {card.accepted_outstanding ? (
              <span className="rounded bg-slate-200 px-1" data-testid={`card-accepted-${card.id}`}>
                accepted outstanding by {card.accepted_outstanding.by}
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <span id={`card-${card.id}-status`} data-testid={`card-status-${card.id}`} data-label={label} className="rounded border border-slate-500 bg-white px-1.5 py-0.5 font-semibold">
            {label}
          </span>
          {review ? (
            <span data-testid={`card-needs-review-${card.id}`} className="rounded bg-amber-200 px-1.5 py-0.5 font-semibold text-amber-950">
              {review}
            </span>
          ) : null}
          <span data-testid={`card-version-${card.id}`}>v{card.version}</span>
          <span className="grow" />
          <button
            ref={provButton}
            type="button"
            data-testid={`card-provenance-${card.id}`}
            data-provenance-button
            aria-expanded={provOpen}
            aria-controls={provId}
            className="rounded border border-slate-400 px-1.5 py-0.5"
            onClick={() => setProvOpen((v) => !v)}
          >
            Provenance
          </button>
          {!history ? (
            <button
              ref={menuButton}
              type="button"
              data-testid={`card-menu-button-${card.id}`}
              data-menu-button
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-controls={menuId}
              className="rounded border border-slate-400 px-1.5 py-0.5"
              onClick={() => setMenuOpen((v) => !v)}
            >
              Actions{act.pending ? " (pending…)" : ""}
            </button>
          ) : null}
        </div>
      </article>
      {/* beside the article, not inside it: a faded history card must not fade its popover (contrast) */}
      {provOpen ? <ProvenancePopover card={card} id={provId} onClose={closeProv} eventSeq={eventSeq} /> : null}
      {menuOpen && !history ? (
        <CardMenu
          card={card}
          id={menuId}
          pending={act.pending}
          onClose={closeMenu}
          onConfirm={() => {
            setMenuOpen(false);
            void act.run((actor) => api.confirmCard(card.id, actor));
          }}
          onEdit={() => {
            setMenuOpen(false);
            setEditOpen(true);
          }}
          onRemove={() => {
            setMenuOpen(false);
            void act.run((actor) => api.removeCard(card.id, actor));
          }}
          onAcceptOutstanding={(reason) => {
            setMenuOpen(false);
            void act.run((actor) => api.acceptQuestion(card.id, actor, reason));
          }}
        />
      ) : null}
      {editOpen ? (
        <CardEditDialog
          card={card}
          open={editOpen}
          pending={act.pending}
          onClose={() => setEditOpen(false)}
          onSave={(patch) => {
            void act.run((actor) => api.updateCard(card.id, actor, patch)).then((r) => {
              if (r) setEditOpen(false);
            });
          }}
        />
      ) : null}
    </li>
  );
}
