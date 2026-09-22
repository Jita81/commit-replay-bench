---
id: dod.page.root
level: page
name: Index redirect
scope: /
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Index redirect

**Purpose.** The route renders nothing a person reads: it replaces itself with `/home`, the
journey's first screen, so a signed-in visitor who opens the site's root lands there and Back does
not return to it.

**Entry → exit.** Arrives by typing the site's address or following a link to `/`. Inside
`RequireAuth`, so a visitor with no session goes to `/login?next=%2F` first. Leaves on `/home`
with the history entry replaced, so Back does not return to `/`.

**Non-goals.** The index route never becomes a landing page, a repository list or a role-specific
dashboard: what a person sees first is `/home`'s job, and the redirect is the only thing this
route does.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| root.purpose.1 | PURPOSE | n/a | `absent` | n/a | the route paints nothing a person can read — it redirects before render, so the purpose a person sees is /home's |
| root.entry-exit.2 | ENTRY-EXIT | A signed-in visit to `/` lands on `/home` with the URL replaced; a visit with no session lands on `/login?next=%2F` and, after signing in, on `/home` | `code:ui/src/App.tsx::App` · `code:ui/src/lib/auth.tsx::RequireAuth` | partial | G-921 |
| root.truth.3 | TRUTH | n/a | `absent` | n/a | no number or state is rendered — the route has no element |
| root.actions.4 | ACTIONS | n/a | `absent` | n/a | no action — the redirect is automatic and the person presses nothing |
| root.explanation.5 | EXPLANATION | n/a | `absent` | n/a | nothing is rendered to hint, and the About block belongs to the page the person lands on (/home) |
| root.evidence.6 | EVIDENCE | A test visits `/` directly — signed in and signed out — and asserts where it lands | `absent` | unmet | G-921 |
| root.roles.7 | ROLES | The route sits inside `RequireAuth`: a session is required, no role is, and every role is sent to the same place | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` | partial | G-921 |
| root.operations.8 | OPERATIONS | n/a | `absent` | n/a | the route calls no API and holds no state — there is nothing for the platform team to run, probe or support |
| root.accessibility.9 | ACCESSIBILITY | n/a | `absent` | n/a | nothing is rendered — focus and the accessibility tree are /home's, held by its own rows |
| root.non-goals.10 | NON-GOALS | n/a | `absent` | n/a | a redirect has no content to scope — its non-goals are stated above and in the App.tsx header, and /home's rows carry the landing page's |

## Gaps
- **G-921** — no test visits `/` directly: `01-login` asserts that a direct login lands on `/home` (the LoginPage default, not this redirect) and no spec or vitest calls `goto('/')` · add two cases to `ui/e2e/smoke.spec.ts` — signed out, `/` → `/login?next=%2F`; signed in, `/` → `/home` · ui
