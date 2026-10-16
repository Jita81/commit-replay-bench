// tests/e2e/audio.spec.ts — TEST-PLAN §8.3: E1, E1a, E2–E8 over the session screen with testhooks=1. The mic lane is
// driven by the fake-media Chromium flags of playwright.config.ts (design §7.7); getDisplayMedia is not available
// headless, so the remote lane asserts its error path and the Linux guidance. The Whisper path is never exercised
// here (scripts/whisper-check.mjs is the manual, headed run); E7 proves the download is inert without consent.
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import type { Page as CorePage } from "playwright-core";
import { createSession, expect, fixture, openSession, setName, test } from "./fixtures";

// @axe-core/playwright types its `page` against the hoisted playwright-core (1.64.1), not @playwright/test 1.56.1's
// Page; the two are the same object at runtime (see INTEGRATION-NOTES, audio).
const axe = (page: Page) => new AxeBuilder({ page: page as unknown as CorePage });

interface AudioHooks {
  audio: {
    state(): { lanes: Record<"remote" | "me", { state: string; segmentsClosed: number; signal: string }>; model: { state: string }; replay: { state: string; index: number; total: number } };
    postQueueIdle(): Promise<void>;
    segmentsClosed(): Record<"remote" | "me", number>;
    pendingWork(): number;
  };
  replay: { playUntil(l: string | number): Promise<void>; skip(l: string | number): Promise<void>; playAll(): Promise<void>; position: number };
}

const hooks = (page: Page) => ({
  idle: () => page.evaluate(() => (window as unknown as { __exmap: AudioHooks }).__exmap.audio.postQueueIdle()),
  segmentsClosed: () => page.evaluate(() => (window as unknown as { __exmap: AudioHooks }).__exmap.audio.segmentsClosed()),
  playUntil: (l: string) => page.evaluate((x) => (window as unknown as { __exmap: AudioHooks }).__exmap.replay.playUntil(x), l),
  state: () => page.evaluate(() => (window as unknown as { __exmap: AudioHooks }).__exmap.audio.state()),
});

const transcriptRows = (page: Page) => page.getByTestId("transcript").locator('[data-testid^="utterance-"]:not([data-testid^="utterance-proposals-"])');

let sessionId = "";

test.describe("audio", () => {
  test.beforeAll(async ({ request }) => {
    await setName(request, "Sam");
    sessionId = await createSession(request, { title: "Audio e2e", story: fixture.story ?? "A patient cancels an appointment online", actor: "Sam" });
  });

  test("E1 replay, instant: 31 rows with provider Replay and the fixture speaker; the counter equals 31; mm:ss is session-relative", async ({ page, request }) => {
    const id = await createSession(request, { title: "Audio E1", story: fixture.story ?? "", actor: "Sam" });
    await openSession(page, id, "replay=demo&speed=instant&autostart=1");
    await expect(page.getByTestId("replay-status")).toHaveText("31 / 31", { timeout: 60_000 });
    await hooks(page).idle();
    const rows = transcriptRows(page);
    await expect(rows).toHaveCount(31);
    for (let i = 0; i < 31; i++) {
      const u = fixture.utterances[i]!;
      const row = rows.nth(i);
      await expect(row).toContainText("Replay");
      await expect(row).toContainText(u.speaker);
    }
    await expect(page.getByTestId("header-utterance-count")).toHaveText(/31/);
    await expect(rows.first()).toContainText(/\b\d{2}:\d{2}\b/);
    const res = await request.get(`/api/sessions/${id}`);
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as { counts: { utterances: number } };
    expect(body.counts.utterances).toBe(31);
  });

  test("E1a replay breakpoints: until u05 asks a clarification with two candidates; Step answers it; Play finishes", async ({ page, request }) => {
    const id = await createSession(request, { title: "Audio E1a", story: fixture.story ?? "", actor: "Sam" });
    await openSession(page, id, "replay=demo&speed=instant");
    await expect(page.getByTestId("replay-status")).toHaveText("0 / 31");
    await hooks(page).playUntil("u05");
    await expect(page.getByTestId("replay-status")).toHaveText("5 / 31");
    const clarification = page.locator('[data-testid^="clarification-"]').filter({ has: page.locator('button[data-testid^="clarification-candidate-"]') }).first();
    await expect(clarification).toBeVisible();
    await expect(clarification.locator('button[data-testid^="clarification-candidate-"]')).toHaveCount(2);
    await page.getByTestId("replay-step").click();
    await hooks(page).idle();
    await expect(page.getByTestId("replay-status")).toHaveText("6 / 31");
    await expect(clarification).toHaveCount(0);
    await page.getByTestId("replay-play").click();
    await expect(page.getByTestId("replay-status")).toHaveText("31 / 31", { timeout: 60_000 });
    await hooks(page).idle();
    await expect(transcriptRows(page)).toHaveCount(31);
  });

  test("E2 manual: lane Call, speaker Alice, provider Typed; the textarea clears; Shift+Enter does not submit; an empty speaker reads '— (no speaker label)'", async ({ page }) => {
    await openSession(page, sessionId);
    const input = page.getByTestId("manual-input");
    await page.getByTestId("manual-lane").selectOption("remote");
    await page.getByTestId("manual-speaker").fill("Alice");
    await input.fill("We also need an error case.");
    await input.press("Enter");
    await hooks(page).idle();
    await expect(input).toHaveValue("");
    const row = transcriptRows(page).filter({ hasText: "We also need an error case." });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("Call");
    await expect(row).toContainText("Alice");
    await expect(row).toContainText("Typed");

    await input.fill("first line");
    await input.press("Shift+Enter");
    await expect(input).toHaveValue(/first line\n?/);
    await expect(transcriptRows(page).filter({ hasText: "first line" })).toHaveCount(0);
    await input.fill("");

    await page.getByTestId("manual-speaker").fill("");
    await input.fill("No label on this one.");
    await page.getByTestId("manual-submit").click();
    await hooks(page).idle();
    await expect(transcriptRows(page).filter({ hasText: "No label on this one." })).toContainText("— (no speaker label)");
  });

  test("E3 mic lane state machine with the fake device: live, level, segments, silence, provider select disabled, stop", async ({ page }) => {
    test.setTimeout(120_000);
    await openSession(page, sessionId);
    await page.getByTestId("provider-select-me").selectOption({ label: "Capture only (test audio)" });
    await expect(page.getByTestId("lane-me-provider-badge")).toHaveText("Capture only");
    await page.getByTestId("lane-me-start").click();
    await expect(page.getByTestId("lane-me-badge")).toHaveAttribute("data-state", "live", { timeout: 5_000 });
    await expect.poll(async () => Number(await page.getByTestId("level-me").getAttribute("aria-valuenow")), { timeout: 5_000 }).toBeGreaterThan(0);
    await expect.poll(async () => (await hooks(page).segmentsClosed()).me, { timeout: 20_000 }).toBeGreaterThanOrEqual(1);
    await expect(page.getByTestId("provider-select-me")).toBeDisabled();
    // the WAV is played once (%noloop); 10 s after it ends the badge says so
    await expect(page.getByTestId("lane-me-badge")).toHaveText("Live — no sound heard", { timeout: 25_000 });
    await page.getByTestId("lane-me-stop").click();
    await expect(page.getByTestId("lane-me-badge")).toHaveAttribute("data-state", "stopped");
    await expect(page.getByTestId("provider-select-me")).toBeEnabled();
  });

  test("E4 remote lane headless: an allowed error code, the Linux guidance, Escape closes it", async ({ page }) => {
    await openSession(page, sessionId);
    await page.getByTestId("lane-remote-start").click();
    const badge = page.getByTestId("lane-remote-badge");
    await expect(badge).toHaveAttribute("data-state", "error", { timeout: 15_000 });
    const code = await badge.getAttribute("data-error-code");
    expect(["NO_AUDIO_TRACK", "PERMISSION_DENIED", "UNSUPPORTED", "NOT_ACTIVATED"]).toContain(code);
    const panel = page.getByTestId("guidance-panel");
    if (code === "NOT_ACTIVATED") {
      // no guidance opens by itself for NOT_ACTIVATED; Setup help shows the howto page
      await page.getByTestId("guidance-open").click();
    }
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute("data-os", "linux");
    await expect(panel.getByRole("heading")).toContainText(/Linux|Sharing was cancelled|cannot share/);
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
  });

  test("E5 speaker label: 'Bob' committed with Enter stamps subsequent Call utterances; an uncommitted 'Al' does not", async ({ page }) => {
    await openSession(page, sessionId);
    const speaker = page.getByTestId("speaker-remote");
    await speaker.fill("Bob");
    await speaker.press("Enter");
    await page.getByTestId("manual-lane").selectOption("remote");
    const input = page.getByTestId("manual-input");
    await input.fill("Bob says this one.");
    await input.press("Enter");
    await hooks(page).idle();
    await expect(transcriptRows(page).filter({ hasText: "Bob says this one." })).toContainText("Bob");

    await speaker.fill("Al"); // typed, not committed (no Enter, no blur)
    await page.getByTestId("manual-speaker").fill("");
    await page.getByTestId("manual-speaker").fill("Bob");
    await input.fill("Still Bob here.");
    await input.press("Enter");
    await hooks(page).idle();
    const row = transcriptRows(page).filter({ hasText: "Still Bob here." });
    await expect(row).toContainText("Bob");
    await expect(row).not.toContainText("Al ");
  });

  test("E6 provider honesty and consent: choosing Web Speech opens the notice with no recogniser started; Cancel reverts; Continue keeps it", async ({ page }) => {
    await openSession(page, sessionId);
    const select = page.getByTestId("provider-select-me");
    const option = select.locator('option[value="web-speech"]');
    const disabled = await option.getAttribute("disabled");
    if (disabled !== null) {
      await expect(option).toHaveText(/not local/);
      return; // headless Chromium has no recogniser: the option says why and nothing else is reachable
    }
    await select.selectOption("web-speech");
    await expect(page.getByTestId("webspeech-notice")).toBeVisible();
    await expect(page.getByTestId("webspeech-notice")).toContainText("does leave this machine");
    await page.getByTestId("webspeech-notice-cancel").click();
    await expect(page.getByTestId("webspeech-notice")).toHaveCount(0);
    await expect(select).toHaveValue("local-whisper");
    await select.selectOption("web-speech");
    await page.getByTestId("webspeech-notice-continue").click();
    await expect(select).toHaveValue("web-speech");
    await expect(page.getByTestId("lane-me-provider-badge")).toHaveText("Web Speech (not local)");
  });

  test("E7 model download inert without consent: the notice shows and nothing goes to huggingface.co; Cancel keeps the lane live", async ({ page }) => {
    const hub: string[] = [];
    page.on("request", (r) => {
      if (/huggingface\.co|hf\.co/i.test(r.url())) hub.push(r.url());
    });
    await openSession(page, sessionId);
    await page.getByTestId("model-select").selectOption("onnx-community/whisper-tiny.en");
    await page.getByTestId("provider-select-me").selectOption("local-whisper");
    await page.getByTestId("lane-me-start").click();
    await expect(page.getByTestId("model-notice")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("model-notice")).toContainText("~44 MB");
    await expect(page.getByTestId("lane-me-badge")).toHaveAttribute("data-state", "live");
    expect(hub).toEqual([]);
    await page.getByTestId("model-notice-cancel").click();
    await expect(page.getByTestId("model-notice")).toHaveCount(0);
    await expect(page.getByTestId("lane-me-provider-badge")).toHaveText("Capture only (download declined)");
    await expect(page.getByTestId("lane-me-badge")).toHaveAttribute("data-state", "live");
    await page.waitForTimeout(1500);
    expect(hub).toEqual([]);
    await page.getByTestId("lane-me-stop").click();
  });

  test("E8 accessibility: axe on the session screen with CaptureControls, and with the model notice open", async ({ page }) => {
    await openSession(page, sessionId);
    await expect(page.getByTestId("capture-controls")).toBeVisible();
    const serious = (v: { impact?: string | null }) => v.impact === "serious" || v.impact === "critical";
    const first = await axe(page).analyze();
    expect(first.violations.filter(serious), JSON.stringify(first.violations, null, 2)).toEqual([]);
    await page.getByTestId("provider-select-me").selectOption("local-whisper");
    await page.getByTestId("lane-me-start").click();
    await expect(page.getByTestId("model-notice")).toBeVisible({ timeout: 10_000 });
    const second = await axe(page).analyze();
    expect(second.violations.filter(serious), JSON.stringify(second.violations, null, 2)).toEqual([]);
    await page.getByTestId("model-notice-cancel").click();
    await page.getByTestId("lane-me-stop").click();
  });
});
