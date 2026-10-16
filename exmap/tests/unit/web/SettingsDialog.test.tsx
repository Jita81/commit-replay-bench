// TEST-PLAN §6.7 — Settings and the actor: an empty name blocks acts (an act button opens settings); the classifier
// status renders provider / model / reason from a mocked /api/config; no `claude-` literal under src/web; no password
// input and nothing named "key"; SessionPicker has settings-open.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { ConfigResponse } from "../../../src/core/types.js";
import { ApiClient } from "../../../src/web/api/client.js";
import { ProposalTray } from "../../../src/web/components/ProposalTray.js";
import { SessionPicker } from "../../../src/web/components/SessionPicker.js";
import { SettingsDialog } from "../../../src/web/components/SettingsDialog.js";
import { classifierChipText } from "../../../src/web/components/Header.js";
import { renderWithEnv, richMap } from "./helpers.js";

const CONFIG: ConfigResponse = {
  app: "exmap",
  version: "0.1.0",
  port: 4317,
  home: "/home/sam/.exmap",
  loopback: true,
  coop: true,
  classifier: { provider: "claude", reason: "ANTHROPIC_API_KEY is set", model: "served-model-from-config", credentials: "api_key", last_error: null },
};

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|css|html|json)$/.test(name)) out.push(p);
  }
  return out;
}

describe("Settings and the actor", () => {
  it("an empty name blocks acts: the act button opens settings instead of calling the API", async () => {
    const { b, ids } = richMap();
    const onNeedActor = vi.fn();
    const { api } = renderWithEnv(<ProposalTray />, { state: b.state, actor: "", onNeedActor });
    await userEvent.click(screen.getByTestId(`proposal-accept-${ids.pRemove}`));
    expect(onNeedActor).toHaveBeenCalledTimes(1);
    expect(api.acceptProposal).not.toHaveBeenCalled();
  });

  it("renders the classifier status from /api/config and never a key field", () => {
    renderWithEnv(<SettingsDialog open onClose={() => {}} userName="Sam" onSaveName={async () => {}} config={CONFIG} prompt="Set your name so the record says who did this" />, { state: richMap().b.state });
    const status = screen.getByTestId("classifier-status");
    expect(screen.getByTestId("classifier-provider")).toHaveTextContent("claude");
    expect(screen.getByTestId("classifier-model")).toHaveTextContent("served-model-from-config");
    expect(screen.getByTestId("classifier-reason")).toHaveTextContent("ANTHROPIC_API_KEY is set");
    expect(status).toBeInTheDocument();
    expect(screen.getByText("Set ANTHROPIC_API_KEY before starting to use Claude; without it the offline rules classifier is used.")).toBeInTheDocument();
    expect(screen.getByTestId("settings-prompt")).toHaveTextContent("Set your name so the record says who did this");
    expect(screen.getByTestId("settings-home")).toHaveTextContent("/home/sam/.exmap");
    const dialog = screen.getByTestId("settings-dialog");
    expect(dialog.querySelectorAll('input[type="password"]')).toHaveLength(0);
    for (const input of Array.from(dialog.querySelectorAll("input, textarea, select"))) {
      expect((input.getAttribute("name") ?? "").toLowerCase()).not.toContain("key");
      expect((input.getAttribute("data-testid") ?? "").toLowerCase()).not.toContain("key");
    }
  });

  it("the header chip names the provider, the served model and a fallback — never a model literal of its own", () => {
    expect(classifierChipText(null)).toContain("unknown");
    expect(classifierChipText({ ...CONFIG, classifier: { ...CONFIG.classifier, provider: "rules.v1", model: null } })).toBe("rules.v1 (offline)");
    expect(classifierChipText(CONFIG)).toBe("claude · served-model-from-config");
    expect(classifierChipText({ ...CONFIG, classifier: { ...CONFIG.classifier, last_error: { code: "CLASSIFIER_TIMEOUT", message: "x", at: "t" } } })).toBe("claude → rules.v1 (fallback: CLASSIFIER_TIMEOUT)");
  });

  it("saves the name through the callback", async () => {
    const onSaveName = vi.fn(async () => {});
    renderWithEnv(<SettingsDialog open onClose={() => {}} userName="" onSaveName={onSaveName} config={CONFIG} />, { state: richMap().b.state });
    await userEvent.type(screen.getByTestId("settings-name"), "Sam");
    await userEvent.click(screen.getByTestId("settings-save"));
    expect(onSaveName).toHaveBeenCalledWith("Sam");
  });

  it("no `claude-` model literal lives under src/web", () => {
    const root = resolve(process.cwd(), "src", "web");
    expect(existsSync(join(root, "App.tsx")), `src/web not found from ${process.cwd()}`).toBe(true);
    const offenders = walk(root).filter((p) => /claude-/i.test(readFileSync(p, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("SessionPicker carries settings-open", async () => {
    const api = new ApiClient("", async () => new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    const onSettings = vi.fn();
    renderWithEnv(<SessionPicker api={api} userName="" onOpen={() => {}} onSettings={onSettings} />, { state: richMap().b.state });
    await userEvent.click(screen.getByTestId("settings-open"));
    expect(onSettings).toHaveBeenCalled();
    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Example Map Live" })).toBeInTheDocument();
  });
});
