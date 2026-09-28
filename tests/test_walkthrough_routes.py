"""Every screen the app routes to is in the walkthrough's sweep of every route.

``11-screens.spec.ts``'s ``routes()`` is the list the walkthrough renders for every persona at
375 and 1280 px, captures, checks for its About block and sweeps with axe (WCAG 2.1 AA). A
route added to ``ui/src/App.tsx`` but not to that list is never swept: ``/classes`` shipped
that way, with a link inside running text told apart by colour alone (axe
``link-in-text-block``), and its accessibility criterion read met on a spec that never opened
it (docs/PREVENTION.md P-687).

Navigation
----------
What it is:   A source gate over ui/src/App.tsx (the route table) and
              ui/e2e/walkthrough/11-screens.spec.ts (``routes()``, the sweep's list).
What it does: Fails, naming the route, when a route inside the authenticated shell has no
              path in ``routes()`` that it matches (``:name`` segments match any segment; the
              catch-all ``*`` is the 404, swept as ``/nowhere/at/all``); a negative control pins
              that a route missing from the list is caught.
How:          Text scan of the two TypeScript sources; no browser, no stack.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/src/App.tsx (the routes), ui/e2e/walkthrough/11-screens.spec.ts (the sweep),
              ui/e2e/axe.ts (the scan it runs), docs/PREVENTION.md (P-687)
Tested by:    (this is a test file)
Touch when:   onboarding a client repository never needs it; a screen is added to the app (add
              its route to ``routes()`` in 11-screens with a slug, in the same change).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "ui" / "src" / "App.tsx"
SCREENS = ROOT / "ui" / "e2e" / "walkthrough" / "11-screens.spec.ts"
#: Routes outside the authenticated shell (no persona sweep applies) and the catch-all.
OUTSIDE = {"/login", "/invite", "*"}


def app_routes(src: str) -> list[str]:
    return [p for p in re.findall(r'<Route\s+path="([^"]+)"', src) if p not in OUTSIDE]


def swept_paths(src: str) -> list[str]:
    body = re.search(r"function routes\(c: Ctx\)(?P<body>.*?)\n}\n", src, re.S)
    assert body, "11-screens.spec.ts no longer has routes(c: Ctx)"
    literals = re.findall(r"'(/[^']*)'|`(/[^`]*)`", body.group("body"))
    return [re.sub(r"\$\{[^}]*\}", "x", a or b) for a, b in literals]


def unswept(routes: list[str], swept: list[str]) -> list[str]:
    def pattern(route: str) -> re.Pattern[str]:
        parts = [("[^/]+" if seg.startswith(":") else re.escape(seg)) for seg in route.split("/")]
        return re.compile("/".join(parts) + r"$")

    return [r for r in routes if not any(pattern(r).match(p) for p in swept)]


def test_every_routed_screen_is_in_the_walkthroughs_sweep() -> None:
    routes = app_routes(APP.read_text(encoding="utf-8"))
    swept = swept_paths(SCREENS.read_text(encoding="utf-8"))
    assert "/classes" in routes and len(routes) > 20, "the route table was not read"
    missing = unswept(routes, swept)
    assert missing == [], (
        f"add these routes to routes() in ui/e2e/walkthrough/11-screens.spec.ts: {missing}"
    )


def test_the_gate_catches_a_route_missing_from_the_sweep() -> None:
    swept = swept_paths(SCREENS.read_text(encoding="utf-8"))
    assert unswept(["/classes", "/library/:repo", "/nowhere-yet"], swept) == ["/nowhere-yet"]
    assert unswept(["/library/:repo"], ["/library"]) == ["/library/:repo"]
