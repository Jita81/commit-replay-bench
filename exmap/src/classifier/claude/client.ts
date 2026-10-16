// exmap/src/classifier/claude/client.ts — the client seam (design §6.4). ModelClient is structural so tests inject a fake;
// the real Anthropic client satisfies it. createAnthropicClient() is a step-zero stub (= new Anthropic()).
import type { Message, MessageCreateParamsNonStreaming } from "@anthropic-ai/sdk/resources/messages";

export interface CreateResult extends Pick<Message, "content" | "stop_reason" | "model"> {
  stop_details?: { type: "refusal"; category?: string | null; explanation?: string | null } | null;
  usage?: { cache_read_input_tokens?: number | null };
}

export interface ModelClient {
  messages: {
    create(
      params: MessageCreateParamsNonStreaming,
      options?: { timeout?: number; maxRetries?: number; signal?: AbortSignal },
    ): Promise<CreateResult>;
  };
}

/** new Anthropic(); credentials from ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile. */
export function createAnthropicClient(): ModelClient {
  throw new Error("not implemented: createAnthropicClient");
}
