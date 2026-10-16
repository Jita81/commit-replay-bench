// exmap/src/classifier/claude/claude-provider.ts — createClaudeClassifier({ client, rules, onError }) (design §6.4–6.5).
// Step-zero stub. Provider failures are never thrown: they become provenance (fallback_from "claude", error <code>).
import type { Classifier } from "../../core/types.js";
import type { ClassifierErrorEvent } from "../index.js";
import type { ModelClient } from "./client.js";

export interface ClaudeClassifierOptions {
  client?: ModelClient;
  rules: Classifier;
  onError?: (e: ClassifierErrorEvent) => void;
}

export function createClaudeClassifier(opts: ClaudeClassifierOptions): Classifier {
  void opts;
  throw new Error("not implemented: createClaudeClassifier");
}
