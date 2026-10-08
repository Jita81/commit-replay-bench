"""Every screen the app routes to is in the walkthrough's sweep of every route.

``11-screens.spec.ts``'s ``routes()`` is the list the walkthrough renders for every persona at
375 and 1280 px, captures, checks for its About block and sweeps with axe (WCAG 2.1 AA). A
route added to ``ui/src/App.tsx`` but not to that list is never swept: ``/classes`` shipped
that way, with a link inside running text told apart by colour alone (axe
``link-in-text-block``), and its accessibility criterion read met on a spec that never opened
it (docs/PREVENTION.md P-687).

Navigation
----------
What it is:   A source gate over ui/src/App.tsx (the route table),
              ui/e2e/walkthrough/11-screens.spec.ts (``routes()``, the sweep's list) and
              ui/e2e/walkthrough/15-classes.spec.ts (``CLASS_SAMPLE_MINE``), and every spec
              under ui/e2e (its tests' time limits).
What it does: Fails, naming the route, when a route inside the authenticated shell has no
              path in ``routes()`` that it matches (``:name`` segments match any segment; the
              catch-all ``*`` is the 404, swept as ``/nowhere/at/all``); a negative control pins
              that a route missing from the list is caught. Also fails when spec 15 mines too
              few commits for its labelling sample: the fixture's commit ids change every run,
              so a small sample offered nothing to label about 1 run in 5. And fails when a
              test that walks a list a function builds, as 11-screens walks ``routes()``, has a
              time limit not computed from that list: a fixed one fell over when two routes
              were added (P-771).
How:          Text scan of the TypeScript sources; the chance from the class sets' split and
              example shares; no browser, no stack.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/src/App.tsx (the routes), ui/e2e/walkthrough/11-screens.spec.ts (the sweep),
              ui/e2e/axe.ts (the scan it runs), src/crb/core/class_sets.py (the shares),
              docs/PREVENTION.md (P-687, P-771)
Tested by:    (this is a test file)
Touch when:   onboarding a client repository never needs it; a screen is added to the app (add
              its route to ``routes()`` in 11-screens with a slug, in the same change); a
              spec gets a test that walks a built list.
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


# --- spec 15's labelling sample is not a matter of luck (P-687) -----------------------------

SPEC_15 = ROOT / "ui" / "e2e" / "walkthrough" / "15-classes.spec.ts"
#: The most often spec 15 may find nothing to label, for want of data, not of a defect.
EMPTY_QUEUE_MAX = 1e-3


def empty_queue_chance(commits: int) -> float:
    """The chance that none of ``commits`` replayable commits is offered for labelling: each
    is a derivation commit with :data:`DERIVATION_SHARE` and, if so, set aside as an example
    with :data:`EXAMPLE_SHARE`, both by a hash of its id, which the fixture changes every run."""
    from crb.core.class_sets import DERIVATION_SHARE, EXAMPLE_SHARE

    offered = DERIVATION_SHARE * (1 - EXAMPLE_SHARE)
    return float((1 - offered) ** commits)


def test_spec_15_mines_a_sample_it_is_almost_sure_to_label() -> None:
    src = SPEC_15.read_text(encoding="utf-8")
    found = re.search(r"const CLASS_SAMPLE_MINE = (\d+)", src)
    assert found, "15-classes.spec.ts no longer names CLASS_SAMPLE_MINE"
    assert "limit: CLASS_SAMPLE_MINE" in src, "spec 15 no longer mines its sample before labelling"
    n = int(found.group(1))
    assert empty_queue_chance(n) < EMPTY_QUEUE_MAX, (
        f"with {n} mined commits, spec 15 offers nothing to label in "
        f"{empty_queue_chance(n):.1%} of runs: mine more"
    )


def test_the_bound_catches_the_sample_earlier_specs_leave() -> None:
    # 5 replayable commits is what 03 and 11 left on the run that found nothing to label
    assert empty_queue_chance(5) > 0.1


# --- a pass over routes() is given time for every route it walks (P-771) ------------------------

E2E = ROOT / "ui" / "e2e"
#: A test's first line, its indent captured; prettier closes the test at that indent with `})`.
_TEST_LINE = re.compile(r"^(?P<indent> *)test\(")
#: A loop over a list a function builds, such as `for (const r of routes(ctx))`.
_LIST_LOOP = re.compile(r"for \(const \w+ of (?P<list>[A-Za-z_]\w*)\(")
_SET_TIMEOUT = re.compile(r"test\.setTimeout\((?P<arg>.*)\)\s*$", re.M)


def list_walks(src: str) -> list[tuple[int, str, list[str]]]:
    """Each test that loops over a list a function builds: its line, the list, its time limits."""
    lines = src.splitlines()
    walks = []
    for i, line in enumerate(lines):
        m = _TEST_LINE.match(line)
        if not m:
            continue
        close = m["indent"] + "})"
        end = next((j for j in range(i + 1, len(lines)) if lines[j].rstrip() == close), len(lines))
        body = "\n".join(lines[i:end])
        limits = [t["arg"] for t in _SET_TIMEOUT.finditer(body)]
        for name in sorted({loop["list"] for loop in _LIST_LOOP.finditer(body)}):
            walks.append((i + 1, name, limits))
    return walks


def fixed_limits(src: str) -> list[str]:
    """The walks whose time limit does not grow with the list: a fixed one, or the default."""
    return [
        f"line {line}: walks {name}() under {limits[0] if limits else 'the default time limit'}"
        for line, name, limits in list_walks(src)
        if not any(f"{name}(" in arg for arg in limits)
    ]


def test_a_pass_over_a_built_list_takes_its_time_limit_from_that_list() -> None:
    specs = sorted(E2E.rglob("*.spec.ts"))
    walks = [(p, w) for p in specs for w in list_walks(p.read_text(encoding="utf-8"))]
    assert any(p == SCREENS and w[1] == "routes" for p, w in walks), "11-screens' pass was not read"
    found = [
        f"{p.relative_to(ROOT)} {f}"
        for p in specs
        for f in fixed_limits(p.read_text(encoding="utf-8"))
    ]
    assert found == [], (
        "a test that walks a list gets a time limit computed from the list's length, so adding an "
        f"entry adds time (see passTimeoutMs in 11-screens.spec.ts): {found}"
    )


def test_the_gate_catches_a_fixed_limit_and_a_missing_one() -> None:
    def spec(limit: str) -> str:
        return (
            "  test('every route', async ({ page }) => {\n"
            f"{limit}"
            "    for (const r of routes(ctx)) {\n"
            "      await page.goto(r.path)\n"
            "    }\n"
            "  })\n"
        )

    assert fixed_limits(spec("    test.setTimeout(6 * 60_000)\n")) == [
        "line 1: walks routes() under 6 * 60_000"
    ]
    assert fixed_limits(spec("")) == ["line 1: walks routes() under the default time limit"]
    assert fixed_limits(spec("    test.setTimeout(passTimeoutMs(routes(ctx).length))\n")) == []
