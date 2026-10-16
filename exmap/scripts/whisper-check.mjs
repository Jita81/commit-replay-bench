#!/usr/bin/env node
// exmap/scripts/whisper-check.mjs — MANUAL check of the real local-whisper pipeline on this machine (design §7.7,
// TEST-PLAN §3 case 52 is the contract test with a fake worker; this script is the only thing that touches the real
// model). It builds nothing new: it starts the built server on a free port, opens the web app in the preinstalled
// Chromium (headed by default, --headless to hide it), pre-accepts the download notice, starts the microphone lane
// with Chromium's fake device playing tests/fixtures/audio/mlk16k.wav, and waits for a Whisper utterance to land in the
// session ledger. It prints the device the model actually loaded on, the load time, the backlog and the transcript.
//
//   node scripts/whisper-check.mjs [--model tiny|base] [--dtype q8|q4] [--headless] [--timeout <s>] [--keep]
//
// Needs: a prior `npm run build` (dist/), network access to huggingface.co on the first run (≈44 MB tiny.en, ≈77 MB
// base.en, cached by the browser afterwards). Exit 0 when a Whisper utterance was recorded, 1 otherwise.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
const flag = (n) => args.includes(`--${n}`);
const val = (n, d) => {
  const i = args.indexOf(`--${n}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : d;
};
const MODEL = val("model", "tiny") === "base" ? "onnx-community/whisper-base.en" : "onnx-community/whisper-tiny.en";
const DTYPE = val("dtype", "q8");
const TIMEOUT_S = Number(val("timeout", "900"));
const HEADLESS = flag("headless");
const WAV = join(ROOT, "tests", "fixtures", "audio", "mlk16k.wav");
const SERVER_MAIN = join(ROOT, "dist", "server", "server", "main.js");
const EXPECTED_WORDS = ["dream", "nation", "rise"];

function log(...parts) {
  console.log(`[whisper-check] ${parts.join(" ")}`);
}

if (!existsSync(SERVER_MAIN)) {
  console.error(`[whisper-check] ${SERVER_MAIN} is missing: run npm run build first`);
  process.exit(1);
}

let chromium;
try {
  ({ chromium } = require("@playwright/test"));
} catch (e) {
  console.error(`[whisper-check] @playwright/test is not installed (${e.message}); run npm install`);
  process.exit(1);
}

const home = mkdtempSync(join(tmpdir(), "exmap-whisper-check-"));
const server = spawn(process.execPath, [SERVER_MAIN], {
  cwd: ROOT,
  env: { ...process.env, EXMAP_HOME: home, EXMAP_PORT: "0", EXMAP_CLASSIFIER: "rules.v1", EXMAP_NO_OPEN: "1" },
  stdio: ["ignore", "pipe", "pipe"],
});
const baseURL = await new Promise((res, rej) => {
  let out = "";
  const t = setTimeout(() => rej(new Error(`server did not print its listening line\n${out}`)), 30_000);
  server.stdout.on("data", (d) => {
    out += d.toString();
    const m = /exmap listening on (http:\/\/127\.0\.0\.1:\d+)/.exec(out);
    if (m) {
      clearTimeout(t);
      res(m[1]);
    }
  });
  server.stderr.on("data", (d) => process.stderr.write(`[server] ${d}`));
  server.once("exit", (c) => rej(new Error(`server exited early (${c})`)));
});
log(`server ${baseURL} (home ${home})`);

let exitCode = 1;
let browser = null;
try {
  const created = await fetch(`${baseURL}/api/sessions`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: "whisper-check", actor: "whisper-check" }) });
  if (created.status !== 201) throw new Error(`POST /api/sessions -> ${created.status}`);
  const { session } = await created.json();
  log(`session ${session.id}`);

  browser = await chromium.launch({
    headless: HEADLESS,
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${WAV}%noloop`, "--autoplay-policy=no-user-gesture-required"],
  });
  const context = await browser.newContext({ permissions: ["microphone"], baseURL });
  const page = await context.newPage();
  const hubRequests = [];
  page.on("request", (r) => {
    if (/huggingface\.co|hf\.co/i.test(r.url())) hubRequests.push(r.url());
  });
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") console.error(`[page:${m.type()}] ${m.text()}`);
  });
  page.on("pageerror", (e) => console.error(`[pageerror] ${e.message}`));

  // pre-accept the download notice and pin the model/dtype (the same keys the UI writes)
  await page.addInitScript(
    ({ model, dtype }) => {
      try {
        localStorage.setItem(`exmap.audio.modelSeen.${model}`, "1");
        const key = "exmap.audio.v1";
        const cur = JSON.parse(localStorage.getItem(key) || "{}");
        localStorage.setItem(key, JSON.stringify({ ...cur, provider: { remote: "local-whisper", me: "local-whisper" }, whisperModel: model, whisperDtype: dtype, whisperDevice: "auto" }));
      } catch {}
    },
    { model: MODEL, dtype: DTYPE },
  );
  await page.goto(`/?session=${encodeURIComponent(session.id)}&testhooks=1`);
  await page.getByTestId("lane-me-start").click();
  const t0 = Date.now();
  log(`model ${MODEL} (${DTYPE}); waiting for the model to load (first run downloads from huggingface.co)…`);
  await page.waitForFunction(() => {
    const s = window.__exmap?.audio?.state();
    return s && (s.model.state === "ready" || s.model.state === "error");
  }, null, { timeout: TIMEOUT_S * 1000 });
  const model = await page.evaluate(() => window.__exmap.audio.state().model);
  const loadMs = Date.now() - t0;
  if (model.state !== "ready") {
    console.error(`[whisper-check] model load failed: ${JSON.stringify(model.error)}`);
    throw new Error("MODEL_LOAD_FAILED");
  }
  log(`model ready on ${model.device} with ${model.threads ?? 1} thread(s) in ${(loadMs / 1000).toFixed(1)} s; ${hubRequests.length} request(s) to the Hub${hubRequests.length === 0 ? " (served from the browser cache)" : ""}`);

  log("waiting for the fake microphone's segments to be transcribed and posted…");
  await page.waitForFunction(() => {
    const s = window.__exmap?.audio?.state();
    return s && s.lanes.me.segmentsClosed >= 1;
  }, null, { timeout: 60_000 });
  await page.waitForFunction(() => window.__exmap.audio.pendingWork() === 0 && window.__exmap.audio.state().lanes.me.segmentsClosed >= 1, null, { timeout: 180_000 });
  await page.getByTestId("lane-me-stop").click();
  await page.evaluate(() => window.__exmap.audio.postQueueIdle());
  const backlog = await page.evaluate(() => window.__exmap.audio.state().backlog);
  const res = await fetch(`${baseURL}/api/sessions/${session.id}/events`);
  const events = res.ok ? await res.json() : null;
  const list = Array.isArray(events) ? events : (events?.events ?? []);
  const utterances = list.filter((e) => e.type === "utterance.recorded").map((e) => e.utterance).filter((u) => u.provider === "local-whisper");
  log(`segments closed: ${(await page.evaluate(() => window.__exmap.audio.state().lanes.me.segmentsClosed))}; dropped as likely hallucination: ${backlog.droppedAsHallucination}; post retries: ${backlog.postRetries}`);
  for (const u of utterances) log(`utterance ${u.id} [${u.t_start_ms}–${u.t_end_ms} ms] model=${u.model} is_local=${u.is_local}: ${JSON.stringify(u.text)}`);
  const text = utterances.map((u) => u.text).join(" ").toLowerCase();
  const found = EXPECTED_WORDS.filter((w) => text.includes(w));
  if (utterances.length === 0) {
    console.error("[whisper-check] FAIL: no local-whisper utterance reached the ledger");
  } else if (found.length < 2) {
    console.error(`[whisper-check] FAIL: the transcript does not contain at least two of ${EXPECTED_WORDS.join(", ")} (found: ${found.join(", ") || "none"})`);
  } else {
    log(`PASS: ${utterances.length} Whisper utterance(s) in the ledger; words found: ${found.join(", ")}`);
    exitCode = 0;
  }
} catch (e) {
  console.error(`[whisper-check] ${e?.stack ?? e}`);
} finally {
  if (browser) await browser.close().catch(() => undefined);
  server.kill("SIGTERM");
  await new Promise((r) => server.once("exit", r));
  if (flag("keep")) log(`kept ${home}`);
  else rmSync(home, { recursive: true, force: true });
  void pathToFileURL;
}
process.exit(exitCode);
