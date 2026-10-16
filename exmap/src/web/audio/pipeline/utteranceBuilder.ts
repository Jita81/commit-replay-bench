// exmap/src/web/audio/pipeline/utteranceBuilder.ts — a draft becomes core's Utterance (design §7.5). The wire shape IS
// core's type; segment duration is t_end_ms − t_start_ms, never a second field.
import { PostError } from "../errors.js";
import type { UtteranceDraft, UtteranceWire } from "../types.js";

export function mintUtteranceId(): string {
  return "utt_" + crypto.randomUUID();
}

export function buildUtterance(draft: UtteranceDraft, idFn: () => string = mintUtteranceId): UtteranceWire {
  const text = draft.text.trim();
  if (text.length === 0) throw new PostError("EMPTY_TEXT", "an utterance needs text");
  const tStart = Math.max(0, Math.round(draft.tStartMs));
  const tEnd = Math.max(tStart, Math.round(draft.tEndMs));
  let confidence: number | null = null;
  if (typeof draft.confidence === "number" && Number.isFinite(draft.confidence)) {
    confidence = Math.round(Math.min(1, Math.max(0, draft.confidence)) * 100) / 100;
  }
  return {
    id: idFn(),
    text,
    lane: draft.lane,
    speaker: draft.speaker === null ? null : draft.speaker.trim() || null,
    provider: draft.provider,
    model: draft.model,
    t_start_ms: tStart,
    t_end_ms: tEnd,
    is_local: draft.isLocal,
    confidence,
  };
}
