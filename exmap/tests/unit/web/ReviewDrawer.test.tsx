// TEST-PLAN §6.5 — ReviewDrawer: five checks with pass/fail text; dod-mark-* only on checks 1, 2, 4; the mark sends
// exactly the previewed card_ids; check 3 renders dod-act-accept-* per unreviewed act and a link per open
// clarification; the invalidation notice; the "signed off but not currently verified" line; the catching-up gate;
// submit disabled until both fields are filled; a 422 renders signoff-errors.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { dodReport } from "../../../src/core/index.js";
import { ApiError } from "../../../src/web/api/client.js";
import { ReviewDrawer, markList } from "../../../src/web/components/ReviewDrawer.js";
import { activeButDodFailedState, invalidatedState, verifiedState } from "../export/fixtures.js";
import { fakeApi, renderWithEnv, richMap } from "./helpers.js";

const noop = () => {};

describe("ReviewDrawer", () => {
  it("renders the five checks with pass / fail text and their details", () => {
    const { b } = richMap();
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state: b.state });
    expect(screen.getByTestId("review-drawer")).toHaveAttribute("aria-modal", "true");
    const report = dodReport(b.state);
    for (const check of report.checks) {
      expect(screen.getByTestId(`dod-check-${check.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`dod-check-status-${check.id}`)).toHaveTextContent(check.pass ? "passes" : "fails");
    }
    expect(screen.getByTestId("dod-check-status-story_rules_confirmed")).toHaveTextContent("fails");
    expect(screen.getByTestId("dod-check-status-final_version_recorded")).toHaveTextContent("passes");
    expect(screen.getByTestId("review-verified")).toHaveTextContent("Not verified");
  });

  it("offers Mark reviewed only on checks 1, 2 and 4", () => {
    const { b } = richMap();
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state: b.state });
    expect(screen.getByTestId("dod-mark-story_rules_confirmed")).toBeInTheDocument();
    expect(screen.getByTestId("dod-mark-examples_reviewed")).toBeInTheDocument();
    expect(screen.getByTestId("dod-mark-questions_resolved")).toBeInTheDocument();
    expect(screen.queryByTestId("dod-mark-changes_resolved")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dod-mark-final_version_recorded")).not.toBeInTheDocument();
  });

  it("the mark previews the list and sends exactly those card_ids", async () => {
    const { b, ids } = richMap();
    const { api } = renderWithEnv(<ReviewDrawer open onClose={noop} />, { state: b.state });
    await userEvent.click(screen.getByTestId("dod-mark-story_rules_confirmed"));
    const list = screen.getByTestId("dod-mark-list-story_rules_confirmed");
    const previewed = Array.from(list.querySelectorAll("[data-card-id]")).map((el) => el.getAttribute("data-card-id"));
    expect(previewed).toEqual([ids.rule]); // the story is already confirmed
    expect(markList(b.state, "story_rules_confirmed")).toEqual([ids.rule]);
    await userEvent.click(screen.getByTestId("dod-mark-confirm-story_rules_confirmed"));
    expect(api.reviewChecks).toHaveBeenCalledWith("Sam", "story_rules_confirmed", [ids.rule]);
    // check 2 lists the flagged example (exGp is confirmed and unflagged)
    expect(markList(b.state, "examples_reviewed")).toEqual([ids.exNurse]);
    // check 4 lists the answered, unconfirmed question only
    expect(markList(b.state, "questions_resolved")).toEqual([ids.q2]);
  });

  it("check 3 is actionable in place: Accept / Reject per unreviewed act and a link per open clarification", async () => {
    const { b, ids } = richMap();
    const onClose = vi.fn();
    const { api } = renderWithEnv(<ReviewDrawer open onClose={onClose} />, { state: b.state });
    expect(screen.getByTestId("dod-check-status-changes_resolved")).toHaveTextContent("fails");
    expect(screen.getByTestId(`dod-act-reject-${ids.pRemove}`)).toHaveTextContent("Restore");
    await userEvent.click(screen.getByTestId(`dod-act-accept-${ids.pRemove}`));
    expect(api.acceptProposal).toHaveBeenCalledWith(ids.pRemove, "Sam");
    expect(screen.getByTestId(`dod-clarification-${ids.clar}`)).toHaveTextContent("Which example do you mean");
    await userEvent.click(screen.getByTestId(`dod-clarification-${ids.clar}`));
    expect(onClose).toHaveBeenCalled();
  });

  it("outstanding questions are accepted with a required reason and never called answered", async () => {
    const { b, ids } = richMap();
    const { api } = renderWithEnv(<ReviewDrawer open onClose={noop} />, { state: b.state });
    const accept = screen.getByTestId(`question-accept-${ids.q1}`);
    expect(accept).toBeDisabled();
    expect(screen.queryByTestId(`question-accept-${ids.q2}`)).not.toBeInTheDocument(); // answered: not outstanding
    await userEvent.type(screen.getByTestId("question-accept-reason"), "To be settled with the practice manager");
    expect(accept).toBeEnabled();
    await userEvent.click(accept);
    expect(api.acceptQuestion).toHaveBeenCalledWith(ids.q1, "Sam", "To be settled with the practice manager");
    b.run({ kind: "question.accept", question_id: ids.q1, by: "Sam", reason: "To be settled with the practice manager" });
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state: b.state });
    const accepted = screen.getAllByTestId("accepted-questions").at(-1)!;
    expect(accepted).toHaveTextContent("accepted outstanding by Sam: To be settled with the practice manager");
    expect(accepted).not.toHaveTextContent("answered");
  });

  it("shows the invalidation notice when the last sign-off is invalidated", () => {
    const state = invalidatedState();
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state });
    const notice = screen.getByTestId("signoff-invalidated");
    expect(notice).toHaveAttribute("role", "status");
    expect(notice).toHaveTextContent("The sign-off by Sam");
    expect(notice).toHaveTextContent("was invalidated by");
    expect(notice).toHaveTextContent("Review the map and sign off again.");
    expect(screen.getByTestId("review-verified")).toHaveTextContent("Not verified");
  });

  it("shows 'signed off but not currently verified' with check 3's details", () => {
    const state = activeButDodFailedState();
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state });
    expect(screen.getByTestId("signoff-not-current")).toHaveTextContent("Signed off on this revision, but not currently verified: clarification clar_1 is open");
    expect(screen.queryByTestId("signoff-invalidated")).not.toBeInTheDocument();
  });

  it("a verified map reads human verified and shows the sign-off status from the ledger", () => {
    const state = verifiedState();
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state });
    expect(screen.getByTestId("review-verified")).toHaveTextContent("Human verified by Sam");
    expect(screen.getByTestId("signoff-status")).toHaveTextContent("Signed off by Sam");
  });

  it("the catching-up gate disables submit until the backlog is 0 or 'sign off anyway' is ticked", async () => {
    const { b } = richMap();
    renderWithEnv(<ReviewDrawer open onClose={noop} pendingWork={() => 3} />, { state: b.state });
    expect(screen.getByTestId("review-catching-up")).toHaveTextContent("Transcription is still catching up (3 segments or utterances on their way into the ledger)");
    await userEvent.click(screen.getByTestId("signoff-insert"));
    expect(screen.getByTestId("signoff-reviewer")).toHaveValue("Sam");
    const submit = screen.getByTestId("signoff-submit");
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByTestId("signoff-anyway"));
    expect(submit).toBeEnabled();
  });

  it("submit stays disabled until both the reviewer and the statement are filled", async () => {
    const { b } = richMap();
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state: b.state, actor: "" });
    const submit = screen.getByTestId("signoff-submit");
    expect(screen.queryByTestId("review-catching-up")).not.toBeInTheDocument();
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByTestId("signoff-reviewer"), "Sam");
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByTestId("signoff-insert"));
    expect(screen.getByTestId("signoff-statement")).toHaveValue("I have reviewed the complete requirement and confirm it represents the agreed intent.");
    expect(submit).toBeEnabled();
  });

  it("a 422 renders the failing checks inline", async () => {
    const { b } = richMap();
    const checks = dodReport(b.state);
    const api = fakeApi({
      signoff: vi.fn(async () => {
        throw new ApiError(422, { reason: "SIGNOFF_DOD_FAILED", detail: "the Definition of Done fails", checks });
      }),
    });
    renderWithEnv(<ReviewDrawer open onClose={noop} />, { state: b.state, api });
    await userEvent.click(screen.getByTestId("signoff-insert"));
    await userEvent.click(screen.getByTestId("signoff-submit"));
    const errors = await screen.findByTestId("signoff-errors");
    expect(errors).toHaveTextContent("The sign-off was refused");
    expect(errors).toHaveTextContent("Story and business rules accurately represent the agreed intent");
    expect(within(errors).queryByText(/final version/i)).not.toBeInTheDocument();
    expect(api.signoff).toHaveBeenCalledWith("Sam", "I have reviewed the complete requirement and confirm it represents the agreed intent.", b.state.revisions.at(-1)!.hash);
  });
});
