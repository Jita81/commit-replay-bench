// exmap/src/web/api/client.ts — ApiClient (every route of design §8) and ApiError. Every non-2xx answer becomes an
// ApiError carrying the server's ErrorBody (reason, detail, checks, signoff); the UI never invents its own shapes.
import type {
  ActResponse, CardPatch, ClarificationAnswer, ConfigResponse, DodCheckId, DodReport, ExmapEvent, ExportFile, ExportOptions,
  ExportOptionsInput, ExportRefusal, MapState, NewCard, Sha256Hex, SessionSummary, Signoff, Utterance, UtterancePostResponse,
} from "../../core/types.js";

export class ApiError extends Error {
  readonly status: number;
  readonly reason: string;
  readonly detail: string;
  readonly checks?: DodReport;
  readonly signoff?: ExportRefusal["signoff"];
  constructor(status: number, body: { reason: string; detail: string; checks?: DodReport; signoff?: ExportRefusal["signoff"] }) {
    super(`${status} ${body.reason}: ${body.detail}`);
    this.name = "ApiError";
    this.status = status;
    this.reason = body.reason;
    this.detail = body.detail;
    if (body.checks) this.checks = body.checks;
    if (body.signoff) this.signoff = body.signoff;
  }
}

/** The vendored crb catalogue as `GET /api/catalogue` serves it (the JSON file verbatim). */
export interface CatalogueSlot {
  name: string;
  question: string;
  kind: "structural" | "value";
}
export interface CatalogueResponse {
  _source?: string;
  _source_commit?: string;
  _copied?: string;
  classes: Record<string, CatalogueSlot[]>;
}

export interface SessionDetail {
  session: SessionSummary;
  dod: DodReport;
  signoff: Signoff | null;
  export_options: ExportOptions | null;
}
export interface EventsPage {
  events: ExmapEvent[];
  head: { seq: number; hash: Sha256Hex | "" };
  has_more: boolean;
}
export interface SettingsBody {
  user_name: string;
}
export type ClarificationWireAnswer = Exclude<ClarificationAnswer, { kind: "text" }> | { kind: "text"; text: string };
export type ExportOptionsBody = Omit<ExportOptionsInput, "by">;
export interface ExportOptionsResponse {
  ok: true;
  events: ExmapEvent[];
  export_options: ExportOptions;
}
export interface ClarificationAnswerResponse {
  ok: true;
  events: ExmapEvent[];
  utterance_id?: string;
  resolved?: boolean;
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

const JSON_HEADERS = { "content-type": "application/json", accept: "application/json" };

async function parseError(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => "");
  try {
    const body = JSON.parse(text) as { reason?: unknown; detail?: unknown; checks?: DodReport; signoff?: ExportRefusal["signoff"] };
    if (body && typeof body === "object" && typeof body.reason === "string") {
      return new ApiError(res.status, {
        reason: body.reason,
        detail: typeof body.detail === "string" ? body.detail : "",
        ...(body.checks ? { checks: body.checks } : {}),
        ...(body.signoff ? { signoff: body.signoff } : {}),
      });
    }
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, { reason: `HTTP_${res.status}`, detail: text.slice(0, 200) || res.statusText || "request failed" });
}

/** Every route of §8.3–§8.6 as one method each; `session(id)` binds the per-session ones. */
export class ApiClient {
  readonly baseUrl: string;
  readonly #fetch: FetchLike;

  constructor(baseUrl = "", fetchFn?: FetchLike) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.#fetch = fetchFn ?? ((input, init) => fetch(input, init));
  }

  async #json<T>(method: string, path: string, body?: unknown): Promise<T> {
    const init: RequestInit = { method, headers: JSON_HEADERS };
    if (body !== undefined) init.body = JSON.stringify(body);
    const res = await this.#fetch(`${this.baseUrl}${path}`, init);
    if (!res.ok) throw await parseError(res);
    return (await res.json()) as T;
  }

  async #text(path: string): Promise<string> {
    const res = await this.#fetch(`${this.baseUrl}${path}`, { method: "GET" });
    if (!res.ok) throw await parseError(res);
    return res.text();
  }

  /* ───── meta ───── */
  health(): Promise<{ app: string; version: string; ok?: boolean; pid?: number }> {
    return this.#json("GET", "/api/health");
  }
  config(): Promise<ConfigResponse> {
    return this.#json("GET", "/api/config");
  }
  getSettings(): Promise<SettingsBody> {
    return this.#json("GET", "/api/settings");
  }
  putSettings(user_name: string): Promise<SettingsBody> {
    return this.#json("PUT", "/api/settings", { user_name });
  }
  catalogue(): Promise<CatalogueResponse> {
    return this.#json("GET", "/api/catalogue");
  }

  /* ───── sessions ───── */
  listSessions(): Promise<{ sessions: SessionSummary[] }> {
    return this.#json("GET", "/api/sessions");
  }
  createSession(body: { title: string; actor?: string; story?: string }): Promise<{ session: SessionSummary }> {
    return this.#json("POST", "/api/sessions", body);
  }
  getSession(id: string): Promise<SessionDetail> {
    return this.#json("GET", `/api/sessions/${encodeURIComponent(id)}`);
  }
  events(id: string, after = 0, limit = 2000): Promise<EventsPage> {
    return this.#json("GET", `/api/sessions/${encodeURIComponent(id)}/events?after=${after}&limit=${limit}`);
  }
  state(id: string): Promise<{ state: MapState }> {
    return this.#json("GET", `/api/sessions/${encodeURIComponent(id)}/state`);
  }

  /* ───── utterances ───── */
  postUtterance(id: string, utterance: Utterance, wait = false): Promise<UtterancePostResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/utterances${wait ? "?wait=1" : ""}`, utterance);
  }

  /* ───── human acts (§8.5) ───── */
  acceptProposal(id: string, pid: string, actor: string): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/proposals/${encodeURIComponent(pid)}/accept`, { actor });
  }
  rejectProposal(id: string, pid: string, actor: string): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/proposals/${encodeURIComponent(pid)}/reject`, { actor });
  }
  answerClarification(id: string, cid: string, actor: string, answer: ClarificationWireAnswer, wait = false): Promise<ClarificationAnswerResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/clarifications/${encodeURIComponent(cid)}/answer${wait ? "?wait=1" : ""}`, { actor, answer });
  }
  createCard(id: string, actor: string, card: NewCard): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/cards`, { actor, card });
  }
  confirmCard(id: string, cardId: string, actor: string): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/cards/${encodeURIComponent(cardId)}/confirm`, { actor });
  }
  removeCard(id: string, cardId: string, actor: string): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/cards/${encodeURIComponent(cardId)}/remove`, { actor });
  }
  updateCard(id: string, cardId: string, actor: string, patch: CardPatch): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/cards/${encodeURIComponent(cardId)}/update`, { actor, patch });
  }
  acceptQuestion(id: string, questionId: string, actor: string, reason: string): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/questions/${encodeURIComponent(questionId)}/accept-outstanding`, { actor, reason });
  }
  undo(id: string, actor: string, to_revision_seq: number | null = null): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/undo`, { actor, to_revision_seq });
  }
  reviewChecks(id: string, actor: string, check_id: DodCheckId, card_ids: string[]): Promise<ActResponse & { card_ids?: string[] }> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/review/checks`, { actor, check_id, card_ids });
  }
  signoff(id: string, reviewer: string, statement: string, revision_hash: Sha256Hex): Promise<ActResponse> {
    return this.#json("POST", `/api/sessions/${encodeURIComponent(id)}/signoff`, { reviewer, statement, revision_hash });
  }
  putExportOptions(id: string, actor: string, options: ExportOptionsBody): Promise<ExportOptionsResponse> {
    return this.#json("PUT", `/api/sessions/${encodeURIComponent(id)}/export-options`, { actor, ...options });
  }

  /* ───── export (§8.6) ───── */
  exportUrl(id: string, file: ExportFile, draft: boolean): string {
    return `${this.baseUrl}/api/sessions/${encodeURIComponent(id)}/export/${file}?draft=${draft ? "true" : "false"}`;
  }
  exportText(id: string, file: ExportFile, draft: boolean): Promise<string> {
    return this.#text(`/api/sessions/${encodeURIComponent(id)}/export/${file}?draft=${draft ? "true" : "false"}`);
  }

  /** The per-session routes bound to one id (what the session screen's components consume). */
  session(id: string): SessionApi {
    return {
      sessionId: id,
      get: () => this.getSession(id),
      events: (after, limit) => this.events(id, after, limit),
      postUtterance: (u, wait) => this.postUtterance(id, u, wait),
      acceptProposal: (pid, actor) => this.acceptProposal(id, pid, actor),
      rejectProposal: (pid, actor) => this.rejectProposal(id, pid, actor),
      answerClarification: (cid, actor, answer, wait) => this.answerClarification(id, cid, actor, answer, wait),
      createCard: (actor, card) => this.createCard(id, actor, card),
      confirmCard: (cardId, actor) => this.confirmCard(id, cardId, actor),
      removeCard: (cardId, actor) => this.removeCard(id, cardId, actor),
      updateCard: (cardId, actor, patch) => this.updateCard(id, cardId, actor, patch),
      acceptQuestion: (qid, actor, reason) => this.acceptQuestion(id, qid, actor, reason),
      undo: (actor, to) => this.undo(id, actor, to),
      reviewChecks: (actor, check_id, card_ids) => this.reviewChecks(id, actor, check_id, card_ids),
      signoff: (reviewer, statement, revision_hash) => this.signoff(id, reviewer, statement, revision_hash),
      putExportOptions: (actor, options) => this.putExportOptions(id, actor, options),
      exportUrl: (file, draft) => this.exportUrl(id, file, draft),
      exportText: (file, draft) => this.exportText(id, file, draft),
      catalogue: () => this.catalogue(),
      config: () => this.config(),
    };
  }
}

/** The session-bound view of ApiClient; tests pass a fake with the same names. */
export interface SessionApi {
  readonly sessionId: string;
  get(): Promise<SessionDetail>;
  events(after?: number, limit?: number): Promise<EventsPage>;
  postUtterance(u: Utterance, wait?: boolean): Promise<UtterancePostResponse>;
  acceptProposal(pid: string, actor: string): Promise<ActResponse>;
  rejectProposal(pid: string, actor: string): Promise<ActResponse>;
  answerClarification(cid: string, actor: string, answer: ClarificationWireAnswer, wait?: boolean): Promise<ClarificationAnswerResponse>;
  createCard(actor: string, card: NewCard): Promise<ActResponse>;
  confirmCard(cardId: string, actor: string): Promise<ActResponse>;
  removeCard(cardId: string, actor: string): Promise<ActResponse>;
  updateCard(cardId: string, actor: string, patch: CardPatch): Promise<ActResponse>;
  acceptQuestion(questionId: string, actor: string, reason: string): Promise<ActResponse>;
  undo(actor: string, to_revision_seq?: number | null): Promise<ActResponse>;
  reviewChecks(actor: string, check_id: DodCheckId, card_ids: string[]): Promise<ActResponse & { card_ids?: string[] }>;
  signoff(reviewer: string, statement: string, revision_hash: Sha256Hex): Promise<ActResponse>;
  putExportOptions(actor: string, options: ExportOptionsBody): Promise<ExportOptionsResponse>;
  exportUrl(file: ExportFile, draft: boolean): string;
  exportText(file: ExportFile, draft: boolean): Promise<string>;
  catalogue(): Promise<CatalogueResponse>;
  config(): Promise<ConfigResponse>;
}
