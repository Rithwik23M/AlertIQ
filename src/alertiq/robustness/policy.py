"""
Performance degradation monitoring policy for AlertIQ Milestone 3.

This module defines:
  - Alert triggers (when to raise an alarm)
  - Alert severities (P0 = stop production, P1 = escalate, P2 = investigate)
  - Recommended actions per trigger
  - An evaluation function that checks a set of metrics against all triggers

Design principles
-----------------
1. Triggers are defined declaratively — no hidden logic.
2. Each trigger has an explicit severity, metric, threshold direction, and action.
3. Triggers are evaluated independently — multiple can fire simultaneously.
4. No trigger requires test data for calibration; all thresholds are based on
   domain knowledge and M3 experimental findings.
5. P0 triggers must halt production deployment; P1/P2 are escalation / watch.

Trigger table
-------------
ID       Severity  Metric                 Condition              Action
------   --------  --------------------   --------------------   -------
T01      P0        recall_at_20pct        < 0.40                 Halt
T02      P0        auc_roc                < 0.65                 Halt
T03      P1        recall_at_20pct        < 0.50                 Escalate
T04      P1        auc_roc                < 0.70                 Escalate
T05      P1        ece                    >= 0.05                Escalate
T06      P1        max_psi (any feature)  >= 0.25                Escalate
T07      P2        recall_at_20pct drift  |Δ| > 0.08 vs prev    Investigate
T08      P2        threshold_drift        |Δ| > 0.10 vs prev     Investigate
T09      P2        sar_rate_drift         |Δ| > 0.03 vs baseline Investigate
T10      P2        auc_roc_drift          |Δ| > 0.05 vs prev     Investigate
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trigger definitions
# ---------------------------------------------------------------------------

SEVERITY_LABELS = {0: "P0", 1: "P1", 2: "P2"}


@dataclasses.dataclass(frozen=True)
class Trigger:
    """A single monitoring trigger definition."""

    trigger_id: str
    severity: int           # 0 = P0 (halt), 1 = P1 (escalate), 2 = P2 (watch)
    metric: str             # Name of the metric (key in metrics dict)
    condition: str          # "lt" | "gt" | "abs_delta_gt"
    threshold: float
    action: str
    description: str
    reference_metric: str | None = None  # For drift triggers: reference metric name

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABELS.get(self.severity, f"P{self.severity}")


TRIGGERS: list[Trigger] = [
    Trigger(
        trigger_id="T01",
        severity=0,
        metric="recall_at_20pct",
        condition="lt",
        threshold=0.40,
        action="Halt deployment. Model cannot meet minimum recall requirement.",
        description="Recall@20% fell below the absolute minimum acceptable floor.",
    ),
    Trigger(
        trigger_id="T02",
        severity=0,
        metric="auc_roc",
        condition="lt",
        threshold=0.65,
        action="Halt deployment. Ranking ability is near-random.",
        description="AUC-ROC below 0.65 indicates severe ranking failure.",
    ),
    Trigger(
        trigger_id="T03",
        severity=1,
        metric="recall_at_20pct",
        condition="lt",
        threshold=0.50,
        action="Escalate to model risk team. Review feature pipeline and label quality.",
        description="Recall@20% is below operational target — immediate investigation required.",
    ),
    Trigger(
        trigger_id="T04",
        severity=1,
        metric="auc_roc",
        condition="lt",
        threshold=0.70,
        action="Escalate to model risk team. Review score distribution and model staleness.",
        description="AUC-ROC below 0.70 indicates significant ranking degradation.",
    ),
    Trigger(
        trigger_id="T05",
        severity=1,
        metric="ece",
        condition="gt",
        threshold=0.05,
        action="Escalate. Apply Platt or isotonic calibration on recent validation data.",
        description="Expected Calibration Error ≥ 0.05 means probabilities are misleading.",
    ),
    Trigger(
        trigger_id="T06",
        severity=1,
        metric="max_feature_psi",
        condition="gt",
        threshold=0.25,
        action="Escalate. Identify shifted features; assess whether retraining is required.",
        description="PSI ≥ 0.25 on at least one feature indicates significant distribution shift.",
    ),
    Trigger(
        trigger_id="T07",
        severity=2,
        metric="recall_at_20pct",
        condition="abs_delta_gt",
        threshold=0.08,
        reference_metric="prev_recall_at_20pct",
        action="Investigate. Monitor for continued trend; consider partial retraining.",
        description="Recall@20% drifted >0.08 from previous monitoring period.",
    ),
    Trigger(
        trigger_id="T08",
        severity=2,
        metric="cls_threshold",
        condition="abs_delta_gt",
        threshold=0.10,
        reference_metric="prev_cls_threshold",
        action="Investigate. Threshold instability may indicate score distribution shift.",
        description="Classification threshold shifted >0.10 since last window.",
    ),
    Trigger(
        trigger_id="T09",
        severity=2,
        metric="test_sar_rate",
        condition="abs_delta_gt",
        threshold=0.03,
        reference_metric="baseline_sar_rate",
        action="Investigate. Alert label shift may indicate process or regulatory change.",
        description="SAR rate drifted >3 percentage points from baseline.",
    ),
    Trigger(
        trigger_id="T10",
        severity=2,
        metric="auc_roc",
        condition="abs_delta_gt",
        threshold=0.05,
        reference_metric="prev_auc_roc",
        action="Investigate. Monitor score quality; consider feature monitoring expansion.",
        description="AUC-ROC drifted >0.05 from previous monitoring period.",
    ),
]


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class TriggerFiring:
    """A trigger that fired on a given evaluation."""

    trigger: Trigger
    window_label: str
    metric_value: float
    reference_value: float | None
    message: str

    @property
    def severity_label(self) -> str:
        return self.trigger.severity_label

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger.trigger_id,
            "severity": self.trigger.severity_label,
            "window_label": self.window_label,
            "metric": self.trigger.metric,
            "metric_value": round(self.metric_value, 4),
            "reference_value": round(self.reference_value, 4) if self.reference_value is not None else None,
            "condition": self.trigger.condition,
            "threshold": self.trigger.threshold,
            "message": self.message,
            "action": self.trigger.action,
            "description": self.trigger.description,
        }


def evaluate_triggers(
    metrics: dict[str, float | None],
    window_label: str,
    triggers: list[Trigger] | None = None,
) -> list[TriggerFiring]:
    """
    Evaluate a set of metrics against the monitoring trigger table.

    Args:
        metrics:       Dict mapping metric names to values.
                       Keys should include the metric names in TRIGGERS plus
                       any reference metrics (e.g. prev_recall_at_20pct).
                       Values of None are treated as missing and skip the trigger.
        window_label:  Label for the monitoring window or evaluation run.
        triggers:      Trigger list to evaluate (defaults to the global TRIGGERS).

    Returns:
        List of TriggerFiring for every trigger that fired.
        Ordered by severity ascending (P0 first).
    """
    triggers = triggers or TRIGGERS
    firings: list[TriggerFiring] = []

    for t in triggers:
        val = metrics.get(t.metric)
        if val is None:
            log.debug("Trigger %s: metric %s missing — skipped", t.trigger_id, t.metric)
            continue

        ref_val: float | None = None
        fired = False
        msg = ""

        if t.condition == "lt":
            fired = val < t.threshold
            if fired:
                msg = f"{t.metric}={val:.4f} < threshold {t.threshold}"

        elif t.condition == "gt":
            fired = val > t.threshold
            if fired:
                msg = f"{t.metric}={val:.4f} > threshold {t.threshold}"

        elif t.condition == "abs_delta_gt":
            if t.reference_metric is None:
                log.debug("Trigger %s: no reference_metric defined", t.trigger_id)
                continue
            ref_val = metrics.get(t.reference_metric)
            if ref_val is None:
                log.debug(
                    "Trigger %s: reference metric %s missing — skipped",
                    t.trigger_id, t.reference_metric,
                )
                continue
            delta = abs(val - ref_val)
            fired = delta > t.threshold
            if fired:
                msg = (
                    f"|{t.metric}={val:.4f} − {t.reference_metric}={ref_val:.4f}| "
                    f"= {delta:.4f} > threshold {t.threshold}"
                )

        if fired:
            log.warning(
                "[%s] Trigger %s FIRED | %s | %s",
                t.severity_label, t.trigger_id, window_label, msg,
            )
            firings.append(TriggerFiring(
                trigger=t,
                window_label=window_label,
                metric_value=val,
                reference_value=ref_val,
                message=msg,
            ))

    firings.sort(key=lambda f: f.trigger.severity)
    return firings


def firings_to_dataframe(firings: list[TriggerFiring]) -> pd.DataFrame:
    """Convert list of TriggerFiring to a tidy DataFrame."""
    if not firings:
        return pd.DataFrame(columns=[
            "trigger_id", "severity", "window_label", "metric",
            "metric_value", "reference_value", "condition", "threshold",
            "message", "action", "description",
        ])
    return pd.DataFrame([f.to_dict() for f in firings])


def triggers_to_dataframe(triggers: list[Trigger] | None = None) -> pd.DataFrame:
    """Return the trigger table as a DataFrame (for documentation)."""
    triggers = triggers or TRIGGERS
    rows = []
    for t in triggers:
        rows.append({
            "trigger_id": t.trigger_id,
            "severity": t.severity_label,
            "metric": t.metric,
            "condition": t.condition,
            "threshold": t.threshold,
            "reference_metric": t.reference_metric or "",
            "action": t.action,
            "description": t.description,
        })
    return pd.DataFrame(rows).set_index("trigger_id")
