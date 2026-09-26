"""The Helm API and worker read and write ONE secrets store.

The API writes the stored credentials (Settings → Claude Code login, the tracker token) and
checks them at submit; the worker reads them at build time. The chart used to mount an
``emptyDir`` at ``/srv/crb`` on the API and the worker's own claim at ``/srv/crb`` on the
worker, with no ``CRB_SECRETS_DIR``: a token saved through Settings landed where the worker
never looks, the API's presence check passed, the run was queued and every attempt failed —
the failure P-003 refuses at submit, moved to a place the check could not see
(the adversarial check on PR #57, 2026-09-26; docs/PREVENTION.md P-043).

Navigation
----------
What it is:   The chart suite that pins one secrets store for the API and the worker pods.
What it does: Renders the chart and, for the API and the worker Deployments, resolves the
              secrets directory the way the code does (``CRB_SECRETS_DIR``, else
              ``$CRB_HOME/secrets``), finds the volume that backs it, and asserts both pods
              name the same directory on the same persistent claim; that a ReadWriteOnce claim
              pins both pods to one node (merged with any affinity the operator sets); and that
              an operator's own claim replaces the chart's.
How:          ``helm template`` → ``yaml.safe_load_all`` → the Deployment pod specs; skipped
              without ``helm`` only off CI (on CI a missing ``helm`` fails the suite).
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         none
Works with:   deploy/helm/crb/templates/_helpers.tpl (the ``crb.secretsStore*`` helpers both
              pods include), deploy/helm/crb/templates/secrets-pvc.yaml (the chart's claim),
              deploy/helm/crb/values.yaml (``secretsStore``), src/crb/core/secrets_file.py
              (``resolve_secrets_dir``, the resolution this suite mirrors),
              docs/PREVENTION.md (P-043, the row this suite closes)
Tested by:    tests/test_deploy_secrets_store.py
Touch when:   a pod that reads or writes the secrets store is added to the chart, or the
              store's resolution changes in src/crb/core/secrets_file.py; never give the API
              and the worker separate stores.
"""

from __future__ import annotations

import os
import posixpath
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from crb.core.secrets_file import resolve_secrets_dir

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "deploy" / "helm" / "crb"
BASE = ["--set", "networkPolicy.postgres.cidrs={10.0.0.0/8}"]
HOSTNAME = "kubernetes.io/hostname"

if shutil.which("helm") is None:
    if os.environ.get("CI"):
        pytest.fail("helm is not on PATH on CI: the chart's secrets store would go unchecked")
    pytest.skip("helm not on PATH", allow_module_level=True)


def _render(*args: str) -> list[dict[str, Any]]:
    r = subprocess.run(
        ["helm", "template", "t", str(CHART), *BASE, *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _deployment(docs: list[dict[str, Any]], component: str) -> dict[str, Any]:
    return next(
        d
        for d in docs
        if d["kind"] == "Deployment"
        and d["metadata"]["labels"].get("app.kubernetes.io/component") == component
    )


def _store(deployment: dict[str, Any], container: str) -> tuple[str, tuple[str, str]]:
    """``(secrets dir, (volume kind, identity))`` for one pod — the directory resolved as
    :func:`resolve_secrets_dir` resolves it, and the volume whose mount holds it."""
    pod = deployment["spec"]["template"]["spec"]
    c = next(x for x in pod["containers"] if x["name"] == container)
    env = {e["name"]: e["value"] for e in c.get("env", []) if "value" in e}
    secrets_dir = str(resolve_secrets_dir(env))
    mounts = [
        m
        for m in c.get("volumeMounts", [])
        if secrets_dir == m["mountPath"] or secrets_dir.startswith(m["mountPath"].rstrip("/") + "/")
    ]
    assert mounts, f"{container}: nothing is mounted over {secrets_dir} (the read-only root)"
    mount = max(mounts, key=lambda m: len(m["mountPath"]))
    volume = next(v for v in pod["volumes"] if v["name"] == mount["name"])
    if "persistentVolumeClaim" in volume:
        backing = ("pvc", volume["persistentVolumeClaim"]["claimName"])
    else:
        # an emptyDir (or any pod-local volume) is private to its pod
        backing = ("pod-local", f"{deployment['metadata']['name']}/{volume['name']}")
    return posixpath.normpath(secrets_dir), backing


def _pod_labels(deployment: dict[str, Any]) -> dict[str, str]:
    return dict(deployment["spec"]["template"]["metadata"]["labels"])


def _node_pins(deployment: dict[str, Any]) -> list[dict[str, Any]]:
    pod = deployment["spec"]["template"]["spec"]
    affinity = (pod.get("affinity") or {}).get("podAffinity") or {}
    return [
        t
        for t in affinity.get("requiredDuringSchedulingIgnoredDuringExecution", [])
        if t.get("topologyKey") == HOSTNAME
    ]


def test_the_api_and_the_worker_resolve_one_secrets_store() -> None:
    docs = _render()
    api = _store(_deployment(docs, "api"), "api")
    worker = _store(_deployment(docs, "worker"), "worker")
    assert api[1][0] == "pvc", f"the API's secrets store is pod-local: {api}"
    assert api == worker, f"the API writes {api}, the worker reads {worker}"
    claims = [d for d in docs if d["kind"] == "PersistentVolumeClaim"]
    assert any(c["metadata"]["name"] == api[1][1] for c in claims), "the chart makes the claim"


def test_a_read_write_once_store_pins_the_api_and_the_worker_to_one_node() -> None:
    docs = _render("--set", "api.affinity.nodeAffinity.x=1")
    api, worker = _deployment(docs, "api"), _deployment(docs, "worker")
    for d in (api, worker):
        pins = _node_pins(d)
        assert pins, f"{d['metadata']['name']}: a ReadWriteOnce store with no node pin"
        # the pin selects BOTH pods, so whichever is scheduled first decides the node
        for labels in (_pod_labels(api), _pod_labels(worker)):
            assert any(
                all(labels.get(k) == v for k, v in t["labelSelector"]["matchLabels"].items())
                for t in pins
            )
    # the operator's own affinity is kept, not replaced
    assert _deployment(docs, "api")["spec"]["template"]["spec"]["affinity"]["nodeAffinity"]


def test_an_operators_claim_replaces_the_charts_and_many_nodes_need_no_pin() -> None:
    docs = _render(
        "--set",
        "secretsStore.existingClaim=kv-secrets",
        "--set",
        "secretsStore.accessMode=ReadWriteMany",
    )
    api = _store(_deployment(docs, "api"), "api")
    assert api == _store(_deployment(docs, "worker"), "worker")
    assert api[1] == ("pvc", "kv-secrets")
    assert not [
        d
        for d in docs
        if d["kind"] == "PersistentVolumeClaim" and "secrets" in d["metadata"]["name"]
    ]
    assert not _node_pins(_deployment(docs, "api")) and not _node_pins(_deployment(docs, "worker"))
