# Artefact template — copy, rename, fill every row

Copy the block for the level you are writing. Keep every category row: a category that does
not apply is `n/a` with the reason in the gap column, never deleted. Evidence references are
typed (`STANDARD.md` §3) and must resolve; write `absent` when nothing proves the criterion
yet and give the row a gap. `status:` is written by `scripts/dod_check.py` — leave it.

```markdown
---
id: dod.page.<route-slug>
level: page
name: <the name a person sees>
scope: /<route>
parent: dod.journey.<slug>
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# <name>

**Purpose.** <one sentence — the About block's first sentence>

**Entry → exit.** <how they arrive → what they leave with, and the one-click next step>

**Non-goals.** <what this page deliberately does not do>

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| <slug>.purpose.1 | PURPOSE | … | `hint:about:/<route>` | met | |
| <slug>.entry-exit.2 | ENTRY-EXIT | … | … | met | |
| <slug>.truth.3 | TRUTH | … | … | … | |
| <slug>.actions.4 | ACTIONS | … | … | … | |
| <slug>.explanation.5 | EXPLANATION | Every element is hinted and the ratchet enforces the route | `hint:ratchet:/<route>` | met | |
| <slug>.evidence.6 | EVIDENCE | … | `vitest:…` · `spec:…` | … | |
| <slug>.roles.7 | ROLES | … | … | … | |
| <slug>.operations.8 | OPERATIONS | … | … | … | |
| <slug>.accessibility.9 | ACCESSIBILITY | … | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"…"` | … | |
| <slug>.non-goals.10 | NON-GOALS | The non-goals above are stated on the page's About block or guide | … | … | |

## Gaps
- **G-001** — <what is missing · the smallest change that closes it · owner layer>
```

`owner layer` is one of `ui`, `server`, `factory`, `docs`, `deploy`. Take the `G-nnn` from
this level's band — pages `G-100`–`G-299`, journeys `G-300`–`G-499`, streams `G-500`–`G-599`,
the product `G-600`–`G-699` — and from the shared band `G-900`–`G-999` when the same change
closes a criterion in another artefact too; a shared id carries the same line, word for word,
in every file that cites it.

Journeys add rows for `STEPS`, `PROOF`, `TIME-COST`, `RECOVERY`; value streams add `TRIGGER`,
`OUTCOME`, `HANDOFF`, `MEASURE`, `AUTOMATION`; the product adds `IDENTITY`, `GO-LIVE`,
`CLAIMS`, `RELEASE`, `POSTURE`, `SUPPORT`, `EXTENSIBILITY` (`STANDARD.md` §4). A journey's
`children` are its page ids in step order; a stream's are its journeys; the product's are
the streams.
