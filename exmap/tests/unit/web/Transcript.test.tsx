// Transcript (design §10.3) — extra to TEST-PLAN §6: rows carry the lane badge, the speaker a person assigned (or
// "— (no speaker label)"), mm:ss, the provider chip and the ledger-built chips; inner test ids never start with
// "utterance-" so the e2e row locator `[data-testid^="utterance-"]:not([data-testid^="utterance-proposals-"])` counts rows.
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Transcript } from "../../../src/web/components/Transcript.js";
import { classify } from "../core/fixtures.js";
import { MapBuilder, renderWithEnv, richMap } from "./helpers.js";

describe("Transcript", () => {
  it("renders one row per utterance with lane, speaker, mm:ss, provider and the proposal chips", () => {
    const { b, ids } = richMap();
    renderWithEnv(<Transcript />, { state: b.state });
    const log = screen.getByTestId("transcript");
    expect(log).toHaveAttribute("role", "log");
    expect(log).toHaveAttribute("aria-live", "polite");
    const rows = log.querySelectorAll('[data-testid^="utterance-"]:not([data-testid^="utterance-proposals-"])');
    expect(rows).toHaveLength(b.state.utterances.length);
    const remove = screen.getByTestId(`utterance-${ids.uRemove}`);
    expect(within(remove).getByTestId("transcript-lane")).toHaveTextContent("Me");
    expect(within(remove).getByTestId("transcript-speaker")).toHaveTextContent("Sam");
    expect(within(remove).getByTestId("transcript-provider")).toHaveTextContent("Replay");
    expect(within(remove).getByTestId("transcript-time")).toHaveTextContent(/^\d{2}:\d{2}$/);
    expect(within(screen.getByTestId(`utterance-proposals-${ids.uRemove}`)).getByTestId(`chip-proposal-${ids.pRemove}`)).toHaveTextContent("remove · applied");
  });

  it("a null speaker reads '— (no speaker label)'; none, classifying and fallback chips come from the ledger", () => {
    const b = new MapBuilder();
    const quiet = b.utter("Let's park that for now.", { speaker: null, lane: "manual", provider: "manual" });
    b.run(classify(quiet, "none", [], { heard_intent: "remove", rationale: "no card to remove" }));
    const waiting = b.utter("We also need an error case.");
    const fallback = b.utter("Right.");
    b.run(classify(fallback, "none", [], { classifier: { provider: "rules.v1", model: null, prompt_version: null, fallback_from: "claude", error: "rate_limit", actor: null }, rationale: "nothing" }));
    renderWithEnv(<Transcript />, { state: b.state });
    const q = screen.getByTestId(`utterance-${quiet}`);
    expect(within(q).getByTestId("transcript-speaker")).toHaveTextContent("— (no speaker label)");
    expect(within(q).getByTestId("transcript-provider")).toHaveTextContent("Typed");
    expect(within(q).getByTestId("transcript-lane")).toHaveTextContent("Typed");
    expect(screen.getByTestId(`utterance-proposals-${quiet}`)).toHaveTextContent("heard remove — no map change — no card to remove");
    expect(within(screen.getByTestId(`utterance-proposals-${waiting}`)).getByTestId("chip-classifying")).toHaveTextContent("classifying…");
    expect(screen.getByTestId(`utterance-proposals-${fallback}`)).toHaveTextContent("fallback from claude: rate_limit");
  });
});
