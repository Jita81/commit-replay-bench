// TEST-PLAN §6.3 — Board: four columns with the kind backgrounds; cards show text, a status chip from statusLabel (a
// removed card reads "removed", never "rejected"), the version; the history toggle; the needs_review chip; provenance
// shows restored_by and confirmation.by; keyboard: ArrowDown, ArrowRight, Enter opens the menu, Escape returns focus.
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Board } from "../../../src/web/components/Board.js";
import { renderWithEnv, richMap } from "./helpers.js";

describe("Board", () => {
  it("renders the four Example Mapping columns with their backgrounds and counts", () => {
    const { b } = richMap();
    renderWithEnv(<Board />, { state: b.state });
    expect(screen.getByTestId("board")).toBeInTheDocument();
    expect(screen.getByTestId("column-story")).toHaveClass("bg-yellow-100", "text-slate-900");
    expect(screen.getByTestId("column-rule")).toHaveClass("bg-sky-100", "text-slate-900");
    expect(screen.getByTestId("column-example")).toHaveClass("bg-green-100", "text-slate-900");
    expect(screen.getByTestId("column-question")).toHaveClass("bg-red-100", "text-slate-900");
    expect(screen.getByRole("region", { name: "Story (1)" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Examples (2)" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Questions (2)" })).toBeInTheDocument();
  });

  it("cards show their text, a statusLabel chip and the version", () => {
    const { b, ids } = richMap();
    renderWithEnv(<Board />, { state: b.state });
    const rule = screen.getByTestId(`card-${ids.rule}`);
    expect(within(rule).getByTestId(`card-text-${ids.rule}`)).toHaveTextContent("24 hours for nurse appointments");
    expect(within(rule).getByTestId(`card-status-${ids.rule}`)).toHaveTextContent("applied");
    expect(within(rule).getByTestId(`card-version-${ids.rule}`)).toHaveTextContent("v2");
    expect(screen.getByTestId(`card-status-${ids.story}`)).toHaveTextContent("confirmed");
    expect(screen.getByTestId(`card-status-${ids.exGp}`)).toHaveTextContent("confirmed");
    expect(screen.getByTestId(`card-link-${ids.exGp}`)).toHaveTextContent("for rule:");
    expect(screen.getByTestId(`card-link-${ids.q1}`)).toHaveTextContent("about:");
    expect(screen.getByTestId(`card-answer-${ids.q1}`)).toHaveTextContent("unanswered");
    expect(screen.getByTestId(`card-answer-${ids.q2}`)).toHaveTextContent("answer: Yes, a nurse may cancel");
  });

  it("the history toggle hides non-live cards by default and shows them struck through as 'removed'", async () => {
    const { b, ids } = richMap();
    renderWithEnv(<Board />, { state: b.state });
    expect(screen.queryByTestId(`card-${ids.exRemoved}`)).not.toBeInTheDocument();
    const toggle = screen.getByTestId("history-toggle");
    expect(toggle).toHaveAttribute("role", "switch");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    const removed = screen.getByTestId(`card-${ids.exRemoved}`);
    expect(within(removed).getByTestId(`card-status-${ids.exRemoved}`)).toHaveTextContent("removed");
    expect(within(removed).getByTestId(`card-status-${ids.exRemoved}`)).not.toHaveTextContent("rejected");
    expect(within(removed).getByTestId(`card-text-${ids.exRemoved}`)).toHaveClass("line-through");
    expect(removed).toHaveClass("opacity-60");
    expect(within(removed).queryByTestId(`card-menu-button-${ids.exRemoved}`)).not.toBeInTheDocument();
    expect(within(removed).getByTestId(`card-provenance-${ids.exRemoved}`)).toBeInTheDocument();
  });

  it("shows the needs_review chip with the reason", () => {
    const { b, ids } = richMap();
    renderWithEnv(<Board />, { state: b.state });
    expect(screen.getByTestId(`card-needs-review-${ids.exNurse}`)).toHaveTextContent(/needs review: rule changed \(event .+\)/);
    expect(screen.queryByTestId(`card-needs-review-${ids.exGp}`)).not.toBeInTheDocument();
  });

  it("provenance shows the confirmation and a restore", async () => {
    const { b, ids } = richMap();
    const undo = b.human({ kind: "undo", to_revision_seq: null }).pid; // restores the removed example
    renderWithEnv(<Board />, { state: b.state });
    await userEvent.click(screen.getByTestId(`card-provenance-${ids.exGp}`));
    const prov = screen.getByTestId(`provenance-${ids.exGp}`);
    expect(prov).toHaveAttribute("role", "dialog");
    expect(within(prov).getByTestId(`confirmed-by-${ids.exGp}`)).toHaveTextContent("confirmed by Sam (version seen v1)");
    expect(prov).toHaveTextContent("classifier: rules.v1");
    expect(prov).toHaveTextContent("confidence: 1");
    await userEvent.click(screen.getByTestId(`card-provenance-${ids.exRemoved}`));
    const restored = screen.getByTestId(`provenance-${ids.exRemoved}`);
    expect(within(restored).getByTestId(`restored-by-${ids.exRemoved}`)).toHaveTextContent(`restored by undo ${undo}`);
    expect(screen.getByTestId(`card-status-${ids.exRemoved}`)).toHaveTextContent("applied");
    await userEvent.click(screen.getByTestId(`card-provenance-${ids.rule}`));
    expect(screen.getByTestId(`provenance-${ids.rule}`)).toHaveTextContent("v1 → v2 replaced by");
  });

  it("a removed card's provenance names the act's classifier and who reviewed it; definitions read 'term — definition'", async () => {
    const { b, ids } = richMap();
    b.ai({ kind: "definition.refine", card_id: ids.story, term: "appointment", definition: "a booked slot, not a walk-in" }, b.utter("By appointment I mean a booked slot, not a walk-in."));
    renderWithEnv(<Board showHistory />, { state: b.state });
    expect(screen.getByTestId(`card-definitions-${ids.story}`).textContent).toBe("appointment — a booked slot, not a walk-in");
    await userEvent.click(screen.getByTestId(`card-provenance-${ids.exRemoved}`));
    const before = screen.getByTestId(`rejection-${ids.exRemoved}`);
    expect(before).toHaveTextContent(`removed by proposal ${ids.pRemove}`);
    expect(before).toHaveTextContent("classifier: rules.v1, confidence 0.5");
    expect(screen.getByTestId(`rejection-review-${ids.exRemoved}`)).toHaveTextContent("not reviewed — an AI act needs a person's Accept or Reject");
  });

  it("a removal reviewed by voice reads 'confirmed by voice (<provider>, <confidence>, speaker <label>)'", async () => {
    const { b, ids } = richMap();
    const yes = b.utter("Yes.", { speaker: "Priya" });
    b.ai({ kind: "confirm", card_ids: [], proposal_ids: [ids.pRemove] }, yes, { confidence: 0.5, stamp: { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null, actor: "Priya" } });
    renderWithEnv(<Board showHistory />, { state: b.state });
    await userEvent.click(screen.getByTestId(`card-provenance-${ids.exRemoved}`));
    expect(screen.getByTestId(`rejection-review-${ids.exRemoved}`)).toHaveTextContent("review: confirmed by voice (rules.v1, 0.5, speaker Priya)");
  });

  it("keyboard: ArrowDown moves to the next card, ArrowRight to the next column, Enter opens the menu and Escape returns focus", async () => {
    const { b, ids } = richMap();
    renderWithEnv(<Board />, { state: b.state });
    const rule = screen.getByTestId(`card-${ids.rule}`);
    const exGp = screen.getByTestId(`card-${ids.exGp}`);
    const exNurse = screen.getByTestId(`card-${ids.exNurse}`);
    expect(exGp).toHaveAttribute("tabindex", "0");
    expect(exNurse).toHaveAttribute("tabindex", "-1");
    exGp.focus();
    fireEvent.keyDown(exGp, { key: "ArrowDown" });
    expect(document.activeElement).toBe(exNurse);
    expect(exNurse).toHaveAttribute("tabindex", "0");
    expect(exGp).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(exNurse, { key: "ArrowUp" });
    expect(document.activeElement).toBe(exGp);
    rule.focus();
    fireEvent.keyDown(rule, { key: "ArrowRight" });
    expect(document.activeElement).toBe(exGp);
    fireEvent.keyDown(exGp, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(rule);
    fireEvent.keyDown(rule, { key: "Enter" });
    const menu = await screen.findByTestId(`card-menu-${ids.rule}`);
    expect(menu).toHaveAttribute("role", "menu");
    expect(document.activeElement).toBe(within(menu).getByTestId(`card-confirm-${ids.rule}`));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByTestId(`card-menu-${ids.rule}`)).not.toBeInTheDocument();
    expect(document.activeElement).toBe(rule);
  });

  it("on a confirmed card the menu still takes focus (Confirm is aria-disabled) and Escape closes it", async () => {
    const { b, ids } = richMap();
    const { api } = renderWithEnv(<Board />, { state: b.state });
    const story = screen.getByTestId(`card-${ids.story}`);
    story.focus();
    fireEvent.keyDown(story, { key: "Enter" });
    const menu = await screen.findByTestId(`card-menu-${ids.story}`);
    const confirm = within(menu).getByTestId(`card-confirm-${ids.story}`);
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(document.activeElement).toBe(confirm);
    await userEvent.click(confirm);
    expect(api.confirmCard).not.toHaveBeenCalled();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByTestId(`card-menu-${ids.story}`)).not.toBeInTheDocument();
    expect(document.activeElement).toBe(story);
  });

  it("the card menu sends a human confirm / remove through the API", async () => {
    const { b, ids } = richMap();
    const { api } = renderWithEnv(<Board />, { state: b.state });
    await userEvent.click(screen.getByTestId(`card-menu-button-${ids.rule}`));
    await userEvent.click(screen.getByTestId(`card-confirm-${ids.rule}`));
    expect(api.confirmCard).toHaveBeenCalledWith(ids.rule, "Sam");
    await userEvent.click(screen.getByTestId(`card-menu-button-${ids.q1}`));
    await userEvent.click(screen.getByTestId(`card-remove-${ids.q1}`));
    expect(api.removeCard).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId(`card-remove-confirm-${ids.q1}`));
    expect(api.removeCard).toHaveBeenCalledWith(ids.q1, "Sam");
  });
});
