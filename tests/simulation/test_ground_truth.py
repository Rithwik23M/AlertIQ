"""
Tests for ground truth label assignment.

Covers: SAR label correctness, calling-order violations,
        integrity verification, impossible state detection.
"""

from __future__ import annotations

import datetime

import pytest

from alertiq.simulation.entities import (
    Account,
    AccountRiskCategory,
    AccountType,
    Alert,
    AlertSeverity,
    AlertStatus,
    JurisdictionRisk,
    TypologyType,
    new_id,
)
from alertiq.simulation.ground_truth import (
    assign_ground_truth,
    verify_ground_truth_integrity,
)


def _make_alert(account_id: str, triggered_by_typology: bool = False) -> Alert:
    return Alert(
        alert_id=new_id("ALT"),
        account_id=account_id,
        triggered_date=datetime.date(2023, 6, 15),
        rule_id="R01",
        rule_name="Test Rule",
        severity=AlertSeverity.HIGH,
        status=AlertStatus.OPEN,
        true_sar=None,
        triggered_by_typology_txn=triggered_by_typology,
    )


def _active_ml_account(account_id: str) -> Account:
    return Account(
        account_id=account_id,
        account_type=AccountType.SHELL,
        risk_category=AccountRiskCategory.ACTIVE_ML,
        jurisdiction=JurisdictionRisk.HIGH,
        onboard_date=datetime.date(2020, 1, 1),
        declared_annual_revenue=500_000.0,
        expected_monthly_volume=40_000.0,
        assigned_typology=TypologyType.STRUCTURING,
    )


def _low_risk_account(account_id: str) -> Account:
    return Account(
        account_id=account_id,
        account_type=AccountType.RETAIL,
        risk_category=AccountRiskCategory.LOW_RISK,
        jurisdiction=JurisdictionRisk.LOW,
        onboard_date=datetime.date(2015, 1, 1),
        declared_annual_revenue=30_000.0,
        expected_monthly_volume=2_500.0,
    )


class TestGroundTruthAssignment:
    def test_active_ml_typology_alert_is_true_sar(self):
        acc = _active_ml_account("A1")
        alert = _make_alert("A1", triggered_by_typology=True)
        assign_ground_truth([alert], {"A1": acc})
        assert alert.true_sar is True

    def test_active_ml_routine_alert_is_false_positive(self):
        """An ACTIVE_ML account's routine alert should NOT be a SAR."""
        acc = _active_ml_account("A1")
        alert = _make_alert("A1", triggered_by_typology=False)
        assign_ground_truth([alert], {"A1": acc})
        assert alert.true_sar is False

    def test_non_ml_typology_alert_is_false_positive(self):
        """Low-risk account's alert (even typology-triggered) is not a SAR."""
        acc = _low_risk_account("A2")
        alert = _make_alert("A2", triggered_by_typology=True)
        assign_ground_truth([alert], {"A2": acc})
        # Low risk account shouldn't have typology txns, but if it did:
        assert alert.true_sar is False

    def test_low_risk_alert_always_false_positive(self):
        acc = _low_risk_account("A3")
        alert = _make_alert("A3", triggered_by_typology=False)
        assign_ground_truth([alert], {"A3": acc})
        assert alert.true_sar is False

    def test_all_categories_assigned(self):
        accounts = {
            "ML": _active_ml_account("ML"),
            "LR": _low_risk_account("LR"),
        }
        alerts = [
            _make_alert("ML", True),
            _make_alert("ML", False),
            _make_alert("LR", True),
            _make_alert("LR", False),
        ]
        assign_ground_truth(alerts, accounts)
        assert alerts[0].true_sar is True
        assert alerts[1].true_sar is False
        assert alerts[2].true_sar is False
        assert alerts[3].true_sar is False


class TestCallingOrderProtection:
    def test_raises_if_true_sar_already_set(self):
        acc = _active_ml_account("A1")
        alert = _make_alert("A1", True)
        alert.true_sar = True  # simulate double-call
        with pytest.raises(ValueError, match="already set"):
            assign_ground_truth([alert], {"A1": acc})

    def test_raises_if_account_missing(self):
        alert = _make_alert("UNKNOWN", True)
        with pytest.raises(ValueError, match="not found"):
            assign_ground_truth([alert], {})


class TestIntegrityVerification:
    def test_passes_on_correct_labels(self):
        acc = _active_ml_account("A1")
        alert = _make_alert("A1", True)
        assign_ground_truth([alert], {"A1": acc})
        errors = verify_ground_truth_integrity([alert], {"A1": acc})
        assert errors == []

    def test_detects_unlabelled_alert(self):
        acc = _low_risk_account("A1")
        alert = _make_alert("A1")
        # Do NOT call assign_ground_truth
        errors = verify_ground_truth_integrity([alert], {"A1": acc})
        assert any("None" in e for e in errors)

    def test_detects_impossible_non_ml_true_sar(self):
        acc = _low_risk_account("A1")
        alert = _make_alert("A1", False)
        alert.true_sar = True  # impossible state — manually injected
        errors = verify_ground_truth_integrity([alert], {"A1": acc})
        assert len(errors) > 0
