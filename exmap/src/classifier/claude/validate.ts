// exmap/src/classifier/claude/validate.ts — validateModelProposal(m, input, { model }) (design §6.4–6.5). Step-zero stub.
import type { ClassifierInput, ClassifierProposal } from "../../core/types.js";
import type { ModelProposal } from "../schema.js";

export type ValidateResult = { ok: ClassifierProposal } | { fallback: string };

export function validateModelProposal(m: ModelProposal, input: ClassifierInput, meta: { model: string }): ValidateResult {
  void m;
  void input;
  void meta;
  throw new Error("not implemented: validateModelProposal");
}
