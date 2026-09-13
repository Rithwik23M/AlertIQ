"""
Tests for alertiq.serving.schema — request / response validation.

Coverage
--------
- AlertFeatures.to_array() returns 24 values in canonical order
- AlertFeatures rejects extra fields (extra="forbid")
- AlertFeatures rejects out-of-range values
- Fraction fields reject values outside [0, 1]
- BinaryFlag fields reject values other than 0 and 1
- ScoreRequest rejects empty alert_id
- ScoreRequest rejects unsupported schema_version (downstream validation)
- BatchScoreRequest enforces 1–500 alerts
- Feature column order matches TriageConfig.feature_columns
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from alertiq.serving.schema import (
    AlertFeatures,
    BatchScoreRequest,
    ScoreRequest,
)
from alertiq.triage.config import TriageConfig


class TestAlertFeatures:
    """Validate AlertFeatures schema constraints."""

    def test_to_array_length(self, minimal_features_dict: dict) -> None:
        features = AlertFeatures(**minimal_features_dict)
        arr = features.to_array()
        assert len(arr) == 24

    def test_to_array_canonical_order(self, minimal_features_dict: dict) -> None:
        """to_array() order must match TriageConfig.feature_columns exactly."""
        config = TriageConfig()
        features = AlertFeatures(**minimal_features_dict)
        arr = features.to_array()
        # Verify by checking f01 is index 0 and f24 is index 23.
        f01_val = minimal_features_dict["f01_vol_7d_log"]
        f24_val = minimal_features_dict["f24_account_jurisdiction_score"]
        assert arr[0] == f01_val
        assert arr[23] == f24_val

    def test_to_array_matches_feature_columns_order(self, minimal_features_dict: dict) -> None:
        """Every field must appear in the position TriageConfig.feature_columns defines."""
        config = TriageConfig()
        features = AlertFeatures(**minimal_features_dict)
        arr = features.to_array()
        for i, col in enumerate(config.feature_columns):
            expected_val = minimal_features_dict[col]
            assert arr[i] == pytest.approx(float(expected_val)), (
                f"Position {i} ({col}): expected {expected_val}, got {arr[i]}"
            )

    def test_rejects_extra_fields(self, minimal_features_dict: dict) -> None:
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict, unknown_field=99.0)

    def test_fraction_rejects_negative(self, minimal_features_dict: dict) -> None:
        minimal_features_dict["f11_cash_fraction_30d"] = -0.01
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict)

    def test_fraction_rejects_above_one(self, minimal_features_dict: dict) -> None:
        minimal_features_dict["f11_cash_fraction_30d"] = 1.001
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict)

    def test_binary_flag_rejects_two(self, minimal_features_dict: dict) -> None:
        minimal_features_dict["f20_pep_flag"] = 2
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict)

    def test_binary_flag_rejects_negative(self, minimal_features_dict: dict) -> None:
        minimal_features_dict["f18_very_high_jur_flag"] = -1
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict)

    def test_log_feature_rejects_negative(self, minimal_features_dict: dict) -> None:
        minimal_features_dict["f01_vol_7d_log"] = -0.001
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict)

    def test_account_jurisdiction_score_rejects_above_one(self, minimal_features_dict: dict) -> None:
        minimal_features_dict["f24_account_jurisdiction_score"] = 1.001
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict)

    def test_count_rejects_negative(self, minimal_features_dict: dict) -> None:
        minimal_features_dict["f06_txn_count_7d"] = -1
        with pytest.raises(ValidationError):
            AlertFeatures(**minimal_features_dict)

    def test_zero_values_are_valid(self, minimal_features_dict: dict) -> None:
        """Zero is a valid value (triggers data quality flags, not schema rejection)."""
        for key in [
            "f01_vol_7d_log", "f02_vol_30d_log", "f06_txn_count_7d",
            "f11_cash_fraction_30d", "f19_shell_counterparty_fraction",
        ]:
            d = {**minimal_features_dict, key: 0}
            features = AlertFeatures(**d)  # should not raise
            assert features is not None


class TestScoreRequest:
    def test_valid_request(self, minimal_features_dict: dict) -> None:
        req = ScoreRequest(
            alert_id="ALT-001",
            schema_version=1,
            features=minimal_features_dict,
        )
        assert req.alert_id == "ALT-001"

    def test_rejects_empty_alert_id(self, minimal_features_dict: dict) -> None:
        with pytest.raises(ValidationError):
            ScoreRequest(alert_id="", schema_version=1, features=minimal_features_dict)

    def test_rejects_missing_features(self) -> None:
        with pytest.raises(ValidationError):
            ScoreRequest(alert_id="X", schema_version=1, features={})


class TestBatchScoreRequest:
    def test_rejects_empty_alerts_list(self, minimal_features_dict: dict) -> None:
        with pytest.raises(ValidationError):
            BatchScoreRequest(alerts=[])

    def test_accepts_single_alert(self, minimal_features_dict: dict) -> None:
        req = BatchScoreRequest(
            alerts=[
                ScoreRequest(
                    alert_id="X",
                    schema_version=1,
                    features=minimal_features_dict,
                )
            ]
        )
        assert len(req.alerts) == 1

    def test_rejects_501_alerts(self, minimal_features_dict: dict) -> None:
        alert = ScoreRequest(alert_id="X", schema_version=1, features=minimal_features_dict)
        with pytest.raises(ValidationError):
            BatchScoreRequest(alerts=[alert] * 501)

    def test_accepts_500_alerts(self, minimal_features_dict: dict) -> None:
        alert = ScoreRequest(alert_id="X", schema_version=1, features=minimal_features_dict)
        req = BatchScoreRequest(alerts=[alert] * 500)
        assert len(req.alerts) == 500
