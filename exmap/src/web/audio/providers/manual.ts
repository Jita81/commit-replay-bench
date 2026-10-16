// exmap/src/web/audio/providers/manual.ts — typed or pasted text (design §7.4). Always available, always local.
import { ProviderError } from "../errors.js";
import type { CaptureLaneId, ProviderContext, Segment, TranscribeResult, TranscriptionProvider, WireLane } from "../types.js";

export class ManualProvider implements TranscriptionProvider {
  readonly id = "manual" as const;
  readonly label = "Typed";
  readonly isLocal = true;
  readonly lanes: CaptureLaneId[] = [];
  readonly mode = "push" as const;
  readonly model = null;
  #ctx: ProviderContext | null = null;

  async start(ctx: ProviderContext): Promise<void> {
    this.#ctx = ctx;
  }

  transcribe(_segment: Segment): Promise<TranscribeResult> {
    return Promise.reject(new ProviderError("NOT_SEGMENT_PROVIDER", "manual text is submitted, not transcribed"));
  }

  async stop(): Promise<void> {
    this.#ctx = null;
  }

  /**
   * `tStartMs` is the first keystroke into an empty box (null → now); `tEndMs` is the submit. An empty text is refused
   * (returns false) so the UI can keep the box.
   */
  submit(text: string, lane: WireLane, speaker: string | null, tStartMs: number | null = null): boolean {
    const ctx = this.#ctx;
    if (!ctx) throw new ProviderError("NOT_SEGMENT_PROVIDER", "manual provider not started");
    const trimmed = text.trim();
    if (trimmed.length === 0) return false;
    const now = ctx.clock.nowMs();
    const start = tStartMs === null ? now : Math.min(tStartMs, now);
    ctx.emit({
      text: trimmed,
      lane,
      speaker: speaker === null ? null : speaker.trim() || null,
      provider: "manual",
      model: null,
      isLocal: true,
      confidence: null,
      tStartMs: start,
      tEndMs: now,
    });
    return true;
  }
}
