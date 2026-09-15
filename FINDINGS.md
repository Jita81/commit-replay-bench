# Findings — file-header programme, Python scope (runners / oracle / builders / observability)

Bugs and observations noticed while documenting. Nothing here was changed in code.

## 1. OpenAILabeller live path always fails with a TypeError (bug)

- File: src/crb/builders/labeller.py (OpenAILabeller._chat, ~line 241) and src/crb/builders/openai_client.py (make_chat, ~line 434).
- What: OpenAILabeller._chat() calls make_chat(self.model, ep, max_tokens=self.max_tokens, temperature=self.temperature). make_chat forwards **kw to OpenAIChat(...) while ALSO passing temperature=ep.temperature, max_tokens=ep.max_tokens explicitly, so Python raises TypeError: OpenAIChat() got multiple values for keyword argument max_tokens.
- Effect: every live (non-chat_fn) OpenAI-compatible label run yields unclassified labels with rationale "model_error: TypeError: ..." — the except Exception in label() swallows it, so the run succeeds with 100% errors rather than crashing. Hermetic tests inject chat_fn and never reach make_chat, which is why the suite is green.
- Reproduction (no SDK, no key): stub openai_client.make_client and call make_chat("m", EndpointConfig(), max_tokens=512, temperature=0.0) -> the TypeError.
- Likely fix (not applied): in make_chat build the explicit kwargs into a dict and let kw override it ({**explicit, **kw}), or have the labeller build an EndpointConfig with its own max_tokens/temperature instead of passing them as **kw.

## 2. openai_agent run_target_tests does not bind the task author date (observation)

- File: src/crb/builders/openai_agent.py (_Tools.run_target_tests).
- What: calls self.runner.run(...) rather than run_for(..., authored=task.authored). The brief carries no authored, so with runner_opts.services declared the era falls back to the worktree HEAD date (BaseRunner.run docstring: exact except for a commit sitting on an era boundary). The adapter sighted_test_command brings the right era up first and the running variant is reused, so this only matters for a task on an era boundary. Not a verdict issue (the grader binds the date itself).

## 3. crb.core.oracle.sealed_corpus has no caller outside its package (observation)

- Files: src/crb/core/oracle/sealed_corpus.py, src/crb/core/oracle/__init__.py.
- What: build_manifests / write_outputs / verify_outputs are exported but no CLI verb, route or worker run kind calls them. The header Works with says so; a crb corpus seal|verify verb (or a note in docs/OPERATOR.md that sealing is a Python-API step) would close the gap.

## 4. fixture_gold rows are not excluded by the abstract export (observation)

- Files: src/crb/builders/fixture_gold.py (module docstring), src/crb/core/federated.py (export_abstract), src/crb/server/routes/ledger.py.
- What: the fixture module states the abstract-cell export and any federated learning MUST exclude builder == "fixture_gold" rows, but export_abstract keys cells on builder without filtering it and the ledger route does not either (grep for fixture in both is empty). The rows are unmistakably labelled, so a consumer CAN filter; the exclusion the docstring promises is not enforced in code. Suggest a filter in export_abstract (or the route) plus a test.
