/**
 * docs.ts — the eight guides are bundled, `docHref` builds the route and `slugify` is GitHub's.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the bundled-docs module.
 * What it does: Pins that the glob holds exactly the nine user-facing guides and no ADR; that
 *               `loadDoc` resolves to the file on disk and rejects an unknown name; that
 *               `docHref` maps an anchor to `/help/docs/<name>#<slug>`; and that `slugify`
 *               reproduces the docs' own anchors (`#4-the-apparatus-stamp--evidence-expires`).
 * How:          A `?raw` import of the same file the glob bundles; the slug cases are the
 *               anchors the screens link to.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/docs.ts, docs/EVIDENCE-AND-CLAIMS.md (an anchor source)
 * Tested by:    ui/src/help/docs.test.ts
 * Touch when:   never for a new repository; a guide is added to the bundle.
 */
import { describe, expect, it } from 'vitest'
import dataRetention from '../../../docs/DATA-RETENTION.md?raw'
import humanReviewGuide from '../../../docs/reviews/human-review-guide.md?raw'
import { DOC_NAMES, docByPath, docHref, docPath, isDocName, loadDoc, slugify } from './docs'

describe('bundled docs', () => {
  it('bundles exactly the nine guides and no ADR', () => {
    expect([...DOC_NAMES].sort()).toEqual(['DATA-RETENTION', 'DEPLOYMENT', 'EVIDENCE-AND-CLAIMS', 'GITHUB-APP', 'HUMAN-REVIEW-GUIDE', 'LEARNING-LOOP', 'ONBOARDING-A-REPO', 'OPERATOR', 'SECURITY'])
    expect(isDocName('OPERATOR')).toBe(true)
    expect(isDocName('adr/0003-one-routing-rule')).toBe(false)
    expect(isDocName('ARCHITECTURE')).toBe(false)
  })

  it('loadDoc serves the file on disk and rejects an unknown name', async () => {
    const text = await loadDoc('DATA-RETENTION')
    expect(text).toBe(dataRetention)
    expect(text).toMatch(/^# Data, retention and privacy/)
    await expect(loadDoc('NOPE' as never)).rejects.toThrow(/No guide/)
  })

  it('bundles the Step 6 human-review guide from docs/reviews, and resolves it by its path (G-481)', async () => {
    expect(docPath('HUMAN-REVIEW-GUIDE')).toBe('reviews/human-review-guide')
    expect(docPath('OPERATOR')).toBe('OPERATOR')
    expect(docByPath('reviews/human-review-guide')).toBe('HUMAN-REVIEW-GUIDE')
    expect(docByPath('reviews/2026-09-13-critical-friend')).toBeUndefined()
    const text = await loadDoc('HUMAN-REVIEW-GUIDE')
    expect(text).toBe(humanReviewGuide)
    expect(text).toMatch(/^# Human review guide/)
  })

  it('docHref builds the route with and without a slug', () => {
    expect(docHref('OPERATOR')).toBe('/help/docs/OPERATOR')
    expect(docHref('OPERATOR#4-read-the-capability-map')).toBe('/help/docs/OPERATOR#4-read-the-capability-map')
  })

  it('slugify follows the GitHub rule so the docs’ own anchors resolve', () => {
    expect(slugify('4. The apparatus stamp — evidence expires')).toBe('4-the-apparatus-stamp--evidence-expires')
    expect(slugify('Step 3 — prove the instrument on this repository (operator, £0)')).toBe('step-3--prove-the-instrument-on-this-repository-operator-0')
    expect(slugify('3.1 Sandboxed test execution — `crb.core.execution.DockerExecutor`')).toBe('31-sandboxed-test-execution--crbcoreexecutiondockerexecutor')
    expect(slugify('6a. What a signed cell may be claimed to mean (signoff-policy.v3)')).toBe('6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv3')
    expect(slugify('  Trailing spaces  ')).toBe('trailing-spaces')
  })
})
