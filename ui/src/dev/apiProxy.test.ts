// @vitest-environment node
/**
 * apiProxy.ts and its wiring in vite.config.ts — a request that reached the dev or preview
 * server from another machine never looks, to the API, like a browser on this one.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Vite dev / preview proxy's forwarding mark (ADR-0027).
 * What it does: Pins that `isLoopbackAddress` admits only 127.0.0.0/8, ::1 and their IPv4-mapped
 *               form; that `markOffMachineRequest` adds `X-Forwarded-For` for any other client
 *               address (and for a missing one) and leaves a loopback client's headers alone;
 *               and that the real `ui/vite.config.ts`, loaded the way Vite loads it, registers
 *               the mark on the `/api` proxy's `start` event and does not give `vite preview` a
 *               proxy of its own that would skip it.
 * How:          `loadConfigFromFile` on the real config, then its `configure` hook driven with
 *               a stand-in proxy (records and emits events) and stand-in requests.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0027-dev-autologin-on-loopback.md
 * Works with:   ui/src/dev/apiProxy.ts, ui/vite.config.ts, src/crb/server/auth.py
 *               (`dev_autologin_refusal`, which refuses any request carrying the header)
 * Tested by:    ui/src/dev/apiProxy.test.ts
 * Touch when:   the dev proxy changes; never to drop the mark for a client that is not on
 *               this machine.
 */
import { loadConfigFromFile } from 'vite'
import type { ProxyOptions } from 'vite'
import { describe, expect, it } from 'vitest'
import { isLoopbackAddress, markOffMachineRequest, type IncomingLike } from './apiProxy'

/** A stand-in for the proxy server Vite hands `configure`: it only records and emits events. */
function fakeProxy() {
  const handlers = new Map<string, ((...args: unknown[]) => void)[]>()
  return {
    on(event: string, fn: (...args: unknown[]) => void) {
      handlers.set(event, [...(handlers.get(event) ?? []), fn])
      return this
    },
    emit(event: string, ...args: unknown[]) {
      for (const fn of handlers.get(event) ?? []) fn(...args)
    },
  }
}

function request(remoteAddress: string | undefined, headers: IncomingLike['headers'] = {}): IncomingLike {
  return { socket: { remoteAddress }, headers: { host: 'localhost:5173', ...headers } }
}

describe('isLoopbackAddress', () => {
  it.each(['127.0.0.1', '127.0.0.9', '::1', '::ffff:127.0.0.1'])('admits %s', (a) => {
    expect(isLoopbackAddress(a)).toBe(true)
  })
  it.each(['192.168.1.20', '10.0.0.5', '::ffff:192.168.1.20', 'fe80::1%lo0', '0.0.0.0', '::', '', undefined, '127.0.0.1.evil'])(
    'refuses %s',
    (a) => {
      expect(isLoopbackAddress(a)).toBe(false)
    },
  )
})

describe('markOffMachineRequest', () => {
  it('adds X-Forwarded-For for a client on another machine', () => {
    const req = request('192.168.1.50')
    markOffMachineRequest(req)
    expect(req.headers['x-forwarded-for']).toBe('192.168.1.50')
  })

  it('appends to a forwarding header the client sent itself', () => {
    const req = request('192.168.1.50', { 'x-forwarded-for': '127.0.0.1' })
    markOffMachineRequest(req)
    expect(req.headers['x-forwarded-for']).toBe('127.0.0.1, 192.168.1.50')
  })

  it('marks a request whose client address is unknown', () => {
    const req: IncomingLike = { socket: null, headers: {} }
    markOffMachineRequest(req)
    expect(req.headers['x-forwarded-for']).toBe('unknown')
  })

  it.each(['127.0.0.1', '::1', '::ffff:127.0.0.1'])('leaves a browser on this machine (%s) alone', (a) => {
    const req = request(a)
    markOffMachineRequest(req)
    expect(req.headers).toEqual({ host: 'localhost:5173' })
  })
})

describe('ui/vite.config.ts', () => {
  async function apiProxy(command: 'serve' | 'build') {
    const loaded = await loadConfigFromFile(
      { command, mode: 'development', isPreview: command === 'serve' ? false : undefined },
      new URL('../../vite.config.ts', import.meta.url).pathname,
    )
    if (!loaded) throw new Error('vite.config.ts did not load')
    return loaded.config
  }

  it('marks a request that reached the /api proxy from another machine', async () => {
    const config = await apiProxy('serve')
    const route = config.server?.proxy?.['/api'] as ProxyOptions
    expect(route.xfwd).not.toBe(false)
    const proxy = fakeProxy()
    route.configure?.(proxy as never, route)

    const remote = request('192.168.1.50')
    proxy.emit('start', remote, {}, new URL('http://127.0.0.1:8000'))
    expect(remote.headers['x-forwarded-for']).toBe('192.168.1.50')

    const local = request('127.0.0.1')
    proxy.emit('start', local, {}, new URL('http://127.0.0.1:8000'))
    expect(local.headers['x-forwarded-for']).toBeUndefined()
  })

  it('gives vite preview no proxy of its own, so it inherits the marked one', async () => {
    const config = await apiProxy('serve')
    expect(config.preview?.proxy).toBeUndefined()
  })
})
