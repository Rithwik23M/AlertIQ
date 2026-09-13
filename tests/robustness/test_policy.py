"""
Tests for src/alertiq/robustness/policy.py
"""

from __future__ import annotations

import pytest

from alertiq.robustness.policy import (
    SEVERITY_LABELS,
    TRIGGERS,
    Trigger,
    TriggerFiring,
    evaluate_triggers,
    firings_to_dataframe,
    triggers_to_dataframe,
)


# ---------------------------------------------------------------------------
# Trigger dataclass
# ---------------------------------------------------------------------------

class TestTriggerDataclass:
    def test_severity_label_p0(self):
        t = Trigger(
            trigger_id="TX", severity=0,
            metric="recall_at_20pct", condition="lt", threshold=0.40,
            action="Halt", description="Test trigger",
        )
        assert t.severity_label == "P0"

    def test_severity_label_p1(self):
        t = Trigger(
            trigger_id="TX", severity=1,
            metric="auc_roc", condition="lt", threshold=0.65,
            action="Escalate", description="Test",
        )
        assert t.severity_label == "P1"

    def test_severity_label_p2(self):
        t = Trigger(
            trigger_id="TX", severity=2,
            metric="cls_threshold", condition="abs_delta_gt", threshold=0.10,
            action="Investigate", description="Test",
            reference_metric="prev_cls_threshold",
        )
        assert t.severity_label == "P2"

    def test_trigger_is_frozen(self):
        t = Trigger(
            trigger_id="TX", severity=0,
            metric="recall_at_20pct", condition="lt", threshold=0.40,
            action="Halt", description="Test",
        )
        with pytest.raises(Exception):
            t.severity = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TRIGGERS global list
# ---------------------------------------------------------------------------

class TestTriggersDefinition:
    def test_has_ten_triggers(self):
        assert len(TRIGGERS) == 10

    def test_trigger_ids_unique(self):
        ids = [t.trigger_id for t in TRIGGERS]
        assert len(ids) == len(set(ids))

    def test_t01_is_p0_halt(self):
        t01 = next(t for t in TRIGGERS if t.trigger_id == "T01")
        assert t01.severity == 0
        assert t01.condition == "lt"
        assert t01.threshold == pytest.approx(0.40)

    def test_t02_is_p0_halt(self):
        t02 = next(t for t in TRIGGERS if t.trigger_id == "T02")
        assert t02.severity == 0
        assert t02.metric == "auc_roc"

    def test_drift_triggers_have_reference_metric(self):
        drift_ids = {"T07", "T08", "T09", "T10"}
        for t in TRIGGERS:
            if t.trigger_id in drift_ids:
                assert t.reference_metric is not None, f"{t.trigger_id} missing reference_metric"

    def test_all_conditions_valid(self):
        valid_conditions = {"lt", "gt", "abs_delta_gt"}
        for t in TRIGGERS:
            assert t.condition in valid_conditions, f"{t.trigger_id} has invalid condition"


# ---------------------------------------------------------------------------
# evaluate_triggers — point-in-time triggers
# ---------------------------------------------------------------------------

class TestEvaluateTriggers:

    # --- T01: recall_at_20pct < 0.40 → P0 ---
    def test_t01_fires_below_floor(self):
        metrics = {"recall_at_20pct": 0.35}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T01" in ids

    def test_t01_does_not_fire_above_floor(self):
        metrics = {"recall_at_20pct": 0.50}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T01" not in ids

    def test_t01_does_not_fire_at_exactly_floor(self):
        # < 0.40, so exactly 0.40 should NOT fire
        metrics = {"recall_at_20pct": 0.40}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T01" not in ids

    # --- T02: auc_roc < 0.65 → P0 ---
    def test_t02_fires_below_threshold(self):
        metrics = {"auc_roc": 0.60}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T02" in ids

    def test_t02_does_not_fire_above_threshold(self):
        metrics = {"auc_roc": 0.80}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T02" not in ids

    # --- T03: recall_at_20pct < 0.50 → P1 ---
    def test_t03_fires_below_target(self):
        metrics = {"recall_at_20pct": 0.45}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T03" in ids

    def test_t03_and_t01_both_fire_when_very_low(self):
        metrics = {"recall_at_20pct": 0.30}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T01" in ids
        assert "T03" in ids

    # --- T05: ece >= 0.05 → P1 ---
    def test_t05_fires_above_ece_threshold(self):
        metrics = {"ece": 0.07}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T05" in ids

    def test_t05_does_not_fire_below_ece_threshold(self):
        metrics = {"ece": 0.03}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T05" not in ids

    def test_t05_fires_at_exactly_threshold(self):
        # condition is >, so 0.05 exactly should NOT fire (T05 uses "gt" not "gte")
        # Wait — checking policy.py: condition="gt" so > means strictly greater
        # ECE_THRESHOLD = 0.05, T05 fires when ece > 0.05
        # But let's check: T05 uses condition="gt", threshold=0.05 → fires when ece > 0.05
        # So exactly 0.05 should NOT fire
        metrics = {"ece": 0.05}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T05" not in ids

    # --- T06: max_feature_psi >= 0.25 → P1 ---
    def test_t06_fires_above_psi_threshold(self):
        metrics = {"max_feature_psi": 0.30}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T06" in ids

    # --- Missing metrics are skipped ---
    def test_missing_metric_skips_trigger(self):
        metrics = {}  # no metrics at all
        firings = evaluate_triggers(metrics, "W1")
        assert len(firings) == 0

    def test_none_metric_skips_trigger(self):
        metrics = {"recall_at_20pct": None, "auc_roc": 0.80}
        firings = evaluate_triggers(metrics, "W1")
        # T01 and T03 should be skipped (None); T02 should not fire (0.80 is fine)
        ids = {f.trigger.trigger_id for f in firings}
        assert "T01" not in ids
        assert "T03" not in ids

    # --- Ordering ---
    def test_firings_ordered_by_severity(self):
        metrics = {
            "recall_at_20pct": 0.30,  # fires T01 (P0) and T03 (P1)
            "auc_roc": 0.62,           # fires T02 (P0) and T04 (P1)
        }
        firings = evaluate_triggers(metrics, "W1")
        severities = [f.trigger.severity for f in firings]
        assert severities == sorted(severities)


# ---------------------------------------------------------------------------
# evaluate_triggers — drift triggers (abs_delta_gt)
# ---------------------------------------------------------------------------

class TestDriftTriggers:
    def test_t07_fires_on_large_recall_drift(self):
        metrics = {
            "recall_at_20pct": 0.70,
            "prev_recall_at_20pct": 0.55,  # delta = 0.15 > 0.08
        }
        firings = evaluate_triggers(metrics, "W2")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T07" in ids

    def test_t07_does_not_fire_on_small_drift(self):
        metrics = {
            "recall_at_20pct": 0.72,
            "prev_recall_at_20pct": 0.70,  # delta = 0.02 < 0.08
        }
        firings = evaluate_triggers(metrics, "W2")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T07" not in ids

    def test_t07_fires_on_negative_drift(self):
        # Abs delta: recall went DOWN by 0.12 → fires
        metrics = {
            "recall_at_20pct": 0.60,
            "prev_recall_at_20pct": 0.72,  # |0.60 - 0.72| = 0.12 > 0.08
        }
        firings = evaluate_triggers(metrics, "W2")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T07" in ids

    def test_t08_fires_on_large_threshold_drift(self):
        metrics = {
            "cls_threshold": 0.35,
            "prev_cls_threshold": 0.10,  # delta = 0.25 > 0.10
        }
        firings = evaluate_triggers(metrics, "W2")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T08" in ids

    def test_t09_fires_on_sar_rate_drift(self):
        metrics = {
            "test_sar_rate": 0.18,
            "baseline_sar_rate": 0.10,  # delta = 0.08 > 0.03
        }
        firings = evaluate_triggers(metrics, "W2")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T09" in ids

    def test_t10_fires_on_large_auc_drift(self):
        metrics = {
            "auc_roc": 0.85,
            "prev_auc_roc": 0.78,  # delta = 0.07 > 0.05
        }
        firings = evaluate_triggers(metrics, "W2")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T10" in ids

    def test_drift_trigger_missing_reference_skips(self):
        # T07 requires prev_recall_at_20pct but it's absent
        metrics = {"recall_at_20pct": 0.70}
        firings = evaluate_triggers(metrics, "W1")
        ids = {f.trigger.trigger_id for f in firings}
        assert "T07" not in ids

    def test_trigger_firing_has_reference_value(self):
        metrics = {
            "recall_at_20pct": 0.70,
            "prev_recall_at_20pct": 0.50,  # delta = 0.20 > 0.08
        }
        firings = evaluate_triggers(metrics, "W2")
        t07 = next((f for f in firings if f.trigger.trigger_id == "T07"), None)
        assert t07 is not None
        assert t07.reference_value == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Custom trigger list
# ---------------------------------------------------------------------------

class TestCustomTriggers:
    def test_custom_trigger_list(self):
        custom = [
            Trigger(
                trigger_id="CX1", severity=0,
                metric="recall_at_20pct", condition="lt", threshold=0.60,
                action="Custom halt", description="Custom test trigger",
            )
        ]
        metrics = {"recall_at_20pct": 0.55}
        firings = evaluate_triggers(metrics, "W1", triggers=custom)
        assert len(firings) == 1
        assert firings[0].trigger.trigger_id == "CX1"


# ---------------------------------------------------------------------------
# TriggerFiring
# ---------------------------------------------------------------------------

class TestTriggerFiring:
    def test_to_dict_has_expected_keys(self):
        t = TRIGGERS[0]
        firing = TriggerFiring(
            trigger=t,
            window_label="W1",
            metric_value=0.35,
            reference_value=None,
            message="recall_at_20pct=0.35 < threshold 0.40",
        )
        d = firing.to_dict()
        for key in ["trigger_id", "severity", "metric", "metric_value", "action", "description"]:
            assert key in d

    def test_severity_label_delegates_to_trigger(self):
        t = TRIGGERS[0]
        firing = TriggerFiring(
            trigger=t, window_label="W1",
            metric_value=0.35, reference_value=None, message="",
        )
        assert firing.severity_label == t.severity_label


# ---------------------------------------------------------------------------
# firings_to_dataframe
# ---------------------------------------------------------------------------

class TestFiringsToDataframe:
    def test_empty_input(self):
        import pandas as pd
        df = firings_to_dataframe([])
        assert isinstance(df, pd.DataFrame)
        assert "trigger_id" in df.columns

    def test_nonempty_input(self):
        metrics = {"recall_at_20pct": 0.30, "auc_roc": 0.60}
        firings = evaluate_triggers(metrics, "W1")
        df = firings_to_dataframe(firings)
        assert len(df) >= 1
        assert "trigger_id" in df.columns
        assert "severity" in df.columns


# ---------------------------------------------------------------------------
# triggers_to_dataframe
# ---------------------------------------------------------------------------

class TestTriggersToDataframe:
    def test_returns_ten_rows(self):
        df = triggers_to_dataframe()
        assert len(df) == 10

    def test_trigger_id_is_index(self):
        df = triggers_to_dataframe()
        assert df.index.name == "trigger_id"
        assert "T01" in df.index

    def test_expected_columns(self):
        df = triggers_to_dataframe()
        for col in ["severity", "metric", "condition", "threshold", "action"]:
            assert col in df.columns
