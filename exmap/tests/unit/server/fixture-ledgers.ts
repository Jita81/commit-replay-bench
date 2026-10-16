// exmap/tests/unit/server/fixture-ledgers.ts — the prebuilt ledgers in tests/fixtures/sessions/ (valid, tampered,
// truncated), generated with the real core (apply() with a fixed clock and counter ids, so the bytes are reproducible).
// persistence.test.ts asserts the checked-in files equal this output. Regenerate after a deliberate core change with:
//   npx tsx tests/unit/server/fixture-ledgers.ts --write
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { apply, canonicalJson, initialState } from "../../../src/core/index.js";
import type { ApplyContext, Command, ExmapEvent, IdPrefix, MapState, Operation, Proposal, SessionMeta, Utterance } from "../../../src/core/types.js";
import { sha256 } from "../../../src/server/hash.js";

export const FIXTURE_DIR = fileURLToPath(new URL("../../fixtures/sessions/", import.meta.url));

export const FIXTURE_IDS = {
  valid: "ses_valid01_0000a1",
  tampered: "ses_tamper01_0000b2",
  truncated: "ses_trunc01_0000c3",
} as const;

const CREATED_AT = "2026-10-16T12:00:00.000Z";
const TITLE = { valid: "Online cancellation (valid ledger)", tampered: "Online cancellation (tampered ledger)", truncated: "Online cancellation (truncated ledger)" } as const;

function fixtureCtx(): ApplyContext {
  const counters = new Map<IdPrefix, number>();
  let t = Date.parse(CREATED_AT) + 1000;
  return {
    now: () => {
      const at = new Date(t).toISOString();
      t += 1000;
      return at;
    },
    nextId: (prefix) => {
      const n = (counters.get(prefix) ?? 0) + 1;
      counters.set(prefix, n);
      return `${prefix}_${n}`;
    },
    sha256, // node:crypto through the server's adapter (pinned to the §5 vectors)
  };
}

/** The events of the fixture conversation for one session id: a story, a rule, an example under it, a question, a confirmation. */
export function fixtureEvents(sessionId: string): ExmapEvent[] {
  const ctx = fixtureCtx();
  let state: MapState = initialState(sessionId);
  const events: ExmapEvent[] = [];
  const run = (c: Command): ExmapEvent[] => {
    const r = apply(state, c, ctx);
    if (!r.ok) throw new Error(`fixture: ${c.kind}: ${r.reason}: ${r.detail}`);
    state = r.state;
    events.push(...r.events);
    return r.events;
  };
  const human = (op: Operation, actor: string): Proposal => ({
    id: ctx.nextId("prop"), intent: INTENT[op.kind], operation: op, template: null, pending_operation: null, candidates: [], confidence: 1,
    needs_clarification: false, question: null, source_utterance_ids: [],
    classifier: { provider: "human", model: null, prompt_version: null, fallback_from: null, error: null, actor },
    resolves_clarification_id: null, rationale: `by ${actor}`,
  });
  let n = 0;
  const voice = (text: string, speaker: string, op: Operation): string => {
    n++;
    const u: Utterance = {
      id: `utt_${n.toString(16).padStart(12, "0")}`, text, lane: "remote", speaker, provider: "replay", model: null,
      t_start_ms: n * 4000, t_end_ms: n * 4000 + 2500, is_local: true, confidence: null,
    };
    run({ kind: "utterance.record", utterance: u });
    const pid = ctx.nextId("prop");
    const made = run({
      kind: "proposal.propose",
      proposals: [{
        id: pid, intent: INTENT[op.kind], operation: op, template: null, pending_operation: null, candidates: [], confidence: 0.8,
        needs_clarification: false, question: null, source_utterance_ids: [u.id],
        classifier: { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null, actor: null },
        resolves_clarification_id: null, rationale: "fixture interpretation",
      }],
    });
    run({
      kind: "classification.record", utterance_id: u.id, intent: INTENT[op.kind], heard_intent: null,
      classifier: { provider: "rules.v1", model: null, prompt_version: null, fallback_from: null, error: null, actor: null },
      confidence: 0.8, rationale: "fixture interpretation", proposal_ids: [pid], refused: [], error: null,
    });
    const created = made.find((e): e is Extract<ExmapEvent, { type: "proposal.made" }> => e.type === "proposal.made")?.effects.find((f) => f.before === null);
    return created?.card_id ?? "";
  };

  run({ kind: "proposal.propose", proposals: [human({ kind: "card.create", card: { kind: "story", text: "A patient can cancel an appointment online." } }, "Sam")] });
  const rule = voice("A patient should be able to cancel online, but not within two hours of their appointment.", "Priya",
    { kind: "card.create", card: { kind: "rule", text: "A patient cannot cancel online within two hours of the appointment." } });
  const example = voice("So a GP appointment at ten cancelled at nine is refused.", "Sam",
    { kind: "card.create", card: { kind: "example", text: "A GP appointment at 10am cancelled at 9am is refused.", rule_id: rule } });
  voice("What happens if the clinic cancels?", "Priya", { kind: "card.create", card: { kind: "question", text: "What happens if the clinic cancels?", about_card_id: rule } });
  run({ kind: "proposal.propose", proposals: [human({ kind: "confirm", card_ids: [rule, example], proposal_ids: [] }, "Sam")] });
  return events;
}

const INTENT: Record<Operation["kind"], Proposal["intent"]> = {
  "card.create": "add", "card.update": "amend", "card.remove": "remove", "card.replace": "replace", "definition.refine": "clarify",
  "interpretation.reject": "reject", confirm: "confirm", undo: "undo",
};

export interface FixtureFiles {
  meta: string;
  events: string;
}

function metaOf(id: string, title: string): string {
  const meta: SessionMeta = { schema: "exmap.session-meta.v1", id, title, created_at: CREATED_AT };
  return JSON.stringify(meta, null, 2) + "\n";
}

/** The three fixtures as file contents. tampered: one character of row 3's utterance text flipped; truncated: the last line cut mid-JSON. */
export function fixtureFiles(): Record<keyof typeof FIXTURE_IDS, FixtureFiles> {
  const lines = (id: string): string[] => fixtureEvents(id).map((e) => canonicalJson(e));
  const valid = lines(FIXTURE_IDS.valid);
  const tampered = lines(FIXTURE_IDS.tampered);
  if (!tampered[2]!.includes("cancel online")) throw new Error("fixture: row 3 is not the first utterance");
  tampered[2] = tampered[2]!.replace("cancel online", "cancel Online");
  const truncated = lines(FIXTURE_IDS.truncated);
  const last = truncated[truncated.length - 1]!;
  const cut = truncated.slice(0, -1).map((l) => l + "\n").join("") + last.slice(0, Math.floor(last.length / 2));
  return {
    valid: { meta: metaOf(FIXTURE_IDS.valid, TITLE.valid), events: valid.map((l) => l + "\n").join("") },
    tampered: { meta: metaOf(FIXTURE_IDS.tampered, TITLE.tampered), events: tampered.map((l) => l + "\n").join("") },
    truncated: { meta: metaOf(FIXTURE_IDS.truncated, TITLE.truncated), events: cut },
  };
}

export function writeFixtures(dir = FIXTURE_DIR): void {
  const files = fixtureFiles();
  for (const key of Object.keys(FIXTURE_IDS) as Array<keyof typeof FIXTURE_IDS>) {
    const d = join(dir, FIXTURE_IDS[key]);
    mkdirSync(d, { recursive: true });
    writeFileSync(join(d, "meta.json"), files[key].meta);
    writeFileSync(join(d, "events.jsonl"), files[key].events);
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1] && process.argv.includes("--write")) {
  writeFixtures();
  console.log(`wrote ${Object.values(FIXTURE_IDS).join(", ")} under ${FIXTURE_DIR}`);
}
