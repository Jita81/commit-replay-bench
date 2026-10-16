// tests/e2e/web-helpers.ts — locators and hooks the web module's specs (journey, replay, axe) share. Cards, rows and
// proposals are found by their text and ledger ids, never by ordinal (design §13.1). Kept apart from fixtures.ts so the
// shared fixture file only grows by what every module needs.
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page, TestInfo } from "@playwright/test";
import type { Page as CorePage } from "playwright-core";
import { expect, fixture } from "./fixtures";

export type Kind = "story" | "rule" | "example" | "question";

interface Hooks {
  audio: { postQueueIdle(): Promise<void>; pendingWork(): number };
  replay: { playUntil(l: string | number): Promise<void>; skip(l: string | number): Promise<void>; playAll(): Promise<void>; position: number };
  store?: { settled?(): Promise<void> };
}

/** The session screen installed window.__exmap (it does so once the replay fixture, if any, is loaded). */
export async function waitForHooks(page: Page): Promise<void> {
  await page.waitForFunction(() => Boolean((window as unknown as { __exmap?: Hooks }).__exmap?.replay), undefined, { timeout: 30_000 });
}

/** The page's reduced ledger holds every utterance it posted, with its classification record. */
export async function settled(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const h = (window as unknown as { __exmap: Hooks }).__exmap;
    await h.audio.postQueueIdle();
    await h.store?.settled?.();
  });
}

export function fixtureText(label: string): string {
  const u = fixture.utterances.find((x) => x.label === label);
  if (!u) throw new Error(`no fixture utterance ${label}`);
  return u.text;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The transcript row whose text is exactly `text`. */
export function transcriptRow(page: Page, text: string): Locator {
  return page
    .getByTestId("transcript")
    .locator('li[data-testid^="utterance-"]')
    .filter({ has: page.locator('[data-testid="transcript-text"]', { hasText: new RegExp(`^${escapeRe(text)}$`) }) });
}

export const transcriptRows = (page: Page): Locator => page.getByTestId("transcript").locator('[data-testid^="utterance-"]:not([data-testid^="utterance-proposals-"])');

/** The utterance id of the fixture row `label` (the replay provider mints it; the row's test id carries it). */
export async function utteranceId(page: Page, label: string): Promise<string> {
  const row = transcriptRow(page, fixtureText(label));
  await expect(row).toHaveCount(1);
  const testId = await row.getAttribute("data-testid");
  return testId!.slice("utterance-".length);
}

/** The id of the proposal chip under an utterance whose text starts with `<intent> · `. */
export async function proposalIdOf(page: Page, uttId: string, intent: string): Promise<string> {
  const chip = page.getByTestId(`utterance-proposals-${uttId}`).locator('[data-testid^="chip-proposal-"]', { hasText: new RegExp(`^${escapeRe(intent)} · `) }).first();
  await expect(chip).toBeVisible();
  return (await chip.getAttribute("data-testid"))!.slice("chip-proposal-".length);
}

/** Cards of a column whose text contains `substring` (live ones only unless the history toggle is on). */
export function cards(page: Page, kind: Kind, substring: string): Locator {
  return page
    .getByTestId(`column-${kind}`)
    .locator("article[data-card]")
    .filter({ has: page.locator('[data-testid^="card-text-"]', { hasText: substring }) });
}

export async function cardId(card: Locator): Promise<string> {
  await expect(card).toHaveCount(1);
  return (await card.getAttribute("data-testid"))!.slice("card-".length);
}

export const statusOf = (page: Page, id: string): Locator => page.getByTestId(`card-status-${id}`);

export async function setHistory(page: Page, on: boolean): Promise<void> {
  const toggle = page.getByTestId("history-toggle");
  if ((await toggle.getAttribute("aria-checked")) !== String(on)) await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", String(on));
}

/** Opens a card's provenance popover and returns it (closing any other first). */
export async function openProvenance(page: Page, id: string): Promise<Locator> {
  const popover = page.getByTestId(`provenance-${id}`);
  if ((await popover.count()) === 0) await page.getByTestId(`card-provenance-${id}`).click();
  await expect(popover).toBeVisible();
  return popover;
}

export async function closeProvenance(page: Page, id: string): Promise<void> {
  const popover = page.getByTestId(`provenance-${id}`);
  if ((await popover.count()) > 0) await page.getByTestId(`provenance-close-${id}`).click();
  await expect(popover).toHaveCount(0);
}

export async function openDrawer(page: Page, which: "review" | "export"): Promise<Locator> {
  await page.getByTestId(`${which}-open`).click();
  const drawer = page.getByTestId(`${which}-drawer`);
  await expect(drawer).toBeVisible();
  return drawer;
}

export async function closeDrawer(page: Page, which: "review" | "export" | "settings"): Promise<void> {
  const id = which === "settings" ? "settings-dialog" : `${which}-drawer`;
  await page.getByTestId(`${id}-close`).click();
  await expect(page.getByTestId(id)).toHaveCount(0);
}

export async function revisionChip(page: Page): Promise<{ seq: number; hash: string }> {
  const chip = page.getByTestId("revision-chip");
  return { seq: Number(await chip.getAttribute("data-seq")), hash: (await chip.getAttribute("data-hash")) ?? "" };
}

/** Runs axe; attaches the full violation list to the report; returns the serious / critical ones. */
export async function seriousViolations(page: Page, testInfo: TestInfo, name: string): Promise<unknown[]> {
  // @axe-core/playwright types `page` against the hoisted playwright-core, not @playwright/test's Page; same object at
  // runtime (INTEGRATION-NOTES, audio §7).
  const result = await new AxeBuilder({ page: page as unknown as CorePage }).analyze();
  await testInfo.attach(`axe-${name}.json`, { body: JSON.stringify(result.violations, null, 2), contentType: "application/json" });
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => n.target.join(" ")) }));
}
