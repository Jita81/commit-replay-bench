// tests/e2e/axe.spec.ts — TEST-PLAN §8.4 / design §10.8: axe on the session screen with cards and tray items (after
// u13, and a separate session replayed to u05 so an open clarification is on screen), then with the review drawer, the
// export drawer, the settings dialog and the model consent notice open. Serious and critical violations must be [];
// the full list for every screen is attached to the report.
import { createSession, expect, fixture, openSession, playUntil, setName, test } from "./fixtures";
import { closeDrawer, openDrawer, seriousViolations, settled, waitForHooks } from "./web-helpers";

test.describe("accessibility", () => {
  test("axe reports no serious or critical violations on the session screen, its drawers, settings and the consent notice", async ({ page, request }, testInfo) => {
    test.setTimeout(240_000);
    await setName(request, "Sam");

    // a state with an open clarification (u05)
    const clarifyingId = await createSession(request, { title: "Axe — clarification", story: fixture.story!, actor: "Sam" });
    await openSession(page, clarifyingId, "replay=demo&speed=instant");
    await waitForHooks(page);
    await playUntil(page, "u05");
    await settled(page);
    await expect(page.getByTestId("tray").locator('[role="group"][data-testid^="clarification-"]')).toHaveCount(1);
    expect(await seriousViolations(page, testInfo, "clarification")).toEqual([]);

    // (a) the session screen with cards and tray items
    const id = await createSession(request, { title: "Axe — main screen", story: fixture.story!, actor: "Sam" });
    await openSession(page, id, "replay=demo&speed=instant");
    await waitForHooks(page);
    await playUntil(page, "u13");
    await settled(page);
    await expect(page.getByTestId("column-question").locator("article[data-card]")).toHaveCount(2);
    await expect(page.getByTestId("tray").locator('[data-testid^="proposal-"][data-status]').first()).toBeVisible();
    expect(await seriousViolations(page, testInfo, "session")).toEqual([]);

    // the board's keyboard path: a card menu and a provenance popover open
    const rule = page.getByTestId("column-rule").locator("article[data-card]").first();
    await rule.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator('[role="menu"]')).toBeVisible();
    expect(await seriousViolations(page, testInfo, "card-menu")).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page.locator('[role="menu"]')).toHaveCount(0);
    await expect(rule).toBeFocused();
    await page.keyboard.press("p");
    await expect(page.locator('[data-testid^="provenance-"][role="dialog"]')).toBeVisible();
    expect(await seriousViolations(page, testInfo, "provenance")).toEqual([]);
    await page.keyboard.press("Escape");

    // (b) the review drawer
    await openDrawer(page, "review");
    expect(await seriousViolations(page, testInfo, "review-drawer")).toEqual([]);
    await closeDrawer(page, "review");

    // (c) the export drawer
    await openDrawer(page, "export");
    await expect(page.getByTestId("export-class").locator("option")).not.toHaveCount(1);
    await page.getByTestId("export-class").selectOption("backend.route.edit");
    await expect(page.getByTestId("export-fact-slot-route_identity")).toBeVisible();
    expect(await seriousViolations(page, testInfo, "export-drawer")).toEqual([]);
    await closeDrawer(page, "export");

    // (d) the settings dialog
    await page.getByTestId("header").getByTestId("settings-open").click();
    await expect(page.getByTestId("settings-dialog")).toBeVisible();
    expect(await seriousViolations(page, testInfo, "settings")).toEqual([]);
    await closeDrawer(page, "settings");

    // (e) the model consent notice (the mic lane on local Whisper with no model consent yet; nothing is downloaded)
    await page.getByTestId("provider-select-me").selectOption("local-whisper");
    await page.getByTestId("lane-me-start").click();
    await expect(page.getByTestId("model-notice")).toBeVisible({ timeout: 10_000 });
    expect(await seriousViolations(page, testInfo, "model-notice")).toEqual([]);
    await page.getByTestId("model-notice-cancel").click();
    await page.getByTestId("lane-me-stop").click();
  });
});
