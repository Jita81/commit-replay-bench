// TEST-PLAN §6.6 — ExportDrawer: slot questions change with the class; structural/value chips; a free fact with a
// foreign slot shows the prose warning; download links carry ?draft=true when toggled and use crb-backlog-item.json;
// gate text for unverified; the options-history disclosure from state.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ExportDrawer } from "../../../src/web/components/ExportDrawer.js";
import { OPTIONS, OPTIONS_2, verifiedState } from "../export/fixtures.js";
import { fakeApi, renderWithEnv, richMap } from "./helpers.js";

const CATALOGUE = {
  classes: {
    "backend.route.edit": [
      { name: "route_identity", question: "Which existing route (method + path) changes?", kind: "structural" as const },
      { name: "behaviour_change", question: "What changes in its request/response shape or semantics?", kind: "structural" as const },
      { name: "example_payload", question: "A representative request and its exact expected response.", kind: "value" as const },
    ],
    "bug.fix": [
      { name: "reproduction", question: "How is the bug reproduced (the input / sequence that fails)?", kind: "structural" as const },
      { name: "exact_value", question: "The exact output value / message at the reproduction input.", kind: "value" as const },
    ],
  },
};

function api() {
  return fakeApi({ catalogue: vi.fn(async () => CATALOGUE), exportText: vi.fn(async () => "# Appointment cancellation\n\n## Rules") });
}

const noop = () => {};

describe("ExportDrawer", () => {
  it("slot questions change with the class and carry structural / value chips", async () => {
    const { b } = richMap();
    renderWithEnv(<ExportDrawer open onClose={noop} />, { state: b.state, api: api() });
    const cls = await screen.findByTestId("export-class");
    await waitFor(() => expect(within(cls).getAllByRole("option")).toHaveLength(3));
    expect(screen.queryByTestId("export-fact-slot-route_identity")).not.toBeInTheDocument();
    await userEvent.selectOptions(cls, "backend.route.edit");
    expect(screen.getByTestId("export-fact-slot-route_identity")).toBeInTheDocument();
    expect(screen.getByTestId("export-slots")).toHaveTextContent("Which existing route (method + path) changes?");
    expect(screen.getByTestId("export-slot-kind-route_identity")).toHaveTextContent("required (structural)");
    expect(screen.getByTestId("export-slot-kind-example_payload")).toHaveTextContent("value — routes, does not block");
    await userEvent.selectOptions(cls, "bug.fix");
    expect(screen.queryByTestId("export-fact-slot-route_identity")).not.toBeInTheDocument();
    expect(screen.getByTestId("export-fact-slot-reproduction")).toBeInTheDocument();
  });

  it("a free fact with a foreign slot shows the prose warning; Save sends the facts", async () => {
    const { b } = richMap();
    const a = api();
    renderWithEnv(<ExportDrawer open onClose={noop} />, { state: b.state, api: a });
    const cls = await screen.findByTestId("export-class");
    await waitFor(() => expect(within(cls).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(cls, "backend.route.edit");
    await userEvent.click(screen.getByTestId("export-fact-slot-route_identity"));
    await userEvent.paste("PUT /appointments/{id}/cancel");
    await userEvent.click(screen.getByTestId("export-fact-add"));
    await userEvent.type(screen.getByTestId("export-free-slot-0"), "reproduction");
    await userEvent.type(screen.getByTestId("export-free-text-0"), "cancel at 9am");
    expect(screen.getByTestId("export-free-warning-0")).toHaveTextContent("crb will keep this as prose");
    await userEvent.click(screen.getByTestId("export-save"));
    expect(a.putExportOptions).toHaveBeenCalledWith("Sam", {
      capability_class: "backend.route.edit",
      kind: "code",
      size_estimate: "unsized",
      facts: [
        { slot: "route_identity", text: "PUT /appointments/{id}/cancel" },
        { slot: "reproduction", text: "cancel at 9am" },
      ],
    });
    await waitFor(() => expect(screen.getByTestId("export-options-status")).toHaveTextContent("change 1 of 1"));
    expect(screen.getByTestId("export-options-status")).toHaveTextContent("not part of the sign-off");
  });

  it("download links carry ?draft=true when toggled and use the crb file names", async () => {
    const { b } = richMap();
    renderWithEnv(<ExportDrawer open onClose={noop} />, { state: b.state, api: api() });
    const link = await screen.findByTestId("export-download-crb-backlog-item.json");
    expect(link).toHaveAttribute("href", expect.stringContaining("/export/crb-backlog-item.json?draft=false"));
    expect(link).toHaveAttribute("download");
    await userEvent.click(screen.getByTestId("export-draft-toggle"));
    expect(screen.getByTestId("export-download-crb-backlog-item.json")).toHaveAttribute("href", expect.stringContaining("/export/crb-backlog-item.json?draft=true"));
    expect(screen.getByTestId("export-download-crb-backlog-item.json")).toHaveTextContent("DRAFT-crb-backlog-item.json");
    for (const file of ["ticket.json", "ticket.md", "requirement.feature", "evidence.json"]) {
      expect(screen.getByTestId(`export-download-${file}`)).toHaveAttribute("href", expect.stringContaining(`/export/${file}?draft=true`));
    }
  });

  it("the gate names the failing checks for an unverified map and 'Human verified' for a verified one", async () => {
    const { b } = richMap();
    renderWithEnv(<ExportDrawer open onClose={noop} />, { state: b.state, api: api() });
    const gate = await screen.findByTestId("export-gate");
    expect(gate).toHaveTextContent("Exports are refused until the requirement is human-verified. You can download DRAFT / NOT VERIFIED files instead.");
    expect(gate).toHaveTextContent("Story and business rules accurately represent the agreed intent");
  });

  it("a verified map shows the sign-off and the options history from state", async () => {
    const state = verifiedState({ options: [OPTIONS, OPTIONS_2] });
    renderWithEnv(<ExportDrawer open onClose={noop} />, { state, api: api() });
    const gate = await screen.findByTestId("export-gate");
    expect(gate).toHaveTextContent(/Human verified — revision [0-9a-f]{8}, signed by Sam/);
    const status = screen.getByTestId("export-options-status");
    expect(status).toHaveTextContent("Supplied at export by Sam");
    expect(status).toHaveTextContent("(change 2 of 2)");
    const history = screen.getByTestId("export-options-history");
    expect(history).toHaveTextContent("Earlier values (1)");
    expect(history).toHaveTextContent("change 1 by Sam");
    await waitFor(() => expect(screen.getByTestId("export-fact-slot-route_identity")).toHaveValue("PUT /appointments/{id}/cancel"));
    expect(screen.getByTestId("export-class")).toHaveValue("backend.route.edit");
    await waitFor(() => expect(screen.getByTestId("export-preview")).toHaveTextContent("# Appointment cancellation"));
  });
});
