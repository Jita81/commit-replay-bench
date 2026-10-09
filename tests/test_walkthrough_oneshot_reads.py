"""Every one-shot read in the live-stack walkthrough has been judged settled — a ratchet.

On 2026-10-09 (docs/PREVENTION.md P-782) `main` went red on `14-go-live`: the step read the
footer with ``await contentinfo.textContent()`` once, right after the page's heading was
visible, and got "Commit Replay Bench · Help · Glossary". The version line is drawn from
``GET /version``, which had not answered yet. A one-shot read (``textContent``, ``count``,
``getAttribute``, ``evaluate``, ``boundingBox`` and the rest) does not retry, so on a page that
draws in several commits (TanStack Query, the live log's stream, a mutation) it can read an
earlier render. A web-first assertion (``toContainText``, ``toHaveCount``, ``expect.poll``)
retries until the page is right. An audit of the walkthrough's 109 one-shot reads found 18
that could race; each now waits for what it reads or became a web-first assertion. This test
holds the other reads to the audit: each one is in ``SETTLED`` with the reason it cannot read
an earlier render, so a new or edited read fails until someone has judged it.

Navigation
----------
What it is:   The ratchet over one-shot DOM reads in ui/e2e/walkthrough: every line that
              awaits or returns one is listed in ``SETTLED`` with a reason, and every entry
              there is still a line in the walkthrough.
What it does: Scans the walkthrough's ``.ts`` files line by line for a read (``READ``), leaving
              out comments and lines that retry it (``expect.poll(``, ``.toPass(``); fails on a
              read that ``SETTLED`` does not hold, printing an entry ready to paste once the
              read is judged settled, and on an entry no line matches any more. Negative
              controls prove the scan sees a racy read and passes over a retried one.
How:          A multiset (``Counter``) of (file, line with its whitespace collapsed) on each
              side, so two identical reads in one file need two entries. It reads direct calls
              only: a helper that reads (``focusedIs``, ``widestOverflow``) is judged once, at
              its own body, so a helper should wait for the page itself before it reads.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/*.ts (the reads), ui/e2e/walkthrough/keyboard.ts (``tabTo``
              and ``chooseByKeyboard`` wait for their target before they press a key),
              ui/e2e/walkthrough/11-screens.spec.ts (``drawn``, the wait ``widestOverflow``
              and ``hintSample`` make first), tests/test_walkthrough_axe_settles.py (the same
              rule for axe sweeps), docs/PREVENTION.md (P-782)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a walkthrough step adds or edits a one-shot read
              (prefer a web-first assertion; when the read must stay, wait for what it reads and
              add its entry here).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALKTHROUGH = ROOT / "ui" / "e2e" / "walkthrough"

#: An awaited or returned call that reads the page once. ``Promise.all(`` is not a read.
READ = re.compile(
    r"\b(?:await|return)\s[^;]*?(?<!Promise)\.(?:textContent|innerText|innerHTML|getAttribute"
    r"|count|isVisible|isHidden|isChecked|isEnabled|isDisabled|isEditable|inputValue"
    r"|allTextContents|allInnerTexts|boundingBox|all|evaluate|evaluateAll)\("
)
#: A line holding one of these retries the read on it.
RETRIES = ("expect.poll(", ".toPass(")

# Why a read cannot see an earlier render. Each entry in SETTLED names one.
#: A web-first wait just above proved this content drawn, and nothing redraws it after.
WAITED = "waited"
#: A wait just above proved drawn a part of the page that renders in the same commit.
SAME_COMMIT = "same-commit"
#: Markup fixed at first paint or at mount: an id, an href, a registry string, a layout.
FIXED_MARKUP = "fixed-markup"
#: The result of the test's own key press or click, which commits before the press resolves.
OWN_INPUT = "own-input"
#: It acts on the page (a blur, a frame wait, a round trip) and reads nothing back.
ACTS = "acts"
#: It sits in a helper that waits for the page to finish drawing before it reads.
SETTLES = "settles"
#: It is read inside a retrying loop (``expect.poll``, ``escapeUntil``), or after one
#: proved the value final.
RETRIED = "retried"
#: It only feeds a failure message.
MESSAGE_ONLY = "message-only"
REASONS = frozenset(
    (WAITED, SAME_COMMIT, FIXED_MARKUP, OWN_INPUT, ACTS, SETTLES, RETRIED, MESSAGE_ONLY)
)

#: (file in ui/e2e/walkthrough, the line with its whitespace collapsed, why it is settled).
SETTLED: tuple[tuple[str, str, str], ...] = (
    (
        "02-repo-onboard.spec.ts",
        "if ((await log.getByText('setup.auto', { exact: true }).count()) > 0) {",
        WAITED,
    ),
    (
        "03-mine.spec.ts",
        "expect(Number(await bar.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(1)",
        SAME_COMMIT,
    ),
    (
        "03b-qualify.spec.ts",
        "const m = /(\\d+) of (\\d+)/.exec((await tile.textContent()) ?? '')",
        RETRIED,
    ),
    (
        "05-replay-fake.spec.ts",
        "cellClass = (await first.locator('td').nth(1).textContent())?.trim() ?? ''",
        SAME_COMMIT,
    ),
    (
        "05-replay-fake.spec.ts",
        "cellSize = (await first.locator('td').nth(2).textContent())?.trim() ?? ''",
        SAME_COMMIT,
    ),
    ("05-replay-fake.spec.ts", "const text = (await builder.textContent()) ?? ''", SAME_COMMIT),
    (
        "05-replay-fake.spec.ts",
        "const label = (await cell.getAttribute('aria-label')) ?? ''",
        WAITED,
    ),
    (
        "06b-baseline-read.spec.ts",
        "expect(await tileN(lead).textContent()).toBe(await runsGraded.textContent())",
        SAME_COMMIT,
    ),
    ("07-settings-and-a11y.spec.ts", "return (await main.textContent()) ?? ''", SETTLES),
    (
        "07-settings-and-a11y.spec.ts",
        "const apparatus = (await page.getByTestId('settings-apparatus').textContent())?.trim()",
        WAITED,
    ),
    (
        "07-settings-and-a11y.spec.ts",
        "const policy = (await page.getByTestId('settings-policy').textContent())?.trim()",
        WAITED,
    ),
    (
        "07-settings-and-a11y.spec.ts",
        "if ((await users.getByRole('cell', { name: APPROVER, exact: true }).count()) === 0) {",
        SAME_COMMIT,
    ),
    (
        "07-settings-and-a11y.spec.ts",
        "if (!(await toggle.isChecked())) await toggle.check()",
        SAME_COMMIT,
    ),
    ("07-settings-and-a11y.spec.ts", "const fit = await page.evaluate(() => {", WAITED),
    (
        "08-signoff.spec.ts",
        "const value = await select.locator('option').nth(1).getAttribute('value')",
        SAME_COMMIT,
    ),
    (
        "08-signoff.spec.ts",
        "const escaped = env.publicTier ? await controls.getByTestId('controls-escaped').count() > 0 : true",
        SAME_COMMIT,
    ),
    (
        "08-signoff.spec.ts",
        "const link = new URL(((await page.getByTestId('invitation-url').textContent()) ?? '').trim(), env.baseUrl)",
        SAME_COMMIT,
    ),
    (
        "08-signoff.spec.ts",
        "const rowHash = await picker.locator('option').nth(1).getAttribute('value')",
        SAME_COMMIT,
    ),
    ("08-signoff.spec.ts", "const rowHash = await first.getAttribute('value')", WAITED),
    (
        "09-budget-sweep.spec.ts",
        "await expect(tileValue(page.getByTestId('tile-rows'))).toHaveText(String(await rows.count()))",
        SAME_COMMIT,
    ),
    ("09-budget-sweep.spec.ts", "for (const row of await rows.all()) {", SAME_COMMIT),
    (
        "10-factory.spec.ts",
        "if ((await prov.count()) > 0) await expect(prov).toHaveText(/^n = \\d+ · \\d+ % \\[\\d+ %, \\d+ %\\] · apparatus /)",
        SAME_COMMIT,
    ),
    ("10-factory.spec.ts", "const widths = await page.evaluate(() => {", WAITED),
    ("11-screens.spec.ts", "return page.evaluate(() => {", SETTLES),
    (
        "11-screens.spec.ts",
        "expect(await dialog.evaluate((d) => d.matches(':modal')), `${where}: the dialog is modal (top layer)`).toBe(true)",
        SAME_COMMIT,
    ),
    ("11-screens.spec.ts", "const painted = await tip.evaluate((el) => {", WAITED),
    ("11-screens.spec.ts", "return page.evaluate(() => {", OWN_INPUT),
    (
        "11-screens.spec.ts",
        "if ((await firstInMain.count()) > 0) await firstInMain.focus()",
        FIXED_MARKUP,
    ),
    ("11-screens.spec.ts", "if ((await page.locator(':focus').count()) === 0) break", OWN_INPUT),
    (
        "11-screens.spec.ts",
        "const submit = await page.getByRole('button', { name: button, exact: true }).boundingBox()",
        WAITED,
    ),
    (
        "11-screens.spec.ts",
        "await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())",
        ACTS,
    ),
    ("11-screens.spec.ts", "const journey = (await eyebrow.count()) > 0", SAME_COMMIT),
    (
        "11-screens.spec.ts",
        "expect(await page.evaluate(() => document.activeElement?.closest('#shell-menu-actions, #shell-nav-primary, #shell-nav-instrument') !== null), `${where}: Tab from the open Menu button did not move into the menu`).toBe(true)",
        OWN_INPUT,
    ),
    (
        "11-screens.spec.ts",
        "await escapeUntil(page, async () => (await button.getAttribute('aria-expanded')) === 'false')",
        RETRIED,
    ),
    (
        "11-screens.spec.ts",
        "await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())",
        ACTS,
    ),
    ("11-screens.spec.ts", "const n = await hinted.count()", SETTLES),
    ("11-screens.spec.ts", "const id = await el.getAttribute('data-hint')", FIXED_MARKUP),
    (
        "11-screens.spec.ts",
        "if (!(await el.isVisible())) continue // a hidden-below-md column header at 375 px",
        FIXED_MARKUP,
    ),
    (
        "11-screens.spec.ts",
        "await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))))",
        ACTS,
    ),
    ("11-screens.spec.ts", "const text = (await tip.textContent()) ?? ''", FIXED_MARKUP),
    (
        "11-screens.spec.ts",
        "expect(await tip.locator('a').count(), `${where}: hint ${id} contains a link`).toBe(0)",
        FIXED_MARKUP,
    ),
    ("11-screens.spec.ts", "const box = await bar.boundingBox()", FIXED_MARKUP),
    (
        "11b-keyboard.spec.ts",
        "await expect(page.locator(`[id=\"${await disclosure.getAttribute('aria-controls')}\"]`)).toHaveAttribute('role', 'note')",
        FIXED_MARKUP,
    ),
    (
        "11b-keyboard.spec.ts",
        "await escapeUntil(page, async () => (await disclosure.getAttribute('aria-expanded')) === 'false')",
        RETRIED,
    ),
    (
        "11b-keyboard.spec.ts",
        "await escapeUntil(page, async () => (await disclosure.getAttribute('aria-expanded')) === 'false')",
        RETRIED,
    ),
    (
        "11b-keyboard.spec.ts",
        "const name = ((await term.textContent()) ?? '').trim()",
        MESSAGE_ONLY,
    ),
    (
        "11b-keyboard.spec.ts",
        "const note = page.locator(`[id=\"${await term.getAttribute('aria-controls')}\"]`)",
        FIXED_MARKUP,
    ),
    (
        "11b-keyboard.spec.ts",
        "await escapeUntil(page, async () => (await term.getAttribute('aria-expanded')) === 'false')",
        RETRIED,
    ),
    (
        "11b-keyboard.spec.ts",
        "const label = ((await page.locator(':focus').textContent()) ?? '').trim()",
        FIXED_MARKUP,
    ),
    (
        "11b-keyboard.spec.ts",
        "await escapeUntil(page, async () => !(await dialog.isVisible()))",
        RETRIED,
    ),
    ("11b-keyboard.spec.ts", "const cells = await page.evaluate(() => {", SAME_COMMIT),
    (
        "12-intake.spec.ts",
        "const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)",
        WAITED,
    ),
    (
        "13-learn.spec.ts",
        "const id = /strengthen-[0-9a-f]+(?:-v\\d+)?/.exec((await done.textContent()) ?? '')![0]",
        WAITED,
    ),
    ("13-learn.spec.ts", "const href = (await rescore.getAttribute('href')) ?? ''", SAME_COMMIT),
    (
        "13-learn.spec.ts",
        "await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))))",
        ACTS,
    ),
    (
        "13-learn.spec.ts",
        "const ids = ((await tile.getAttribute('aria-describedby')) ?? '').split(' ').filter(Boolean)",
        FIXED_MARKUP,
    ),
    ("13-learn.spec.ts", "const box = await bar.boundingBox()", FIXED_MARKUP),
    (
        "13-learn.spec.ts",
        "const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }))",
        WAITED,
    ),
    (
        "13-orient.spec.ts",
        "const open = await block.locator('details').evaluate((d) => (d as HTMLDetailsElement).open)",
        OWN_INPUT,
    ),
    ("13-orient.spec.ts", "const termHref = (await term.getAttribute('href')) ?? ''", FIXED_MARKUP),
    (
        "13-orient.spec.ts",
        "const guideHref = (await readMore.getAttribute('href')) ?? ''",
        FIXED_MARKUP,
    ),
    (
        "13-recover-an-account.spec.ts",
        "if ((await users.getByRole('cell', { name: PERSON, exact: true }).count()) === 0) {",
        SAME_COMMIT,
    ),
    (
        "13-recover-an-account.spec.ts",
        "expect((await page.locator('main').textContent()) ?? '').not.toContain(fresh)",
        WAITED,
    ),
    (
        "14-go-live.spec.ts",
        "expect((await page.locator('main').textContent()) ?? '').not.toContain(FAKE_SETUP_TOKEN)",
        WAITED,
    ),
    (
        "14-go-live.spec.ts",
        "if ((await app.textContent())?.includes('not configured')) {",
        SAME_COMMIT,
    ),
    (
        "14-go-live.spec.ts",
        "if ((await users.getByRole('cell', { name: APPROVER, exact: true }).count()) === 0) {",
        SAME_COMMIT,
    ),
    ("14-go-live.spec.ts", "const footer = (await contentinfo.textContent()) ?? ''", WAITED),
    ("14-go-live.spec.ts", "const n = await rows.count()", FIXED_MARKUP),
    (
        "14-go-live.spec.ts",
        "if (await card.getByTestId('withdraw-egress-denied').count()) {",
        SAME_COMMIT,
    ),
    (
        "14-library.spec.ts",
        "const workType = ((await first.textContent()) ?? '').split(' · ')[0]!.trim()",
        SAME_COMMIT,
    ),
    (
        "14-library.spec.ts",
        "const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)",
        WAITED,
    ),
    # the first pass: label-definitions, waited for above, is drawn in the same form; each later
    # pass follows the expect.poll that proved the next commit (or none) in place
    ("15-classes.spec.ts", "if (!(await message.isVisible())) break", RETRIED),
    ("15-classes.spec.ts", "const said = (await message.textContent()) ?? ''", RETRIED),
    (
        "15-classes.spec.ts",
        "if (await message.isVisible()) await expect(page.getByTestId('label-next')).toBeFocused()",
        RETRIED,
    ),
    (
        "15-classes.spec.ts",
        "const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)",
        WAITED,
    ),
    ("15-classes.spec.ts", "const box = await open.boundingBox()", WAITED),
    (
        "keyboard.ts",
        "const ids = ((await el.getAttribute('aria-describedby')) ?? '').split(' ').filter(Boolean)",
        FIXED_MARKUP,
    ),
    (
        "keyboard.ts",
        "expect(await page.evaluate(() => document.activeElement?.textContent?.trim()), `${where}: the first Tab after the page loaded did not land on the skip link`).toBe('Skip to content')",
        OWN_INPUT,
    ),
    ("keyboard.ts", "const at = await page.evaluate((sel) => {", OWN_INPUT),
    ("keyboard.ts", "await page.evaluate(() => 0).catch(() => undefined)", ACTS),
    (
        "keyboard.ts",
        "return locator.evaluate((el) => el === document.activeElement || el.contains(document.activeElement))",
        RETRIED,
    ),
    (
        "repo-config.spec.ts",
        "const runnerOptions = await field(dialog, 'Runner').locator('option').allTextContents()",
        FIXED_MARKUP,
    ),
    (
        "repo-config.spec.ts",
        "expect(await runner.locator('option').allTextContents()).toEqual(['node', 'vitest', 'jest', 'mocha'])",
        OWN_INPUT,
    ),
    (
        "repo-config.spec.ts",
        "expect(JSON.parse(await json.inputValue())).toEqual({ node: '/opt/node@24/bin/node', extra_args: ['--selectProjects', 'unit'], env: { TZ: 'UTC' } })",
        WAITED,
    ),
    ("support.ts", "if (await shell.isVisible()) {", WAITED),
    (
        "support.ts",
        "if (!(await button.isVisible())) await page.getByTestId('shell-menu-button').click()",
        SAME_COMMIT,
    ),
    (
        "support.ts",
        "const label = await page.getByTestId('run-status').getAttribute('aria-label')",
        RETRIED,
    ),
    (
        "support.ts",
        "const err = (await page.locator('#main').getByRole('alert').first().textContent({ timeout: 2_000 }).catch(() => '')) ?? ''",
        MESSAGE_ONLY,
    ),
)


def _reads_in(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        code = " ".join(line.split())
        if code.startswith(("//", "*", "/*")) or any(r in code for r in RETRIES):
            continue  # a comment names a read; a retried read is not one-shot
        if READ.search(code):
            found.append((number, code))
    return found


def _reads() -> list[tuple[str, int, str]]:
    return [
        (path.name, number, code)
        for path in sorted(WALKTHROUGH.glob("*.ts"))
        for number, code in _reads_in(path.read_text(encoding="utf-8"))
    ]


def test_the_walkthrough_has_one_shot_reads_to_check() -> None:
    assert len(_reads()) >= 40, "the scan found few one-shot reads: has the walkthrough moved?"


def test_every_settled_entry_names_a_reason() -> None:
    unknown = [entry for entry in SETTLED if entry[2] not in REASONS]
    assert not unknown, f"an entry names no known reason: {unknown}"


def test_every_one_shot_read_has_been_judged_settled() -> None:
    reads = _reads()
    seen = Counter((name, code) for name, _, code in reads)
    held = Counter((name, code) for name, code, _ in SETTLED)
    new = seen - held
    lines = {(name, code): number for name, number, code in reads}
    assert not new, (
        "a walkthrough step reads the page once, and nothing has judged that it reads a settled "
        "page (P-782). Prefer a web-first assertion (toContainText, toHaveCount, expect.poll); "
        "when the read must stay, wait first for what it reads, then add it to SETTLED:\n"
        + "\n".join(
            f"    ({name!r}, {code!r}, WAITED),  # line {lines[name, code]}" for name, code in new
        )
    )


def test_every_settled_entry_is_still_a_read_in_the_walkthrough() -> None:
    seen = Counter((name, code) for name, _, code in _reads())
    held = Counter((name, code) for name, code, _ in SETTLED)
    stale = held - seen
    assert not stale, f"SETTLED holds reads no line makes any more; remove them: {list(stale)}"


def test_the_scan_sees_a_racy_read_and_passes_over_a_retried_one() -> None:
    # negative controls: the 14-go-live read that failed, a returned read, and a read across
    # every element are found; a comment and a retried read are not
    racy = (
        "const footer = (await page.getByRole('contentinfo').textContent()) ?? ''\n"
        "  return locator.evaluate((el) => el === document.activeElement)\n"
        "for (const row of await rows.all()) {\n"
    )
    assert [n for n, _ in _reads_in(racy)] == [1, 2, 3]
    settled = (
        "// await page.locator('main').textContent()\n"
        "await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(1)\n"
        "await expect(async () => expect(await tile.textContent()).toBe('3')).toPass()\n"
        "const [a, b] = await Promise.all([one(), two()])\n"
    )
    assert _reads_in(settled) == []
