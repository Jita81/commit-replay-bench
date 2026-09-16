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

Navigation
----------
What it is:   The package marker for the two negative-control fixtures whose feat commit CHANGES
              an existing unit (ADR-0010).
What it does: Explains why they exist: the base language fixtures ADD a unit, so ``env_poison``
              has nothing at the parent to pollute and is honestly ``not_constructible`` there;
              these keep the two-commit shape but give the control an existing unit. Carries no
              code.
How:          Prose only; the fixtures are ``gorepo_funcvar`` and ``noderepo_fix`` beside it.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0010-polyglot-negative-controls.md
Works with:   tests/fixtures/langs/negctrl/gorepo_funcvar.py and
              tests/fixtures/langs/negctrl/noderepo_fix.py (the fixtures),
              src/crb/core/oracle/controls_go.py and src/crb/core/oracle/controls_js.py (the
              transforms they were built for), tests/fixtures/langs/__init__.py (the shape)
Tested by:    tests/test_oracle_controls_go.py, tests/test_oracle_controls_js.py
Touch when:   a negative control is ported to another language and needs a "changes an existing
              unit" fixture — add it here and describe the vector in this docstring.
"""
