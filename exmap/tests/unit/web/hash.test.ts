// TEST-PLAN §6.1 — the @noble/hashes adapter matches the two §5 vectors (and agrees with node's crypto).
import { describe, expect, it } from "vitest";
import { sha256 } from "../../../src/web/hash.js";
import { sha256 as nodeSha256 } from "../../../src/server/hash.js";

describe("web sha256 adapter", () => {
  it("matches the §5 vectors", () => {
    expect(sha256("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it("agrees with the server's node:crypto adapter on canonical JSON", () => {
    const text = '{"a":1,"b":"ünïcode","c":[1,2,3]}';
    expect(sha256(text)).toBe(nodeSha256(text));
  });
});
