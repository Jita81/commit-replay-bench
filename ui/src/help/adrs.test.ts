/**
 * adrs.ts — the decision list the product shows is the list the repository holds.
 *
 * Navigation
 * ----------
 * What it is:   The ratchet between `ADR_TITLES` and docs/adr/*.md (G-157).
 * What it does: Reads every record in docs/adr as text and pins that (1) each file's first
 *               line is `# ADR-nnnn — <title>` with the number its file name carries; (2) the
 *               numbers and titles are exactly `ADR_TITLES`, both ways — a record added,
 *               renamed, retitled or deleted without its row fails, and so does a row with no
 *               file; (3) every listed record loads through `loadAdr` and matches the file on
 *               disk, and an unknown number rejects; (4) the names and routes are the
 *               `ADR-nnnn` / `/help/docs/ADR-nnnn` pair the Help page links.
 * How:          `import.meta.glob(..., { eager: true, query: '?raw' })` over docs/adr — the
 *               same files the lazy glob in adrs.ts bundles.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-073)
 * Works with:   ui/src/help/adrs.ts (the list under test), docs/adr/*.md (the records it
 *               must match), ui/src/screens/Help/HelpPage.tsx (the list it renders),
 *               ui/src/help/docs.test.ts (the guides' twin test)
 * Tested by:    ui/src/help/adrs.test.ts
 * Touch when:   never to make it pass — change `ADR_TITLES` (or the record) instead.
 */
import { describe, expect, it } from 'vitest'
import { ADR_TITLES, adrHref, adrNumber, adrTitle, isAdrName, loadAdr } from './adrs'

const ON_DISK = import.meta.glob('../../../docs/adr/[0-9][0-9][0-9][0-9]-*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** `[number, title, text]` for every record file, from its name and its first heading. */
function records(): Array<[string, string, string]> {
  return Object.entries(ON_DISK)
    .map(([path, text]): [string, string, string] => {
      const file = path.split('/').at(-1)!
      const head = /^# ADR-(\d{4}) — (.+)$/.exec(text.split('\n')[0] ?? '')
      expect(head, `${file}: the first line must be "# ADR-nnnn — <title>"`).not.toBeNull()
      expect(head![1], `${file}: the heading's number is not the file's`).toBe(file.slice(0, 4))
      return [head![1]!, head![2]!.trim(), text]
    })
    .sort((a, b) => a[0].localeCompare(b[0]))
}

describe('ADR registry', () => {
  it('lists exactly the decision records in docs/adr, by number and title', () => {
    const disk = records().map(([n, t]) => [n, t])
    expect(disk.length).toBeGreaterThan(20)
    expect(ADR_TITLES.map(([n, t]) => [n, t])).toEqual(disk)
  })

  it('loads every listed record as the file on disk, and rejects an unknown number', async () => {
    for (const [num, , text] of records()) {
      expect(await loadAdr(`ADR-${num}`)).toBe(text)
    }
    await expect(loadAdr('ADR-9999')).rejects.toThrow(/No decision record/)
    await expect(loadAdr('OPERATOR')).rejects.toThrow(/No decision record/)
  })

  it('names a record ADR-nnnn and routes it beside the guides', () => {
    expect(isAdrName('ADR-0015')).toBe(true)
    expect(isAdrName('ADR-9999')).toBe(false)
    expect(isAdrName('adr-0015')).toBe(false)
    expect(adrNumber('ADR-0016')).toBe('0016')
    expect(adrTitle('ADR-0016')).toBe('The two-person rule is a policy clause, not an apparatus move')
    expect(adrHref('0015')).toBe('/help/docs/ADR-0015')
  })
})
