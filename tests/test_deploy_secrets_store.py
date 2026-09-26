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
              pins both pods to one node (merged with any affinity the operator sets) and is
              refused when the API could not follow the worker's placement (P-046); that an
              operator's own claim replaces the chart's; that no pod label or annotation the
              chart sets can be set again in ``podLabels`` / ``podAnnotations`` (P-047); and
              that every claim the chart makes is named in DEPLOYMENT §5, the recovery
              procedure (P-048).
How:          ``helm template`` → a YAML loader that refuses a repeated key → the Deployment
              pod specs; skipped without ``helm`` only off CI (on CI a missing ``helm`` fails
              the suite).
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         none
Works with:   deploy/helm/crb/templates/_helpers.tpl (the ``crb.secretsStore*`` helpers both
              pods include), deploy/helm/crb/templates/secrets-pvc.yaml (the chart's claim),
              deploy/helm/crb/values.yaml (``secretsStore``), src/crb/core/secrets_file.py
              (``resolve_secrets_dir``, the resolution this suite mirrors),
              docs/DEPLOYMENT.md (§3.2 and §5, the placement rule and the recovery procedure),
              docs/PREVENTION.md (P-043, P-046 to P-048, the rows this suite closes)
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


class _StrictLoader(yaml.SafeLoader):
    """A loader that refuses a repeated mapping key. PyYAML keeps the last value of a repeated
    key without a word, so a pod label the operator repeats would pass every assertion here
    while the manifest carried both values (CodeRabbit on PR #57, P-047)."""


def _no_repeated_keys(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        assert key not in seen, f"line {key_node.start_mark.line + 1}: the key {key!r} is repeated"
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_repeated_keys)


def _helm(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "t", str(CHART), *BASE, *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _render(*args: str) -> list[dict[str, Any]]:
    r = _helm(*args)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.load_all(r.stdout, Loader=_StrictLoader) if d]


def _refused(*args: str) -> str:
    """The render's error text; the render must fail."""
    r = _helm(*args)
    assert r.returncode != 0, f"the chart rendered {args}"
    return r.stderr


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


#: The dedicated, tainted worker pool of docs/DEPLOYMENT.md §3.1 and §4.4.
WORKER_POOL = (
    "--set",
    "worker.nodeSelector.crb\\.dev/pool=worker",
    "--set",
    "worker.tolerations[0].key=crb.dev/worker",
    "--set",
    "worker.tolerations[0].operator=Exists",
    "--set",
    "worker.tolerations[0].effect=NoSchedule",
)


def test_a_read_write_once_store_refuses_a_worker_placement_the_api_cannot_follow() -> None:
    """The pin puts the API on the worker's node. A worker on a tainted pool the API does not
    tolerate would leave whichever pod is scheduled second pending for ever, so the render
    refuses it and names both ways out (CodeRabbit on PR #57, P-046)."""
    err = _refused(*WORKER_POOL)
    for name in ("api.nodeSelector", "api.tolerations", "ReadWriteMany"):
        assert name in err, err
    # either way out renders: the API placed with the worker ...
    same = [a.replace("worker.", "api.", 1) if a.startswith("worker.") else a for a in WORKER_POOL]
    docs = _render(*WORKER_POOL, *same)
    api, worker = _deployment(docs, "api"), _deployment(docs, "worker")
    assert (
        api["spec"]["template"]["spec"]["tolerations"]
        == (worker["spec"]["template"]["spec"]["tolerations"])
    )
    assert _node_pins(api) and _node_pins(worker)
    # ... or a claim that many nodes can mount, which needs no pin
    rwx = (
        "--set",
        "secretsStore.existingClaim=kv",
        "--set",
        "secretsStore.accessMode=ReadWriteMany",
    )
    assert not _node_pins(_deployment(_render(*WORKER_POOL, *rwx), "worker"))


def _set_key(key: str) -> str:
    return key.replace(".", "\\.")


@pytest.mark.parametrize("component", ["api", "worker"])
@pytest.mark.parametrize("field", ["labels", "annotations"])
def test_a_pod_map_cannot_overwrite_a_key_the_chart_sets(component: str, field: str) -> None:
    """Every label and annotation the chart puts on a pod — read from the render, so a key
    added later is covered — is refused in ``<component>.pod<Field>``. An operator's value would
    otherwise repeat the key: the store's pin would stop selecting the pod, or the Deployment's
    selector would stop matching its own pods (CodeRabbit on PR #57, P-047)."""
    owned = _deployment(_render(), component)["spec"]["template"]["metadata"][field]
    assert owned, f"the chart sets no pod {field} on the {component}"
    values = f"{component}.pod{field.capitalize()}"
    for key in owned:
        err = _refused("--set-string", f"{values}.{_set_key(key)}=operator")
        assert f"{values}" in err and key in err, err
    # a key of the operator's own is kept
    docs = _render("--set-string", f"{values}.team=payments")
    assert _deployment(docs, component)["spec"]["template"]["metadata"][field]["team"] == "payments"


#: Each persistent claim the chart can make, by its component, and the words §5 of
#: docs/DEPLOYMENT.md must use to name it in the recovery procedure.
CLAIM_IN_RECOVERY = {
    "worker": "`worker.workDir`",
    "secrets-store": "`secretsStore`",
    "postgres": "the database",
}


def test_every_claim_the_chart_makes_is_in_the_recovery_procedure() -> None:
    """A claim the chart makes holds state; §5 (backup and restore) must say what to do with
    it, or an operator who follows §5 cannot bring it back (CodeRabbit on PR #57, P-048)."""
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    section = text.split("## 5. Backup and restore", 1)[1].split("\n## 6.", 1)[0]
    components: set[str] = set()
    for docs in (_render(), _render("--set", "postgresql.mode=embedded")):
        for d in docs:
            spec = d.get("spec") or {}
            if d["kind"] == "PersistentVolumeClaim" or spec.get("volumeClaimTemplates"):
                components.add(d["metadata"]["labels"]["app.kubernetes.io/component"])
    assert components, "the chart renders no claim"
    unmapped = components - CLAIM_IN_RECOVERY.keys()
    assert not unmapped, (
        f"a new claim {unmapped}: name it in DEPLOYMENT §5 and in CLAIM_IN_RECOVERY"
    )
    for component in sorted(components):
        assert CLAIM_IN_RECOVERY[component] in section, (
            f"DEPLOYMENT §5 does not name the {component} claim ({CLAIM_IN_RECOVERY[component]})"
        )
