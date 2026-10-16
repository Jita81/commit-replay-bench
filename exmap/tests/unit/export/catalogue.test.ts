// TEST-PLAN §5.6 — catalogue.test.ts: the vendored crb readiness catalogue (design §12.6) is intact and unchanged.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { isCatalogueClass, loadCatalogue, slotsFor } from "../../../src/export/index.js";

/** sha256 of src/export/crb-catalogue.json as generated from crb's source at vendoring time (2026-10-16). Updating the
 *  catalogue is a copy of a fresh generator run, never an edit: the new hash is checked in together with the file. */
const VENDORED_SHA256 = "de1012c23566710b31bdb4272d5737754af4dece1c6689be31b31dc7ad7d0cf1";

const CLASSES = [
  "backend.route.add", "backend.route.edit", "backend.model.edit", "backend.migration.add", "frontend.component.add", "frontend.component.edit",
  "frontend.route.add", "bug.fix", "test.add", "test.fix", "docs.update", "ci.workflow.edit", "infra.helm.edit", "infra.terraform.edit",
];

const fileUrl = new URL("../../../src/export/crb-catalogue.json", import.meta.url);

describe("the vendored crb catalogue", () => {
  it("is byte-identical to the generator's output at vendoring time", () => {
    const bytes = readFileSync(fileUrl);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(VENDORED_SHA256);
  });

  it("names its source, commit (40 hex) and copy date (YYYY-MM-DD), and has 14 classes", () => {
    const raw = JSON.parse(readFileSync(fileUrl, "utf8")) as { _source: string; _source_commit: string; _copied: string; classes: Record<string, unknown[]> };
    expect(raw._source).toBe("src/crb/factory/readiness.py CATALOGUE in jita81/commit-replay-bench");
    expect(raw._source_commit).toMatch(/^[0-9a-f]{40}$/);
    expect(raw._copied).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(Object.keys(raw.classes)).toEqual(CLASSES);
    const loaded = loadCatalogue();
    expect(loaded.source).toBe(raw._source);
    expect(loaded.source_commit).toBe(raw._source_commit);
    expect(loaded.copied).toBe(raw._copied);
    expect(Object.keys(loaded.classes)).toHaveLength(14);
  });

  it("every slot has a name, a question and a kind of structural or value", () => {
    for (const [cls, slots] of Object.entries(loadCatalogue().classes)) {
      expect(slots.length, cls).toBeGreaterThan(0);
      for (const slot of slots) {
        expect(slot.name).toMatch(/^[A-Za-z][A-Za-z0-9_]*$/);
        expect(slot.question.length).toBeGreaterThan(0);
        expect(["structural", "value"]).toContain(slot.kind);
      }
      expect(new Set(slots.map((s) => s.name)).size).toBe(slots.length);
      expect(slots.some((s) => s.kind === "structural"), cls).toBe(true);
    }
  });

  it("slotsFor(bug.fix) lists reproduction and expected_behaviour as structural and exact_value as value", () => {
    expect(slotsFor("bug.fix").map((s) => [s.name, s.kind])).toEqual([
      ["reproduction", "structural"], ["expected_behaviour", "structural"], ["exact_value", "value"],
    ]);
    expect(slotsFor("backend.route.edit").map((s) => s.name)).toEqual(["route_identity", "behaviour_change", "error_contract", "example_payload"]);
    expect(slotsFor("nope")).toEqual([]);
    expect(slotsFor("unclassified")).toEqual([]);
  });

  it("isCatalogueClass: the 14 classes are; unclassified and prototype keys are not", () => {
    for (const cls of CLASSES) expect(isCatalogueClass(cls), cls).toBe(true);
    expect(isCatalogueClass("unclassified")).toBe(false);
    expect(isCatalogueClass("")).toBe(false);
    expect(isCatalogueClass("toString")).toBe(false);
    expect(isCatalogueClass("__proto__")).toBe(false);
  });
});
