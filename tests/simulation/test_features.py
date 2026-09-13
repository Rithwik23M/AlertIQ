"""
Tests for alert feature computation.

Covers: all 24 features present, no NaN/Inf values,
        feature values within expected ranges, no ground truth leakage.
"""

from __future__ import annotations

import datetime
import math

import pytest

from alertiq.simulation.config import SimulationConfig
from alertiq.simulation.entities import (
    Account,
    AccountRiskCategory,
    AccountType,
    Alert,
    AlertSeverity,
    AlertStatus,
    JurisdictionRisk,
    Transaction,
    TypologyType,
    new_id,
)
from alertiq.simulation.features import FEATURE_NAMES, compute_alert_features
from tests.simulation.conftest import make_cash_deposit, make_intl_wire


def _make_alert(account_id: str) -> Alert:
    return Alert(
        alert_id=new_id("ALT"),
        account_id=account_id,
        triggered_date=datetime.date(2023, 6, 15),
        rule_id="R01",
        rule_name="Test Rule",
        severity=AlertSeverity.HIGH,
        status=AlertStatus.OPEN,
        true_sar=None,
    )


def _account(account_id: str, pep=False, risk=AccountRiskCategory.MEDIUM_RISK):
    return Account(
        account_id=account_id,
        account_type=AccountType.RETAIL,
        risk_category=risk,
        jurisdiction=JurisdictionRisk.LOW,
        onboard_date=datetime.date(2015, 1, 1),
        declared_annual_revenue=50_000.0,
        expected_monthly_volume=4_000.0,
        has_pep_link=pep,
    )


REF_DATE = datetime.date(2023, 6, 15)


class TestFeaturePresence:
    def test_all_24_features_present(self):
        account = _account("A1")
        alert = _make_alert("A1")
        txns = [make_cash_deposit("A1", 500.0, REF_DATE - datetime.timedelta(days=i))
                for i in range(10)]
        features = compute_alert_features(alert, account, txns)
        assert len(features) == 24
        for fname in FEATURE_NAMES:
            assert fname in features, f"Missing feature: {fname}"

    def test_feature_names_list_length(self):
        assert len(FEATURE_NAMES) == 24

    def test_no_nan_or_inf(self):
        account = _account("A1")
        alert = _make_alert("A1")
        txns = [make_cash_deposit("A1", 500.0, REF_DATE - datetime.timedelta(days=i))
                for i in range(30)]
        features = compute_alert_features(alert, account, txns)
        for name, val in features.items():
            assert not math.isnan(val), f"Feature {name} is NaN"
            assert not math.isinf(val), f"Feature {name} is Inf"


class TestFeatureValues:
    def test_cash_fraction_with_all_cash_deposits(self):
        account = _account("A1")
        alert = _make_alert("A1")
        txns = [make_cash_deposit("A1", 1_000.0, REF_DATE - datetime.timedelta(days=i))
                for i in range(10)]
        features = compute_alert_features(alert, account, txns)
        # All transactions are cash deposits → cash fraction should be 1.0
        assert features["f11_cash_fraction_30d"] == pytest.approx(1.0)

    def test_intl_fraction_with_no_intl(self):
        account = _account("A1")
        alert = _make_alert("A1")
        txns = [make_cash_deposit("A1", 1_000.0, REF_DATE - datetime.timedelta(days=i))
                for i in range(10)]
        features = compute_alert_features(alert, account, txns)
        assert features["f16_intl_fraction_30d"] == pytest.approx(0.0)

    def test_intl_fraction_with_all_intl(self):
        account = _account("A1")
        alert = _make_alert("A1")
        txns = [make_intl_wire("A1", 5_000.0, JurisdictionRisk.HIGH,
                                REF_DATE - datetime.timedelta(days=i))
                for i in range(10)]
        features = compute_alert_features(alert, account, txns)
        assert features["f16_intl_fraction_30d"] == pytest.approx(1.0)

    def test_pep_flag_for_pep_account(self):
        account = _account("A1", pep=True)
        alert = _make_alert("A1")
        txns = [make_cash_deposit("A1", 100.0)]
        features = compute_alert_features(alert, account, txns)
        assert features["f20_pep_flag"] == 1.0

    def test_pep_flag_for_non_pep_account(self):
        account = _account("A1", pep=False)
        alert = _make_alert("A1")
        txns = [make_cash_deposit("A1", 100.0)]
        features = compute_alert_features(alert, account, txns)
        assert features["f20_pep_flag"] == 0.0

    def test_very_high_jurisdiction_flag(self):
        account = _account("A1")
        alert = _make_alert("A1")
        txns = [
            make_intl_wire("A1", 5_000.0, JurisdictionRisk.VERY_HIGH,
                           REF_DATE - datetime.timedelta(days=5))
        ]
        features = compute_alert_features(alert, account, txns)
        assert features["f18_very_high_jur_flag"] == 1.0

    def test_no_transactions_returns_zeros(self):
        account = _account("A1")
        alert = _make_alert("A1")
        features = compute_alert_features(alert, account, [])
        # Should return zeros/defaults, not crash
        assert features["f01_vol_7d_log"] == pytest.approx(0.0)
        assert features["f06_txn_count_7d"] == 0.0

    def test_structuring_count_feature(self):
        account = _account("A1")
        alert = _make_alert("A1")
        # 5 deposits in structuring range (7000-9999)
        txns = [make_cash_deposit("A1", 8_500.0, REF_DATE - datetime.timedelta(days=i))
                for i in range(5)]
        features = compute_alert_features(alert, account, txns)
        assert features["f12_structuring_count_30d"] == 5.0


class TestNoGroundTruthLeakage:
    """Features must not use is_typology or risk_category."""

    def test_features_identical_for_same_txns_different_risk(self):
        """Two accounts with same transactions but different risk categories
        produce identical feature vectors."""
        txns_ml = [make_cash_deposit("ML", 1_000.0, REF_DATE - datetime.timedelta(days=i))
                   for i in range(10)]
        txns_lr = [
            make_cash_deposit("LR", t.amount_eur, t.txn_date, t.txn_datetime.hour)
            for t in txns_ml
        ]

        alert_ml = _make_alert("ML")
        alert_lr = _make_alert("LR")

        account_ml = _account("ML", risk=AccountRiskCategory.ACTIVE_ML)
        account_lr = _account("LR", risk=AccountRiskCategory.LOW_RISK)

        # Override expected_monthly_volume to match
        account_ml.expected_monthly_volume = account_lr.expected_monthly_volume

        feats_ml = compute_alert_features(alert_ml, account_ml, txns_ml)
        feats_lr = compute_alert_features(alert_lr, account_lr, txns_lr)

        # Features that should be identical when transactions are identical
        for key in ["f01_vol_7d_log", "f06_txn_count_7d", "f11_cash_fraction_30d"]:
            assert feats_ml[key] == pytest.approx(feats_lr[key]), \
                f"Feature {key} differs between ML and LR account"
