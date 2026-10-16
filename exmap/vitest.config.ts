// exmap/vitest.config.ts — design §13. Two projects: "node" (pure modules) and "web" (jsdom + testing-library).
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "node",
          environment: "node",
          globals: true,
          include: ["tests/unit/{core,classifier,audio,server,export,launcher}/**/*.test.ts"],
        },
      },
      {
        plugins: [react()],
        test: {
          name: "web",
          environment: "jsdom",
          globals: true,
          include: ["tests/unit/web/**/*.test.{ts,tsx}"],
          setupFiles: ["tests/unit/web/setup.ts"],
        },
      },
    ],
    exclude: ["tests/e2e/**", "node_modules/**"],
  },
});
