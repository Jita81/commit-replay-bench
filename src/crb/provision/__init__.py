"""crb.provision — how a deployment gets a task's dependencies into the sealed posture.

ADR-0019 §6: dependencies belong to the task. They are read from git objects, fetched
outside the test container through the allowlisting proxy, sealed by digest and mounted
read-only. This package is where that lives; :func:`make_deps_provider` is the one place a
deployment's provider is chosen, so the worker, the CLI and the tests all get it the same
way.

Until provisioning lands (ADR-0019 stream D) every deployment gets
:class:`~crb.core.deps.NullDepsProvider`: the host's own environment under the ``local``
executor, and nothing at all under ``docker`` — which the qualification then states
honestly (``QUAL_ENV_UNLOADABLE``) instead of a replay charging the model for it.

Navigation
----------
What it is:   The provisioning package's front door — ``make_deps_provider``.
What it does: Chooses the deployment's ``DepsProvider`` from its provisioning settings; today
              always the null provider (provisioning off is the default and the only mode).
How:          One function; the settings object is duck-typed (``enabled``) because this
              layer sits below ``crb.server`` and must not import it.
Layer:        provision — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/deps.py (the protocol and the null provider it returns),
              src/crb/server/settings.py (``ProvisionSettings``, the settings it reads),
              src/crb/server/worker.py (the caller: one provider per worker),
              src/crb/cli/commands/repo.py (``crb repo qualify`` gets its provider here)
Tested by:    tests/test_deps_seam.py, tests/test_worker.py
Touch when:   provisioning lands (stream D replaces the body); never to special-case one
              repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crb.core.deps import DepsProvider, NullDepsProvider


def make_deps_provider(settings: Any, *, home: Path | str) -> DepsProvider:
    """The deployment's dependency provider. ``settings`` is the ``provision`` block of the
    server settings (``enabled``); ``home`` is ``CRB_HOME`` (the store lives under it)."""
    return NullDepsProvider()


__all__ = ["make_deps_provider"]
