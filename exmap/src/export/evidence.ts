// exmap/src/export/evidence.ts — evidence.json (design §12.5): the sign-off (active when verified; otherwise the last one
// with its status, never an invalidated one shown as current), the chain head, the DoD report at export time and the
// verified revision's canonical state, whose sha256(canonicalJson(.)) is requirement_revision.hash.
import { canonicalState } from "../core/index.js";
import type { Evidence } from "../core/types.js";
import { liveCards } from "./backlog-item.js";
import type { ExportContext } from "./index.js";
import { DRAFT_WATERMARK } from "./text.js";

export function evidence(ctx: ExportContext): Evidence {
  const s = ctx.signoff;
  return {
    schema: "exmap.evidence.v1",
    exported_at: ctx.now,
    draft: ctx.draft,
    verified: ctx.verified,
    session: { id: ctx.session.id, title: ctx.session.title, created_at: ctx.session.created_at },
    requirement_revision: { seq: ctx.revision.seq, hash: ctx.revision.hash },
    chain_head: { seq: ctx.head.seq, hash: ctx.head.hash, event_id: ctx.head.event_id },
    signoff: s === null
      ? null
      : {
          id: s.id,
          reviewer: { name: s.reviewer.name },
          confirmation_text: s.confirmation_text,
          revision: { seq: s.revision.seq, hash: s.revision.hash },
          evidence: { head_seq: s.evidence.head_seq, head_hash: s.evidence.head_hash },
          checks: s.checks,
          status: s.status,
          at: s.at,
          event_id: s.event_id,
          invalidated: s.invalidated,
        },
    dod: ctx.dod,
    canonical_state: canonicalState(liveCards(ctx)),
    export_options: ctx.options.seq === 0 ? null : ctx.options,
    export_options_history: ctx.optionsHistory,
    watermark: ctx.draft ? DRAFT_WATERMARK : null,
  };
}
