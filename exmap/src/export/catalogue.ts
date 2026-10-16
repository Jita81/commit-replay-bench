// exmap/src/export/catalogue.ts — the vendored crb readiness catalogue (design §12.6). Copied unchanged from the generator's
// output; updating it is a copy, never an edit. tsc copies the JSON into dist/server/export/.
import catalogue from "./crb-catalogue.json" with { type: "json" };

export interface Slot {
  name: string;
  question: string;
  kind: "structural" | "value";
}

export interface Catalogue {
  source: string;
  source_commit: string;
  copied: string;
  classes: Record<string, Slot[]>;
}

export function loadCatalogue(): Catalogue {
  return {
    source: catalogue._source,
    source_commit: catalogue._source_commit,
    copied: catalogue._copied,
    classes: catalogue.classes as Record<string, Slot[]>,
  };
}

/** [] for an unknown class. */
export function slotsFor(cls: string): Slot[] {
  return loadCatalogue().classes[cls] ?? [];
}

/** "unclassified" is not a class. */
export function isCatalogueClass(cls: string): boolean {
  return Object.hasOwn(loadCatalogue().classes, cls);
}
