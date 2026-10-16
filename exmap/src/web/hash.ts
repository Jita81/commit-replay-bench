// exmap/src/web/hash.ts — the browser's Sha256Fn via @noble/hashes (only the .js subpaths are exported), pinned to the
// §5 vectors: sha256("") = e3b0c442…52b855, sha256("abc") = ba7816bf…0015ad.
import { sha256 as nobleSha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import type { Sha256Fn } from "../core/types.js";

export const sha256: Sha256Fn = (utf8) => bytesToHex(nobleSha256(utf8ToBytes(utf8)));
