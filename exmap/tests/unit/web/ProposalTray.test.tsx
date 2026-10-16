// TEST-PLAN §6.4 — ProposalTray: rationale and a numeric confidence; Accept calls api.acceptProposal; Accept on a
// removal and Reject reads "Restore"; an unreviewed act / an open clarification 15 utterances old is still listed;
// template clarifications render candidates, the "Will:" line and the text field; pending_operation renders Yes;
// a pure question renders only text + Dismiss; text answers are listed under the question.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ProposalTray, trayItems } from "../../../src/web/components/ProposalTray.js";
import { MapBuilder, renderWithEnv, richMap } from "./helpers.js";

describe("ProposalTray", () => {
  it("items show the rationale and a numeric confidence", () => {
    const { b, ids } = richMap();
    renderWithEnv(<ProposalTray />, { state: b.state });
    const item = screen.getByTestId(`proposal-${ids.pRemove}`);
    expect(within(item).getByTestId(`proposal-rationale-${ids.pRemove}`)).toHaveTextContent("removal of the last example");
    expect(within(item).getByTestId(`proposal-confidence-${ids.pRemove}`)).toHaveTextContent("0.5");
    const update = screen.getByTestId(`proposal-${ids.pRuleUpdate}`);
    expect(within(update).getByTestId(`proposal-confidence-${ids.pRuleUpdate}`)).toHaveTextContent("0.83");
    expect(within(update).getByTestId(`proposal-diff-${ids.pRuleUpdate}`)).toHaveTextContent("24 hours for nurse appointments");
  });

  it("Accept calls api.acceptProposal with the actor", async () => {
    const { b, ids } = richMap();
    const { api } = renderWithEnv(<ProposalTray />, { state: b.state });
    await userEvent.click(screen.getByTestId(`proposal-accept-${ids.pRemove}`));
    expect(api.acceptProposal).toHaveBeenCalledWith(ids.pRemove, "Sam");
  });

  it("a removal offers Accept, its Reject reads 'Restore', and it carries the unreviewed line", () => {
    const { b, ids } = richMap();
    renderWithEnv(<ProposalTray />, { state: b.state });
    const item = screen.getByTestId(`proposal-${ids.pRemove}`);
    expect(within(item).getByTestId(`proposal-accept-${ids.pRemove}`)).toBeInTheDocument();
    expect(within(item).getByTestId(`proposal-reject-${ids.pRemove}`)).toHaveTextContent("Restore");
    expect(within(item).getByTestId(`proposal-unreviewed-${ids.pRemove}`)).toHaveTextContent("AI act — needs a person's Accept or Reject");
    expect(within(item).getByTestId(`proposal-intent-${ids.pRemove}`)).toHaveTextContent("remove");
  });

  it("an unreviewed act and an open clarification 15 utterances old are still listed", () => {
    const { b, ids } = richMap();
    for (let i = 0; i < 15; i++) b.chatter(`Chatter number ${i + 1}.`);
    renderWithEnv(<ProposalTray />, { state: b.state });
    expect(screen.getByTestId(`proposal-${ids.pRemove}`)).toBeInTheDocument();
    expect(screen.getByTestId(`clarification-${ids.clar}`)).toBeInTheDocument();
    // the plain applied update is older than the last 10 utterances: it lives in the transcript now
    expect(screen.queryByTestId(`proposal-${ids.pRuleUpdate}`)).not.toBeInTheDocument();
    const items = trayItems(b.state);
    expect(items.map((i) => i.kind)).toEqual(["clarification", "proposal"]);
  });

  it("a template clarification renders one button per candidate, a 'Will:' line and the text field", async () => {
    const { b, ids } = richMap();
    const { api } = renderWithEnv(<ProposalTray />, { state: b.state });
    const item = screen.getByTestId(`clarification-${ids.clar}`);
    expect(item).toHaveAttribute("role", "group");
    expect(within(item).getByTestId(`clarification-will-${ids.clar}`)).toHaveTextContent("Will: remove the chosen example");
    const nurse = within(item).getByTestId(`clarification-candidate-${ids.clar}-${ids.exNurse}`);
    const gp = within(item).getByTestId(`clarification-candidate-${ids.clar}-${ids.exGp}`);
    expect(nurse).toHaveTextContent("(example)");
    expect(within(item).getAllByRole("button", { name: /\(example\)/ })).toHaveLength(2);
    expect(within(item).getByTestId(`clarification-text-${ids.clar}`)).toBeInTheDocument();
    expect(within(item).getByTestId(`clarification-dismiss-${ids.clar}`)).toBeInTheDocument();
    expect(within(item).queryByTestId(`clarification-yes-${ids.clar}`)).not.toBeInTheDocument();
    await userEvent.click(gp);
    expect(api.answerClarification).toHaveBeenCalledWith(ids.clar, "Sam", { kind: "candidate", card_id: ids.exGp });
    await userEvent.type(within(item).getByTestId(`clarification-text-${ids.clar}`), "the GP one");
    await userEvent.click(within(item).getByTestId(`clarification-text-submit-${ids.clar}`));
    expect(api.answerClarification).toHaveBeenCalledWith(ids.clar, "Sam", { kind: "text", text: "the GP one" });
  });

  it("a pending_operation clarification renders Yes and no candidates", async () => {
    const { b, ids } = richMap();
    const u = b.utter("Delete the nurse one, I think.");
    const { cid } = b.clarify("remove", u, { question: "Did you mean: remove the nurse example?", pending: { kind: "card.remove", card_id: ids.exNurse } });
    const { api } = renderWithEnv(<ProposalTray />, { state: b.state });
    const item = screen.getByTestId(`clarification-${cid}`);
    const yes = within(item).getByTestId(`clarification-yes-${cid}`);
    expect(yes).toHaveTextContent(/^Yes — remove example/);
    expect(within(item).queryAllByTestId(/clarification-candidate-/)).toHaveLength(0);
    expect(within(item).getByTestId(`clarification-will-${cid}`)).toHaveTextContent("Will: remove example");
    await userEvent.click(yes);
    expect(api.answerClarification).toHaveBeenCalledWith(cid, "Sam", { kind: "yes" });
  });

  it("a pure question renders only the text field and Dismiss, and Dismiss needs a reason", async () => {
    const b = new MapBuilder();
    b.human({ kind: "card.create", card: { kind: "story", text: "A patient cancels an appointment online" } });
    const u = b.utter("That one should go.");
    const { cid } = b.clarify("remove", u, { question: "Which card should go?" });
    const { api } = renderWithEnv(<ProposalTray />, { state: b.state });
    const item = screen.getByTestId(`clarification-${cid}`);
    expect(within(item).queryAllByTestId(/clarification-candidate-/)).toHaveLength(0);
    expect(within(item).queryByTestId(`clarification-yes-${cid}`)).not.toBeInTheDocument();
    expect(within(item).queryByTestId(`clarification-will-${cid}`)).not.toBeInTheDocument();
    expect(within(item).getByTestId(`clarification-text-${cid}`)).toBeInTheDocument();
    await userEvent.click(within(item).getByTestId(`clarification-dismiss-${cid}`));
    await userEvent.type(within(item).getByTestId(`clarification-dismiss-reason-${cid}`), "never mind");
    await userEvent.click(within(item).getByTestId(`clarification-dismiss-confirm-${cid}`));
    expect(api.answerClarification).toHaveBeenCalledWith(cid, "Sam", { kind: "dismiss", reason: "never mind" });
  });

  it("text answers are listed under the question and the clarification stays open", () => {
    const { b, ids } = richMap();
    b.run({ kind: "clarification.answer", clarification_id: ids.clar, answer: { kind: "text", text: "the GP one", utterance_id: null }, actor: "Sam" });
    renderWithEnv(<ProposalTray />, { state: b.state });
    const item = screen.getByTestId(`clarification-${ids.clar}`);
    expect(within(item).getByTestId(`clarification-text-answers-${ids.clar}`)).toHaveTextContent("answered in words by Sam: “the GP one” — still open");
  });

  it("shows the classifier's last error once as a dismissible notice", async () => {
    const { b } = richMap();
    renderWithEnv(<ProposalTray lastError={{ code: "CLASSIFIER_TIMEOUT", message: "timed out after 45 s", at: "2026-10-16T12:00:00.000Z" }} />, { state: b.state });
    const notice = screen.getByTestId("classifier-notice");
    expect(notice).toHaveTextContent("CLASSIFIER_TIMEOUT");
    await userEvent.click(screen.getByTestId("classifier-notice-dismiss"));
    expect(screen.queryByTestId("classifier-notice")).not.toBeInTheDocument();
  });
});
