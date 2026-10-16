// tests/e2e/journey.spec.ts — TEST-PLAN §8.1 / design §13.1: the brief's interaction model (§0 steps 1–5) end to end,
// driven by the replay provider over conversation.v1.json in slices (window.__exmap.replay), with the human acts done
// through the UI between slices; plus the typed variant through ManualInput. rules.v1 is forced by the server fixture,
// so §14's expectations are the ground truth. Cards, rows and proposals are located by text and ledger ids.
import type { Page } from "@playwright/test";
import { createSession, expect, fixture, openSession, playUntil, setName, skip, test } from "./fixtures";
import {
  cardId, cards, closeDrawer, closeProvenance, openDrawer, openProvenance, proposalIdOf, revisionChip, setHistory, settled, statusOf,
  transcriptRow, transcriptRows, utteranceId, waitForHooks,
} from "./web-helpers";

const REASON = "To be settled with the practice manager";
const SIGNOFF_TEXT = "I have reviewed the complete requirement and confirm it represents the agreed intent.";

async function play(page: Page, label: string): Promise<void> {
  await playUntil(page, label);
  await settled(page);
}

/** Presses dod-mark-<check> twice: the first press previews the exact list, the second sends it. */
async function markReviewed(page: Page, check: "story_rules_confirmed" | "examples_reviewed", expectInList: string[], expectCount: number): Promise<void> {
  await page.getByTestId(`dod-mark-${check}`).click();
  const list = page.getByTestId(`dod-mark-list-${check}`);
  await expect(list).toBeVisible();
  await expect(list.locator("[data-card-id]")).toHaveCount(expectCount);
  for (const text of expectInList) await expect(list).toContainText(text);
  await page.getByTestId(`dod-mark-${check}`).click();
  await expect(list).toHaveCount(0);
  await expect(page.getByTestId(`dod-check-status-${check}`)).toHaveText("passes");
}

async function signOff(page: Page): Promise<void> {
  await page.getByTestId("signoff-reviewer").fill("Sam");
  await page.getByTestId("signoff-insert").click();
  await expect(page.getByTestId("signoff-statement")).toHaveValue(SIGNOFF_TEXT);
  await expect(page.getByTestId("signoff-submit")).toBeEnabled();
  await page.getByTestId("signoff-submit").click();
  await expect(page.getByTestId("signoff-status")).toContainText("Signed off by Sam");
  await expect(page.getByTestId("verified-badge")).toHaveText("Human verified");
}

test.describe("journey", () => {
  test("talk, watch the map, change it by talking, verify, sign off, invalidate, re-verify, export", async ({ page, request }) => {
    test.setTimeout(300_000);
    await setName(request, "Sam");
    const sessionId = await createSession(request, { title: "Appointment cancellation", story: fixture.story!, actor: "Sam" });
    await openSession(page, sessionId, "replay=demo&speed=instant");
    await waitForHooks(page);
    await expect(page.getByTestId("replay-status")).toHaveText("0 / 31");
    const story = cards(page, "story", "A patient cancels an appointment online");
    const storyId = await cardId(story);

    /* 1. Talk naturally / watch the map populate. */
    await play(page, "u04");
    const rule = cards(page, "rule", "A patient should be able to cancel online");
    const ruleId = await cardId(rule);
    await expect(page.getByTestId(`card-text-${ruleId}`)).toContainText("not within two hours");
    await expect(statusOf(page, ruleId)).toHaveText("applied");
    const exGpId = await cardId(cards(page, "example", "the patient tries to cancel at 9am"));
    const exNurseId = await cardId(cards(page, "example", "say it is at 10am and they cancel at 8am"));
    for (const id of [exGpId, exNurseId]) await expect(page.getByTestId(`card-link-${id}`)).toContainText("for rule: A patient should be able to cancel");
    for (const label of ["u02", "u03", "u04"]) {
      const u = fixture.utterances.find((x) => x.label === label)!;
      const row = transcriptRow(page, u.text);
      await expect(row).toContainText("Replay");
      await expect(row.getByTestId("transcript-speaker")).toHaveText(u.speaker);
    }
    const u02 = await utteranceId(page, "u02");
    await expect(page.getByTestId(`utterance-proposals-${u02}`)).toContainText("add · applied");
    const p02 = await proposalIdOf(page, u02, "add");
    await expect(page.getByTestId(`proposal-rationale-${p02}`)).not.toBeEmpty();
    await expect(page.getByTestId(`proposal-confidence-${p02}`)).toHaveText(/^(0(\.\d{1,2})?|1(\.0{1,2})?)$/);

    /* 2. Clarification, answered by click. */
    await play(page, "u05");
    const clarification = page.getByTestId("tray").locator('[role="group"][data-testid^="clarification-"]');
    await expect(clarification).toHaveCount(1);
    const cid = (await clarification.getAttribute("data-testid"))!.slice("clarification-".length);
    const candidates = page.locator(`button[data-testid^="clarification-candidate-${cid}-"]`);
    await expect(candidates).toHaveCount(2);
    await expect(candidates.nth(0)).toContainText("nurse");
    await expect(candidates.nth(1)).toContainText("GP");
    await expect(page.getByTestId(`clarification-will-${cid}`)).toHaveText("Will: remove the chosen example");
    await openDrawer(page, "review");
    await expect(page.getByTestId("dod-check-status-changes_resolved")).toHaveText("fails");
    await expect(page.getByTestId("dod-details-changes_resolved")).toContainText(`clarification ${cid}`);
    await closeDrawer(page, "review");
    await page.getByTestId(`clarification-candidate-${cid}-${exGpId}`).click();
    await expect(clarification).toHaveCount(0);
    await setHistory(page, true);
    await expect(statusOf(page, exGpId)).toHaveText("removed");
    await expect(statusOf(page, exNurseId)).toHaveText("applied");
    const u05 = await utteranceId(page, "u05");
    await expect(page.getByTestId(`utterance-proposals-${u05}`)).toContainText("remove · answered");
    const removedProv = await openProvenance(page, exGpId);
    await expect(removedProv.getByTestId(`rejection-${exGpId}`)).toContainText("rules.v1");
    await expect(removedProv.getByTestId(`rejection-${exGpId}`)).toContainText("answered by Sam");
    await closeProvenance(page, exGpId);
    await setHistory(page, false);
    await skip(page, "u06"); // the click stood in for the voice answer

    /* 3. Change your mind by talking. */
    await play(page, "u09");
    await expect(page.getByTestId(`card-text-${ruleId}`)).toContainText("24 hours");
    await expect(page.getByTestId(`card-text-${ruleId}`)).toHaveText(/Keep two hours for GPs\.$/);
    await expect(page.getByTestId(`card-needs-review-${exNurseId}`)).toContainText("rule changed");
    await expect(statusOf(page, ruleId)).toHaveText("confirmed");
    const ruleProv = await openProvenance(page, ruleId);
    await expect(ruleProv).toContainText("Provenance — v3");
    await expect(ruleProv.getByTestId("history-v1")).toContainText("v1 → v2");
    await expect(ruleProv.getByTestId("history-v2")).toContainText("v2 → v3");
    await expect(ruleProv.getByTestId(`confirmed-by-${ruleId}`)).toContainText("confirmed by voice (rules.v1, 1, speaker Priya)");
    await closeProvenance(page, ruleId);

    /* 4. Questions and definitions. */
    await play(page, "u13");
    const questions = page.getByTestId("column-question").locator("article[data-card]");
    await expect(questions).toHaveCount(2);
    for (let i = 0; i < 2; i++) await expect(questions.nth(i).locator('[data-testid^="card-link-"]')).toContainText("about: A patient should be able to cancel");
    await expect(page.getByTestId(`card-definitions-${storyId}`)).toHaveText("appointment — a booked slot, not a walk-in");
    const exErrorId = await cardId(cards(page, "example", "We also need an error case"));
    await expect(page.getByTestId(`card-link-${exErrorId}`)).toContainText("for rule: A patient should be able to cancel");

    /* 5. Remove, unambiguous, as an AI act — then reviewed by voice. */
    await play(page, "u14");
    await setHistory(page, true);
    await expect(statusOf(page, exErrorId)).toHaveText("removed");
    const u14 = await utteranceId(page, "u14");
    const p14 = await proposalIdOf(page, u14, "remove");
    await expect(page.getByTestId(`proposal-unreviewed-${p14}`)).toBeVisible();
    await expect(page.getByTestId(`proposal-accept-${p14}`)).toBeVisible();
    await expect(page.getByTestId(`proposal-reject-${p14}`)).toHaveText("Restore");
    await openDrawer(page, "review");
    await expect(page.getByTestId(`dod-act-accept-${p14}`)).toBeVisible();
    await closeDrawer(page, "review");
    await play(page, "u15");
    await expect(page.getByTestId(`utterance-proposals-${u14}`)).toContainText("remove · confirmed");
    await expect(page.getByTestId(`proposal-unreviewed-${p14}`)).toHaveCount(0);
    await openDrawer(page, "review");
    await expect(page.getByTestId(`dod-act-accept-${p14}`)).toHaveCount(0);
    await closeDrawer(page, "review");
    const errorProv = await openProvenance(page, exErrorId);
    await expect(errorProv.getByTestId(`rejection-review-${exErrorId}`)).toContainText("confirmed by voice (rules.v1, 0.5, speaker Priya)");
    await closeProvenance(page, exErrorId);

    /* 6. Reject by voice. */
    await play(page, "u18");
    const overrideId = await cardId(cards(page, "rule", "must be able to override"));
    await expect(statusOf(page, overrideId)).toHaveText("interpretation rejected");
    const override2Id = await cardId(cards(page, "rule", "must not be able to override"));
    await expect(statusOf(page, override2Id)).toHaveText("applied");
    const u17 = await utteranceId(page, "u17");
    const p17 = await proposalIdOf(page, u17, "reject");
    await expect(page.getByTestId(`proposal-unreviewed-${p17}`)).toBeVisible();

    /* 7. Replace by an existing card, then undo by voice. */
    await play(page, "u19");
    const h19 = await revisionChip(page);
    const exNurse2Id = await cardId(cards(page, "example", "refused under the 24-hour rule"));
    await play(page, "u20");
    await expect(statusOf(page, exNurseId)).toHaveText("superseded");
    await expect(statusOf(page, exNurse2Id)).toHaveText("applied");
    const nurse2Prov = await openProvenance(page, exNurse2Id);
    await expect(nurse2Prov.getByTestId(`supersedes-${exNurse2Id}`)).toContainText(exNurseId);
    await closeProvenance(page, exNurse2Id);
    const h20 = await revisionChip(page);
    expect(h20.seq).toBeGreaterThan(h19.seq);
    expect(h20.hash).not.toBe(h19.hash);
    await play(page, "u21");
    await expect(statusOf(page, exNurseId)).toHaveText("applied");
    await expect(page.getByTestId(`card-needs-review-${exNurseId}`)).toContainText("rule changed");
    await expect(statusOf(page, exNurse2Id)).toHaveText("applied");
    const h21 = await revisionChip(page);
    expect(h21.seq).toBeGreaterThan(h20.seq);
    expect(h21.hash).toBe(h19.hash);
    const u21 = await utteranceId(page, "u21");
    const p21 = await proposalIdOf(page, u21, "undo");
    await expect(page.getByTestId(`proposal-unreviewed-${p21}`)).toBeVisible();

    /* 8. The rest of the talk. */
    await play(page, "u30");
    await cardId(cards(page, "question", "the same for dentists"));
    await cardId(cards(page, "example", "cancelled at 7am is allowed"));
    const exGp3Id = await cardId(cards(page, "example", "cancelled at 9am is refused"));
    await cardId(cards(page, "question", "twice in one day"));
    await expect(statusOf(page, exGp3Id)).toHaveText("applied");
    const u27 = await utteranceId(page, "u27");
    const p27 = await proposalIdOf(page, u27, "undo");
    const gp3Prov = await openProvenance(page, exGp3Id);
    await expect(gp3Prov.getByTestId(`restored-by-${exGp3Id}`)).toHaveText(`restored by undo ${p27}`);
    await closeProvenance(page, exGp3Id);
    await setHistory(page, false);
    await openDrawer(page, "review");
    const actAccepts = page.locator('button[data-testid^="dod-act-accept-"]');
    // §13.1: exactly the u17 reject, the u21 undo and the u27 undo (see INTEGRATION-NOTES, classifier §4, for $p26)
    await expect(actAccepts).toHaveCount(3);
    for (const pid of [p17, p21, p27]) await expect(page.getByTestId(`dod-act-accept-${pid}`)).toBeVisible();

    /* 9. Human-verified completion. */
    await expect(page.getByTestId("dod-check-status-questions_resolved")).toHaveText("fails");
    const questionAccepts = page.locator('button[data-testid^="question-accept-"]');
    await expect(questionAccepts).toHaveCount(4);
    await page.getByTestId("question-accept-reason").fill(REASON);
    for (let left = 4; left > 0; left--) {
      await questionAccepts.first().click();
      await expect(questionAccepts).toHaveCount(left - 1);
    }
    await expect(page.getByTestId("dod-check-status-questions_resolved")).toHaveText("passes");
    await expect(page.getByTestId("dod-details-questions_resolved")).toContainText("accepted outstanding");
    await expect(page.getByTestId("dod-details-questions_resolved")).not.toContainText("answered");
    await expect(page.getByTestId("dod-check-status-changes_resolved")).toHaveText("fails");
    for (let left = await actAccepts.count(); left > 0; left--) {
      await actAccepts.first().click();
      await expect(actAccepts).toHaveCount(left - 1);
    }
    await expect(page.getByTestId("dod-check-status-changes_resolved")).toHaveText("passes");
    await markReviewed(page, "story_rules_confirmed", ["A patient cancels an appointment online", "must not be able to override"], 2);
    await markReviewed(page, "examples_reviewed", ["say it is at 10am and they cancel at 8am", "refused under the 24-hour rule", "cancelled at 7am", "cancelled at 9am is refused"], 4);
    for (const check of ["story_rules_confirmed", "examples_reviewed", "changes_resolved", "questions_resolved", "final_version_recorded"]) {
      await expect(page.getByTestId(`dod-check-status-${check}`)).toHaveText("passes");
    }
    await expect(page.getByTestId("verified-badge")).toHaveText("Not verified");

    /* 10. Sign-off. */
    await signOff(page);
    const verified = (await (await request.get(`/api/sessions/${sessionId}`)).json()) as { session: { human_verified: boolean } };
    expect(verified.session.human_verified).toBe(true);
    await closeDrawer(page, "review");

    /* 11. Invalidation by a later change. */
    await play(page, "u31");
    await expect(page.getByTestId("verified-badge")).toHaveText("Not verified");
    await expect(page.getByTestId(`card-text-${ruleId}`)).toHaveText(/Make the GP window three hours\.$/);
    const liveExamples = page.getByTestId("column-example").locator("article[data-card]");
    await expect(liveExamples).toHaveCount(4);
    for (let i = 0; i < 4; i++) await expect(liveExamples.nth(i).locator('[data-testid^="card-needs-review-"]')).toBeVisible();
    await openDrawer(page, "review");
    const invalidated = page.getByTestId("signoff-invalidated");
    await expect(invalidated).toContainText("Sam");
    await expect(invalidated).toContainText("proposal.applied");

    /* 12. Re-verify. */
    await markReviewed(page, "story_rules_confirmed", ["Make the GP window three hours."], 1);
    await markReviewed(page, "examples_reviewed", ["say it is at 10am and they cancel at 8am", "refused under the 24-hour rule"], 4);
    await signOff(page);
    await expect(page.getByTestId("signoff-invalidated")).toHaveCount(0);
    await closeDrawer(page, "review");

    /* 13. Export. */
    await openDrawer(page, "export");
    await expect(page.getByTestId("export-gate")).toContainText("Human verified — revision");
    await expect(page.getByTestId("export-gate")).toContainText("signed by Sam");
    await expect(page.getByTestId("export-class").locator('option[value="backend.route.edit"]')).toHaveCount(1);
    await page.getByTestId("export-class").selectOption("backend.route.edit");
    await expect(page.getByTestId("export-slot-kind-route_identity")).toHaveText("required (structural)");
    await page.getByTestId("export-fact-slot-route_identity").fill("PUT /appointments/{id}/cancel");
    await page.getByTestId("export-save").click();
    await expect(page.getByTestId("export-options-status")).toContainText("change 1 of 1");
    await expect(page.getByTestId("export-preview")).toContainText("## Open questions explicitly accepted as outstanding");
    const hrefOf = async (file: string) => {
      const href = await page.getByTestId(`export-download-${file}`).getAttribute("href");
      expect(href).toBe(`/api/sessions/${sessionId}/export/${file}?draft=false`);
      return href!;
    };
    const backlogRes = await request.get(await hrefOf("crb-backlog-item.json"));
    expect(backlogRes.status()).toBe(200);
    const backlog = (await backlogRes.json()) as { id: string; labels: Record<string, string>; acceptance_criteria: string[]; structural_facts: string[] };
    expect(backlog.id).toMatch(/^a-patient-cancels-an-appointment-online-[0-9a-f]{8}$/);
    expect(backlog.labels.exmap_signoff ?? "").not.toBe("");
    expect(backlog.acceptance_criteria).toContain("Example: For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused under the 24-hour rule.");
    expect(backlog.acceptance_criteria).toContain("route_identity: PUT /appointments/{id}/cancel");
    expect(backlog.structural_facts).toHaveLength(1);
    const ticketMd = await (await request.get(await hrefOf("ticket.md"))).text();
    expect(ticketMd).toContain("## Open questions explicitly accepted as outstanding");
    expect(ticketMd).toContain("practice manager");
    const feature = await (await request.get(await hrefOf("requirement.feature"))).text();
    expect(feature).toContain("Rule:");
    expect(feature).toContain("Scenario:");
    expect(feature).toMatch(/accepted as outstanding by Sam/);
    const evidence = (await (await request.get(await hrefOf("evidence.json"))).json()) as { verified: boolean; signoff: { reviewer: { name: string } }; export_options_history: unknown[] };
    expect(evidence.verified).toBe(true);
    expect(evidence.signoff.reviewer.name).toBe("Sam");
    expect(evidence.export_options_history).toHaveLength(1);
    await closeDrawer(page, "export");

    /* 14. Draft gate. */
    const draftId = await createSession(request, { title: "Draft gate", story: fixture.story!, actor: "Sam" });
    const refused = await request.get(`/api/sessions/${draftId}/export/ticket.json`);
    expect(refused.status()).toBe(422);
    const refusal = (await refused.json()) as { reason: string; checks: { checks: unknown[] } };
    expect(refusal.reason).toBe("NOT_HUMAN_VERIFIED");
    expect(refusal.checks.checks).toHaveLength(5);
    const draft = await request.get(`/api/sessions/${draftId}/export/ticket.json?draft=true`);
    expect(draft.status()).toBe(200);
    expect(draft.headers()["content-disposition"]).toContain('filename="DRAFT-ticket.json"');
    expect(((await draft.json()) as { title: string }).title.startsWith("[DRAFT / NOT VERIFIED]")).toBe(true);
    await openSession(page, draftId);
    await openDrawer(page, "export");
    await expect(page.getByTestId("export-gate")).toContainText("Exports are refused until the requirement is human-verified.");
    await page.getByTestId("export-draft-toggle").check();
    await expect(page.getByTestId("export-download-ticket.json")).toHaveAttribute("href", `/api/sessions/${draftId}/export/ticket.json?draft=true`);
    await expect(page.getByTestId("export-download-ticket.json")).toHaveText("DRAFT-ticket.json");
  });

  test("typed variant: an add, an amend and a resolving removal through ManualInput yield the replay's ledger shapes", async ({ page, request }) => {
    test.setTimeout(120_000);
    await setName(request, "Sam");
    const sessionId = await createSession(request, { title: "Typed journey", story: fixture.story!, actor: "Sam" });
    // the rule exists before the talk, made by hand, so the typed removal has exactly one example to resolve to
    const made = await request.post(`/api/sessions/${sessionId}/cards`, {
      data: { actor: "Sam", card: { kind: "rule", text: "A patient should be able to cancel online, but not within two hours of their appointment." } },
    });
    expect(made.status()).toBe(200);
    await openSession(page, sessionId);
    await waitForHooks(page);
    const sentences = [
      "So for example, if a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused.",
      "Change that limit to 24 hours.",
      "Delete that example.",
    ];
    await expect(page.getByTestId("manual-lane")).toHaveValue("manual");
    for (const text of sentences) {
      await page.getByTestId("manual-input").fill(text);
      await page.getByTestId("manual-input").press("Enter");
      await expect(page.getByTestId("manual-input")).toHaveValue("");
      await settled(page);
    }
    await expect(transcriptRows(page)).toHaveCount(3);
    for (const text of sentences) {
      const row = transcriptRow(page, text);
      await expect(row.getByTestId("transcript-lane")).toHaveText("Typed");
      await expect(row.getByTestId("transcript-provider")).toHaveText("Typed");
      await expect(row.getByTestId("transcript-speaker")).toHaveText("Sam");
    }
    const rule = cards(page, "rule", "A patient should be able to cancel online");
    await expect(rule.locator('[data-testid^="card-text-"]')).toContainText("24 hours");
    await expect(page.getByTestId("column-example").locator("article[data-card]")).toHaveCount(0);
    await setHistory(page, true);
    const exId = await cardId(cards(page, "example", "the patient tries to cancel at 9am"));
    await expect(statusOf(page, exId)).toHaveText("removed");

    const res = await request.get(`/api/sessions/${sessionId}/events?after=0`);
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as { events: Array<Record<string, unknown> & { type: string }> };
    const recorded = body.events.filter((e) => e.type === "utterance.recorded").map((e) => e.utterance as Record<string, unknown>);
    expect(recorded).toHaveLength(3);
    for (const u of recorded) {
      expect(u).toMatchObject({ lane: "manual", provider: "manual", speaker: "Sam", model: null, is_local: true, confidence: null });
      expect(String(u.id)).toMatch(/^utt_[0-9a-f-]{8,40}$/);
      expect(Number(u.t_end_ms)).toBeGreaterThanOrEqual(Number(u.t_start_ms));
    }
    const classified = body.events.filter((e) => e.type === "utterance.classified");
    expect(classified.map((e) => e.intent)).toEqual(["add", "amend", "remove"]);
  });
});
