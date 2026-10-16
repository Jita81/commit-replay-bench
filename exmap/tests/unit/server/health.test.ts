// TEST-PLAN §4.1 — GET /api/health and GET /api/config (provider selection, reason, model, never a credential, last_error).
import { APIConnectionError } from "@anthropic-ai/sdk";
import { describe, expect, it } from "vitest";
import { CLAUDE_MODEL } from "../../../src/classifier/constants.js";
import type { CreateResult, ModelClient } from "../../../src/classifier/claude/client.js";
import type { ConfigResponse } from "../../../src/core/types.js";
import { buildApp, type ExmapApp } from "../../../src/server/app.js";
import { call, createSession, json, makeApp, postUtterance, tempHome, track, uttId } from "./helpers.js";

/** An app with the real classifier selection (no injected classifier) over `env`. */
async function envApp(env: NodeJS.ProcessEnv, modelClient?: ModelClient): Promise<ExmapApp> {
  return track(await buildApp({ home: tempHome(), port: 4317, webDist: null, ortDir: null, env, ...(modelClient ? { modelClient } : {}) }));
}

function fakeModel(script: Array<CreateResult | Error>): ModelClient & { count: number } {
  let i = 0;
  const client = {
    count: 0,
    messages: {
      async create(): Promise<CreateResult> {
        client.count++;
        const step = script[Math.min(i++, script.length - 1)]!;
        if (step instanceof Error) throw step;
        return step;
      },
    },
  };
  return client;
}

function addRuleReply(text = "Patients must confirm a cancellation by email."): CreateResult {
  const body = {
    intent: "add",
    operations: [{ kind: "card.create", card: { kind: "rule", text, rule_id: null, about_card_id: null } }],
    target_card_ids: [], confidence: 0.9, needs_clarification: false, clarification: null, resolves: null, rationale: "A rule statement.",
  };
  return { content: [{ type: "text", text: JSON.stringify(body), citations: null }], stop_reason: "end_turn", model: CLAUDE_MODEL, stop_details: null };
}

describe("GET /api/health and /api/config", () => {
  it("health answers { app: \"exmap\" }; config names the key's variable, the model, and never the credential; EXMAP_CLASSIFIER=rules.v1 wins over a key; last_error is set by a fallback and cleared by a clean claude classification", async () => {
    const { app } = await makeApp();
    const health = await call(app, "GET", "/api/health");
    expect(health.statusCode).toBe(200);
    expect(json(health)).toMatchObject({ app: "exmap", ok: true });
    expect(health.headers["cache-control"]).toBe("no-store");

    // a key in the environment selects claude; the body names the variable, never its value
    const keyed = await envApp({ ANTHROPIC_API_KEY: "x" }, fakeModel([addRuleReply()]));
    const cfgRes = await call(keyed, "GET", "/api/config");
    expect(cfgRes.statusCode).toBe(200);
    const cfg = json<ConfigResponse>(cfgRes);
    expect(cfg.app).toBe("exmap");
    expect(cfg.loopback).toBe(true);
    expect(cfg.classifier.provider).toBe("claude");
    expect(cfg.classifier.reason).toBe("ANTHROPIC_API_KEY is set");
    expect(cfg.classifier.model).toBe(CLAUDE_MODEL);
    expect(cfg.classifier.credentials).toBe("api_key");
    expect(cfg.classifier.last_error).toBeNull();
    expect(cfgRes.body).not.toContain('"x"');
    expect(cfgRes.body).not.toMatch(/:\s*"x"/);

    // EXMAP_CLASSIFIER=rules.v1 with a key → rules.v1
    const forced = await envApp({ ANTHROPIC_API_KEY: "x", EXMAP_CLASSIFIER: "rules.v1" });
    const forcedCfg = json<ConfigResponse>(await call(forced, "GET", "/api/config"));
    expect(forcedCfg.classifier.provider).toBe("rules.v1");
    expect(forcedCfg.classifier.reason).toBe("EXMAP_CLASSIFIER=rules.v1");
    expect(forcedCfg.classifier.model).toBeNull();

    // last_error: a connection failure falls back (onError → last_error); a clean claude classification clears it
    const model = fakeModel([new APIConnectionError({ message: "connect ECONNREFUSED" }), addRuleReply()]);
    const claudeApp = await envApp({ ANTHROPIC_API_KEY: "x" }, model);
    const s = await createSession(claudeApp, { story: "A patient can cancel an appointment online." });
    const first = await postUtterance(claudeApp, s.id, uttId(), "Patients must confirm a cancellation by email.");
    expect(first.statusCode).toBe(201);
    const fallback = json<{ classification: { classifier: { provider: string; fallback_from: string | null; error: string | null } } }>(first).classification;
    expect(fallback.classifier).toMatchObject({ provider: "rules.v1", fallback_from: "claude", error: "connection" });
    const afterFallback = json<ConfigResponse>(await call(claudeApp, "GET", "/api/config"));
    expect(afterFallback.classifier.last_error).toMatchObject({ code: "connection", message: "connect ECONNREFUSED" });
    expect(typeof afterFallback.classifier.last_error?.at).toBe("string");
    const second = await postUtterance(claudeApp, s.id, uttId(), "Patients must also confirm a cancellation by text message.");
    expect(json<{ classification: { classifier: { provider: string; fallback_from: string | null } } }>(second).classification.classifier).toMatchObject({ provider: "claude", fallback_from: null });
    const cleared = json<ConfigResponse>(await call(claudeApp, "GET", "/api/config"));
    expect(cleared.classifier.last_error).toBeNull();
    expect(model.count).toBe(2);
  });

  it("no key and no EXMAP_CLASSIFIER → rules.v1 with the offline reason", async () => {
    const { app } = await makeApp({ env: {} });
    const cfg = json<ConfigResponse>(await call(app, "GET", "/api/config"));
    expect(cfg.classifier).toMatchObject({ provider: "rules.v1", reason: "no model configured; using the offline rules classifier", model: null, credentials: "none", last_error: null });
    expect(cfg.port).toBe(4317);
  });
});
