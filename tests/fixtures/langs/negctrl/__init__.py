"""Fixture repositories for the polyglot negative controls (ADR-0010).

The base language fixtures (:mod:`fixtures.langs.gorepo`, :mod:`fixtures.langs.noderepo`)
have a feat commit that ADDS a new unit, so ``env_poison`` — which needs an existing
unit to pollute — is honestly ``not_constructible`` there. These two repositories keep
the same two-commit shape but their feat commit CHANGES an existing unit:

* :mod:`gorepo_funcvar` — ``calc/scale.go`` declares ``var Scale = func(a int) int``;
  the feat commit changes its body and adds ``calc/scale_test.go``. A package-level
  variable is the ONE thing a Go ``init()`` in a new file can re-assign.
* :mod:`noderepo_fix` — ``src/mul.js`` ships buggy; the feat commit fixes it and adds
  its test, in all four runner flavours.

Both carry a second unit with its own test (``util.Twice`` / ``src/calc.js``) so the
regression control has an adjacent unit inside a BARE belt.
"""
