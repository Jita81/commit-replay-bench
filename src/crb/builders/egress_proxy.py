"""The builder's only route out: a CONNECT-only, allowlisting egress proxy.

This file is **standalone** — standard library only, no ``crb`` imports — because it
runs inside the proxy sidecar container (ADR-0012), where the crb package is not
installed. :mod:`crb.builders.container` copies it next to the sealed checkout and
bind-mounts it read-only; the sidecar runs::

    python3 egress_proxy.py --listen 0.0.0.0:3128 --allow api.anthropic.com

Policy, stated so it can be checked against the code:

* Only ``CONNECT host:port`` is served (:meth:`_Handler.handle`). Plain ``GET``/``POST``
  through the proxy is refused with ``405``: the model endpoints are TLS, and a
  tunnel is the only shape that cannot be used to smuggle a request to a host the
  allowlist did not name.
* ``host`` must equal an allowlist entry exactly (case-insensitive, trailing dot
  stripped; no wildcards, no suffix matching) and ``port`` must be the entry's port
  (``443`` unless written ``host:port``). Anything else is ``403`` — logged as
  ``deny host:port`` with nothing from the request beyond that.
* The upstream connection is made by the proxy, so the builder container never
  needs DNS or a default route: it lives on an ``--internal`` network whose only
  other member is this sidecar.
* Nothing that flows through a tunnel is logged; the proxy cannot see inside TLS
  and does not try.

``READY <host>:<port>`` is printed (and flushed) once the listener is bound — the
worker treats a sidecar that has not printed it within its start timeout as
unhealthy and fails the build closed.

Navigation
----------
What it is:   The egress-proxy sidecar's program — a standalone, stdlib-only CONNECT proxy
              with an exact-match host:port allowlist — plus the pure ``parse_allow`` /
              ``decide`` functions the worker validates settings with.
What it does: Serves ``CONNECT`` to allowlisted hosts only (``403`` otherwise, ``405`` for any
              other method), opens the upstream itself so the builder needs no DNS or
              default route, pumps bytes both ways until close or idle, logs decisions but
              never tunnel contents, and prints ``READY`` once bound.
How:          ``parse_allow`` (normalise, refuse malformed) → ``EgressProxy`` (threading TCP
              server) → ``_Handler.handle``: read the request line, drain headers,
              ``decide`` → connect upstream → ``200`` → ``_pump`` over a selector.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/builders/container.py (copies this file beside the checkout, mounts
              it read-only, runs it in the sidecar and waits for ``READY``; validates the
              allowlist with ``parse_allow`` before any container starts),
              deploy/Dockerfile.builder (the image the sidecar runs on — it needs only
              ``python3``), docs/DEPLOYMENT.md (``CRB_BUILDER__ALLOW_HOSTS``)
Tested by:    tests/test_builders_container.py, tests/test_builders_container_docker.py
Touch when:   a model endpoint on a new host is an allowlist entry
              (``CRB_BUILDER__ALLOW_HOSTS``), never an edit here; any change to what is
              served must keep this file free of ``crb`` imports — it runs where the package
              is not installed — and needs a loopback test on a real socket.
"""

from __future__ import annotations

import argparse
import contextlib
import selectors
import socket
import socketserver
import sys
import threading

DEFAULT_PORT = 443
IDLE_TIMEOUT_S = 300.0
CONNECT_TIMEOUT_S = 15.0
_MAX_HEADER_BYTES = 16 * 1024


def parse_allow(entries: list[str] | tuple[str, ...]) -> dict[str, int]:
    """``["api.anthropic.com", "mock:8443"]`` → ``{"api.anthropic.com": 443, "mock": 8443}``.

    Entries are normalised the way :func:`normalise_host` normalises request hosts;
    an empty or malformed entry is a ``ValueError`` (a typo must not become "allow
    nothing" silently — the worker validates before the sidecar starts).
    """
    out: dict[str, int] = {}
    for raw in entries:
        entry = str(raw).strip()
        if not entry:
            raise ValueError("empty allowlist entry")
        host, _, port_s = entry.rpartition(":")
        if not host:
            host, port_s = entry, ""
        port = int(port_s) if port_s else DEFAULT_PORT
        if not (0 < port < 65536):
            raise ValueError(f"allowlist entry {entry!r}: port out of range")
        norm = normalise_host(host)
        if not norm or any(c in norm for c in " /\\@?#*"):
            raise ValueError(f"allowlist entry {entry!r}: not a plain hostname")
        out[norm] = port
    return out


def normalise_host(host: str) -> str:
    """Lower-case, no surrounding whitespace, no trailing dot (``Mock.Local.`` → ``mock.local``)."""
    return host.strip().lower().rstrip(".")


def decide(allow: dict[str, int], target: str) -> tuple[bool, str, int]:
    """``(allowed, host, port)`` for a CONNECT target such as ``api.anthropic.com:443``."""
    host, sep, port_s = target.rpartition(":")
    if not sep or not host or not port_s.isdigit():
        return False, normalise_host(target), 0
    if host.startswith("[") and host.endswith("]"):  # IPv6 literal — never allowlisted
        return False, host, int(port_s)
    norm = normalise_host(host)
    port = int(port_s)
    return (allow.get(norm) == port), norm, port


class _Handler(socketserver.StreamRequestHandler):
    """One client connection: exactly one ``CONNECT`` decision, then a tunnel or a refusal."""

    server: EgressProxy  # narrowed for mypy; assigned by socketserver
    #: UNBUFFERED reads: a buffered ``rfile`` may read past the blank header line into the
    #: first TLS bytes the client sends after ``CONNECT`` (an eager client), and ``_pump``
    #: reads the raw socket, so those bytes would be lost and the handshake would hang
    #: (CodeRabbit on PR #3, 2026-09-15). Header reads are a few hundred bytes; byte-wise
    #: is fine.
    rbufsize = 0

    def handle(self) -> None:
        """Read the request line, drain the headers unread, decide, tunnel."""
        request = self.connection
        request.settimeout(CONNECT_TIMEOUT_S)
        try:
            line = self.rfile.readline(_MAX_HEADER_BYTES)
            # drain the headers; nothing in them is used
            while True:
                hdr = self.rfile.readline(_MAX_HEADER_BYTES)
                if hdr in (b"\r\n", b"\n", b""):
                    break
        except (OSError, ValueError):
            return
        parts = line.decode("latin-1", "replace").strip().split()
        if len(parts) < 2:
            self._reply(400, "Bad Request")
            return
        method, target = parts[0].upper(), parts[1]
        if method != "CONNECT":
            self.server.log(f"deny method={method}")
            self._reply(405, "Method Not Allowed")
            return
        allowed, host, port = decide(self.server.allow, target)
        if not allowed:
            self.server.log(f"deny {host}:{port}")
            self._reply(403, "Forbidden")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S)
        except OSError as exc:
            self.server.log(f"upstream-unreachable {host}:{port} {type(exc).__name__}")
            self._reply(502, "Bad Gateway")
            return
        self.server.log(f"allow {host}:{port}")
        try:
            request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            _pump(request, upstream)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                upstream.close()

    def _reply(self, code: int, reason: str) -> None:
        """A minimal HTTP/1.1 error response with ``Connection: close``."""
        body = f"{code} {reason}\n".encode()
        with contextlib.suppress(OSError):
            self.connection.sendall(
                f"HTTP/1.1 {code} {reason}\r\nContent-Type: text/plain\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )


def _pump(a: socket.socket, b: socket.socket) -> None:
    """Copy bytes both ways until either side closes or the tunnel idles out."""
    a.settimeout(None)
    b.settimeout(None)
    a.setblocking(False)
    b.setblocking(False)
    peers = {a: b, b: a}
    with selectors.DefaultSelector() as sel:
        sel.register(a, selectors.EVENT_READ)
        sel.register(b, selectors.EVENT_READ)
        while peers:
            events = sel.select(IDLE_TIMEOUT_S)
            if not events:
                return
            for key, _ in events:
                src = key.fileobj
                assert isinstance(src, socket.socket)
                dst = peers.get(src)
                if dst is None:
                    continue
                try:
                    data = src.recv(65536)
                except BlockingIOError:
                    continue
                except OSError:
                    data = b""
                if not data:
                    return
                dst.setblocking(True)
                try:
                    dst.sendall(data)
                except OSError:
                    return
                finally:
                    dst.setblocking(False)


class EgressProxy(socketserver.ThreadingTCPServer):
    """Bind, serve, log to stdout. ``allow`` is the parsed allowlist."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, listen: tuple[str, int], allow: dict[str, int], *, quiet: bool = False):
        self.allow = dict(allow)
        self.quiet = quiet
        self._log_lock = threading.Lock()
        super().__init__(listen, _Handler)

    def log(self, line: str) -> None:
        """One decision line to stdout (the worker keeps the tail in ``proxy_log``)."""
        if self.quiet:
            return
        with self._log_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    """The sidecar entry point: ``--listen host:port --allow host[:port] …``; an empty
    allowlist is refused (the worker never starts a sidecar with one either)."""
    p = argparse.ArgumentParser(description="CONNECT-only allowlisting egress proxy")
    p.add_argument("--listen", default="0.0.0.0:3128", help="host:port to bind")
    p.add_argument(
        "--allow",
        action="append",
        default=[],
        help="allowed host[:port] (repeatable; comma-separated accepted); port defaults to 443",
    )
    args = p.parse_args(argv)
    entries = [e for chunk in args.allow for e in str(chunk).split(",") if e.strip()]
    if not entries:
        p.error("at least one --allow entry is required (an empty allowlist is a stopped run)")
    host, _, port_s = args.listen.rpartition(":")
    allow = parse_allow(entries)
    with EgressProxy((host or "0.0.0.0", int(port_s)), allow) as server:  # noqa: S104
        bound_host, bound_port = server.server_address[0], server.server_address[1]
        sys.stdout.write(f"READY {bound_host!s}:{bound_port} allow={','.join(sorted(allow))}\n")
        sys.stdout.flush()
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
