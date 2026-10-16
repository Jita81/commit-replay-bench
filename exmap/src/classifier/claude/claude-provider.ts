// exmap/src/classifier/claude/claude-provider.ts — createClaudeClassifier({ client, rules, onError }) (design §6.4–6.5).
// Builds the exact request of §6.4 (the frozen system block with cache_control ephemeral, the rendered user message,
// output_config format + effort, a 20 s timeout and one retry) and turns every provider failure — a typed SDK error, a
// refusal, a max_tokens truncation, a reply that does not parse, a malformed proposal — into a rules.v1 proposal whose
// provenance names the fallback and its code. Provider failures are never thrown.
import { APIConnectionError, APIConnectionTimeoutError, APIError, APIUserAbortError, AuthenticationError, RateLimitError } from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import type { Classifier, ClassifierInput, ClassifierProposal } from "../../core/types.js";
import { CLAUDE_EFFORT, CLAUDE_MAX_TOKENS, CLAUDE_MODEL, CLAUDE_TIMEOUT_MS, RATIONALE_MAX } from "../constants.js";
import type { ClassifierErrorEvent } from "../index.js";
import { ClassifierInputSchema, ModelProposalSchema, assertProposalInvariants, type ModelProposal } from "../schema.js";
import { ClassifierError } from "../types.js";
import { createAnthropicClient, type CreateResult, type ModelClient } from "./client.js";
import { FROZEN_SYSTEM } from "./system-prompt.js";
import { renderUserMessage } from "./user-message.js";
import { validateModelProposal } from "./validate.js";

export interface ClaudeClassifierOptions {
  client?: ModelClient;
  rules: Classifier;
  onError?: (e: ClassifierErrorEvent) => void;
}

/** One object: .schema goes to the API, .parse() runs on the reply (JSON + zod). */
export const FORMAT = zodOutputFormat(ModelProposalSchema);

function errorCode(e: unknown, signal: AbortSignal | undefined): string {
  if (e instanceof APIUserAbortError || signal?.aborted) return "aborted";
  if (e instanceof AuthenticationError) return "auth";
  if (e instanceof RateLimitError) return "rate_limit";
  if (e instanceof APIConnectionTimeoutError) return "timeout";
  if (e instanceof APIConnectionError) return "connection";
  if (e instanceof APIError) return `api:${e.status ?? "?"}:${e.type ?? "unknown"}`;
  const message = e instanceof Error ? e.message : String(e);
  if (/authentication method|credential|api key/i.test(message)) return "auth";
  return "transport";
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function createClaudeClassifier(opts: ClaudeClassifierOptions): Classifier {
  let client: ModelClient | null = opts.client ?? null;
  let errorKey: string | null = null;

  async function fallback(code: string, message: string, input: ClassifierInput): Promise<ClassifierProposal> {
    const base = await opts.rules.classify(input);
    const note = ` (rules.v1 fallback: claude ${code})`;
    const keep = Math.max(1, RATIONALE_MAX - note.length);
    const head = base.rationale.length > keep ? base.rationale.slice(0, keep).trimEnd() : base.rationale;
    const p: ClassifierProposal = {
      ...base,
      classifier: { provider: "rules.v1", model: null, prompt_version: null, fallback_from: "claude", error: code },
      rationale: `${head}${note}`,
    };
    assertProposalInvariants(p, input);
    if (code !== "aborted" && code !== errorKey) {
      errorKey = code;
      opts.onError?.({ code, message });
    }
    return p;
  }

  return {
    provider: "claude",
    async classify(input, o) {
      const parsed = ClassifierInputSchema.safeParse(input);
      if (!parsed.success) {
        throw new ClassifierError("E_CLASSIFIER_INPUT_INVALID", parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
      }
      const signal = o?.signal;
      let res: CreateResult;
      try {
        if (!client) client = createAnthropicClient();
        res = await client.messages.create(
          {
            model: CLAUDE_MODEL,
            max_tokens: CLAUDE_MAX_TOKENS,
            system: [{ type: "text", text: FROZEN_SYSTEM, cache_control: { type: "ephemeral" } }],
            messages: [{ role: "user", content: renderUserMessage(input) }],
            output_config: { format: FORMAT, effort: CLAUDE_EFFORT },
          },
          { timeout: CLAUDE_TIMEOUT_MS, maxRetries: 1, ...(signal ? { signal } : {}) },
        );
      } catch (e) {
        return fallback(errorCode(e, signal), messageOf(e), input);
      }
      if (res.stop_reason === "refusal") return fallback(`refusal:${res.stop_details?.category ?? "unknown"}`, res.stop_details?.explanation ?? "", input);
      if (res.stop_reason === "max_tokens") return fallback("stop:max_tokens", "", input);
      const text = res.content.find((b) => b.type === "text")?.text;
      if (text === undefined) return fallback("parse", "no text block in the reply", input);
      let m: ModelProposal;
      try {
        m = FORMAT.parse(text);
      } catch (e) {
        return fallback("parse", messageOf(e), input);
      }
      const v = validateModelProposal(m, input, { model: res.model });
      if ("fallback" in v) return fallback(v.fallback, "", input);
      errorKey = null;
      return v.ok;
    },
  };
}
