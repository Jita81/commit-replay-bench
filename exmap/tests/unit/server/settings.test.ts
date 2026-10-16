// TEST-PLAN §4.12 — GET/PUT /api/settings: default "", persisted atomically, survives a restart, ≤ 80 characters.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { call, json, makeApp } from "./helpers.js";

describe("settings", () => {
  it("defaults to an empty name", async () => {
    const { app } = await makeApp();
    const res = await call(app, "GET", "/api/settings");
    expect(res.statusCode).toBe(200);
    expect(json(res)).toEqual({ user_name: "" });
  });

  it("PUT persists to settings.json and survives a restart", async () => {
    const { app, home } = await makeApp();
    const put = await call(app, "PUT", "/api/settings", { user_name: "  Ana  " });
    expect(put.statusCode).toBe(200);
    expect(json(put)).toEqual({ user_name: "Ana" });
    const file = JSON.parse(readFileSync(join(home, "settings.json"), "utf8")) as Record<string, unknown>;
    expect(file).toEqual({ schema: "exmap.settings.v1", user_name: "Ana" });
    await app.close();
    const again = (await makeApp({ home })).app;
    expect(json(await call(again, "GET", "/api/settings"))).toEqual({ user_name: "Ana" });
  });

  it("an 81-character name is 400; 80 is accepted", async () => {
    const { app } = await makeApp();
    const long = await call(app, "PUT", "/api/settings", { user_name: "a".repeat(81) });
    expect(long.statusCode).toBe(400);
    expect(json(long)).toMatchObject({ ok: false, reason: "BAD_REQUEST" });
    expect((await call(app, "PUT", "/api/settings", { user_name: "a".repeat(80) })).statusCode).toBe(200);
    expect((await call(app, "PUT", "/api/settings", { name: "Ana" })).statusCode).toBe(400);
  });
});
