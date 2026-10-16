// exmap/src/web/audio/react/ModelProgress.tsx — the model download / load line (design §7.4, §7.7).
import { modelShortName } from "../settings.js";
import type { ModelStatus } from "../types.js";

export function modelProgressText(model: ModelStatus): string {
  const short = model.model ? modelShortName(model.model) : "model";
  switch (model.state) {
    case "idle":
      return "Model not loaded";
    case "awaiting_consent":
      return "Waiting for your OK to download";
    case "loading": {
      const p = model.progress;
      if (!p || p.phase === "downloading") {
        const pct = p ? Math.round(p.percent) : 0;
        const mb = (b: number) => Math.round(b / 1e6);
        return p && p.totalBytes > 0 ? `Downloading ${short} ${pct} % (${mb(p.loadedBytes)} of ${mb(p.totalBytes)} MB)` : `Downloading ${short}…`;
      }
      if (p.phase === "loading_runtime") return "Loading runtime…";
      if (p.phase === "error") return "Model load failed";
      return "Loading…";
    }
    case "ready":
      return `Ready · ${model.device ?? "?"} · ${model.threads ?? 1} thread${(model.threads ?? 1) === 1 ? "" : "s"}`;
    case "error":
      return `Model load failed: ${model.error?.message ?? model.error?.code ?? "unknown"}`;
  }
}

export function ModelProgress({ model }: { model: ModelStatus }) {
  const pct = model.state === "ready" ? 100 : model.progress ? Math.round(model.progress.percent) : 0;
  return (
    <div data-testid="model-progress" data-state={model.state} className="flex items-center gap-2 text-xs">
      <progress aria-label="Model download" max={100} value={pct} className="h-2 w-32" />
      <span aria-live="polite">{modelProgressText(model)}</span>
      {model.restarts > 0 ? <span className="opacity-70">(restarted {model.restarts}×)</span> : null}
    </div>
  );
}
