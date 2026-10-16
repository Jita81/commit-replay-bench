// exmap/tests/unit/classifier/claude-provider.test.ts — TEST-PLAN §2 claude provider rows 1–27 (design §6.4–6.5), with a
// fake ModelClient that records params and never touches the network.
import { APIConnectionError, APIConnectionTimeoutError, APIUserAbortError, AuthenticationError, RateLimitError } from "@anthropic-ai/sdk";
import type { MessageCreateParamsNonStreaming } from "@anthropic-ai/sdk/resources/messages";
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { createClaudeClassifier } from "../../../src/classifier/claude/claude-provider.js";
import type { CreateResult, ModelClient } from "../../../src/classifier/claude/client.js";
import { FROZEN_SYSTEM } from "../../../src/classifier/claude/system-prompt.js";
import { renderUserMessage } from "../../../src/classifier/claude/user-message.js";
import { CLAUDE_MODEL, CLAUDE_TIMEOUT_MS, SYSTEM_PROMPT_VERSION } from "../../../src/classifier/constants.js";
import { ClassifierError, createClassifier, selectProvider } from "../../../src/classifier/index.js";
import { createRulesClassifier } from "../../../src/classifier/rules-v1.js";
import { ProposalSchema, assertProposalInvariants } from "../../../src/classifier/schema.js";
import type { Classifier, ClassifierInput, ClassifierProposal } from "../../../src/core/types.js";
import { card, input, label, pending, ref, story, utt } from "./helpers.js";

/** The SHA-256 of FROZEN_SYSTEM, computed once at implementation and pinned here (design §6.4). */
const FROZEN_SYSTEM_SHA256 = "be2ecbc5f192cd57604441f89971cce95aae00d520b2065b7eacaac2d656a626";

const E1 = card("card_e1", "example", "If a GP appointment is at 10am and the patient cancels at 9am, it is refused.", { seq: 3, last_utterance_id: "utt_3", last_speaker: "Sam", proposal_id: "prop_b" });
const E2 = card("card_e2", "example", "For a nurse appointment at 10am, cancelling at 8am is allowed.", { seq: 4, last_utterance_id: "utt_4", last_speaker: "Priya", proposal_id: "prop_c" });
const E3 = card("card_e3", "example", "A receptionist cancels on the patient's behalf at 9am.", { seq: 5, last_utterance_id: "utt_5", last_speaker: "Sam", proposal_id: "prop_d" });
const R1 = card("card_r1", "rule", "A patient should be able to cancel online, but not within two hours of their appointment.", { seq: 2, last_utterance_id: "utt_2", last_speaker: "Priya", proposal_id: "prop_a" });

type Call = { params: MessageCreateParamsNonStreaming; options: { timeout?: number; maxRetries?: number; signal?: AbortSignal } | undefined };

function fakeCreate(script: Array<CreateResult | Error | (() => CreateResult)>): { client: ModelClient; calls: Call[] } {
  const calls: Call[] = [];
  let i = 0;
  const client: ModelClient = {
    messages: {
      async create(params, options) {
        calls.push({ params, options });
        const step = script[Math.min(i, script.length - 1)];
        i++;
        if (step instanceof Error) throw step;
        if (typeof step === "function") return step();
        if (!step) throw new Error("no script");
        return step;
      },
    },
  };
  return { client, calls };
}

function reply(json: unknown, over: Partial<CreateResult> = {}): CreateResult {
  return { content: [{ type: "text", text: typeof json === "string" ? json : JSON.stringify(json), citations: null }], stop_reason: "end_turn", model: "claude-opus-5-5", stop_details: null, ...over };
}

function addRule(text = "Patients must confirm by email."): Record<string, unknown> {
  return { intent: "add", operations: [{ kind: "card.create", card: { kind: "rule", text, rule_id: null, about_card_id: null } }], target_card_ids: [], confidence: 0.9, needs_clarification: false, clarification: null, resolves: null, rationale: "A rule statement." };
}

function removeOp(card_id: string): Record<string, unknown> {
  return { intent: "remove", operations: [{ kind: "card.remove", card_id, reason: "" }], target_card_ids: [card_id], confidence: 0.9, needs_clarification: false, clarification: null, resolves: null, rationale: "They said delete." };
}

function make(script: Parameters<typeof fakeCreate>[0], onError?: (e: { code: string; message: string }) => void, rules: Classifier = createRulesClassifier()): { classifier: Classifier; calls: Call[] } {
  const { client, calls } = fakeCreate(script);
  const classifier = createClaudeClassifier({ client, rules, ...(onError ? { onError } : {}) });
  return { classifier, calls };
}

const baseInput = (text = "Patients must confirm by email.", over: Partial<ClassifierInput> = {}): ClassifierInput => input({ utterance: utt("utt_9", text), cards: [story(), R1, E1], ...over });

function authError(): AuthenticationError {
  return new AuthenticationError(401, { type: "error", error: { type: "authentication_error", message: "invalid x-api-key" } }, "invalid x-api-key", new Headers());
}

describe("claude provider", () => {
  it("1. a valid reply is stamped claude and the request has the designed shape", async () => {
    const { classifier, calls } = make([reply(addRule())]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier).toEqual({ provider: "claude", model: "claude-opus-5-5", prompt_version: SYSTEM_PROMPT_VERSION, fallback_from: null, error: null });
    expect(p.intent).toBe("add");
    expect(p.confidence).toBe(0.9);
    const call = calls[0]!;
    const params = call.params as MessageCreateParamsNonStreaming & { output_config: { format: { type: string }; effort: string }; thinking?: unknown; tool_choice?: unknown; temperature?: unknown };
    expect(params.model).toBe(CLAUDE_MODEL);
    expect(params.max_tokens).toBe(4096);
    const system = params.system as Array<{ type: string; text: string; cache_control?: { type: string } }>;
    expect(system[0]?.cache_control?.type).toBe("ephemeral");
    expect(system[0]?.text).toBe(FROZEN_SYSTEM);
    expect(params.output_config.effort).toBe("medium");
    expect(params.output_config.format.type).toBe("json_schema");
    expect(params.messages).toHaveLength(1);
    expect(params.messages[0]?.role).toBe("user");
    expect(call.options?.timeout).toBe(CLAUDE_TIMEOUT_MS);
    expect(call.options?.timeout).toBe(20000);
    expect(call.options?.maxRetries).toBe(1);
    expect("thinking" in params).toBe(false);
    expect("tool_choice" in params).toBe(false);
    expect("temperature" in params).toBe(false);
  });

  it("2a. a refusal falls back to rules.v1 with its category and reports the error once", async () => {
    const errors: Array<{ code: string }> = [];
    const { classifier } = make([{ content: [], stop_reason: "refusal", model: "claude-opus-5-5", stop_details: { type: "refusal", category: "general_harms" } }], (e) => errors.push(e));
    const p = await classifier.classify(baseInput());
    expect(p.classifier).toEqual({ provider: "rules.v1", model: null, prompt_version: null, fallback_from: "claude", error: "refusal:general_harms" });
    expect(p.rationale.endsWith(" (rules.v1 fallback: claude refusal:general_harms)")).toBe(true);
    expect(p.intent).toBe("add");
    expect(errors).toEqual([{ code: "refusal:general_harms", message: "" }]);
  });

  it("2b. a refusal with partial text is a refusal, not a parse failure", async () => {
    const { classifier } = make([reply("I can't", { stop_reason: "refusal", stop_details: { type: "refusal", category: null } })]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("refusal:unknown");
  });

  it("3. a reply that is not JSON falls back with code parse", async () => {
    const { classifier } = make([reply("not json")]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier).toMatchObject({ provider: "rules.v1", fallback_from: "claude", error: "parse" });
  });

  it("4. an AuthenticationError falls back with code auth", async () => {
    const errors: Array<{ code: string }> = [];
    const { classifier } = make([authError()], (e) => errors.push(e));
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("auth");
    expect(errors.map((e) => e.code)).toEqual(["auth"]);
  });

  it("5. onError fires once per distinct failure run, again after a success", async () => {
    const errors: string[] = [];
    const rl = new RateLimitError(429, { type: "error", error: { type: "rate_limit_error", message: "slow down" } }, "slow down", new Headers());
    const { classifier } = make([rl, rl, reply(addRule()), rl], (e) => errors.push(e.code));
    for (let i = 0; i < 4; i++) await classifier.classify(baseInput());
    expect(errors).toEqual(["rate_limit", "rate_limit"]);
  });

  it("6. a connection timeout is coded timeout, not connection", async () => {
    const { classifier } = make([new APIConnectionTimeoutError({ message: "Request timed out." })]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("timeout");
  });

  it("7. a connection error is coded connection", async () => {
    const { classifier } = make([new APIConnectionError({ message: "Connection error." })]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("connection");
  });

  it("8. a max_tokens truncation is coded stop:max_tokens, not parse", async () => {
    const { classifier } = make([reply('{"intent":"add","operations":[{"kind":"card.cre', { stop_reason: "max_tokens" })]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("stop:max_tokens");
  });

  it("9. an unknown target id becomes a choose_target over the examples, most recent first", async () => {
    const { classifier } = make([reply(removeOp("card_9999"))]);
    const p = await classifier.classify(baseInput("Delete that example.", { cards: [story(), E1, E2, E3] }));
    expect(p.classifier.provider).toBe("claude");
    expect(p.classifier.error).toBeNull();
    expect(p.intent).toBe("remove");
    expect(p.clarification?.kind).toBe("choose_target");
    expect(p.clarification?.candidates.map((c) => c.card_id)).toEqual(["card_e3", "card_e2", "card_e1"]);
    expect(p.clarification?.pending_operations).toEqual([{ kind: "card.remove", card_id: "$choice", reason: "" }]);
    expect(p.clarification?.question.startsWith("I could not match that to a card. Which did you mean: (1) ")).toBe(true);
  });

  it("10. an unknown target id with one example is a confirm_intent bound to it", async () => {
    const { classifier } = make([reply(removeOp("card_9999"))]);
    const p = await classifier.classify(baseInput("Delete that example.", { cards: [story(), E1] }));
    expect(p.clarification?.kind).toBe("confirm_intent");
    expect(p.clarification?.pending_operations).toEqual([{ kind: "card.remove", card_id: "card_e1", reason: "" }]);
  });

  it("11. an unknown target id with no card is none / heard remove, still provider claude", async () => {
    const { classifier } = make([reply(removeOp("card_9999"))]);
    const p = await classifier.classify(baseInput("Delete that example.", { cards: [story()] }));
    expect(p.intent).toBe("none");
    expect(p.heard_intent).toBe("remove");
    expect(p.classifier.provider).toBe("claude");
  });

  it("12. an intent / operation mismatch is a provider failure", async () => {
    const { classifier } = make([reply({ ...addRule(), intent: "remove" })]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("invalid:intent_op_mismatch");
  });

  it("13. an actionable intent with no operations is a provider failure", async () => {
    const { classifier } = make([reply({ ...addRule(), intent: "amend", operations: [] })]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("invalid:intent_op_mismatch");
  });

  it("14. a low confidence becomes a confirm_intent question", async () => {
    const op = { kind: "card.update", card_id: "card_r1", patch: { text: null, text_append: "Make it 24 hours.", answer: null, rule_id: null, about_card_id: null }, amendment: null };
    const { classifier } = make([reply({ intent: "amend", operations: [op], target_card_ids: ["card_r1"], confidence: 0.2, needs_clarification: false, clarification: null, resolves: null, rationale: "Loose words." })]);
    const p = await classifier.classify(baseInput("Make it 24 hours."));
    expect(p.clarification?.kind).toBe("confirm_intent");
    expect(p.clarification?.question.startsWith("Did you mean to")).toBe(true);
    expect(p.clarification?.pending_operations).toEqual([op]);
    expect(p.operations).toEqual([]);
  });

  it("15. a confidence above 1 is clamped", async () => {
    const { classifier } = make([reply({ ...addRule(), confidence: 1.7 })]);
    const p = await classifier.classify(baseInput());
    expect(p.confidence).toBe(1);
  });

  it("16. a resolves naming the wrong proposal is dropped and the answer re-asked", async () => {
    const pc = pending({ proposal_id: "prop_05", intent: "remove", kind: "choose_target", candidates: [E2, E1].map((c) => ({ card_id: c.id, label: label(c) })), pending_operations: [{ kind: "card.remove", card_id: "$choice", reason: "" }], asked_by_utterance_id: "utt_05" });
    const { classifier } = make([reply({ ...removeOp("card_e1"), resolves: { proposal_id: "prop_wrong", chosen_card_ids: ["card_e1"], dismissed: false } })]);
    const p = await classifier.classify(baseInput("The GP one.", { cards: [story(), E1, E2], pending_clarification: pc }));
    expect(p.resolves).toBeNull();
    expect(p.intent).toBe("none");
    expect(p.heard_intent).toBe("remove");
    expect(p.rationale).toBe("Please say which one: first or second, or name it.");
  });

  it("17. target_card_ids are recomputed from the operations", async () => {
    const c7 = card("card_0007", "example", "An example seven.", { seq: 7, proposal_id: "prop_7" });
    const { classifier } = make([reply({ ...removeOp("card_0007"), target_card_ids: [] })]);
    const p = await classifier.classify(baseInput("Delete that.", { cards: [story(), c7] }));
    expect(p.target_card_ids).toEqual(["card_0007"]);
  });

  it("18. an unknown rule_id link is dropped and the rationale says so", async () => {
    const { classifier } = make([reply({ intent: "add", operations: [{ kind: "card.create", card: { kind: "example", text: "A GP cancels at 9am.", rule_id: "card_404", about_card_id: null } }], target_card_ids: [], confidence: 0.9, needs_clarification: false, clarification: null, resolves: null, rationale: "An example." })]);
    const p = await classifier.classify(baseInput("A GP cancels at 9am."));
    expect(p.operations).toEqual([{ kind: "card.create", card: { kind: "example", text: "A GP cancels at 9am.", rule_id: null, about_card_id: null } }]);
    expect(p.rationale).toContain("(link dropped: unknown card)");
  });

  it("19. a reject naming an unknown proposal becomes a confirm_intent on the last rejectable", async () => {
    const lr = ref("prop_b", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e1"], utterance_id: "utt_3" });
    const { classifier } = make([reply({ intent: "reject", operations: [{ kind: "interpretation.reject", proposal_id: "prop_nope" }], target_card_ids: [], confidence: 0.9, needs_clarification: false, clarification: null, resolves: null, rationale: "They said no." })]);
    const p = await classifier.classify(baseInput("No, that's not what I said.", { last_rejectable: lr }));
    expect(p.clarification?.kind).toBe("confirm_intent");
    expect(p.clarification?.question).toBe("Did you mean to reject the last interpretation?");
    expect(p.clarification?.pending_operations).toEqual([{ kind: "interpretation.reject", proposal_id: "prop_b" }]);
    expect(p.operations).toEqual([]);
  });

  it("20. renderUserMessage has the sections in order, every id, and no timestamp or session id", () => {
    const pc = pending({ proposal_id: "prop_05", intent: "remove", kind: "choose_target", question: "Which example do you mean: (1) nurse, or (2) GP?", candidates: [E2, E1].map((c) => ({ card_id: c.id, label: label(c) })), pending_operations: [{ kind: "card.remove", card_id: "$choice", reason: "It's not what I meant." }], asked_by_utterance_id: "utt_05" });
    const inp = input({
      utterance: utt("utt_06", "The GP one.", { speaker: "Priya", lane: "remote" }),
      recent: [utt("utt_01", "Right, let's start with how cancellation works today.", { speaker: "Sam", lane: "me" }), utt("utt_02", "What counts as an appointment?", { speaker: "Sam", lane: "manual" }), utt("utt_03", "A patient should be able to cancel.", { speaker: null, lane: "remote" })],
      cards: [story(), R1, E1, E2],
      last_proposal: ref("prop_05", { intent: "remove", op: "card.remove", kind: "example", card_ids: [], utterance_id: "utt_05" }),
      last_rejectable: ref("prop_c", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e2"], utterance_id: "utt_04" }),
      pending_clarification: pc,
    });
    const text = renderUserMessage(inp);
    const order = ["## CARD INDEX", "## LAST PROPOSAL", "## LAST REJECTABLE", "## PENDING CLARIFICATION", "## RECENT UTTERANCES (oldest first)", "## NEW UTTERANCE"];
    const positions = order.map((h) => text.indexOf(h));
    expect(positions.every((p) => p >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
    for (const id of ["card_story", "card_r1", "card_e1", "card_e2", "prop_05", "prop_c", "utt_01", "utt_02", "utt_03", "utt_06"]) expect(text).toContain(id);
    expect(text).toContain("candidates: 1. card_e2 — ");
    expect(text).toContain(" | 2. card_e1 — ");
    expect(text).toContain("[utt_02] (typed): What counts as an appointment?");
    expect(text).toContain("[utt_03] (remote): A patient should be able to cancel.");
    expect(text).toContain("[utt_06] Priya (remote): The GP one.");
    expect(text.trimEnd().endsWith("[utt_06] Priya (remote): The GP one.")).toBe(true);
    expect(/20\d\d-\d\d-\d\dT/.test(text)).toBe(false);
    expect(/session/i.test(text)).toBe(false);
  });

  it("21. FROZEN_SYSTEM is pinned by SHA-256 and names every intent and operation kind", () => {
    const sha = createHash("sha256").update(FROZEN_SYSTEM, "utf8").digest("hex");
    expect(sha).toBe(FROZEN_SYSTEM_SHA256);
    expect(/20\d\d-\d\d/.test(FROZEN_SYSTEM)).toBe(false);
    for (const intent of ["add", "amend", "remove", "replace", "clarify", "reject", "confirm", "undo", "none"]) expect(FROZEN_SYSTEM).toMatch(new RegExp(`\\b${intent}\\b`));
    for (const op of ["card.create", "card.update", "card.remove", "card.replace", "definition.refine", "interpretation.reject", "confirm", "undo"]) expect(FROZEN_SYSTEM).toContain(op);
    expect(FROZEN_SYSTEM).toContain("confirm {card_ids: []}");
  });

  it("22. selectProvider reads EXMAP_CLASSIFIER and the credential variables", () => {
    expect(selectProvider({})).toBe("rules.v1");
    expect(selectProvider({ ANTHROPIC_API_KEY: "x" })).toBe("claude");
    expect(selectProvider({ ANTHROPIC_AUTH_TOKEN: "x" })).toBe("claude");
    expect(selectProvider({ EXMAP_CLASSIFIER: "rules.v1", ANTHROPIC_API_KEY: "x" })).toBe("rules.v1");
    expect(selectProvider({ EXMAP_CLASSIFIER: "rules" })).toBe("rules.v1");
    expect(selectProvider({ EXMAP_CLASSIFIER: "claude" })).toBe("claude");
    expect(() => selectProvider({ EXMAP_CLASSIFIER: "gpt" })).toThrow(ClassifierError);
    try {
      selectProvider({ EXMAP_CLASSIFIER: "gpt" });
    } catch (e) {
      expect((e as ClassifierError).code).toBe("E_CLASSIFIER_UNKNOWN_PROVIDER");
    }
    expect(createClassifier({ env: {} }).provider).toBe("rules.v1");
    const { client } = fakeCreate([reply(addRule())]);
    expect(createClassifier({ env: { EXMAP_CLASSIFIER: "claude" }, client }).provider).toBe("claude");
  });

  it("23. an aborted call is coded aborted and never reported", async () => {
    const errors: string[] = [];
    const ac = new AbortController();
    const { classifier } = make([new APIUserAbortError()], (e) => errors.push(e.code));
    ac.abort();
    const p = await classifier.classify(baseInput(), { signal: ac.signal });
    expect(p.classifier.error).toBe("aborted");
    expect(errors).toEqual([]);
  });

  it("24. a plain credential error from the SDK is coded auth", async () => {
    const errors: string[] = [];
    const { classifier } = make([new Error("Could not resolve authentication method. Expected either apiKey or authToken to be set.")], (e) => errors.push(e.code));
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("auth");
    expect(errors).toEqual(["auth"]);
  });

  it("25. an off-enum intent fails zod client-side and is coded parse", async () => {
    const { classifier } = make([reply({ ...addRule(), intent: "modify" })]);
    const p = await classifier.classify(baseInput());
    expect(p.classifier.error).toBe("parse");
  });

  it("26. a 200-char rules.v1 rationale is shortened to fit the fallback note", async () => {
    const long = "x".repeat(200);
    const rules: Classifier = { provider: "rules.v1", classify: async (inp) => ({ ...(await createRulesClassifier().classify(inp)), rationale: long }) };
    const { classifier } = make([reply("not json")], undefined, rules);
    const inp = baseInput();
    const p = await classifier.classify(inp);
    expect(p.rationale.length).toBeLessThanOrEqual(200);
    expect(p.rationale.endsWith(" (rules.v1 fallback: claude parse)")).toBe(true);
    expect(() => assertProposalInvariants(p, inp)).not.toThrow();
    expect(() => ProposalSchema.parse(p)).not.toThrow();
  });

  it("27. an empty confirm is kept only as a review of a removal / undo / rejection", async () => {
    const confirmEmpty = { intent: "confirm", operations: [{ kind: "confirm", card_ids: [] }], target_card_ids: [], confidence: 0.8, needs_clarification: false, clarification: null, resolves: null, rationale: "They said yes." };
    const a = make([reply(confirmEmpty)]);
    const pa = await a.classifier.classify(baseInput("Yes.", { last_proposal: ref("prop_14", { intent: "remove", op: "card.remove", kind: "example", card_ids: ["card_gone"], utterance_id: "utt_8" }) }));
    expect(pa.intent).toBe("confirm");
    expect(pa.operations).toEqual([{ kind: "confirm", card_ids: [] }]);
    const b = make([reply(confirmEmpty)]);
    const pb = await b.classifier.classify(baseInput("Yes.", { last_proposal: ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_8" }) }));
    expect(pb.intent).toBe("none");
    expect(pb.heard_intent).toBe("confirm");
    const proposals: ClassifierProposal[] = [pa, pb];
    for (const p of proposals) expect(() => ProposalSchema.parse(p)).not.toThrow();
  });
});

describe("claude: reject of the last rejectable when the last interpretation is a different, confirmed one (review finding)", () => {
  const lp = ref("prop_c", { intent: "add", op: "card.create", kind: "example", card_ids: ["card_e2"], utterance_id: "utt_4", status: "confirmed", rejectable: false });
  const lr = ref("prop_a", { intent: "add", op: "card.create", kind: "rule", card_ids: ["card_r1"], utterance_id: "utt_2" });

  it("becomes a confirm_intent naming the older interpretation instead of rejecting it", async () => {
    const { classifier } = make([reply({ intent: "reject", operations: [{ kind: "interpretation.reject", proposal_id: "prop_a" }], target_card_ids: [], confidence: 0.95, needs_clarification: false, clarification: null, resolves: null, rationale: "They said no." })]);
    const p = await classifier.classify(input({ utterance: utt("utt_5", "No, that's not what I said.", { speaker: "Priya" }), cards: [story(), R1, { ...E2, status: "confirmed" }], last_proposal: lp, last_rejectable: lr }));
    expect(p.operations).toEqual([]);
    expect(p.clarification?.kind).toBe("confirm_intent");
    expect(p.clarification?.question).toContain("The last interpretation has been confirmed");
    expect(p.clarification?.pending_operations).toEqual([{ kind: "interpretation.reject", proposal_id: "prop_a" }]);
    expect(ProposalSchema.safeParse(p).success).toBe(true);
  });

  it("a leading reject of that older interpretation on another intent is dropped", async () => {
    const { classifier } = make([reply({ intent: "remove", operations: [{ kind: "interpretation.reject", proposal_id: "prop_a" }, { kind: "card.remove", card_id: "card_e2", reason: "" }], target_card_ids: ["card_e2"], confidence: 0.9, needs_clarification: false, clarification: null, resolves: null, rationale: "No, remove it." })]);
    const p = await classifier.classify(input({ utterance: utt("utt_5", "No, delete the nurse example.", { speaker: "Priya" }), cards: [story(), R1, { ...E2, status: "confirmed" }], last_proposal: lp, last_rejectable: lr }));
    expect(p.operations).toEqual([{ kind: "card.remove", card_id: "card_e2", reason: "" }]);
  });
});
