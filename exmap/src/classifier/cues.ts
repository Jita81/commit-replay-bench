// exmap/src/classifier/cues.ts — INTENT_CUES, KIND_CUES, DISCOURSE_MARKERS, REFERENT_PATTERNS, ANSWER_FILLER and the
// other word lists of design §6.3. Data only: every entry is a phrase matched at word boundaries on the normalised text or a
// regular expression. Each intent has ordered groups; a group scores 1 when any of its entries matches.
import type { Intent } from "../core/types.js";

export type CueEntry = string | RegExp;

export interface CueGroup {
  /** A1 … U2 as named in the design. */
  id: string;
  entries: CueEntry[];
  /** Groups computed by code rather than by matching entries: A2 (kindCue on the masked sentence) and A6 (continuation). */
  special?: "kind" | "continuation";
}

export const INTENT_CUES: Record<Intent, CueGroup[]> = {
  add: [
    {
      id: "A1",
      entries: [
        "we need", "we also need", "we will need", "also need", "need a", "need an", "needs a", "there is also",
        "there is another", "another", "add a", "add an", "add the", "let us add", "we should also", "we should have",
        "one more", "what about adding", "we need to cover", "cover the case", "include",
      ],
    },
    { id: "A2", entries: [], special: "kind" },
    { id: "A3", entries: [] }, // subject-modal opener: evaluated by code (A3_OPENER + A3_EXCLUDED_SUBJECTS)
    {
      id: "A4",
      entries: [
        /^(for example|for instance|e g|say|suppose|imagine|let us say)\b/,
        /\b(if|when|given)\b.*\bthen\b/,
        /\b(say|suppose|imagine) (a|an|the|it|they|we|there|you)\b/,
      ],
    },
    { id: "A5", entries: [] }, // interrogative: evaluated by code (A5_TERMINAL + A5_OPENER)
    { id: "A6", entries: [], special: "continuation" },
  ],
  amend: [
    {
      id: "M1",
      entries: [
        "change", "make that", "make it", "make the", "make them", "make those", "update", "set that to", "set it to",
        "set the", "bump", "raise", "lower", "increase", "decrease", "extend", "shorten", "reduce", "switch to", "tweak",
        "amend", "adjust", "alter", "revise", "reword", "rename", "correct that", "should actually be", "should really be",
      ],
    },
    { id: "M2", entries: [/\b(to|up to|down to|rather than|instead of|now|not \d+ but)\s+\d+(\.\d+)?/] },
    {
      id: "M3",
      entries: ["actually", "correction", "i meant", "on second thought", "let me correct", "wait", "strike that", "scrap that", "no wait"],
    },
    { id: "M4", entries: ["the answer is", "the answer to that is", "to answer that", "answering that", /^answer\b/] },
  ],
  remove: [
    { id: "D1", entries: ["delete", "remove", "drop", "get rid of", "scrap", "take out", "take that out", "take it out", "bin", "lose", "strike", /(?<![a-z0-9'])cut(?! ?off)(?![a-z0-9'])/, "ditch"] },
    {
      id: "D2",
      entries: ["do not need", "no need for", "not needed", "do not want", "unnecessary", "does not belong", "should not be there", "redundant", "duplicate", "duplicates"],
    },
    { id: "D3", entries: ["does not apply", "irrelevant", "not relevant", "out of scope", "forget that", "forget it", "never mind that", "ignore that", "ignore it"] },
  ],
  replace: [
    { id: "P1", entries: ["instead", "instead of", "rather than", "replace", "replaces", "swap", "in place of", "supersede", "supersedes", "better example", "better rule"] },
    { id: "P2", entries: ["use this", "use that", "use the following", "this one instead", "this version", "this example", "this rule", "this wording", "the following"] },
  ],
  clarify: [
    {
      id: "C1",
      entries: ["i mean", "we mean", "to clarify", "to be clear", "just to clarify", "define", "definition", "means", "meaning", "when i say", "when we say", "what i mean by", "let me clarify", "in other words"],
    },
    { id: "C2", entries: [] }, // definition patterns: DEFINITION_PATTERNS (captures term / def)
  ],
  reject: [
    { id: "R1", entries: [/^(no|nope|nah)\b/, "that is not", "that was not", "wrong", "incorrect", "not right", "not correct", "you got that wrong", "you have got that wrong", "that is off"] },
    {
      id: "R2",
      entries: ["not what i said", "not what i meant", "not what we said", "not what we meant", "misunderstood", "misheard", "did not say that", "never said", "that is not it", "you misread", "i did not mean", "we did not mean"],
    },
  ],
  confirm: [
    { id: "F1", entries: [/^(yes|yeah|yep|yup|correct|right|exactly|agreed|ok|okay|sure|fine|perfect|great|good|absolutely|definitely)\b/] },
    {
      id: "F2",
      entries: ["that is right", "that is correct", "that is it", "that is exactly", "exactly right", "exactly", "precisely", "spot on", "looks good", "looks right", "sounds right", "sounds good", "i agree", "we agree", "confirmed", "happy with that", "that works", "absolutely"],
    },
  ],
  undo: [
    { id: "U1", entries: ["undo", "go back", "revert", "roll back", "rollback", "put it back", "put that back", "restore", "scratch that", "as it was", "back to how it was", "reinstate", "bring back"] },
    {
      id: "U2",
      entries: ["previous version", "last version", "earlier version", "the way it was", "how it was", "that change", "the last change", "what it was", "previous state", "previous revision", "before that", /\b(last|previous)( \d+)? (changes?|steps?|versions?)\b/],
    },
  ],
};

/** Precedence used to break score ties (design §6.3 "best, runner"). */
export const INTENT_PRECEDENCE: Intent[] = ["undo", "reject", "remove", "replace", "amend", "clarify", "confirm", "add"];

/** A3: subject-modal opener. Group 1 = optional determiner, 2 = subject word 1, 3 = optional subject word 2, 4 = modal. */
export const A3_OPENER =
  /^(?:(a|an|the|every|any|all|no|each) )?([a-z]+)(?: ([a-z]+))? (should|must|shall|can not|can|may not|may|needs?|has to|have to|is not|are not|is|are)\b/;
export const A3_EXCLUDED_SUBJECTS = new Set([
  "it", "that", "this", "we", "i", "you", "they", "there", "he", "she", "who", "what", "which", "answer",
  "yes", "no", "yeah", "yep", "yup", "nope", "nah", "ok", "okay", "right", "correct", "exactly", "actually", "sure", "fine",
  "perfect", "great", "good", "so", "well", "and", "but",
]);

/** A5: interrogative form — a trailing "?" or an interrogative opener ("when" is left out: it opens examples). */
export const A5_TERMINAL = /\?$/;
export const A5_OPENER = /^(what|why|how|who|which|where|does|do|is|are|can|could|should|would|will|has|have|did)\b/;
/** Openers removed before the rule-kind cue search (a sentence-initial "should" is A5, not a rule cue). */
export const INTERROGATIVE_OPENERS = new Set([
  "what", "why", "how", "when", "where", "who", "which", "does", "do", "is", "are", "can", "could", "should", "would", "will", "has", "have", "did",
]);

/** C2: definition patterns on the sentence text (commas kept). Named groups term / def. */
export const DEFINITION_PATTERNS: RegExp[] = [
  /\bby (?:an? |the )?(?<term>[a-z][a-z0-9 ]{1,40}?)\s*,?\s*(?:i|we) mean (?<def>.+)$/d,
  /^(?:an? |the )?(?<term>[a-z][a-z0-9 ]{1,40}?) means (?<def>.+)$/d,
  /(?:when (?:i|we) say|what (?:i|we) mean by) (?:an? |the )?(?<term>[a-z][a-z0-9 ]{1,40}?)\s*,?\s*(?:is|i mean|we mean|means|,)\s*(?<def>.+)$/d,
];

export const KIND_CUES: Record<"rule" | "example" | "question", CueEntry[]> = {
  rule: [
    "should", "must", "shall", "may not", "can not", "is not allowed", "are not allowed", "not allowed", "not within", "only if",
    "only when", "unless", "always", "never", "needs to", "need to be", "has to", "have to", "at least", "at most", "no more than",
    "no later than", "no earlier than", "within", "required", "mandatory", "is allowed", "are allowed", "can only", "able to",
  ],
  example: [
    "for example", "for instance", "e g", "say", "suppose", "imagine", "let us say", "scenario", "case where", "such as", "example",
    "another example", "an instance", "take a",
    /\b(if|when) (a|an|the|someone|somebody|i|we|you|they|it)\b/,
    /\b(if|when|given)\b.*\bthen\b/,
  ],
  question: [
    "what about", "what if", "do we know", "does anyone know", "not sure whether", "not sure if", "unclear whether", "unclear if",
    "need to check", "need to find out", "to be confirmed", "open question", "who decides", "i wonder", "the question is",
  ],
};

/** A1 noun heuristic for the card kind when no kind cue matched. */
export const KIND_NOUNS: Array<{ kind: "example" | "question" | "rule"; re: RegExp }> = [
  { kind: "example", re: /\b(cases?|scenarios?|instances?|examples?)\b/ },
  { kind: "question", re: /\b(questions?|unknowns?|to check|find out)\b/ },
  { kind: "rule", re: /\b(rules?|constraints?|policy|policies|limits?|restrictions?)\b/ },
];

/** Leading markers removed by stripDiscourse when followed by a comma or by >= 3 words. */
export const DISCOURSE_MARKERS = new Set([
  "ok", "okay", "right", "alright", "so", "well", "now", "anyway", "um", "uh", "er", "hmm", "got it", "i see", "understood",
  "sure", "sorry", "and", "but", "also", "then",
]);
/** A sentence made only of one of these is dropped. */
export const DISCOURSE_DROP = new Set(["got it", "i see", "understood", "so", "well", "anyway", "um", "uh", "er", "hmm", "sorry"]);
/** Never stripped (they carry a confirm / reject / correction cue). */
export const NEVER_STRIP = new Set(["yes", "yeah", "yep", "no", "nope", "exactly", "correct", "actually"]);
/** A6: a first word (before stripping) in this set continues the previous add. */
export const CONTINUATION_WORDS = new Set(["and", "also", "similarly", "likewise", "plus", "or"]);

/** Lead-ins removed from the front of a draft's raw sentence (case-insensitive, with an optional comma / colon). */
export const LEAD_IN_PATTERNS: RegExp[] = [
  /^(for example|for instance|e\.g\.|one more example|another example|the story is|i said|i meant|we said|say)\b\s*[,:]?\s+/i,
  /^(one more example|another example|the story is)\b\s*[,:]?\s*$/i,
  /^(yes|no|yeah|yep|nope)\b\s*,?\s*(but\b\s+)?/i,
];
/** Correction cues removed from the front of an amendment's appended text. */
export const CORRECTION_PREFIX = /^(actually|correction|i meant|on second thought|let me correct|wait|strike that|scrap that|no wait)\s*,?\s*/i;

/** Words removed before a clarification answer is matched by label (design §6.6 form 4). */
export const ANSWER_FILLER: string[] = [
  "one", "ones", "example", "rule", "question", "card", "first", "second", "that", "this", "please", "the", "it", "i mean", "i meant",
  "yes", "ok", "okay",
];

export const REFERENT_PATTERNS = {
  determiners: new Set(["that", "this", "the", "those", "these"]),
  kindWords: { rule: "rule", rules: "rule", example: "example", examples: "example", question: "question", questions: "question", story: "story" } as Record<string, "rule" | "example" | "question" | "story">,
  noKindWords: new Set(["card", "cards", "one", "ones"]),
  ordinals: { first: 1, second: 2, third: 3, fourth: 4, last: "last", latest: "last", new: "last", newer: "last", previous: "previous", earlier: "previous", older: "previous", old: "previous" } as Record<string, 1 | 2 | 3 | 4 | "last" | "previous">,
  /** Verbs after which a bare demonstrative / "it" / a paraphrase noun phrase is a target. */
  targetVerbs: new Set([
    "change", "make", "update", "set", "bump", "raise", "lower", "increase", "decrease", "extend", "shorten", "reduce", "tweak",
    "amend", "adjust", "alter", "revise", "reword", "rename", "correct", "delete", "remove", "drop", "scrap", "bin", "lose",
    "strike", "cut", "ditch", "undo", "revert", "restore", "reinstate", "replace", "swap", "supersede", "keep", "forget", "ignore",
    "of", "out", "scratch", "park", "take",
  ]),
  unitNouns: new Set(["hour", "hours", "hr", "hrs", "minute", "minutes", "min", "mins", "day", "days", "week", "weeks", "month", "months", "year", "years", "percent", "pound", "pounds", "dollar", "dollars", "time", "times"]),
  /** Phrases in which "that" is part of a cue, not a referent (R1 / R2 / F2 / C-phrases). */
  notReferentPhrases: [
    "that is not", "that was not", "that is off", "that is right", "that is correct", "that is it", "that is exactly", "happy with that",
    "that works", "not what i said", "not what i meant", "did not say that", "that is not it", "the answer to that is", "to answer that",
    "answering that",
  ],
};

export const STOP_WORDS = new Set([
  "a", "an", "the", "is", "are", "am", "be", "been", "being", "was", "were", "to", "of", "and", "or", "but", "it", "its", "that", "this",
  "these", "those", "we", "i", "you", "they", "them", "their", "theirs", "our", "ours", "your", "yours", "my", "mine", "me", "us",
  "him", "her", "his", "he", "she", "in", "on", "at", "for", "with", "by", "as", "not", "no", "yes", "do", "does", "did", "done",
  "can", "could", "should", "would", "will", "shall", "may", "might", "must", "if", "when", "then", "than", "so", "there", "here",
  "has", "have", "had", "more", "most", "about", "from", "up", "out", "also", "just", "very", "what", "which", "who", "whom", "how",
  "why", "where", "because", "into", "onto", "over", "under", "again", "once", "only", "own", "same", "too", "s", "t", "got", "get",
  "let", "us", "ok", "okay", "right", "well", "now", "one", "ones", "some", "any", "all", "each", "every", "both", "few", "such",
  "mean", "meant", "say", "said", "think", "know", "see", "still", "already", "please", "really", "actually", "thing", "things",
  "something", "anything", "everything", "nothing", "card", "cards", "<ref>",
]);
