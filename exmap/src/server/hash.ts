// exmap/src/server/hash.ts — the server's Sha256Fn (node:crypto), pinned to the §5 vectors:
// sha256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
// sha256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
import { createHash } from "node:crypto";
import type { Sha256Fn } from "../core/types.js";

export const sha256: Sha256Fn = (utf8) => createHash("sha256").update(utf8, "utf8").digest("hex");
