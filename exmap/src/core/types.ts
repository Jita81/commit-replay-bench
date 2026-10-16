// exmap/src/core/types.ts

/* ───────────── 1. Scalars and ids ───────────── */
export type CardId = string;          // "card_…"  minted by apply()
export type ProposalId = string;      // "prop_…"  minted by the server when it turns a classifier/UI act into a proposal.propose
                                      //           command, or by apply() for an engine-built clarification resolver; apply() refuses duplicates
export type ClarificationId = string; // "clar_…"  minted by apply()
export type UtteranceId = string;     // "utt_…"   minted by the capturing client ("utt_" + crypto.randomUUID()); the server mints
                                      //           one ("utt_" + 12 hex) for an utterance it originates (a typed clarification answer)
export type EventId = string;         // "evt_…"   minted by apply()
export type SignoffId = string;       // "sig_…"   minted by apply()
export type IsoTimestamp = string;    // ctx.now(), e.g. "2026-10-16T12:00:00.000Z"
export type Sha256Hex = string;       // 64 lowercase hex chars
export type Sha256Fn = (utf8: string) => Sha256Hex;

/** Omit that distributes over a union. TS's built-in Omit on a union keeps only the common keys. */
export type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

export type CardKind = "story" | "rule" | "example" | "question";
export type CardStatus = "proposed" | "applied" | "confirmed" | "rejected" | "superseded";
export type Intent = "add" | "amend" | "remove" | "replace" | "clarify" | "reject" | "confirm" | "undo";
/** What the words carried when nothing could be proposed; set only on a classification whose intent is "none". */
export type HeardIntent = Intent | null;

/* ───────────── 2. Cards ───────────── */
export interface Definition { term: string; definition: string }   // terms trimmed, unique, sorted by term

export interface NeedsReview {                 // examples only
  reason: "rule_changed" | "rule_removed" | "rule_replaced";
  rule_id: CardId;                             // the rule as it is now (the replacement's id after a replace)
  event_id: EventId;                           // the event that set the flag
}
export interface Rejection {                   // non-null iff status === "rejected"
  kind: "removed" | "interpretation_rejected" | "undone";
  proposal_id: ProposalId;                     // the remove / reject / undo proposal
  event_id: EventId;
}
export interface ConfirmedBy {                 // copied from the confirm proposal's ClassifierStamp
  provider: ClassifierProvider;                // "human" = a click; "rules.v1" / "claude" = a voice "yes" interpreted by that classifier
  actor: string | null;                        // the person (click) or the speaker label (voice; never inferred)
  confidence: number;                          // 1 for a click; the classifier's figure for a voice confirm
}
export interface Confirmation {                // non-null iff status === "confirmed"
  proposal_id: ProposalId; event_id: EventId;  // the confirm act
  version: number;                             // the card version the person looked at (never rewritten)
  by: ConfirmedBy;
}
export interface Provenance {
  proposal_id: ProposalId; event_id: EventId;
  utterance_ids: UtteranceId[];                // copied from the proposal
  classifier: ClassifierProvider;
}
export interface AcceptedOutstanding { by: string; reason: string; event_id: EventId }

export interface CardCommon {
  id: CardId;
  text: string;                                // trimmed, CRLF→LF, non-empty
  definitions: Definition[];
  status: CardStatus;
  version: number;                             // 1 at creation; +1 on every content change (§5.2)
  history: CardVersion[];                      // earlier versions, oldest first; derived by reduce, never in events
  supersedes: CardId | null;
  superseded_by: CardId | null;
  rejection: Rejection | null;
  confirmation: Confirmation | null;
  created: Provenance;
  changed: Provenance;                         // who authored the current content (text / definitions / links / answer)
  restored_by: Provenance | null;              // the reject/undo that brought this content back; null unless the current
                                               // version is a restore; cleared by the next content change
}
export interface StoryCard    extends CardCommon { kind: "story" }
export interface RuleCard     extends CardCommon { kind: "rule" }
export interface ExampleCard  extends CardCommon { kind: "example";  rule_id: CardId | null; needs_review: NeedsReview | null }
export interface QuestionCard extends CardCommon { kind: "question"; about_card_id: CardId | null;
                                                   answer: string | null;                      // content: the recorded answer
                                                   accepted_outstanding: AcceptedOutstanding | null } // review decision
export type Card = StoryCard | RuleCard | ExampleCard | QuestionCard;

/** A card as carried in an event effect or a revision snapshot: everything except `history`. */
export type CardRecord = DistributiveOmit<Card, "history">;
export interface CardVersion { version: number; record: CardRecord; replaced_by_event_id: EventId }

/* ───────────── 3. Utterance ───────────── */
export type Lane = "remote" | "me" | "manual";
export type TranscriptionProvider = "local-whisper" | "web-speech" | "manual" | "replay";
export interface Utterance {
  id: UtteranceId;
  text: string;                 // trimmed, non-empty
  lane: Lane;
  speaker: string | null;       // the label a person assigned to the lane; never inferred
  provider: TranscriptionProvider;
  model: string | null;         // the Whisper model id; null for manual / web-speech / replay
  t_start_ms: number;           // integer ms from session start (the session's created_at)
  t_end_ms: number;             // >= t_start_ms
  is_local: boolean;            // false only for web-speech in v1
  confidence: number | null;    // the transcriber's own figure in [0,1], <= 2 dp, or null when it gives none
}

/* ───────────── 4. Classifier stamp, proposal, operations ───────────── */
export type ClassifierProvider = "rules.v1" | "claude" | "human";
export interface ClassifierStamp {
  provider: ClassifierProvider;
  model: string | null;           // served model id for "claude"; null otherwise
  prompt_version: string | null;  // SYSTEM_PROMPT_VERSION for "claude"; null otherwise
  fallback_from: "claude" | null; // rules.v1 answered because claude refused/errored
  error: string | null;           // the failure code (§6.5) when fallback_from is set; null otherwise
  actor: string | null;           // the person behind this proposal: the UI user for "human"; for a proposal that resolves a
                                  // clarification, the person who answered (UI user, or the speaker label of the voice answer);
                                  // null for a pure AI interpretation
}
/** What a classifier provider stamps: ClassifierStamp without the human provider and without actor. */
export type ClassifierProvenance = Omit<ClassifierStamp, "provider" | "actor"> & { provider: "rules.v1" | "claude" };

export interface Candidate { card_id: CardId; label: string; score: number | null }   // null = unranked (shown in asking order)

export interface Proposal {
  id: ProposalId;
  intent: Intent;
  operation: Operation | null;           // null <=> needs_clarification
  template: OperationTemplate | null;    // needs_clarification only: the operation minus its target ("which one?")
  pending_operation: Operation | null;   // needs_clarification only: a fully resolved operation awaiting a yes/no ("did you mean…?")
  candidates: Candidate[];               // needs_clarification with a template only; may be []
  confidence: number;                    // 0..1, <= 2 decimals (INVALID_CONFIDENCE otherwise; apply() never rounds)
  needs_clarification: boolean;
  question: string | null;               // the text asked of the humans; required when needs_clarification
  source_utterance_ids: UtteranceId[];   // [] for provider "human"
  classifier: ClassifierStamp;
  resolves_clarification_id: ClarificationId | null;
  rationale: string;                     // the classifier's one-line reason; "" allowed
}

export type NewCard =
  | { kind: "story";    text: string; definitions?: Definition[] }
  | { kind: "rule";     text: string; definitions?: Definition[] }
  | { kind: "example";  text: string; rule_id: CardId | null; definitions?: Definition[] }
  | { kind: "question"; text: string; about_card_id: CardId | null; definitions?: Definition[] };

export interface CardPatch {             // every field optional; at least one must change something
  text?: string;
  definitions?: Definition[];
  rule_id?: CardId | null;               // example only
  about_card_id?: CardId | null;         // question only
  answer?: string | null;                // question only (null re-opens)
}

/** A target-independent amendment; resolveTemplate() turns it into patch.text for the chosen card (§5.5). `to` may be "" when `from` is null. */
export interface Amendment { from: string | null; to: string; scope: string | null; append: string }

export type Operation =
  | { kind: "card.create";           card: NewCard }
  | { kind: "card.update";           card_id: CardId; patch: CardPatch }
  | { kind: "card.remove";           card_id: CardId }
  | { kind: "card.replace";          card_id: CardId; replacement: { text: string; definitions?: Definition[] } }
  | { kind: "card.replace";          card_id: CardId; replacement_card_id: CardId }     // an existing live card of the same kind
  | { kind: "definition.refine";     card_id: CardId; term: string; definition: string }
  | { kind: "interpretation.reject"; proposal_id: ProposalId }
  | { kind: "confirm";               card_ids: CardId[]; proposal_ids: ProposalId[] }  // at least one non-empty
  | { kind: "undo";                  to_revision_seq: number | null };                // null = one step back (§5.9)
export type OperationKind = Operation["kind"];

/** An operation whose target is still unknown; a clarification answer of kind "candidate" fills it. */
export type OperationTemplate =
  | { kind: "card.create"; card: NewCard & { kind: "example" | "question" } }   // the answer fills rule_id / about_card_id
  | { kind: "card.update"; patch: CardPatch; amendment: Amendment | null }      // amendment => patch.text is recomputed per card
  | { kind: "card.remove" }
  | { kind: "card.replace"; replacement: { text: string; definitions?: Definition[] } }
  | { kind: "card.replace"; replacement_card_id: CardId }                       // the answer names the card being replaced
  | { kind: "definition.refine"; term: string; definition: string }
  | { kind: "confirm" }                                                         // the answer names a card -> card_ids: [it]
  | { kind: "interpretation.reject" };                                          // the answer names a card; its changed.proposal_id is the target

/* ───────────── 5. Clarification ───────────── */
export type ClarificationAnswer =
  | { kind: "candidate"; card_id: CardId }                               // fills the template's target
  | { kind: "yes" }                                                      // applies pending_operation
  | { kind: "text"; text: string; utterance_id: UtteranceId | null }     // free text -> the server re-runs the classifier
  | { kind: "dismiss"; reason: string };

export interface TextAnswer { text: string; utterance_id: UtteranceId | null; actor: string; event_id: EventId }

export interface Clarification {
  id: ClarificationId;
  proposal_id: ProposalId;               // the proposal that asked
  question: string;
  candidates: Candidate[];
  template: OperationTemplate | null;
  pending_operation: Operation | null;
  status: "open" | "answered" | "dismissed";
  asked_event_id: EventId;
  text_answers: TextAnswer[];            // every text answer so far, oldest first; they do not close the clarification
  answer: ClarificationAnswer | null;    // the answer that resolved or dismissed it
  answered_event_id: EventId | null;
  resolved_by_proposal_id: ProposalId | null;   // non-null <=> status === "answered"
}

/* ───────────── 6. Export options (a person's export-time annotations; in the chain, outside the sign-off) ───────────── */
export type BacklogKind = "code" | "infra" | "operator";
export type SizeEstimate = "XS" | "S" | "M" | "L" | "XL" | "unsized";
export interface ExportFact { slot: string; text: string }       // slot /^[A-Za-z][A-Za-z0-9_]*$/, text non-empty
export interface ExportOptionsInput { capability_class: string; kind: BacklogKind; size_estimate: SizeEstimate; facts: ExportFact[]; by: string }
export interface ExportOptions extends ExportOptionsInput { seq: number; at: IsoTimestamp }   // seq 1.. per session; the current value is the last

/* ───────────── 7. Events ───────────── */
export interface RevisionStamp { seq: number; hash: Sha256Hex }
export interface CardEffect { card_id: CardId; before: CardRecord | null; after: CardRecord }
export interface RefusedOperation { operation: OperationKind | "unknown"; reason: string; detail: string }
export interface ClassifierErrorInfo { code: string; message: string }

export interface EventBase {
  id: EventId;
  seq: number;                 // 1-based position in the ledger
  at: IsoTimestamp;            // hashed (audit time); excluded from the revision
  session_id: string;          // the same in every event of a ledger
  batch_id: EventId;           // id of the first event of the apply() batch that appended this one (== id for that event)
  prev_hash: Sha256Hex | "";   // "" at genesis
  hash: Sha256Hex;             // sha256(canonicalJson(event without `hash`))
}
export type EventPayload =
  | { type: "utterance.recorded";  utterance: Utterance }
  | { type: "utterance.classified"; utterance_id: UtteranceId; intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp;
                                    confidence: number; rationale: string; proposal_ids: ProposalId[]; refused: RefusedOperation[];
                                    error: ClassifierErrorInfo | null }
  | { type: "proposal.made";       proposal: Proposal; effects: CardEffect[] }          // card.create => one proposed card; else []
  | { type: "proposal.applied";    proposal_id: ProposalId; operation: Operation; effects: CardEffect[]; revision: RevisionStamp }
  | { type: "proposal.rejected";   proposal_id: ProposalId; rejected_proposal_id: ProposalId; effects: CardEffect[]; revision: RevisionStamp }
  | { type: "proposal.confirmed";  proposal_id: ProposalId; card_ids: CardId[]; proposal_ids: ProposalId[]; confirms_proposal_ids: ProposalId[]; effects: CardEffect[] }
  | { type: "undo.applied";        proposal_id: ProposalId; from_revision: RevisionStamp; to_revision: RevisionStamp; effects: CardEffect[]; revision: RevisionStamp }
  | { type: "clarification.asked"; clarification_id: ClarificationId; proposal_id: ProposalId; question: string; candidates: Candidate[];
                                   template: OperationTemplate | null; pending_operation: Operation | null }
  | { type: "clarification.answered"; clarification_id: ClarificationId; answer: ClarificationAnswer; actor: string; resolved_by_proposal_id: ProposalId | null }
  | { type: "question.accepted_outstanding"; question_id: CardId; by: string; reason: string; effects: CardEffect[] }
  | { type: "signoff.recorded";    signoff: SignoffRecord }
  | { type: "signoff.invalidated"; signoff_id: SignoffId; by_event_id: EventId; from_revision: RevisionStamp; to_revision: RevisionStamp }
  | { type: "export.options_set";  options: ExportOptions };
export type ExmapEvent = EventBase & EventPayload;                       // 13 event types
export type EventType = ExmapEvent["type"];
export type EventBody = DistributiveOmit<ExmapEvent, "hash">;           // distributive: every payload keeps its own fields

/* ───────────── 8. State ───────────── */
export type ProposalStatus = "pending" | "applied" | "confirmed" | "rejected" | "clarifying" | "answered" | "dismissed";
export interface ProposalRecord {
  proposal: Proposal;
  status: ProposalStatus;
  made_event_id: EventId;
  outcome_event_id: EventId | null;       // applied / rejected / confirmed / undo / clarification.asked event
  effects: CardEffect[];                  // of the outcome event (what interpretation.reject inverts)
  affected_card_ids: CardId[];            // primary targets: created / updated / removed / replaced (old + replacement) / confirmed / reverted ids
}
export interface ClassificationRecord {
  utterance_id: UtteranceId; event_id: EventId;
  intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp; confidence: number; rationale: string;
  proposal_ids: ProposalId[]; refused: RefusedOperation[]; error: ClassifierErrorInfo | null;
}
export type RevisionCause = "genesis" | "proposal.applied" | "proposal.rejected" | "undo.applied";
export interface Revision {
  seq: number; hash: Sha256Hex; event_id: EventId | null; at: IsoTimestamp | null; cause: RevisionCause;
  batch_id: EventId | null;               // null for genesis; revisions with equal batch_id are one step (§5.9)
  source_utterance_ids: UtteranceId[];    // of the proposal that created it; [] for human acts and genesis
  snapshot: Record<CardId, CardRecord>;   // every card (all statuses) as of this revision; in-memory only (never serialised)
}
export interface SignoffRecord {
  id: SignoffId;
  reviewer: { name: string };
  confirmation_text: string;              // === SIGNOFF_CONFIRMATION_TEXT
  revision: RevisionStamp;                // the exact requirement revision
  evidence: { head_seq: number; head_hash: Sha256Hex };  // chain head immediately before this event
  checks: DodReport;                      // computed by the engine (§5.7)
}
export interface Signoff extends SignoffRecord {
  event_id: EventId; at: IsoTimestamp;
  status: "active" | "invalidated";
  invalidated: { event_id: EventId; by_event_id: EventId; to_revision: RevisionStamp } | null;
}
export interface MapState {
  schema: "exmap.state.v1";
  session_id: string;
  head: { seq: number; hash: Sha256Hex | ""; event_id: EventId | null };
  utterances: Utterance[];
  classifications: ClassificationRecord[];   // ledger order; one utterance may have several (re-runs after a text answer)
  cards: Record<CardId, Card>;          card_order: CardId[];
  proposals: Record<ProposalId, ProposalRecord>; proposal_order: ProposalId[];
  clarifications: Record<ClarificationId, Clarification>; clarification_order: ClarificationId[];
  revisions: Revision[];                // revisions[0] is genesis; revisions.at(-1) is current
  signoffs: Signoff[];                  // oldest first; at most one is "active" and it is always the last
  export_options: ExportOptions[];      // oldest first; the current value is at(-1) ?? null
}
export interface Counts {               // select.counts(state): every number the UI shows comes from here
  utterances: number; classified: number; actionable: number; classifier_errors: number; fallbacks: number;
  cards_live: number; by_kind: Record<CardKind, number>; needs_review: number; open_questions: number; accepted_questions: number;
  open_clarifications: number; unreviewed_acts: number; revision_seq: number; events: number;
}

/* ───────────── 9. Commands, apply context, refusals ───────────── */
export type Command =
  | { kind: "utterance.record";      utterance: Utterance }
  | { kind: "proposal.propose";      proposals: Proposal[] }                  // 1..n, one batch, all or nothing
  | { kind: "classification.record"; utterance_id: UtteranceId; intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp;
                                     confidence: number; rationale: string; proposal_ids: ProposalId[]; refused: RefusedOperation[];
                                     error: ClassifierErrorInfo | null }
  | { kind: "clarification.answer";  clarification_id: ClarificationId; answer: ClarificationAnswer; actor: string }
  | { kind: "question.accept";       question_id: CardId; by: string; reason: string }
  | { kind: "signoff.record";        reviewer: { name: string }; confirmation_text: string; cited_revision_hash: Sha256Hex }
  | { kind: "export.options_set";    options: ExportOptionsInput };

export type IdPrefix = "evt" | "card" | "prop" | "clar" | "sig" | "utt";
export interface ApplyContext {
  now: () => IsoTimestamp;
  nextId: (prefix: IdPrefix) => string;   // called only after validation passes
  sha256: Sha256Fn;
}
export type RefusalCode =
  | "BAD_SHAPE" | "DUPLICATE_ID" | "EMPTY_TEXT" | "INVALID_TIMING" | "INVALID_ENUM" | "INVALID_CONFIDENCE" | "INVALID_DEFINITION"
  | "INTENT_OPERATION_MISMATCH" | "UTTERANCE_UNKNOWN"
  | "CARD_NOT_FOUND" | "CARD_NOT_LIVE" | "KIND_MISMATCH" | "LINK_KIND_MISMATCH" | "STORY_ALREADY_EXISTS"
  | "PATCH_EMPTY" | "PATCH_FIELD_NOT_ALLOWED" | "NO_CHANGE" | "EMPTY_TARGET" | "REPLACEMENT_INVALID"
  | "NOTHING_TO_CONFIRM" | "PROPOSAL_NOT_CONFIRMABLE" | "PROPOSAL_NOT_FOUND" | "PROPOSAL_NOT_REJECTABLE" | "PROPOSAL_KIND_NOT_REJECTABLE" | "REJECT_NOT_LATEST"
  | "UNDO_NO_EARLIER_REVISION" | "UNDO_TARGET_OUT_OF_RANGE" | "UNDO_TARGET_IS_CURRENT"
  | "CLARIFICATION_QUESTION_REQUIRED" | "CLARIFICATION_SHAPE" | "CLARIFICATION_NOT_FOUND" | "CLARIFICATION_NOT_ANSWERABLE"
  | "CLARIFICATION_NOT_AWAITING_PROPOSAL" | "CLARIFICATION_NO_TEMPLATE" | "CLARIFICATION_NO_OPERATION"
  | "CLASSIFICATION_PROPOSAL_MISMATCH" | "ACTOR_REQUIRED" | "REASON_REQUIRED" | "QUESTION_ALREADY_RESOLVED"
  | "SIGNOFF_REVIEWER_REQUIRED" | "SIGNOFF_CONFIRMATION_TEXT_MISMATCH" | "SIGNOFF_STALE_REVISION" | "SIGNOFF_ALREADY_ACTIVE" | "SIGNOFF_DOD_FAILED";
export type ApplyResult =
  | { ok: true;  events: ExmapEvent[]; state: MapState }
  | { ok: false; reason: RefusalCode; detail: string; checks?: DodReport };   // checks only for SIGNOFF_DOD_FAILED

/* ───────────── 10. Chain, revision, DoD ───────────── */
export type ChainErrorCode = "PREV_HASH_MISMATCH" | "HASH_MISMATCH" | "SEQ_MISMATCH" | "SESSION_MISMATCH";
export interface ChainError { code: ChainErrorCode; seq: number; event_id: string; detail: string }
export type VerifyResult = { ok: true; count: number; head: Sha256Hex | "" } | { ok: false; error: ChainError };
export type ReplayError = ChainError | { code: "REVISION_MISMATCH"; seq: number; expected: Sha256Hex; actual: Sha256Hex } | { code: "EMPTY_LEDGER" };
export type ReplayResult = { ok: true; state: MapState } | { ok: false; error: ReplayError };

export interface CanonicalState { schema: "exmap.revision.v1"; cards: CanonicalCard[] }   // live cards, sorted by id
export type CanonicalCard =
  | { id: CardId; kind: "story";    text: string; definitions: Definition[] }
  | { id: CardId; kind: "rule";     text: string; definitions: Definition[] }
  | { id: CardId; kind: "example";  text: string; definitions: Definition[]; rule_id: CardId | null }
  | { id: CardId; kind: "question"; text: string; definitions: Definition[]; about_card_id: CardId | null; answer: string | null };

export type DodCheckId = "story_rules_confirmed" | "examples_reviewed" | "changes_resolved" | "questions_resolved" | "final_version_recorded";
export interface DodCheck { id: DodCheckId; title: string; pass: boolean; details: string[] }   // details name ids
export interface DodReport { pass: boolean; checks: DodCheck[] }   // always all five, in this order
export interface DodOptions { requireHumanConfirm: boolean }       // true: only confirmations with by.provider === "human" count in checks 1, 2, 4

/* ───────────── 11. Classifier input and output (what a classifier sees and returns) ───────────── */
export type ClassifierProviderId = "rules.v1" | "claude";
export type ClassifierIntent = Intent | "none";
/** What the classifier sees of an utterance: core's record minus timing and provider. lane "manual" = typed. */
export type ClassifierUtterance = Pick<Utterance, "id" | "text" | "lane" | "speaker">;

export interface CardIndexEntry {
  id: CardId;
  kind: CardKind;
  title: string;                     // first 60 chars of text (candidate label)
  text: string;                      // full card text
  status: CardStatus;                // the index holds proposed | applied | confirmed only
  links: { rule_id: CardId | null; about_card_id: CardId | null };
  answer: string | null;             // questions: the recorded answer; null otherwise
  seq: number;                       // ledger seq of changed.event_id
  last_utterance_id: UtteranceId | null;  // changed.utterance_ids.at(-1); null for a card made in the UI
  last_speaker: string | null;       // speaker label of that utterance; null when none was assigned
  proposal_id: ProposalId | null;    // changed.proposal_id when a non-human proposal produced the current version; null otherwise
}
export interface LastProposalRef {
  id: ProposalId;
  intent: Intent;
  op: OperationKind;                 // the operation core applied
  kind: CardKind | null;             // kind of card_ids[0] (any status); null for undo
  status: "applied" | "confirmed";
  card_ids: CardId[];                // core affected_card_ids (may include cards no longer in the index)
  utterance_id: UtteranceId;         // source_utterance_ids[0]
  rejectable: boolean;               // select.isRejectable(state, id) at input-build time
}
export interface PendingClarification {
  proposal_id: ProposalId;           // the proposal that asked
  kind: "choose_target" | "confirm_intent";
  question: string;
  candidates: Array<{ card_id: CardId; label: string }>;   // asking order; [] for confirm_intent
  pending_operations: ClassifierOperation[];   // choose_target: "$choice" where the chosen id goes; confirm_intent: exactly one complete operation
  intent: Intent;
  asked_by_utterance_id: UtteranceId;
  source_utterance_ids: UtteranceId[];
  classifier: ClassifierProvenance;  // who asked
}
export interface ClassifierInput {
  utterance: ClassifierUtterance;
  recent: ClassifierUtterance[];                // the last 12 utterances before this one, oldest first
  cards: CardIndexEntry[];                      // every card with status proposed | applied | confirmed, in card_order
  last_proposal: LastProposalRef | null;        // most recent non-human proposal with status applied | confirmed
  last_rejectable: LastProposalRef | null;      // most recent proposal with rejectable === true (may equal last_proposal)
  pending_clarification: PendingClarification | null;   // the most recent open clarification the classifier can represent (§6.6)
}
export interface Classifier {
  readonly provider: ClassifierProviderId;
  classify(input: ClassifierInput, opts?: { signal?: AbortSignal }): Promise<ClassifierProposal>;
}

/** The classifier's own operation shapes (core's names plus three classifier-side fields; the bridge maps them, §8.7). */
export interface CardDraft { kind: CardKind; text: string; rule_id: CardId | null; about_card_id: CardId | null }
export interface ClassifierCardPatch { text: string | null; text_append: string | null; answer: string | null; rule_id: CardId | null; about_card_id: CardId | null }
export interface ClassifierAmendment { from: string | null; to: string; scope: string | null }
export type ClassifierOperation =
  | { kind: "card.create";           card: CardDraft }
  | { kind: "card.update";           card_id: string; patch: ClassifierCardPatch; amendment: ClassifierAmendment | null }   // card_id may be "$choice"
  | { kind: "card.remove";           card_id: string; reason: string }
  | { kind: "card.replace";          card_id: string; replacement: { text: string } | null; replacement_card_id: CardId | null }
  | { kind: "definition.refine";     card_id: string; term: string; definition: string }
  | { kind: "interpretation.reject"; proposal_id: string }
  | { kind: "confirm";               card_ids: CardId[] }     // [] = review the last proposal's act (removal / undo / rejection)
  | { kind: "undo";                  steps: number };         // one step = one batch (one utterance or one click)
export interface ClassifierClarification {
  kind: "choose_target" | "confirm_intent";
  question: string;                                          // one sentence to the people in the meeting
  candidates: Array<{ card_id: CardId; label: string }>;     // >= 2 for choose_target; [] for confirm_intent
  pending_operations: ClassifierOperation[];                 // choose_target: "$choice" in a target field; confirm_intent: exactly one complete operation
}
export interface ClassifierResolves { proposal_id: ProposalId; chosen_card_ids: CardId[]; dismissed: boolean }
export interface ClassifierProposal {
  intent: ClassifierIntent;
  operations: ClassifierOperation[];                         // [] when needs_clarification or intent none
  target_card_ids: CardId[];                                 // every index id referenced (recomputed by the provider)
  confidence: number;                                        // 0..1, 2 dp
  needs_clarification: boolean;
  clarification: ClassifierClarification | null;             // non-null iff needs_clarification
  resolves: ClassifierResolves | null;                       // only when answering pending_clarification
  rationale: string;                                         // one sentence, <= 200 chars
  heard_intent: HeardIntent;                                 // set only on intent "none"
  classifier: ClassifierProvenance;
  source_utterance_ids: UtteranceId[];                       // [utterance.id, (+ asked_by_utterance_id when resolves is set)]
}

/* ───────────── 12. Export shapes ───────────── */
export type ExportFile = "crb-backlog-item.json" | "ticket.json" | "ticket.md" | "requirement.feature" | "evidence.json";
export interface BacklogItem {   // crb BacklogItem (brief §3)
  id: string; title: string; kind: BacklogKind; description: string; acceptance_criteria: string[]; capability_class: string;
  size_estimate: SizeEstimate; structural_facts: string[]; depends_on: string[]; level: "L1" | "L2" | "L3"; supersedes: string;
  registered: IsoTimestamp; labels: Record<string, string>;
}
export interface Ticket {        // crb intake Ticket (brief §3); body is newline-joined plain text
  key: string; title: string; body: string; acceptance_criteria: string[]; type: string; tags: string[]; points: number | null;
  links: string[]; url: string; state: string; author: string;
}
export interface Evidence {
  schema: "exmap.evidence.v1"; exported_at: IsoTimestamp; draft: boolean; verified: boolean;
  session: ExportSession;
  requirement_revision: RevisionStamp;                    // the current revision at export
  chain_head: { seq: number; hash: Sha256Hex | ""; event_id: EventId | null };
  signoff: null | (SignoffRecord & { status: "active" | "invalidated"; at: IsoTimestamp; event_id: EventId; invalidated: Signoff["invalidated"] });
  dod: DodReport;                                         // computed at export time
  canonical_state: CanonicalState;                        // sha256(canonicalJson(.)) === requirement_revision.hash
  export_options: ExportOptions | null;                   // the current value; not covered by the sign-off
  export_options_history: ExportOptions[];                // every value ever set, oldest first
  watermark: "DRAFT / NOT VERIFIED" | null;
}
export interface ExportSession { id: string; title: string; created_at: IsoTimestamp }
export interface ExportInput { session: ExportSession; state: MapState; draft: boolean; now: IsoTimestamp }
export type SignoffGateStatus = "none" | "invalidated" | "active_but_stale" | "active_but_dod_failed";
export interface ExportRefusal {
  ok: false; reason: "NOT_HUMAN_VERIFIED"; detail: string; checks: DodReport;
  signoff: { status: SignoffGateStatus; id?: SignoffId; revision?: RevisionStamp; invalidated_by_event_id?: EventId };
}
export interface ExportResult { ok: true; filename: string; content_type: string; body: string }

/* ───────────── 13. Wire shapes (server <-> browser; the UI never invents its own) ───────────── */
export interface SessionMeta { schema: "exmap.session-meta.v1"; id: string; title: string; created_at: IsoTimestamp }
export interface BrokenInfo { code: string; row: number; seq: number | null; detail: string }
export interface SessionSummary {
  id: string; title: string; created_at: IsoTimestamp;
  head: { seq: number; hash: Sha256Hex | "" };
  revision: RevisionStamp;
  counts: Counts;
  human_verified: boolean;
  broken: BrokenInfo | null;          // set => the session cannot be opened; the summary is computed from the readable prefix
}
export interface ErrorBody { ok: false; reason: string; detail: string; issues?: unknown[]; checks?: DodReport;
                             event?: { id: EventId; seq: number; hash: Sha256Hex };            // DUPLICATE_ID on the utterance route
                             signoff?: ExportRefusal["signoff"] }                               // NOT_HUMAN_VERIFIED
export interface ActResponse { ok: true; events: ExmapEvent[]; proposal_id?: ProposalId }
export interface ClassificationSummary {
  event: { id: EventId; seq: number };                    // the utterance.classified event
  intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp; confidence: number; rationale: string;
  proposals: Array<{ proposal_id: ProposalId; status: ProposalStatus; clarification_id: ClarificationId | null;
                     events: Array<{ id: EventId; seq: number; type: EventType }> }>;
  refused: RefusedOperation[]; error: ClassifierErrorInfo | null;
}
export interface UtterancePostResponse { ok: true; event: { id: EventId; seq: number; hash: Sha256Hex }; classification?: ClassificationSummary }
export interface ClassifierConfig {
  provider: ClassifierProviderId; reason: string; model: string | null;
  credentials: "api_key" | "auth_token" | "none" | "profile_or_none";
  last_error: { code: string; message: string; at: IsoTimestamp } | null;
}
export interface ConfigResponse { app: "exmap"; version: string; port: number; home: string; loopback: true; coop: boolean; classifier: ClassifierConfig }
export type StreamMessage =
  | { type: "hello"; session_id: string; head: { seq: number; hash: Sha256Hex | "" }; after: number }
  | { type: "event"; event: ExmapEvent }
  | { type: "error"; reason: "SESSION_NOT_FOUND" | "LEDGER_BROKEN" | "FORBIDDEN_ORIGIN"; detail: string; row?: number };
