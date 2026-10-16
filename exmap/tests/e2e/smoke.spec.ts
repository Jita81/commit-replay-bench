// Step-zero e2e smoke: the fixture spawns the built server; /api/health answers and the web bundle is served at /.
import { expect, test } from "./fixtures";

test("GET /api/health answers from the spawned server", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.status()).toBe(200);
  const body = (await res.json()) as { app: string; version: string; ok: boolean };
  expect(body.app).toBe("exmap");
  expect(body.ok).toBe(true);
  expect(body.version).toBe("0.1.0");
});

test("the web bundle is served at /", async ({ page }) => {
  await page.goto("/?testhooks=1");
  await expect(page.getByRole("heading", { name: "Example Map Live" })).toBeVisible();
});

test("the ORT runtime files are served at /ort/", async ({ request }) => {
  const wasm = await request.get("/ort/ort-wasm-simd-threaded.asyncify.wasm");
  expect(wasm.status()).toBe(200);
  expect(wasm.headers()["content-type"]).toContain("application/wasm");
  const other = await request.get("/ort/package.json");
  expect(other.status()).toBe(404);
});
