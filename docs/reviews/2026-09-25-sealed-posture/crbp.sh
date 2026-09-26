#!/bin/bash
# `crb` with the proof's provisioning environment (docs/reviews/2026-09-25-sealed-posture.md).
# Set CRB_HOME to a THROWAWAY directory the docker daemon can bind-mount (under colima: under
# $HOME) and REPO_ROOT to a checkout of this repository. Never point CRB_HOME at a live stack.
: "${CRB_HOME:?set CRB_HOME to a throwaway directory}" "${REPO_ROOT:?set REPO_ROOT}"
unset CRB_ENV
export CRB_PROVISION__ENABLED=true CRB_PROVISION__ALLOW_PUBLIC=true
export CRB_PROVISION__STORE="$CRB_HOME/deps"
export CRB_PROVISION__PROXY_IMAGE=python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
export PYTHONPATH="$REPO_ROOT/src"
exec "$REPO_ROOT/.venv/bin/python" -W ignore -m crb.cli.main "$@"
