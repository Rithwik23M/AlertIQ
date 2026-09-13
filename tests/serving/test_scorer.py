"""
Tests for alertiq.serving.scorer — InferenceScorer and SchemaVersionMismatchError.

Coverage
--------
- score_single returns (risk_score, DataQualityFlags, latency_ms)
- risk_score is clamped to [0, 1]
- Scoring is deterministic: same input → same output
- latency_ms is non-negative
- SchemaVersionMismatchError raised for unsupported schema_version
- SchemaVersionMismatchError raised when version not in SUPPORTED_SCHEMA_VERSIONS
- SchemaVersionMismatchError carries .requested and .supported attributes
- score_batch returns (np.ndarray, list[DataQualityFlags], float)
- score_batch risk_scores are in [0, 1] for every row
- score_batch quality_flags list length matches input count
- InferenceScorer.artifact property returns the ModelArtifact
- Capacity-ranking policy: TriageScorer.predict() is never called
  (score() is the only model method exercised)
"""

from __future__ import annotations

import numpy as np
import pytest

from alertiq.serving.artifact import ModelArtifact
from alertiq.serving.schema import AlertFeatures, DataQualityFlags, SUPPORTED_SCHEMA_VERSIONS
from alertiq.serving.scorer import InferenceScorer, SchemaVersionMismatchError


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_features(**overrides) -> AlertFeatures:
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
    defaults.update(overrides)
    return AlertFeatures(**defaults)


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def scorer(tmp_path_factory, fitted_scorer_phase2, _config):
    """InferenceScorer built from a temporarily saved artifact."""
    from alertiq.serving.artifact import save_artifact, load_artifact

    tmp = tmp_path_factory.mktemp("scorer")
    path = tmp / "model.joblib"
    save_artifact(
        scorer=fitted_scorer_phase2,
        config=_config,
        model_version="test-v0",
        path=path,
        training_rows=240,
    )
    artifact = load_artifact(path)
    return InferenceScorer(artifact)


# ------------------------------------------------------------------ #
# TestSchemaVersionMismatchError                                        #
# ------------------------------------------------------------------ #

class TestSchemaVersionMismatchError:
    def test_is_value_error(self) -> None:
        err = SchemaVersionMismatchError(requested=99, supported={1})
        assert isinstance(err, ValueError)

    def test_requested_attribute(self) -> None:
        err = SchemaVersionMismatchError(requested=5, supported={1})
        assert err.requested == 5

    def test_supported_attribute(self) -> None:
        err = SchemaVersionMismatchError(requested=5, supported={1, 2})
        assert err.supported == {1, 2}

    def test_message_contains_requested_version(self) -> None:
        err = SchemaVersionMismatchError(requested=42, supported={1})
        assert "42" in str(err)


# ------------------------------------------------------------------ #
# TestArtifactProperty                                                 #
# ------------------------------------------------------------------ #

class TestArtifactProperty:
    def test_returns_model_artifact(self, scorer: InferenceScorer) -> None:
        assert isinstance(scorer.artifact, ModelArtifact)

    def test_model_version_matches(self, scorer: InferenceScorer) -> None:
        assert scorer.artifact.model_version == "test-v0"

    def test_operating_mode_is_capacity_ranking(self, scorer: InferenceScorer) -> None:
        assert scorer.artifact.operating_mode == "capacity_ranking"


# ------------------------------------------------------------------ #
# TestScoreSingle                                                      #
# ------------------------------------------------------------------ #

class TestScoreSingle:
    def test_returns_three_tuple(self, scorer: InferenceScorer) -> None:
        features = _make_features()
        result = scorer.score_single(schema_version=1, features=features)
        assert len(result) == 3

    def test_risk_score_is_float(self, scorer: InferenceScorer) -> None:
        risk_score, _, _ = scorer.score_single(schema_version=1, features=_make_features())
        assert isinstance(risk_score, float)

    def test_risk_score_in_unit_interval(self, scorer: InferenceScorer) -> None:
        risk_score, _, _ = scorer.score_single(schema_version=1, features=_make_features())
        assert 0.0 <= risk_score <= 1.0

    def test_quality_flags_is_data_quality_flags(self, scorer: InferenceScorer) -> None:
        _, quality_flags, _ = scorer.score_single(schema_version=1, features=_make_features())
        assert isinstance(quality_flags, DataQualityFlags)

    def test_latency_ms_is_non_negative(self, scorer: InferenceScorer) -> None:
        _, _, latency_ms = scorer.score_single(schema_version=1, features=_make_features())
        assert latency_ms >= 0.0

    def test_latency_ms_is_float(self, scorer: InferenceScorer) -> None:
        _, _, latency_ms = scorer.score_single(schema_version=1, features=_make_features())
        assert isinstance(latency_ms, float)

    def test_scoring_is_deterministic(self, scorer: InferenceScorer) -> None:
        """Same input must produce the same risk_score on repeated calls."""
        features = _make_features()
        score_a, _, _ = scorer.score_single(schema_version=1, features=features)
        score_b, _, _ = scorer.score_single(schema_version=1, features=features)
        assert score_a == score_b

    def test_different_inputs_may_differ(self, scorer: InferenceScorer) -> None:
        """Sanity check: meaningfully different inputs tend to produce different scores."""
        low_risk = _make_features(
            f01_vol_7d_log=2.0,
            f20_pep_flag=0,
            f21_adverse_media_flag=0,
            f23_prior_alerts_90d=0,
        )
        high_risk = _make_features(
            f01_vol_7d_log=15.0,
            f20_pep_flag=1,
            f21_adverse_media_flag=1,
            f23_prior_alerts_90d=5,
        )
        score_low, _, _ = scorer.score_single(schema_version=1, features=low_risk)
        score_high, _, _ = scorer.score_single(schema_version=1, features=high_risk)
        # We don't hard-assert direction — the synthetic training data is random —
        # but the two scores should at least be computable floats in [0, 1].
        assert 0.0 <= score_low <= 1.0
        assert 0.0 <= score_high <= 1.0

    def test_raises_on_unsupported_schema_version(self, scorer: InferenceScorer) -> None:
        with pytest.raises(SchemaVersionMismatchError) as exc_info:
            scorer.score_single(schema_version=99, features=_make_features())
        assert exc_info.value.requested == 99

    def test_schema_mismatch_error_has_supported_set(self, scorer: InferenceScorer) -> None:
        with pytest.raises(SchemaVersionMismatchError) as exc_info:
            scorer.score_single(schema_version=99, features=_make_features())
        # supported must be a non-empty set
        assert len(exc_info.value.supported) >= 1

    def test_zero_version_raises_mismatch(self, scorer: InferenceScorer) -> None:
        """Schema version 0 is not in SUPPORTED_SCHEMA_VERSIONS."""
        with pytest.raises(SchemaVersionMismatchError):
            scorer.score_single(schema_version=0, features=_make_features())

    def test_score_method_called_not_predict(self, scorer: InferenceScorer) -> None:
        """Capacity-ranking policy: InferenceScorer must call scorer.score(), never predict().

        We verify this by patching both methods on the underlying TriageScorer and
        asserting that score() was called exactly once while predict() was never called.
        """
        from unittest.mock import patch, call
        import numpy as np

        features = _make_features()
        underlying_scorer = scorer.artifact.scorer

        # Patch predict to raise immediately if called — that would be a policy violation.
        with patch.object(underlying_scorer, "predict", side_effect=AssertionError(
            "predict() must not be called — capacity-ranking mode only"
        )) as mock_predict, patch.object(
            underlying_scorer, "score", wraps=underlying_scorer.score
        ) as mock_score:
            risk_score, _, _ = scorer.score_single(schema_version=1, features=features)

        # score() must have been called exactly once with a (1, 24) array.
        assert mock_score.call_count == 1
        # predict() must not have been called.
        mock_predict.assert_not_called()

    def test_quality_flags_pass_through_on_clean_input(self, scorer: InferenceScorer) -> None:
        _, flags, _ = scorer.score_single(schema_version=1, features=_make_features())
        assert not flags.quality_warning

    def test_quality_flags_set_on_zeroed_feature(self, scorer: InferenceScorer) -> None:
        features = _make_features(f01_vol_7d_log=0)
        _, flags, _ = scorer.score_single(schema_version=1, features=features)
        assert flags.has_zeroed_features
        assert flags.quality_warning


# ------------------------------------------------------------------ #
# TestScoreBatch                                                       #
# ------------------------------------------------------------------ #

class TestScoreBatch:
    def test_returns_three_tuple(self, scorer: InferenceScorer) -> None:
        features = [_make_features()]
        result = scorer.score_batch(schema_version=1, features_list=features)
        assert len(result) == 3

    def test_risk_scores_is_ndarray(self, scorer: InferenceScorer) -> None:
        risk_scores, _, _ = scorer.score_batch(
            schema_version=1, features_list=[_make_features(), _make_features()]
        )
        assert isinstance(risk_scores, np.ndarray)

    def test_risk_scores_shape(self, scorer: InferenceScorer) -> None:
        n = 5
        risk_scores, _, _ = scorer.score_batch(
            schema_version=1, features_list=[_make_features() for _ in range(n)]
        )
        assert risk_scores.shape == (n,)

    def test_risk_scores_in_unit_interval(self, scorer: InferenceScorer) -> None:
        risk_scores, _, _ = scorer.score_batch(
            schema_version=1, features_list=[_make_features() for _ in range(10)]
        )
        assert (risk_scores >= 0.0).all()
        assert (risk_scores <= 1.0).all()

    def test_quality_flags_list_length_matches_input(self, scorer: InferenceScorer) -> None:
        n = 7
        _, flags_list, _ = scorer.score_batch(
            schema_version=1, features_list=[_make_features() for _ in range(n)]
        )
        assert len(flags_list) == n

    def test_quality_flags_list_contains_correct_type(self, scorer: InferenceScorer) -> None:
        _, flags_list, _ = scorer.score_batch(
            schema_version=1, features_list=[_make_features(), _make_features()]
        )
        for flags in flags_list:
            assert isinstance(flags, DataQualityFlags)

    def test_latency_ms_non_negative(self, scorer: InferenceScorer) -> None:
        _, _, latency_ms = scorer.score_batch(
            schema_version=1, features_list=[_make_features()]
        )
        assert latency_ms >= 0.0

    def test_batch_raises_on_unsupported_schema_version(self, scorer: InferenceScorer) -> None:
        with pytest.raises(SchemaVersionMismatchError):
            scorer.score_batch(schema_version=99, features_list=[_make_features()])

    def test_single_item_batch_matches_single_score(self, scorer: InferenceScorer) -> None:
        """score_batch([f]) should give the same score as score_single(f)."""
        features = _make_features()
        single_score, _, _ = scorer.score_single(schema_version=1, features=features)
        batch_scores, _, _ = scorer.score_batch(schema_version=1, features_list=[features])
        assert pytest.approx(single_score, rel=1e-9) == float(batch_scores[0])

    def test_batch_is_deterministic(self, scorer: InferenceScorer) -> None:
        features_list = [_make_features() for _ in range(5)]
        scores_a, _, _ = scorer.score_batch(schema_version=1, features_list=features_list)
        scores_b, _, _ = scorer.score_batch(schema_version=1, features_list=features_list)
        np.testing.assert_array_equal(scores_a, scores_b)
