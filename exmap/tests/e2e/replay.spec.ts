// tests/e2e/replay.spec.ts — TEST-PLAN §8.2: the demo fixture played whole with ?autostart=1 (31 rows, every one
// classified in the ledger, the header's count derived from it), and ?replay= without ?session= creating the session.
import { createSession, expect, fixture, setName, test } from "./fixtures";
import { settled, transcriptRows, waitForHooks } from "./web-helpers";

test.describe("replay", () => {
  test("?replay=demo&speed=instant&autostart=1 plays all 31 utterances and every one is classified", async ({ page, request }) => {
    test.setTimeout(180_000);
    await setName(request, "Sam");
    const id = await createSession(request, { title: "Replay e2e", story: fixture.story!, actor: "Sam" });
    await page.goto(`/?session=${id}&replay=demo&speed=instant&autostart=1&testhooks=1`);
    await waitForHooks(page);
    await expect(page.getByTestId("replay-status")).toHaveText("31 / 31", { timeout: 90_000 });
    await settled(page);
    const rows = transcriptRows(page);
    await expect(rows).toHaveCount(31);
    await expect(page.getByTestId("column-rule").locator("article[data-card]").first()).toBeVisible();
    expect(await page.getByTestId("column-rule").locator("article[data-card]").count()).toBeGreaterThanOrEqual(1);
    await expect(page.getByTestId("header-utterance-count")).toHaveText(String(await rows.count()));
    await expect
      .poll(
        async () => {
          const body = (await (await request.get(`/api/sessions/${id}/events?after=0&limit=5000`)).json()) as { events: Array<{ type: string }> };
          return body.events.filter((e) => e.type === "utterance.classified").length;
        },
        { timeout: 60_000 },
      )
      .toBe(31);
    const summary = (await (await request.get(`/api/sessions/${id}`)).json()) as { session: { counts: { utterances: number; classified: number } } };
    expect(summary.session.counts.utterances).toBe(31);
    expect(summary.session.counts.classified).toBe(31);
  });

  test("?replay=demo without ?session= creates a session with the fixture's story and opens it", async ({ page, request }) => {
    test.setTimeout(180_000);
    await setName(request, "Sam");
    const before = (await (await request.get("/api/sessions")).json()) as { sessions: Array<{ id: string }> };
    await page.goto("/?replay=demo&speed=instant&autostart=1&testhooks=1");
    await expect(page).toHaveURL(/[?&]session=ses_[a-z0-9]+_[a-f0-9]{6}/, { timeout: 30_000 });
    const url = new URL(page.url());
    expect(url.searchParams.get("replay")).toBe("demo");
    expect(url.searchParams.get("testhooks")).toBe("1");
    const id = url.searchParams.get("session")!;
    const after = (await (await request.get("/api/sessions")).json()) as { sessions: Array<{ id: string; title: string; counts: { by_kind: Record<string, number> } }> };
    expect(after.sessions.length).toBe(before.sessions.length + 1);
    const created = after.sessions.find((s) => s.id === id)!;
    expect(created.title).toBe(`Replay — ${fixture.title}`);
    const story = page.getByTestId("column-story").locator("article[data-card]");
    await expect(story).toHaveCount(1);
    await expect(story).toContainText(fixture.story!);
    await waitForHooks(page);
    await expect(page.getByTestId("replay-status")).toHaveText("31 / 31", { timeout: 90_000 });
    await settled(page);
  });
});
