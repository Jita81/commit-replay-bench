"""The Helm API serves the kept patches and transcripts the worker writes: one evidence store.

The worker writes every graded attempt's kept patch under ``$CRB_HOME/evidence/patches``
and a retained transcript under ``$CRB_HOME/transcripts/<run>``; the API serves them at
``/grades/{row_hash}/patch`` and ``/grades/{row_hash}/transcript`` from ITS
``$CRB_HOME``. The chart gave the API an ``emptyDir`` there and the worker its own claim,
so on Kubernetes the API could never find what the worker kept (docs/PREVENTION.md
P-045). Both pods now mount one claim, ``evidenceStore``, at those two directories, under
the same placement rule as the secrets store.

Navigation
----------
What it is:   The chart suite that pins one evidence store for the API and the worker pods.
What it does: Renders the chart and, for the API and the worker Deployments, resolves the
              evidence and transcripts directories the way the code does
              (``$CRB_HOME/evidence``, ``$CRB_HOME/transcripts``), finds the volume and
              sub-path that back each, and asserts both pods name the same persistent claim
              and sub-path; that a ReadWriteOnce evidence claim pins both pods to one node
              even when the secrets store is ReadWriteMany, and that the placement refusal
              names the evidence store; that ReadWriteMany claims for both stores lift the
              pin; that an operator's own claim replaces the chart's; and that the claim
              outlives ``helm uninstall``.
How:          ``helm template`` through tests/test_deploy_secrets_store.py's strict loader →
              the Deployment pod specs; skipped without ``helm`` only off CI.
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   deploy/helm/crb/templates/_helpers.tpl (the ``crb.evidenceStore*`` helpers and
              the shared-store pin), deploy/helm/crb/templates/evidence-pvc.yaml (the chart's
              claim), deploy/helm/crb/values.yaml (``evidenceStore``),
              src/crb/server/routes/grades.py and src/crb/server/worker.py (the directories
              this suite resolves), tests/test_deploy_secrets_store.py (the helpers and the
              secrets store's twin suite), docs/PREVENTION.md (P-045)
Tested by:    tests/test_deploy_evidence_store.py
Touch when:   the API or the worker reads or writes another directory under ``$CRB_HOME``
              that the other pod must see; never give the two pods separate evidence stores.
"""

from __future__ import annotations

import posixpath
from typing import Any

from crb.core.patches import PATCHES_DIRNAME
from test_deploy_secrets_store import RWX_STORES, _deployment, _node_pins, _refused, _render

#: The directories under ``$CRB_HOME`` the worker writes and the API serves from: the
#: evidence packs, the kept patches inside them (``PatchStore.under``) and the transcripts.
SHARED = ("evidence", f"evidence/{PATCHES_DIRNAME}", "transcripts")


def _backing(deployment: dict[str, Any], container: str, sub: str) -> tuple[str, str, str]:
    """``(volume kind, identity, sub-path)`` behind ``$CRB_HOME/<sub>`` in one pod."""
    pod = deployment["spec"]["template"]["spec"]
    c = next(x for x in pod["containers"] if x["name"] == container)
    env = {e["name"]: e["value"] for e in c.get("env", []) if "value" in e}
    path = posixpath.join(env["CRB_HOME"], sub)
    mounts = [
        m
        for m in c.get("volumeMounts", [])
        if path == m["mountPath"] or path.startswith(m["mountPath"].rstrip("/") + "/")
    ]
    assert mounts, f"{container}: nothing is mounted over {path}"
    mount = max(mounts, key=lambda m: len(m["mountPath"]))
    volume = next(v for v in pod["volumes"] if v["name"] == mount["name"])
    rest = posixpath.relpath(path, mount["mountPath"])
    sub_path = posixpath.normpath(posixpath.join(mount.get("subPath", ""), rest))
    if "persistentVolumeClaim" in volume:
        return ("pvc", volume["persistentVolumeClaim"]["claimName"], sub_path)
    return ("pod-local", f"{deployment['metadata']['name']}/{volume['name']}", sub_path)


def test_the_api_and_the_worker_resolve_one_evidence_store() -> None:
    """P-045: the API's ``$CRB_HOME/evidence`` and ``$CRB_HOME/transcripts`` are the
    worker's — the same claim and the same sub-path — so a kept patch and a retained
    transcript the worker wrote are there when the API is asked for them."""
    docs = _render()
    api, worker = _deployment(docs, "api"), _deployment(docs, "worker")
    for sub in SHARED:
        a, w = _backing(api, "api", sub), _backing(worker, "worker", sub)
        assert a[0] == "pvc", f"the API's {sub} directory is pod-local: {a}"
        assert a == w, f"{sub}: the API reads {a}, the worker writes {w}"
    claims = {d["metadata"]["name"]: d for d in docs if d["kind"] == "PersistentVolumeClaim"}
    name = _backing(api, "api", "evidence")[1]
    assert name in claims, "the chart makes the evidence claim"
    # kept patches are the product's retained output (P-007): an uninstall keeps them
    assert claims[name]["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"


def test_a_read_write_once_evidence_store_pins_both_pods_on_its_own() -> None:
    """The secrets store on a ReadWriteMany claim lifts ITS pin; a ReadWriteOnce evidence
    claim still attaches to one node, so both pods are pinned to it."""
    docs = _render(
        "--set", "secretsStore.existingClaim=kv", "--set", "secretsStore.accessMode=ReadWriteMany"
    )
    assert _node_pins(_deployment(docs, "api")) and _node_pins(_deployment(docs, "worker"))


def test_read_write_many_claims_for_both_stores_lift_the_pin() -> None:
    docs = _render(*RWX_STORES)
    api, worker = _deployment(docs, "api"), _deployment(docs, "worker")
    assert not _node_pins(api) and not _node_pins(worker)
    for sub in SHARED:
        assert _backing(api, "api", sub) == _backing(worker, "worker", sub)
        assert _backing(api, "api", sub)[:2] == ("pvc", "files")
    assert not [
        d
        for d in docs
        if d["kind"] == "PersistentVolumeClaim" and "evidence" in d["metadata"]["name"]
    ]


def test_the_placement_refusal_names_the_store_that_needs_the_pin() -> None:
    """With the secrets store on ReadWriteMany, a worker on a pool the API cannot follow is
    refused because of the evidence store — and the refusal says so, with its way out."""
    err = _refused(
        "--set",
        "secretsStore.existingClaim=kv",
        "--set",
        "secretsStore.accessMode=ReadWriteMany",
        "--set",
        "worker.nodeSelector.crb\\.dev/pool=worker",
    )
    assert "evidenceStore.accessMode=ReadWriteOnce" in err, err
    assert "secretsStore.accessMode=ReadWriteOnce" not in err, err
    assert "evidenceStore.existingClaim" in err and "ReadWriteMany" in err, err


def test_an_evidence_access_mode_other_than_once_or_many_is_refused() -> None:
    err = _refused("--set", "evidenceStore.accessMode=ReadOnlyMany")
    assert "evidenceStore.accessMode must be ReadWriteOnce | ReadWriteMany" in err, err
