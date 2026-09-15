# Licensing

**Status (2026-09-15):** licence text pending legal; `LICENSE` is a reservation of rights.
Nothing is granted beyond reading, evaluating and reviewing the source. This page says what
the adopted licence will permit, so a procurement reviewer can assess it before the text lands.

## The decision (DL-015, DL-025)

| Parameter | Value |
|---|---|
| Template | Business Source License 1.1 (SPDX `BUSL-1.1`) |
| Licensor | Automated Agile — the legal entity is confirmed with the text |
| Licensed Work | Commit Replay Bench (crb) `<version>`, per tagged version |
| Additional Use Grant | **Non-production use** (evaluation, testing, development, research) and **verification use** — running the Licensed Work to read, re-derive, re-grade or audit any evidence it produced (ledger rows, evidence packs, capability maps, sign-offs) — without limit. **Production use**, and offering the Licensed Work or a derivative as a service, require a commercial licence. |
| Change Date | Three years after each version's first release |
| Change License | Apache License 2.0 |

## Why this shape

- **Readable, re-runnable source** is the governance argument: every verdict in the ledger can be
  re-derived by anyone with the code (EVIDENCE-AND-CLAIMS §2). A proprietary licence would
  undercut it; MIT would give the product away.
- **A conversion date** is the procurement exit story: an NHS buyer is never locked to a
  vendor for the instrument that graded their evidence — three years after a release, that
  release is Apache-2.0.
- **Verification use is free forever**, from day one: auditing evidence never needs a
  commercial agreement.

## What a reviewer will find in the repository once the text lands

- `LICENSE` with the four parameters filled and the BSL's own reuse notice.
- `pyproject.toml` carrying the SPDX identifier; the container image labelled `BUSL-1.1`
  (`release.yml`); until then both say `NOASSERTION` / reference this page.
- Third-party inventories: the Python SBOM (CycloneDX, CI `sbom` job) — no GPL/AGPL, one LGPL,
  four MPL; the npm tree of `ui/` (to be inventoried before the first tag).
- The IP-ownership statement: the code is substantially AI-generated under human direction
  (`docs/reviews/2026-09-13-critical-friend.md` §6); ownership under CDPA 1988 s.9(3) and the
  model provider's output terms is part of the legal pack.
- Contributions: a CLA before any external commit is accepted.

## Contact

paul@automatedagile.co.uk
