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
              refused when the API could not follow the worker's placement — a difference in
              ``nodeSelector``, ``tolerations`` or any kind of ``affinity`` — or a required
              pod anti-affinity, the same on both pods, that selects a pod carrying the
              store (P-046); that an
              operator's own claim replaces the chart's; that no pod label or annotation the
              chart sets can be set again in ``podLabels`` / ``podAnnotations`` (P-047); and
              that every claim the chart makes is named in DEPLOYMENT §5, the recovery
              procedure (P-048); and that each restore order there brings the credentials
              back before it starts the worker (P-049).
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
              docs/PREVENTION.md (P-043, P-046 to P-049, the rows this suite closes)
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


#: An operator's own affinity, the same on both pods (a difference is refused, P-046).
_ZONE = (
    "affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[0]"
    ".matchExpressions[0]"
)
OWN_AFFINITY = tuple(
    arg
    for pod in ("api", "worker")
    for kv in ("key=topology.kubernetes.io/zone", "operator=In", "values={uksouth-1}")
    for arg in ("--set", f"{pod}.{_ZONE}.{kv}")
)


def test_a_read_write_once_store_pins_the_api_and_the_worker_to_one_node() -> None:
    docs = _render(*OWN_AFFINITY)
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
    for d in (api, worker):
        assert d["spec"]["template"]["spec"]["affinity"]["nodeAffinity"], d["metadata"]["name"]


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


#: Every PodSpec field that decides which node a pod may run on (the Kubernetes scheduler's
#: own inputs), and the three kinds of ``affinity``. A field the chart can emit on the API or
#: the worker must be compared by ``crb.secretsStore.samePlacement``.
PLACEMENT_FIELDS = (
    "nodeSelector",
    "tolerations",
    "affinity",
    "topologySpreadConstraints",
    "nodeName",
    "schedulerName",
)
AFFINITY_KINDS = ("nodeAffinity", "podAffinity", "podAntiAffinity")
_TERM = "requiredDuringSchedulingIgnoredDuringExecution"

#: For each placement value (a field, or ``affinity.<kind>``), the ``--set`` arguments that
#: place the worker only. Each is a placement the API cannot be assumed to follow.
WORKER_ONLY_PLACEMENT = {
    "nodeSelector": ("--set", "worker.nodeSelector.crb\\.dev/pool=worker"),
    "tolerations": (
        "--set",
        "worker.tolerations[0].key=crb.dev/worker",
        "--set",
        "worker.tolerations[0].operator=Exists",
        "--set",
        "worker.tolerations[0].effect=NoSchedule",
    ),
    # the §3.1 pool expressed as required node affinity instead of a nodeSelector
    "affinity.nodeAffinity": (
        "--set",
        f"worker.affinity.nodeAffinity.{_TERM}.nodeSelectorTerms[0]"
        ".matchExpressions[0].key=crb.dev/pool",
        "--set",
        f"worker.affinity.nodeAffinity.{_TERM}.nodeSelectorTerms[0]"
        ".matchExpressions[0].operator=In",
        "--set",
        f"worker.affinity.nodeAffinity.{_TERM}.nodeSelectorTerms[0]"
        ".matchExpressions[0].values={worker}",
    ),
    "affinity.podAffinity": (
        "--set",
        f"worker.affinity.podAffinity.{_TERM}[0].labelSelector.matchLabels.app=gpu-cache",
        "--set",
        f"worker.affinity.podAffinity.{_TERM}[0].topologyKey={HOSTNAME}",
    ),
    "affinity.podAntiAffinity": (
        "--set",
        f"worker.affinity.podAntiAffinity.{_TERM}[0].labelSelector.matchLabels.app=noisy",
        "--set",
        f"worker.affinity.podAntiAffinity.{_TERM}[0].topologyKey={HOSTNAME}",
    ),
}


def _as_api(args: tuple[str, ...]) -> list[str]:
    return [a.replace("worker.", "api.", 1) if a.startswith("worker.") else a for a in args]


def test_every_placement_field_the_chart_emits_is_compared() -> None:
    """The class behind P-046: a placement field the chart lets the operator set on the API or
    the worker, but that the same-placement guard does not compare, leaves one pod pending. The
    first fix compared ``nodeSelector`` and ``tolerations`` and missed ``affinity`` (the
    adversarial check on PR #57). Any field a pod template (or a helper it includes) can emit
    must have a worker-only case below, so a field added later fails here until it is
    compared."""
    templates = "\n".join(
        (CHART / "templates" / name).read_text()
        for name in ("api-deployment.yaml", "worker-deployment.yaml", "_helpers.tpl")
    )
    emitted = [
        f for f in PLACEMENT_FIELDS if any(ln.strip() == f"{f}:" for ln in templates.splitlines())
    ]
    assert "affinity" in emitted and "nodeSelector" in emitted, emitted
    covered = {k.split(".", 1)[0] for k in WORKER_ONLY_PLACEMENT}
    assert set(emitted) <= covered, f"placement fields with no case: {set(emitted) - covered}"
    assert {f"affinity.{k}" for k in AFFINITY_KINDS} <= set(WORKER_ONLY_PLACEMENT)


@pytest.mark.parametrize("placement", sorted(WORKER_ONLY_PLACEMENT))
def test_a_read_write_once_store_refuses_any_worker_only_placement(placement: str) -> None:
    """A worker placed through required node affinity (or pod affinity, or anti-affinity) the
    API does not share is the P-046 failure by another route: the API is scheduled on a general
    node, the pin sends the worker after it, and the worker's own rule forbids that node. The
    render refuses it and names ``api.<field>``; the same placement on both pods renders."""
    worker_only = WORKER_ONLY_PLACEMENT[placement]
    err = _refused(*worker_only)
    assert f"api.{placement.split('.', 1)[0]}" in err and "ReadWriteMany" in err, err
    docs = _render(*worker_only, *_as_api(worker_only))
    api, worker = _deployment(docs, "api"), _deployment(docs, "worker")
    assert _node_pins(api) and _node_pins(worker)
    if placement.startswith("affinity."):
        kind = placement.split(".", 1)[1]
        for d in (api, worker):
            assert kind in d["spec"]["template"]["spec"]["affinity"], d["metadata"]["name"]


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


def _recovery_section() -> str:
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    return text.split("## 5. Backup and restore", 1)[1].split("\n## 6.", 1)[0]


def _restore_orders(section: str) -> list[list[str]]:
    """Each ``Restore order …:`` paragraph of §5, as its steps (split on ``→``)."""
    orders = []
    for para in section.split("\n\n"):
        flat = " ".join(para.split())
        if flat.startswith("Restore order"):
            orders.append([s.strip() for s in flat.split(":", 1)[1].split("→")])
    return orders


def _started(step: str) -> set[str]:
    """The pods a ``start …`` step starts, read before any parenthesis."""
    if not step.lower().startswith("start "):
        return set()
    head = step.split("(", 1)[0]
    return {pod for pod in ("api", "worker") if f" {pod}" in f" {head}"}


def test_the_recovery_procedure_starts_the_worker_only_after_the_credentials() -> None:
    """The submit check (P-003) is the only credential check: the worker claims a run that
    was queued or running at backup time as soon as it starts, and checks nothing. So each
    restore order in §5 must bring the credentials back before it starts the worker, and the
    path that supplies them through Settings must start the api alone first (CodeRabbit on
    PR #57, P-049)."""
    orders = _restore_orders(_recovery_section())
    assert orders, "DEPLOYMENT §5 has no `Restore order …:` paragraph"
    via_settings = 0
    for steps in orders:
        creds = [i for i, s in enumerate(steps) if "secrets store" in s or "credentials" in s]
        workers = [i for i, s in enumerate(steps) if "worker" in _started(s)]
        assert creds and workers, f"a restore order names no credential or no worker: {steps}"
        assert creds[0] < workers[0], f"the worker starts before the credentials: {steps}"
        if "Settings" in steps[creds[0]]:
            via_settings += 1
            api_first = [i for i, s in enumerate(steps[: creds[0]]) if "api" in _started(s)]
            assert api_first, f"Settings is used before the api is started: {steps}"
            assert all("worker" not in _started(s) for s in steps[: creds[0]]), steps
    # §5 offers two choices for the store (restore the claim, or supply the credentials
    # again), so it gives an order for each
    assert len(orders) >= 2 and via_settings >= 1, orders


def test_a_read_write_once_store_refuses_opposing_required_node_affinities() -> None:
    """Both pods carry required node affinity, to different zones: neither is missing a
    rule, but no node satisfies both, so the pin leaves one pending. The guard compares the
    values, not only their presence (CodeRabbit on PR #57, P-046)."""
    term = f"affinity.nodeAffinity.{_TERM}.nodeSelectorTerms[0].matchExpressions[0]"
    args: list[str] = []
    for pod, zone in (("api", "zone-a"), ("worker", "zone-b")):
        args += ["--set", f"{pod}.{term}.key=topology.kubernetes.io/zone"]
        args += ["--set", f"{pod}.{term}.operator=In"]
        args += ["--set", f"{pod}.{term}.values={{{zone}}}"]
    err = _refused(*args)
    assert "api.affinity" in err and "ReadWriteMany" in err, err


def _anti(*term: str) -> list[str]:
    """``--set`` arguments that give BOTH pods the same required pod anti-affinity term (so
    the same-placement guard passes); ``term`` is ``key=value`` under the term."""
    return [
        arg
        for pod in ("api", "worker")
        for kv in term
        for arg in ("--set", f"{pod}.affinity.podAntiAffinity.{_TERM}[0].{kv}")
    ]


#: Required anti-affinity terms that select a pod the store pin must place beside the other:
#: the same on both pods, but each forbids the node the pin sends the other pod to (the
#: adversarial check on PR #57; the guard's own "give the api the worker's placement" leads
#: here). Each selects a label the chart (or the operator's podLabels) puts on a store pod.
REPELLING_ANTI_AFFINITY = {
    "the worker's component": (
        "labelSelector.matchLabels.app\\.kubernetes\\.io/component=worker",
        f"topologyKey={HOSTNAME}",
    ),
    "the api's component": (
        "labelSelector.matchLabels.app\\.kubernetes\\.io/component=api",
        f"topologyKey={HOSTNAME}",
    ),
    "the store label": (
        "labelSelector.matchLabels.crb\\.dev/secrets-store=shared",
        f"topologyKey={HOSTNAME}",
    ),
    "a selector label, by expression": (
        "labelSelector.matchExpressions[0].key=app\\.kubernetes\\.io/instance",
        "labelSelector.matchExpressions[0].operator=Exists",
        f"topologyKey={HOSTNAME}",
    ),
    # one node is one zone, so a zone-wide rule repels the pod beside it just the same
    "the worker's component, zone-wide": (
        "labelSelector.matchExpressions[0].key=app\\.kubernetes\\.io/component",
        "labelSelector.matchExpressions[0].operator=In",
        "labelSelector.matchExpressions[0].values={worker}",
        "topologyKey=topology.kubernetes.io/zone",
    ),
}


@pytest.mark.parametrize("case", sorted(REPELLING_ANTI_AFFINITY))
def test_a_read_write_once_store_refuses_anti_affinity_that_repels_a_store_pod(case: str) -> None:
    """The pin puts every pod that mounts the store on the node of the first one scheduled. A
    required pod anti-affinity that selects one of those pods forbids exactly that node, and
    Kubernetes applies a placed pod's anti-affinity to new pods too, so whichever pod is
    scheduled second stays pending [hypothesis — inferred from Kubernetes' scheduling rules;
    no cluster was run]. The values are the same on both pods, so comparing them cannot catch
    it: the render refuses the term itself (the adversarial check on PR #57, P-046)."""
    err = _refused(*_anti(*REPELLING_ANTI_AFFINITY[case]))
    assert "podAntiAffinity" in err and "ReadWriteMany" in err, err
    assert "give the api the worker's placement" not in err, err
    # ... and a claim that many nodes can mount needs no pin, so the same term renders
    rwx = (
        "--set",
        "secretsStore.existingClaim=kv",
        "--set",
        "secretsStore.accessMode=ReadWriteMany",
    )
    assert not _node_pins(_deployment(_render(*_anti(*REPELLING_ANTI_AFFINITY[case]), *rwx), "api"))


def test_an_operators_pod_label_counts_as_a_store_pods_label() -> None:
    """``worker.podLabels`` is on the worker pod, so an anti-affinity that selects it repels the
    worker just as a chart label does."""
    labels = ("--set", "worker.podLabels.team=builds")
    err = _refused(
        *labels, *_anti("labelSelector.matchLabels.team=builds", f"topologyKey={HOSTNAME}")
    )
    assert "podAntiAffinity" in err, err


#: Negative controls: required anti-affinity terms that select no store pod render.
NON_REPELLING_ANTI_AFFINITY = {
    "another app": ("labelSelector.matchLabels.app=noisy", f"topologyKey={HOSTNAME}"),
    "neither component": (
        "labelSelector.matchExpressions[0].key=app\\.kubernetes\\.io/component",
        "labelSelector.matchExpressions[0].operator=NotIn",
        "labelSelector.matchExpressions[0].values={api,worker}",
        f"topologyKey={HOSTNAME}",
    ),
    "a label no store pod carries": (
        "labelSelector.matchExpressions[0].key=crb\\.dev/other",
        "labelSelector.matchExpressions[0].operator=Exists",
        f"topologyKey={HOSTNAME}",
    ),
    "the worker's component in another namespace": (
        "labelSelector.matchLabels.app\\.kubernetes\\.io/component=worker",
        "namespaces={elsewhere}",
        f"topologyKey={HOSTNAME}",
    ),
}


@pytest.mark.parametrize("case", sorted(NON_REPELLING_ANTI_AFFINITY))
def test_anti_affinity_that_selects_no_store_pod_renders(case: str) -> None:
    docs = _render(*_anti(*NON_REPELLING_ANTI_AFFINITY[case]))
    for component in ("api", "worker"):
        d = _deployment(docs, component)
        assert _node_pins(d), component
        assert d["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"], component
