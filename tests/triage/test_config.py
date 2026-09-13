"""Tests for TriageConfig and its sub-models."""

import pytest
from pydantic import ValidationError

from alertiq.triage.config import (
    ModelHyperparams,
    OperationalAssumptions,
    SplitConfig,
    TriageConfig,
)


class TestSplitConfig:
    def test_default_fracs_sum_to_less_than_one(self):
        s = SplitConfig()
        assert s.train_frac + s.val_frac < 1.0

    def test_holdout_frac_is_implicit_remainder(self):
        s = SplitConfig(train_frac=0.6, val_frac=0.2)
        assert abs(s.holdout_frac - 0.2) < 1e-9

    def test_fracs_that_leave_no_holdout_are_invalid(self):
        with pytest.raises(ValidationError):
            SplitConfig(train_frac=0.8, val_frac=0.2)

    def test_zero_train_frac_is_invalid(self):
        with pytest.raises(ValidationError):
            SplitConfig(train_frac=0.0, val_frac=0.2)


class TestModelHyperparams:
    def test_defaults_are_valid(self):
        hp = ModelHyperparams()
        assert hp.max_iter >= 10
        assert 0.0 < hp.learning_rate <= 1.0
        assert hp.max_leaf_nodes >= 4
        assert hp.min_samples_leaf >= 5
        assert hp.l2_regularization >= 0.0

    def test_too_many_iterations_is_invalid(self):
        with pytest.raises(ValidationError):
            ModelHyperparams(max_iter=9999)

    def test_negative_learning_rate_is_invalid(self):
        with pytest.raises(ValidationError):
            ModelHyperparams(learning_rate=-0.01)


class TestTriageConfig:
    def test_default_config_is_valid(self):
        cfg = TriageConfig()
        assert cfg.seed == 42
        assert len(cfg.feature_columns) == 24
        assert len(cfg.categorical_feature_indices) == 4

    def test_config_is_frozen(self):
        cfg = TriageConfig()
        with pytest.raises(Exception):
            cfg.seed = 99  # type: ignore[misc]

    def test_feature_columns_are_all_f_prefixed(self):
        cfg = TriageConfig()
        for col in cfg.feature_columns:
            assert col.startswith("f"), f"Feature column '{col}' does not start with 'f'"

    def test_categorical_indices_are_within_feature_range(self):
        cfg = TriageConfig()
        n = len(cfg.feature_columns)
        for idx in cfg.categorical_feature_indices:
            assert 0 <= idx < n, f"Categorical index {idx} out of range [0, {n})"

    def test_no_leakage_columns_in_features(self):
        """None of the leakage-guarded column names should appear in feature_columns."""
        cfg = TriageConfig()
        leakage = {"true_sar", "triggered_by_typology_txn", "account_id", "alert_id", "status"}
        overlap = leakage & set(cfg.feature_columns)
        assert not overlap, f"Leakage columns in feature_columns: {overlap}"

    def test_operational_capacity_fractions_are_valid(self):
        cfg = TriageConfig()
        for frac in cfg.operational.review_capacity_fractions:
            assert 0.0 < frac <= 1.0
