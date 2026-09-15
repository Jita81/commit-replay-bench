/**
 * ui/src/lib/jsonObject.ts — the JSON-object editors' parser and the builder-config rules.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for `parseJsonObject`, `validateBuilderConfig`, `parseBuilderConfig`
 *               and `formatJsonObject`.
 * What it does: Pins that blank text is `{}`, that arrays / scalars / invalid JSON are refused
 *               with a readable reason, that the builder-config rules refuse identity keys,
 *               credential-shaped keys, non-identifier keys and more than 32 keys with the
 *               server's wording, and that `{}` formats back to empty text.
 * How:          Table-driven `it.each` over the refusal cases; direct calls otherwise.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/jsonObject.ts (the code under test), src/crb/server/schemas.py (the
 *               server rules these cases must agree with)
 * Tested by:    ui/src/lib/jsonObject.test.ts
 * Touch when:   a rule is added on the server (src/crb/server/schemas.py) — add the case here
 *               and the check in ui/src/lib/jsonObject.ts together.
 */
import { describe, expect, it } from 'vitest'
import { formatJsonObject, parseBuilderConfig, parseJsonObject, validateBuilderConfig } from './jsonObject'

describe('parseJsonObject', () => {
  it('treats blank as an empty object', () => {
    expect(parseJsonObject('')).toEqual({ ok: true, value: {} })
    expect(parseJsonObject('   \n ')).toEqual({ ok: true, value: {} })
  })
  it('accepts an object and keeps nested values', () => {
    expect(parseJsonObject('{"pip": ["pytest", "-r", "req.txt"], "pythonpath_suffix": "/src"}')).toEqual({
      ok: true,
      value: { pip: ['pytest', '-r', 'req.txt'], pythonpath_suffix: '/src' },
    })
  })
  it('refuses invalid JSON with the parser message', () => {
    const r = parseJsonObject('{"a": }')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(/Not valid JSON/)
  })
  it.each(['[1, 2]', '"str"', '42', 'null', 'true'])('refuses a non-object (%s)', (text) => {
    const r = parseJsonObject(text)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(/JSON object/)
  })
})

describe('validateBuilderConfig (mirrors the server rules)', () => {
  it('accepts builder keywords', () => {
    expect(validateBuilderConfig({ auth: 'cli', effort: 'high', extra_args: ['--x'], keep_transcript: true })).toBeUndefined()
  })
  it.each([
    [{ model: 'x' }, /recorded identity/],
    [{ provider: 'x' }, /recorded identity/],
    [{ name: 'x' }, /recorded identity/],
    [{ api_key: 'sk' }, /credential/],
    [{ anthropic_api_key: 'sk' }, /credential/],
    [{ access_token: 'x' }, /credential/],
    [{ Effort: 'high' }, /not a builder keyword/],
    [{ 'bad-key': 1 }, /not a builder keyword/],
    [Object.fromEntries(Array.from({ length: 33 }, (_, i) => [`k${i}`, i])), /At most 32/],
  ])('refuses %j', (cfg, re) => {
    expect(validateBuilderConfig(cfg as Record<string, unknown>)).toMatch(re)
  })
  it('parseBuilderConfig combines both checks', () => {
    expect(parseBuilderConfig('')).toEqual({ ok: true, value: {} })
    expect(parseBuilderConfig('{"auth": "cli"}')).toEqual({ ok: true, value: { auth: 'cli' } })
    expect(parseBuilderConfig('{"model": "x"}').ok).toBe(false)
    expect(parseBuilderConfig('nope').ok).toBe(false)
  })
})

describe('formatJsonObject', () => {
  it('renders {} as empty text and pretty-prints otherwise', () => {
    expect(formatJsonObject({})).toBe('')
    expect(formatJsonObject({ a: 1 })).toBe('{\n  "a": 1\n}')
  })
})
