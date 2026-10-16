// exmap/src/core/canonical.ts — design §5.1. Step-zero stub: signatures only; the core module implements the bodies.
export class CanonicalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CanonicalError";
  }
}

/** Sorted keys (UTF-16 code-unit order, recursive), undefined properties omitted, no whitespace; finite numbers only. */
export function canonicalJson(value: unknown): string {
  void value;
  throw new Error("not implemented: canonicalJson");
}
