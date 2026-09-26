/**
 * The Vite dev / preview proxy's forwarding mark — a request that reached `npm run dev` or
 * `vite preview` from another machine reaches the API marked as proxied (ADR-0027).
 *
 * Navigation
 * ----------
 * What it is:   `markOffMachineRequest`, the hook `ui/vite.config.ts` runs on every `/api`
 *               request its proxy is about to forward, and `isLoopbackAddress`, the test it uses.
 * What it does: The proxy connects to the API from 127.0.0.1 and, with `xfwd` off, adds no
 *               forwarding header, so without this mark a request from another machine (the
 *               dev server started with `--host`) would look to the API like a browser on
 *               this one — enough to be signed in automatically. When the client address is
 *               not loopback, or is unknown, it appends that address to `X-Forwarded-For`,
 *               which the API's automatic sign-in refuses. A loopback client is left alone.
 * How:          Runs on the proxy's `start` event, before the proxy copies the incoming headers
 *               into the outgoing request, so the header is set on the request itself rather
 *               than on one whose headers may already be sent.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0027-dev-autologin-on-loopback.md
 * Works with:   ui/vite.config.ts (registers it), src/crb/server/auth.py
 *               (`dev_autologin_refusal` refuses any request carrying a forwarding header),
 *               docs/SECURITY.md#38-automatic-sign-in-on-a-development-stack
 * Tested by:    ui/src/dev/apiProxy.test.ts
 * Touch when:   the dev proxy changes; never to drop the mark for a client that is not on this
 *               machine.
 */

/** The parts of Node's incoming request the mark reads and writes. */
export interface IncomingLike {
  socket?: { remoteAddress?: string | undefined } | null
  headers: Record<string, string | string[] | undefined>
}

const IPV4_LOOPBACK = /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/

/** Whether a socket's client address is this machine: 127.0.0.0/8, ::1 or IPv4-mapped 127.x. */
export function isLoopbackAddress(address: string | undefined): boolean {
  if (!address) return false
  const a = address.toLowerCase()
  if (a === '::1') return true
  return IPV4_LOOPBACK.test(a.startsWith('::ffff:') ? a.slice('::ffff:'.length) : a)
}

/** Append the client address to `X-Forwarded-For` unless the client is on this machine. */
export function markOffMachineRequest(req: IncomingLike): void {
  const address = req.socket?.remoteAddress
  if (isLoopbackAddress(address)) return
  const existing = req.headers['x-forwarded-for']
  const sent = Array.isArray(existing) ? existing.join(', ') : existing
  const client = address || 'unknown'
  req.headers['x-forwarded-for'] = sent ? `${sent}, ${client}` : client
}
