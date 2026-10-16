// exmap/src/web/components/ExportDrawer.tsx — the crb bridge (design §10.6): the gate (verified, or the failing checks
// and a DRAFT / NOT VERIFIED toggle), the class picker from the catalogue the API serves, slot questions, free facts,
// Save → PUT export-options, a ticket.md preview, and download links for the five files.
import { useCallback, useEffect, useState } from "react";
import { isHumanVerified, select } from "../../core/index.js";
import type { BacklogKind, ExportFile, ExportOptions, SizeEstimate } from "../../core/types.js";
import { ApiError, type CatalogueResponse, type CatalogueSlot } from "../api/client.js";
import { hash8, timeOf } from "../format.js";
import { useAct, useApi, useDod, useSession } from "../store/useSession.js";
import { Drawer } from "./Drawer.js";

export interface ExportDrawerProps {
  open: boolean;
  onClose: () => void;
  returnFocusTo?: HTMLElement | null;
}

export const EXPORT_FILES: ExportFile[] = ["crb-backlog-item.json", "ticket.json", "ticket.md", "requirement.feature", "evidence.json"];
const KINDS: BacklogKind[] = ["code", "infra", "operator"];
const SIZES: SizeEstimate[] = ["XS", "S", "M", "L", "XL", "unsized"];
const SLOT_RE = /^[A-Za-z][A-Za-z0-9_]*$/;

interface FreeFact {
  slot: string;
  text: string;
}

function initialForm(current: ExportOptions | null, slots: CatalogueSlot[]): { cls: string; kind: BacklogKind; size: SizeEstimate; slotText: Record<string, string>; free: FreeFact[] } {
  const slotNames = new Set(slots.map((s) => s.name));
  const slotText: Record<string, string> = {};
  const free: FreeFact[] = [];
  for (const f of current?.facts ?? []) {
    if (slotNames.has(f.slot) && slotText[f.slot] === undefined) slotText[f.slot] = f.text;
    else free.push({ slot: f.slot, text: f.text });
  }
  return { cls: current?.capability_class ?? "unclassified", kind: current?.kind ?? "code", size: current?.size_estimate ?? "unsized", slotText, free };
}

export function ExportDrawer({ open, onClose, returnFocusTo }: ExportDrawerProps) {
  const state = useSession();
  const dod = useDod();
  const api = useApi();
  const act = useAct();
  const [catalogue, setCatalogue] = useState<CatalogueResponse | null>(null);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const [draft, setDraft] = useState(false);
  const [cls, setCls] = useState("unclassified");
  const [kind, setKind] = useState<BacklogKind>("code");
  const [size, setSize] = useState<SizeEstimate>("unsized");
  const [slotText, setSlotText] = useState<Record<string, string>>({});
  const [free, setFree] = useState<FreeFact[]>([]);
  const [preview, setPreview] = useState<string>("");
  const [saved, setSaved] = useState<ExportOptions | null>(null);
  const current = saved ?? select.exportOptions(state);
  const verified = isHumanVerified(state);
  const active = select.activeSignoff(state);
  const slots = cls === "unclassified" ? [] : (catalogue?.classes[cls] ?? []);
  // Links carry exactly the toggle (§10.6); an unverified map without the toggle is told its links will answer 422.
  const effectiveDraft = draft;

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setCatalogueError(null);
    api
      .catalogue()
      .then((c) => {
        if (cancelled) return;
        setCatalogue(c);
        const initial = initialForm(select.exportOptions(state), c.classes[select.exportOptions(state)?.capability_class ?? ""] ?? []);
        setCls(initial.cls);
        setKind(initial.kind);
        setSize(initial.size);
        setSlotText(initial.slotText);
        setFree(initial.free);
      })
      .catch((e: unknown) => {
        if (!cancelled) setCatalogueError(e instanceof ApiError ? `${e.reason}: ${e.detail}` : String(e));
      });
    return () => {
      cancelled = true;
    };
    // The form is seeded once per opening from the options the ledger holds at that moment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, api]);

  const refreshPreview = useCallback(() => {
    if (!open) return;
    api
      .exportText("ticket.md", effectiveDraft)
      .then(setPreview)
      .catch((e: unknown) => setPreview(e instanceof ApiError ? `Preview refused — ${e.reason}: ${e.detail}` : `Preview unavailable: ${String(e)}`));
  }, [open, api, effectiveDraft]);

  useEffect(() => {
    refreshPreview();
  }, [refreshPreview, current]);

  const facts = [
    ...slots.map((s) => ({ slot: s.name, text: (slotText[s.name] ?? "").trim() })).filter((f) => f.text.length > 0),
    ...free.map((f) => ({ slot: f.slot.trim(), text: f.text.trim() })).filter((f) => f.slot.length > 0 && f.text.length > 0),
  ];
  const badSlot = facts.find((f) => !SLOT_RE.test(f.slot));

  const save = () =>
    void act.run((actor) => api.putExportOptions(actor, { capability_class: cls, kind, size_estimate: size, facts })).then((r) => {
      if (r) {
        setSaved(r.export_options);
        refreshPreview();
      }
    });

  const failing = dod.checks.filter((c) => !c.pass);

  return (
    <Drawer open={open} title="Export to crb" testId="export-drawer" onClose={onClose} returnFocusTo={returnFocusTo} wide>
      <div data-testid="export-gate" className={`rounded border p-2 text-sm ${verified ? "border-green-700 bg-green-50" : "border-amber-700 bg-amber-50"}`}>
        {verified && active ? (
          <p>
            Human verified — revision {hash8(active.revision.hash)}, signed by {active.reviewer.name}
          </p>
        ) : (
          <>
            <p className="font-semibold">Exports are refused until the requirement is human-verified. You can download DRAFT / NOT VERIFIED files instead.</p>
            {failing.length > 0 ? (
              <ul className="mt-1 list-inside list-disc text-xs">
                {failing.map((c) => (
                  <li key={c.id}>
                    {c.title}: {c.details.join("; ")}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs">Every check passes, but no sign-off on this revision is active.</p>
            )}
          </>
        )}
        <label className="mt-2 flex items-center gap-2 text-xs">
          <input type="checkbox" role="switch" aria-checked={draft} data-testid="export-draft-toggle" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
          Download as DRAFT / NOT VERIFIED (watermarked files, DRAFT- names)
        </label>
        {!verified && !draft ? <p className="mt-1 text-xs">The links below will answer 422 until the map is verified or the draft toggle is on.</p> : null}
      </div>

      <h3 className="text-sm font-semibold">Capability class and structural facts</h3>
      {catalogueError ? (
        <p role="alert" className="text-xs text-red-800">
          Catalogue unavailable: {catalogueError}
        </p>
      ) : null}
      <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs">
          Capability class
          <select data-testid="export-class" className="rounded border border-slate-400 p-1" value={cls} onChange={(e) => setCls(e.target.value)}>
            <option value="unclassified">unclassified</option>
            {Object.keys(catalogue?.classes ?? {}).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Kind
          <select data-testid="export-kind" className="rounded border border-slate-400 p-1" value={kind} onChange={(e) => setKind(e.target.value as BacklogKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Size estimate
          <select data-testid="export-size" className="rounded border border-slate-400 p-1" value={size} onChange={(e) => setSize(e.target.value as SizeEstimate)}>
            {SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      {slots.length > 0 ? (
        <div className="flex flex-col gap-2" data-testid="export-slots">
          {slots.map((s) => (
            <label key={s.name} className="flex flex-col gap-1 text-xs">
              <span className="flex flex-wrap items-center gap-2">
                <code>{s.name}</code> — {s.question}
                <span className={`rounded px-1.5 py-0.5 ${s.kind === "structural" ? "bg-slate-800 text-white" : "bg-slate-200 text-slate-900"}`} data-testid={`export-slot-kind-${s.name}`}>
                  {s.kind === "structural" ? "required (structural)" : "value — routes, does not block"}
                </span>
              </span>
              <input data-testid={`export-fact-slot-${s.name}`} className="rounded border border-slate-400 px-1.5 py-0.5" value={slotText[s.name] ?? ""} onChange={(e) => setSlotText({ ...slotText, [s.name]: e.target.value })} />
            </label>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-700">{cls === "unclassified" ? "Pick a class to see its slot questions." : "This class has no slots."}</p>
      )}
      <div className="flex flex-col gap-1" data-testid="export-free-facts">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-semibold">Free facts (slot: text)</span>
          <button type="button" data-testid="export-fact-add" className="rounded border border-slate-500 px-1.5 py-0.5" onClick={() => setFree([...free, { slot: "", text: "" }])}>
            Add fact
          </button>
        </div>
        {free.map((f, i) => {
          const foreign = f.slot.trim().length > 0 && !slots.some((s) => s.name === f.slot.trim());
          return (
            <div key={i} className="flex flex-wrap items-center gap-1 text-xs" data-testid={`export-free-${i}`}>
              <label className="sr-only" htmlFor={`export-free-slot-${i}`}>
                Slot
              </label>
              <input id={`export-free-slot-${i}`} data-testid={`export-free-slot-${i}`} className="w-40 rounded border border-slate-400 px-1.5 py-0.5" placeholder="slot" value={f.slot} onChange={(e) => setFree(free.map((x, j) => (j === i ? { ...x, slot: e.target.value } : x)))} />
              <label className="sr-only" htmlFor={`export-free-text-${i}`}>
                Text
              </label>
              <input id={`export-free-text-${i}`} data-testid={`export-free-text-${i}`} className="grow rounded border border-slate-400 px-1.5 py-0.5" placeholder="text" value={f.text} onChange={(e) => setFree(free.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
              <button type="button" className="rounded border border-slate-400 px-1.5" onClick={() => setFree(free.filter((_, j) => j !== i))} aria-label={`Remove fact ${i + 1}`}>
                Remove
              </button>
              {foreign ? (
                <span className="rounded bg-amber-200 px-1.5 py-0.5 text-amber-950" data-testid={`export-free-warning-${i}`}>
                  crb will keep this as prose
                </span>
              ) : null}
            </div>
          );
        })}
      </div>
      {badSlot ? (
        <p role="alert" className="text-xs text-red-800">
          Slot “{badSlot.slot}” is not a valid slot name (letters, digits and underscores, starting with a letter).
        </p>
      ) : null}
      <button type="button" data-testid="export-save" className="self-start rounded border border-slate-700 bg-slate-800 px-3 py-1 text-sm text-white disabled:opacity-50" disabled={act.pending || badSlot !== undefined} onClick={save}>
        Save export options{act.pending ? " (pending…)" : ""}
      </button>
      {current ? (
        <div className="text-xs" data-testid="export-options-status">
          Supplied at export by {current.by} at {timeOf(current.at)} (change {current.seq} of {Math.max(state.export_options.length, current.seq)}); not part of the sign-off
          {state.export_options.length > 1 ? (
            <details className="mt-1" data-testid="export-options-history">
              <summary>Earlier values ({state.export_options.length - 1})</summary>
              <ul className="list-inside list-disc">
                {state.export_options.slice(0, -1).map((o) => (
                  <li key={o.seq}>
                    change {o.seq} by {o.by} at {timeOf(o.at)}: {o.capability_class}, {o.kind}, {o.size_estimate}, {o.facts.length} facts
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-slate-700">No export options recorded yet.</p>
      )}

      <h3 className="text-sm font-semibold">Preview — ticket.md{effectiveDraft ? " (draft)" : ""}</h3>
      <pre data-testid="export-preview" className="max-h-64 overflow-auto rounded border border-slate-300 bg-slate-50 p-2 text-xs whitespace-pre-wrap">
        {preview || "(loading…)"}
      </pre>

      <h3 className="text-sm font-semibold">Download</h3>
      <ul className="flex flex-wrap gap-2 text-sm">
        {EXPORT_FILES.map((file) => (
          <li key={file}>
            <a data-testid={`export-download-${file}`} className="rounded border border-slate-600 px-2 py-1 underline" download href={api.exportUrl(file, effectiveDraft)}>
              {effectiveDraft ? `DRAFT-${file}` : file}
            </a>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
