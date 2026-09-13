"""
Tests for alertiq.serving.quality — data quality checks.

Coverage
--------
- Clean features produce no warnings
- Zeroed 'should-be-positive' features trigger has_zeroed_features
- Only named features trigger zero flags (not all zeros)
- Extreme values trigger has_extreme_values
- quality_warning is True when any flag is set
- quality_warning is False when no flags are set
- zero_feature_names / extreme_feature_names are sorted lists
"""

from __future__ import annotations

import pytest

from alertiq.serving.quality import (
    EXTREME_VALUE_THRESHOLDS,
    SHOULD_BE_POSITIVE,
    check_data_quality,
)
from alertiq.serving.schema import AlertFeatures


def _make_features(overrides: dict | None = None, base: dict | None = None) -> AlertFeatures:
    """Build an AlertFeatures from the base dict with optional overrides."""
    defaults = {
        "f01_vol_7d_log": 8.5,
        "f02_vol_30d_log": 10.2,
        "f03_vol_ratio_7_30": 0.85,
        "f04_max_txn_log": 7.1,
        "f05_vol_vs_revenue": 1.2,
        "f06_txn_count_7d": 12,
        "f07_txn_count_30d": 45,
        "f08_velocity_ratio": 1.1,
        "f09_recency_gap_days": 3.0,
        "f10_account_age_days": 720.0,
        "f11_cash_fraction_30d": 0.15,
        "f12_structuring_count_30d": 0,
        "f13_round_amount_count_30d": 3,
        "f14_digital_channel_fraction": 0.8,
        "f15_night_fraction_30d": 0.1,
        "f16_intl_fraction_30d": 0.05,
        "f17_distinct_jurisdictions_30d": 2,
        "f18_very_high_jur_flag": 0,
        "f19_shell_counterparty_fraction": 0.0,
        "f20_pep_flag": 0,
        "f21_adverse_media_flag": 0,
        "f22_high_risk_industry": 0,
        "f23_prior_alerts_90d": 1,
        "f24_account_jurisdiction_score": 0.3,
    }
    if base:
        defaults = {**defaults, **base}
    if overrides:
        defaults = {**defaults, **overrides}
    return AlertFeatures(**defaults)


class TestCleanFeatures:
    def test_no_warnings_for_valid_input(self) -> None:
        flags = check_data_quality(_make_features())
        assert not flags.quality_warning
        assert not flags.has_zeroed_features
        assert not flags.has_extreme_values
        assert flags.zero_feature_names == []
        assert flags.extreme_feature_names == []


class TestZeroValueCheck:
    @pytest.mark.parametrize("feature_name", sorted(SHOULD_BE_POSITIVE))
    def test_zero_triggers_flag(self, feature_name: str) -> None:
        flags = check_data_quality(_make_features({feature_name: 0}))
        assert flags.has_zeroed_features
        assert feature_name in flags.zero_feature_names
        assert flags.quality_warning

    def test_zero_in_non_flagged_feature_does_not_trigger(self) -> None:
        # f11_cash_fraction_30d=0 is legitimate (no cash in period)
        # and is NOT in SHOULD_BE_POSITIVE.
        assert "f11_cash_fraction_30d" not in SHOULD_BE_POSITIVE
        flags = check_data_quality(_make_features({"f11_cash_fraction_30d": 0.0}))
        assert not flags.has_zeroed_features

    def test_zero_feature_names_are_sorted(self) -> None:
        """When multiple features are zero, names should be sorted."""
        overrides = {name: 0 for name in SHOULD_BE_POSITIVE}
        flags = check_data_quality(_make_features(overrides))
        assert flags.zero_feature_names == sorted(flags.zero_feature_names)

    def test_nonzero_does_not_trigger(self) -> None:
        flags = check_data_quality(_make_features({"f01_vol_7d_log": 0.001}))
        assert not flags.has_zeroed_features


class TestExtremeValueCheck:
    def test_extreme_vol_triggers_flag(self) -> None:
        # f01 threshold is 20.0; send 25.0
        flags = check_data_quality(_make_features({"f01_vol_7d_log": 25.0}))
        assert flags.has_extreme_values
        assert "f01_vol_7d_log" in flags.extreme_feature_names
        assert flags.quality_warning

    def test_at_threshold_does_not_trigger(self) -> None:
        threshold = EXTREME_VALUE_THRESHOLDS["f01_vol_7d_log"]
        flags = check_data_quality(_make_features({"f01_vol_7d_log": threshold}))
        assert not flags.has_extreme_values

    def test_extreme_feature_names_are_sorted(self) -> None:
        # Set multiple extreme values
        flags = check_data_quality(_make_features({
            "f01_vol_7d_log": 99.0,
            "f02_vol_30d_log": 99.0,
        }))
        assert flags.extreme_feature_names == sorted(flags.extreme_feature_names)

    def test_extreme_count_triggers_flag(self) -> None:
        flags = check_data_quality(_make_features({"f06_txn_count_7d": 10000}))
        assert flags.has_extreme_values
        assert "f06_txn_count_7d" in flags.extreme_feature_names


class TestQualityWarning:
    def test_warning_true_on_zero(self) -> None:
        flags = check_data_quality(_make_features({"f01_vol_7d_log": 0}))
        assert flags.quality_warning

    def test_warning_true_on_extreme(self) -> None:
        flags = check_data_quality(_make_features({"f01_vol_7d_log": 99.0}))
        assert flags.quality_warning

    def test_warning_false_on_clean_input(self) -> None:
        flags = check_data_quality(_make_features())
        assert not flags.quality_warning
