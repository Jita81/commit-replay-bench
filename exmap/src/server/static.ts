// exmap/src/server/static.ts — dist/web at / and the ORT runtime files at /ort/ (design §8.2). Real at step zero.
// There is no copy step: the two files transformers.js 4.3.1 loads are served straight from node_modules/onnxruntime-web/dist.
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import fastifyStatic from "@fastify/static";
import type { FastifyInstance } from "fastify";

export const ORT_RUNTIME_FILES = ["ort-wasm-simd-threaded.asyncify.mjs", "ort-wasm-simd-threaded.asyncify.wasm"] as const;
const ORT_ALLOWED = /^\/?ort-wasm-simd-threaded\.asyncify\.(mjs|wasm)$/;
export const NO_WEB_BUILD_TEXT = "exmap: no web build; run npm run build, or npm run dev and open http://127.0.0.1:5173";

/** dirname of the exported runtime subpath (onnxruntime-web/package.json itself is not exported). */
export function resolveOrtDir(root: string): string {
  const require = createRequire(join(root, "package.json"));
  return dirname(require.resolve("onnxruntime-web/ort-wasm-simd-threaded.asyncify.wasm", { paths: [root] }));
}

/** The absolute paths of the runtime files that are absent from ortDir ([] when both exist). */
export function missingOrtFiles(ortDir: string): string[] {
  return ORT_RUNTIME_FILES.map((f) => join(ortDir, f)).filter((p) => !existsSync(p));
}

export async function registerStatic(app: FastifyInstance, opts: { webDist: string | null; ortDir: string | null }): Promise<void> {
  if (opts.ortDir) {
    await app.register(fastifyStatic, {
      root: opts.ortDir,
      prefix: "/ort/",
      decorateReply: false,
      allowedPath: (pathName: string) => ORT_ALLOWED.test(pathName),
      index: false,
      list: false,
    });
  }
  if (opts.webDist) {
    await app.register(fastifyStatic, { root: opts.webDist, prefix: "/", index: ["index.html"], wildcard: true });
  } else {
    app.get("/", async (_req, reply) => reply.code(503).type("text/plain; charset=utf-8").send(NO_WEB_BUILD_TEXT));
  }
}
