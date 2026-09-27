---
id: dod.page.invite
level: page
name: Accept your invitation
scope: /invite
parent: dod.journey.orient
children: []
persons: [anonymous, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-23
---

# Accept your invitation

**Purpose.** "Someone has invited you to review and sign off what this deployment measures.
Choose a password and the account is yours." — the sentence under the brand name
(`AcceptInvitePage.tsx`). It is the only page the second person sees before they have an
account of their own, and the only page in the product whose reader has no role at all.

**Entry → exit.** Arrives by opening the one-time link an admin passed on
(`<deployment>/invite?token=…`, minted by `POST /invitations`); there is no link to it from
inside the product, and there cannot be — nobody signed in has an invitation to accept
(`App.reachability.test.ts` records the reason). Leaves with an activated account: the person
chooses a password, `POST /invitations/accept` sets it and activates the account, and the page
says which account is now live, in what role, with a link to sign in. No session is issued
here, so the first thing the account does is prove the password. A link with no token, or one
that was used, withdrawn or expired, leaves with a sentence and a way forward: ask your admin
for a new one.

**Non-goals.** The page does not create the account (the invitation did, inactive), does not
sign the person in, does not show the invitation's details beyond what they need, and renders
no About block (it is outside the shell, so `AboutThisScreen` never mounts). It cannot resend
or extend a link: that is an admin's act on Settings.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| invite.purpose.1 | PURPOSE | Before any role, the page says in one plain sentence what the reader is being asked to do and what happens: choose a password and the account is theirs | `code:ui/src/screens/Invite/AcceptInvitePage.tsx::AcceptInvitePage` · `vitest:ui/src/screens/Invite/AcceptInvitePage.test.tsx::"a link with no token says what to do instead of showing a form"` | met | |
| invite.entry-exit.2 | ENTRY-EXIT | The page is reached only by the emailed-or-passed-on link and leaves with an active account and the way to sign in; a link with no token renders the sentence, never an empty form | `vitest:ui/src/screens/Invite/AcceptInvitePage.test.tsx::"a link with no token says what to do instead of showing a form"` · `vitest:ui/src/screens/Invite/AcceptInvitePage.test.tsx::"compares the two passwords here, then posts the token and the password and nothing else"` · `vitest:ui/src/App.reachability.test.ts::"is deliberately unlinked"` | met | |
| invite.truth.3 | TRUTH | The page reports no state it did not receive: the success panel names the account and role the API returned, and the refusal is the API's own envelope — never a guess about why a link failed | `vitest:ui/src/screens/Invite/AcceptInvitePage.test.tsx::"a refused link renders the envelope with a title a person can act on"` · `route:POST /invitations/accept` | met | |
| invite.actions.4 | ACTIONS | The one action says what it did and what it did not: while pending the button reads "Setting your password…", a password that is too short or a pair that does not match is refused HERE with its own sentence and nothing is posted, and a refused link keeps the form so the right link can be tried without reloading | `vitest:ui/src/screens/Invite/AcceptInvitePage.test.tsx::"compares the two passwords here, then posts the token and the password and nothing else"` · `vitest:ui/src/screens/Invite/AcceptInvitePage.test.tsx::"a refused link renders the envelope with a title a person can act on"` · `code:ui/src/screens/Invite/AcceptInvitePage.tsx::passwordProblem` | met | |
| invite.explanation.5 | EXPLANATION | Every element — both password fields, the button, the success panel and the no-token sentence — carries a hint that opens on hover, focus and tap, and the ratchet enforces the route so a new unhinted element fails a test | `hint:id:field.invite.password` · `hint:id:field.invite.password_again` · `hint:id:button.invite.accept` · `hint:id:stat.invite.accepted` · `hint:id:stat.invite.no_token` · `hint:ratchet:/invite` | met | |
| invite.evidence.6 | EVIDENCE | The page's behaviour is proved by unit tests run in CI — the token in the body, the two client-side refusals, the success state and the refused link — and the server half by route tests over a real database | `vitest:ui/src/screens/Invite/AcceptInvitePage.test.tsx::"compares the two passwords here, then posts the token and the password and nothing else"` · `test:tests/test_server_invitations.py::test_accepting_sets_the_persons_own_password_activates_the_account_and_spends_the_token` · `ci:ui-unit` | partial | G-208 |
| invite.roles.7 | ROLES | No role is needed, and none is granted beyond the one the invitation named: the route needs no session, activates exactly the invited account, refuses a wrong, spent, withdrawn or expired token with one indistinguishable 401, rate-limits per IP, and records the acceptance as an event whose actor is the account itself | `test:tests/test_server_invitations.py::test_a_wrong_revoked_or_expired_token_is_the_same_refusal_and_the_limiter_bites` · `test:tests/test_server_invitations.py::test_accepting_sets_the_persons_own_password_activates_the_account_and_spends_the_token` · `code:src/crb/server/routes/invitations.py::accept_invitation` | met | |
| invite.operations.8 | OPERATIONS | The platform team can run the whole invitation without this page: `API.md` lists the four routes with their refusals, `OPERATOR.md` §9 says how to invite, what a link is worth and what to do when one is lost, and every write is an event on the account's trace | `doc:docs/API.md#admin` · `doc:docs/OPERATOR.md#9-users` · `route:GET/POST /invitations` · `route:GET /two-person-readiness` | met | |
| invite.accessibility.9 | ACCESSIBILITY | Both fields have visible labels, the form is named "Choose your password", the client-side refusal is a live region (`role="alert"`), and the page is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `code:ui/src/screens/Invite/AcceptInvitePage.tsx::AcceptInvitePage` | partial | G-209 |
| invite.non-goals.10 | NON-GOALS | The page says what it is not: a link works once and expires, and nobody — including the admin who invited you — can read the password chosen here | `code:ui/src/screens/Invite/AcceptInvitePage.tsx::AcceptInvitePage` | met | |

## Gaps
- **G-208** — no browser walkthrough covers the invitation end to end: `11-screens` walks the authenticated routes only, so an admin inviting, the link being opened in a fresh browser context and the invited person signing in with their new password is proved by unit and route tests but never against a live stack · add a tier-1 spec that invites through Settings, opens `accept_url` in a second context, sets a password and signs in · ui
- **G-209** — `/invite` renders outside the shell and no spec visits it, so it gets no axe sweep, no keyboard pass and no 375 px sideways-scroll assertion; the same gap `/login` carries (G-192) · sweep both pre-session screens at 375 and 1280 in the walkthrough before signing in · ui
