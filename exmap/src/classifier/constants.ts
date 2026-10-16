// exmap/src/classifier/constants.ts — design §6.2. The model id and effort are not configurable.
export const MIN_CONFIDENCE = 0.4;
export const TARGET_CUES = 2;
export const RECENT_UTTERANCES = 12;
export const RECENCY_WINDOW = 4;
export const MAX_CANDIDATES = 4;
export const TOPIC_MIN_SCORE = 0.5;
export const DRAFT_MIN_CONTENT_WORDS = 6;
export const ANSWER_MAX_TOKENS = 6;
export const ANSWER_MIN_RATIO = 0.5;
export const RATIONALE_MAX = 200;
export const CLAUDE_MODEL = "claude-opus-5-5";
export const CLAUDE_EFFORT = "medium" as const;
export const CLAUDE_MAX_TOKENS = 4096;
export const CLAUDE_TIMEOUT_MS = 20_000;
export const SYSTEM_PROMPT_VERSION = "exmap.classifier.claude.v1";
