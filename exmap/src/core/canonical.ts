// exmap/src/core/canonical.ts — design §5.1. Canonical JSON: keys sorted by UTF-16 code-unit order (recursively),
// `undefined` properties omitted, arrays in order, strings escaped as JSON.stringify does, no whitespace. Numbers must be
// finite; functions, symbols and bigints are refused. Equivalent to JSON.stringify(sortKeysDeep(value)).
export class CanonicalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CanonicalError";
  }
}

/** Sorted keys (UTF-16 code-unit order, recursive), undefined properties omitted, no whitespace; finite numbers only. */
export function canonicalJson(value: unknown): string {
  if (value === undefined) throw new CanonicalError("cannot canonicalise undefined at $");
  const out: string[] = [];
  write(value, out, "$");
  return out.join("");
}

function write(value: unknown, out: string[], path: string): void {
  switch (typeof value) {
    case "string":
      out.push(JSON.stringify(value));
      return;
    case "number":
      if (!Number.isFinite(value)) throw new CanonicalError(`non-finite number at ${path}`);
      out.push(JSON.stringify(value)); // -0 serialises as "0", like JSON.stringify
      return;
    case "boolean":
      out.push(value ? "true" : "false");
      return;
    case "bigint":
      throw new CanonicalError(`bigint at ${path}`);
    case "function":
      throw new CanonicalError(`function at ${path}`);
    case "symbol":
      throw new CanonicalError(`symbol at ${path}`);
    case "undefined":
      // only reachable inside arrays (object properties are filtered); JSON.stringify writes null there
      out.push("null");
      return;
    case "object":
      break;
  }
  if (value === null) {
    out.push("null");
    return;
  }
  if (Array.isArray(value)) {
    out.push("[");
    for (let i = 0; i < value.length; i++) {
      if (i > 0) out.push(",");
      write(value[i], out, `${path}[${i}]`);
    }
    out.push("]");
    return;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record)
    .filter((k) => record[k] !== undefined)
    .sort(); // default sort = UTF-16 code-unit order
  out.push("{");
  let first = true;
  for (const key of keys) {
    const child = record[key];
    const childType = typeof child;
    if (childType === "function" || childType === "symbol" || childType === "bigint") {
      throw new CanonicalError(`${childType} at ${path}.${key}`);
    }
    if (!first) out.push(",");
    first = false;
    out.push(JSON.stringify(key), ":");
    write(child, out, `${path}.${key}`);
  }
  out.push("}");
}
