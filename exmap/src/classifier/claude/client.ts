// exmap/src/classifier/claude/client.ts — the client seam (design §6.4). ModelClient is structural so tests inject a fake;
// the real Anthropic client satisfies it. createAnthropicClient() = new Anthropic(): credentials come from
// ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile, and ANTHROPIC_BASE_URL (the operator's endpoint)
// is read by the SDK, never interpreted here. Error classes are imported from the SDK by the provider so instanceof works
// for both the real client and a fake that throws them.
import Anthropic from "@anthropic-ai/sdk";
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
  return new Anthropic();
}
