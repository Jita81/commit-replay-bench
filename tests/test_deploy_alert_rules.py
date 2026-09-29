"""The chart ships DEPLOYMENT §9.2's alert rules (four at first, seven since Wave 6), so no
deployment retypes them.

The rules existed only as expressions in docs/DEPLOYMENT.md §9.2: every deployment copied
them into its own Prometheus, and a typo there was silent — an alert on the honesty floor
that can never fire looks exactly like a floor that holds (G-602). The chart now renders
them as a ``PrometheusRule`` (the Prometheus Operator's resource), off by default, and this
suite holds the rendered expressions to the guide's table word for word.

Navigation
----------
What it is:   The chart suite for the ``PrometheusRule`` template.
What it does: Renders the chart with and without ``prometheusRule.enabled`` and asserts that
              nothing is rendered by default; that the enabled render carries exactly the
              alerts of DEPLOYMENT §9.2 (``ALERTS``), each ``expr`` the table's own expression; that
              the false-Q1 alert fires on any non-zero value with no delay; that the
              operator's labels reach the resource; that a worker with its metrics port
              off is refused, since three of the four rules read the worker's series; and
              that the no-worker rule reads a series the API's exposition never serves, so it
              can fire while the API is scraped (P-268).
How:          ``helm template`` through tests/test_deploy_secrets_store.py's strict loader;
              the guide's table read with a regular expression; the API's exposition from
              ``metrics.render_api``.
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         none
Works with:   deploy/helm/crb/templates/prometheusrule.yaml (under test),
              deploy/helm/crb/values.yaml (``prometheusRule``), docs/DEPLOYMENT.md §9.2 (the
              table it reads), src/crb/observability/metrics.py (``render_api``),
              docs/dod/product.md (go-live.20)
Tested by:    tests/test_deploy_alert_rules.py
Touch when:   never for a new repository; an alert rule is added or changed — change the table in
              DEPLOYMENT §9.2 and the template together; this suite fails until they agree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from crb.observability import metrics
from test_deploy_secrets_store import _refused, _render

ROOT = Path(__file__).resolve().parent.parent
ENABLED = ("--set", "prometheusRule.enabled=true")
#: The table's alert names, and the name each carries in the rendered rule.
ALERTS = {
    "False-Q1": "CrbFalseQ1",
    "No worker": "CrbNoWorker",
    "Sandbox failing closed": "CrbSandboxFailingClosed",
    "Deliveries failing": "CrbDeliveriesFailing",
    # Wave 6 (ops): the three stop conditions OPERATOR §8 named and nothing reported (G-400,
    # G-920) — the same table row, chart rule and name discipline as the first four
    "Controls not passed": "CrbControlsNotPassed",
    "Disqualified rising": "CrbDisqualifiedRising",
    "Egress denied": "CrbEgressDenied",
}


def _guide_expressions() -> dict[str, str]:
    """``{alert: expression}`` from the table in DEPLOYMENT §9.2 (the first code span of the
    Expression column)."""
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    section = text.split("### 9.2 Alert rules", 1)[1].split("\n### ", 1)[0]
    rows = re.findall(r"^\| \*\*(.+?)\*\* \| `([^`]+)`", section, flags=re.MULTILINE)
    return dict(rows)


def _rules(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    (rule,) = [d for d in docs if d["kind"] == "PrometheusRule"]
    return {r["alert"]: r for g in rule["spec"]["groups"] for r in g["rules"]}


def test_no_alert_rule_is_rendered_by_default() -> None:
    assert not [d for d in _render() if d["kind"] == "PrometheusRule"]


def test_the_chart_carries_the_guides_four_rules_word_for_word() -> None:
    """Named for the four rules it began with (docs/dod/product.md go-live.20 cites it); it
    holds every rule in ``ALERTS`` — seven since Wave 6 — to the guide word for word."""
    guide = _guide_expressions()
    assert set(guide) == set(ALERTS), f"DEPLOYMENT §9.2 lists {sorted(guide)}"
    rules = _rules(_render(*ENABLED))
    assert set(rules) == set(ALERTS.values())
    for name, alert in ALERTS.items():
        assert rules[alert]["expr"] == guide[name], (
            f"{alert}: the chart says {rules[alert]['expr']!r}, the guide {guide[name]!r}"
        )
        assert rules[alert]["labels"]["severity"] in ("critical", "warning")
        assert rules[alert]["annotations"]["summary"], alert


def test_the_false_q1_alert_fires_on_any_non_zero_value_at_once() -> None:
    """go-live.20: the honesty floor is breached by one clean row with a failed belt; the
    alert waits for nothing and is critical."""
    rule = _rules(_render(*ENABLED))["CrbFalseQ1"]
    assert rule["expr"] == "max(crb_false_q1_total) > 0"
    assert rule.get("for", "0m") in ("0m", "0s")
    assert rule["labels"]["severity"] == "critical"
    assert "OPERATOR.md#8-stop-conditions" in rule["annotations"]["runbook_url"]


def test_the_operators_labels_reach_the_rule_so_prometheus_selects_it() -> None:
    docs = _render(*ENABLED, "--set", "prometheusRule.labels.release=kube-prometheus")
    (rule,) = [d for d in docs if d["kind"] == "PrometheusRule"]
    assert rule["metadata"]["labels"]["release"] == "kube-prometheus"
    assert rule["metadata"]["labels"]["app.kubernetes.io/name"] == "crb"


def test_rules_that_read_the_worker_are_refused_while_its_metrics_are_off() -> None:
    err = _refused(*ENABLED, "--set", "worker.metrics.port=0")
    assert "prometheusRule.enabled" in err and "worker.metrics.port" in err, err


def _served(exposition: bytes) -> set[str]:
    """The sample names an exposition carries (``name{labels} value`` or ``name value``)."""
    return {
        line.split("{", 1)[0].split(" ", 1)[0]
        for line in exposition.decode().splitlines()
        if line and not line.startswith("#")
    }


def test_the_no_worker_rule_reads_a_series_the_api_never_serves() -> None:
    """``absent_over_time`` fires only while NO scraped target serves the series. The API's
    ``/metrics`` once served ``crb_queue_depth 0.0`` (an unlabelled gauge in the shared
    registry), and DEPLOYMENT §9.2 has both targets scraped, so with no worker at all the
    critical alert stayed silent — G-602's class, an alert that can never fire (P-268). The
    API's exposition is ``metrics.render_api()`` (tests/test_server_system.py pins that the
    route serves it); the worker's is the whole registry, which must carry the series."""
    rule = _rules(_render(*ENABLED))["CrbNoWorker"]
    read = re.findall(r"absent_over_time\((crb_[a-z0-9_]+)", rule["expr"])
    assert read, rule["expr"]
    api = _served(metrics.render_api())
    assert "crb_false_q1_total" in api, "the API's exposition lost the honesty gauge"
    assert not set(read) & api, f"the API serves {sorted(set(read) & api)}: CrbNoWorker is mute"
    # the negative control: the worker's exposition serves it, so the rule is not vacuous
    assert set(read) <= _served(metrics.render())
