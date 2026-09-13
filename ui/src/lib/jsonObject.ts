/**
 * Validation for the two free-form JSON editors (repo `runner_opts`, run
 * `builder_config`). Both must be a JSON *object*; an empty editor means "none".
 * The builder-config rules mirror `crb.server.schemas.RunCreateRequest` so the
 * form can refuse what the server would refuse, with the same words — the
 * server remains the authority (a 422 still renders through ErrorState).
 */

export type JsonObject = Record<string, unknown>

export type JsonObjectResult = { ok: true; value: JsonObject } | { ok: false; error: string }

/** Parse editor text into a JSON object. Blank → `{}`. Arrays / scalars are refused. */
export function parseJsonObject(text: string): JsonObjectResult {
  const trimmed = text.trim()
  if (!trimmed) return { ok: true, value: {} }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch (e) {
    return { ok: false, error: `Not valid JSON: ${(e as Error).message}` }
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: 'Must be a JSON object, e.g. {"key": "value"}' }
  }
  return { ok: true, value: parsed as JsonObject }
}

const KWARG_RE = /^[a-z_][a-z0-9_]{0,63}$/
export const BUILDER_CONFIG_IDENTITY_KEYS = ['model', 'provider', 'name'] as const
export const BUILDER_CONFIG_SECRET_MARKERS = ['api_key', 'apikey', 'secret', 'token', 'password', 'passwd', 'credential'] as const
export const BUILDER_CONFIG_MAX_KEYS = 32

/** The server's `builder_config` rules, applied client-side for immediate feedback. */
export function validateBuilderConfig(cfg: JsonObject): string | undefined {
  const keys = Object.keys(cfg)
  if (keys.length > BUILDER_CONFIG_MAX_KEYS) return `At most ${BUILDER_CONFIG_MAX_KEYS} keys`
  for (const key of keys) {
    if (!KWARG_RE.test(key)) return `"${key}" is not a builder keyword (lowercase identifier)`
    if ((BUILDER_CONFIG_IDENTITY_KEYS as readonly string[]).includes(key)) {
      return `"${key}" is the rung's recorded identity — set it on the ladder, not here`
    }
    if (BUILDER_CONFIG_SECRET_MARKERS.some((m) => key.includes(m))) {
      return `"${key}" looks like a credential — provider keys come from the worker's environment`
    }
  }
  return undefined
}

/** Parse + validate a builder-config editor. */
export function parseBuilderConfig(text: string): JsonObjectResult {
  const r = parseJsonObject(text)
  if (!r.ok) return r
  const error = validateBuilderConfig(r.value)
  return error ? { ok: false, error } : r
}

/** Pretty JSON for pre-filling an editor (`{}` → empty text, so "none" stays visibly none). */
export function formatJsonObject(value: JsonObject): string {
  return Object.keys(value).length ? JSON.stringify(value, null, 2) : ''
}
