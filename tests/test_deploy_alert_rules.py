"""The chart ships DEPLOYMENT §9.2's four alert rules, so no deployment retypes them.

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
              four alerts of DEPLOYMENT §9.2, each ``expr`` the table's own expression; that
              the false-Q1 alert fires on any non-zero value with no delay; that the
              operator's labels reach the resource; and that a worker with its metrics port
              off is refused, since three of the four rules read the worker's series.
How:          ``helm template`` through tests/test_deploy_secrets_store.py's strict loader;
              the guide's table read with a regular expression.
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         none
Works with:   deploy/helm/crb/templates/prometheusrule.yaml (under test),
              deploy/helm/crb/values.yaml (``prometheusRule``), docs/DEPLOYMENT.md §9.2 (the
              table it reads), docs/dod/product.md (go-live.20)
Tested by:    tests/test_deploy_alert_rules.py
Touch when:   an alert rule is added or changed — change the table in DEPLOYMENT §9.2 and the
              template together; this suite fails until they agree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from test_deploy_secrets_store import _refused, _render

ROOT = Path(__file__).resolve().parent.parent
ENABLED = ("--set", "prometheusRule.enabled=true")
#: The table's alert names, and the name each carries in the rendered rule.
ALERTS = {
    "False-Q1": "CrbFalseQ1",
    "No worker": "CrbNoWorker",
    "Sandbox failing closed": "CrbSandboxFailingClosed",
    "Deliveries failing": "CrbDeliveriesFailing",
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
