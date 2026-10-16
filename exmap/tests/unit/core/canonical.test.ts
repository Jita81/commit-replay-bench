// TEST-PLAN §1 cases 1–3: canonical JSON and the two sha256 adapters.
import { describe, expect, it } from "vitest";
import { CanonicalError, canonicalJson } from "../../../src/core/canonical.js";
import { sha256 as serverSha256 } from "../../../src/server/hash.js";
import { sha256 as webSha256 } from "../../../src/web/hash.js";

describe("canonicalJson", () => {
  it("1. sorts nested keys, drops undefined, emits no whitespace", () => {
    expect(canonicalJson({ b: 1, a: { d: undefined, c: [2, { z: 1, y: 2 }] } })).toBe('{"a":{"c":[2,{"y":2,"z":1}]},"b":1}');
    // equivalent to JSON.stringify(sortKeysDeep(value)); unicode and escapes follow JSON.stringify
    expect(canonicalJson({ "é": "a\nb\"c", "Z": true, "a": null, " ": [] })).toBe(JSON.stringify({ " ": [], Z: true, a: null, "é": 'a\nb"c' }));
    expect(canonicalJson([undefined, 1])).toBe("[null,1]");
    expect(canonicalJson(-0)).toBe("0");
    expect(canonicalJson("x")).toBe('"x"');
  });

  it("2. refuses NaN / Infinity / bigint / functions with CanonicalError", () => {
    expect(() => canonicalJson({ a: Number.NaN })).toThrow(CanonicalError);
    expect(() => canonicalJson({ a: Number.POSITIVE_INFINITY })).toThrow(CanonicalError);
    expect(() => canonicalJson([Number.NEGATIVE_INFINITY])).toThrow(CanonicalError);
    expect(() => canonicalJson({ a: 10n })).toThrow(CanonicalError);
    expect(() => canonicalJson({ a: () => 1 })).toThrow(CanonicalError);
    expect(() => canonicalJson(Symbol("s"))).toThrow(CanonicalError);
    expect(() => canonicalJson(undefined)).toThrow(CanonicalError);
    expect(() => canonicalJson({ a: Number.NaN })).toThrow(/\$\.a/);
  });

  it("3. the sha256 adapters (server node:crypto, browser @noble/hashes) match the §5 vectors", () => {
    for (const sha256 of [serverSha256, webSha256]) {
      expect(sha256("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
      expect(sha256("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
      expect(sha256('{"cards":[],"schema":"exmap.revision.v1"}')).toBe("8e97e07bb7573b0849c4f8894c845ce76472f2c9f0eda7a7db37004bc269f675");
      expect(sha256("ünïcödé")).toBe(serverSha256("ünïcödé"));
    }
  });
});
