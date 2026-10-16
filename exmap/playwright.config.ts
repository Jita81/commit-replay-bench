// exmap/playwright.config.ts — design §13. No webServer block: tests/e2e/fixtures.ts spawns the built server itself.
// PLAYWRIGHT_BROWSERS_PATH is preset in the dev container; never run `playwright install`.
import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const fakeMicWav = fileURLToPath(new URL("./tests/fixtures/audio/mlk16k.wav", import.meta.url));

export default defineConfig({
  testDir: "tests/e2e",
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  projects: [
    {
      name: "chromium",
      // Not devices["Desktop Chrome"]: that descriptor spoofs a Windows user agent (and userAgentData.platform), so the
      // page would detect Windows on this Linux runner and E4's Linux guidance could never show (integration note).
      use: {
        browserName: "chromium",
        viewport: { width: 1280, height: 720 },
        deviceScaleFactor: 1,
        isMobile: false,
        hasTouch: false,
        permissions: ["microphone"],
        launchOptions: {
          args: [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            `--use-file-for-fake-audio-capture=${fakeMicWav}%noloop`,
            "--autoplay-policy=no-user-gesture-required",
          ],
        },
      },
    },
  ],
});
