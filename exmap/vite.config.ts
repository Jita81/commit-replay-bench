// exmap/vite.config.ts — design §3.2. The Vite root is src/web; the build lands in dist/web.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const SERVER = "http://127.0.0.1:4317";

export default defineConfig({
  root: "src/web",
  publicDir: "public",
  base: "/",
  plugins: [react(), tailwindcss()],
  build: { outDir: "../../dist/web", emptyOutDir: true, sourcemap: false, target: "es2022" },
  worker: { format: "es" },
  optimizeDeps: { exclude: ["@huggingface/transformers"] },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    },
    proxy: {
      "/api": { target: SERVER, ws: true, changeOrigin: true },
      "/ort": { target: SERVER, changeOrigin: true },
    },
  },
});
