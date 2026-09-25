"""Dependency provisioning (ADR-0019): fetched outside the test container, sealed, mounted
read-only.

Navigation
----------
What it is:   The provisioning package: the bundle store, the fetch container and the
              per-language recipes behind the ``crb.core.deps`` seam.
What it does: Seals dependency sets a task's lockfiles name, so a sealed test container can
              run with no network.
How:          ``store`` seals and mounts; later modules fetch and bind.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/provision/store.py (the sealed sets), src/crb/core/deps.py (the seam),
              src/crb/core/provision.py (the inputs)
Tested by:    tests/test_provision_store.py
Touch when:   never for a new repository.
"""
