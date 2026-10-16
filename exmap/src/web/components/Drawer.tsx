// exmap/src/web/components/Drawer.tsx — a modal panel sliding from the right (design §10.6): role="dialog",
// aria-modal, labelled by its heading, focus to the first control, Tab trapped, Escape closes, focus returns to the opener.
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

export interface DrawerProps {
  open: boolean;
  title: string;
  testId: string;
  onClose: () => void;
  children?: ReactNode;
  /** The element to focus on close (the opener); defaults to the element that was active when the drawer opened. */
  returnFocusTo?: HTMLElement | null;
  /** role="dialog" by default; a centred dialog uses variant "dialog". */
  variant?: "drawer" | "dialog";
  wide?: boolean;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null || el === document.activeElement || el.getClientRects().length > 0 || typeof (el as HTMLElement).focus === "function");
}

export function Drawer({ open, title, testId, onClose, children, returnFocusTo, variant = "drawer", wide = false }: DrawerProps) {
  const panel = useRef<HTMLDivElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const headingId = `${testId}-title`;

  useEffect(() => {
    if (!open) return;
    opener.current = returnFocusTo ?? (document.activeElement as HTMLElement | null);
    const root = panel.current;
    if (root) {
      const first = focusables(root).find((el) => !el.hasAttribute("data-drawer-close"));
      (first ?? root).focus();
    }
    return () => {
      const target = opener.current;
      if (target && typeof target.focus === "function" && document.contains(target)) target.focus();
    };
  }, [open, returnFocusTo]);

  if (!open) return null;

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key === "Tab" && panel.current) {
      const items = focusables(panel.current);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const shell =
    variant === "drawer"
      ? `fixed inset-y-0 right-0 z-40 flex h-full ${wide ? "w-full max-w-3xl" : "w-full max-w-xl"} flex-col overflow-y-auto border-l border-slate-300 bg-white text-slate-900 shadow-xl motion-safe:animate-slide-in`
      : "fixed left-1/2 top-16 z-40 flex max-h-[85vh] w-full max-w-lg -translate-x-1/2 flex-col overflow-y-auto rounded border border-slate-300 bg-white text-slate-900 shadow-xl";

  return (
    <div className="fixed inset-0 z-30" data-testid={`${testId}-backdrop`}>
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} aria-hidden="true" />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={headingId} data-testid={testId} tabIndex={-1} className={shell} onKeyDown={onKeyDown}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 id={headingId} className="text-lg font-semibold">
            {title}
          </h2>
          <button type="button" data-drawer-close data-testid={`${testId}-close`} className="rounded border border-slate-400 px-2 py-1 text-sm" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="flex flex-col gap-4 px-4 py-3">{children}</div>
      </div>
    </div>
  );
}
