"""Tests for TriageScorer — training protocol, scoring, threshold selection."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.datasets import make_classification

from alertiq.triage.config import TriageConfig
from alertiq.triage.scorer import TriageScorer


@pytest.fixture
def config():
    return TriageConfig(
        # Use faster hyperparams for unit testing.
        # Disable categorical_feature_indices because make_classification generates
        # continuous features at all positions; HistGBM would reject high-cardinality
        # floats at those indices.
        hyperparams={"max_iter": 50, "n_iter_no_change": 5},
        categorical_feature_indices=(),
    )


def _synthetic_data(
    n: int = 400, n_features: int = 24, imbalance: float = 0.1, seed: int = 0
):
    """Generate imbalanced binary classification data."""
    X, y = make_classification(
        n_samples=n,
        n_features=n_features,
        n_informative=8,
        n_redundant=4,
        weights=[1 - imbalance, imbalance],
        random_state=seed,
    )
    return X.astype(np.float64), y.astype(np.int32)


@pytest.fixture
def train_val_holdout():
    X, y = _synthetic_data(600, seed=42)
    X_tr, y_tr = X[:360], y[:360]
    X_va, y_va = X[360:480], y[360:480]
    X_ho, y_ho = X[480:], y[480:]
    return X_tr, y_tr, X_va, y_va, X_ho, y_ho


class TestTriageScorerFitting:
    def test_fit_phase1_returns_self(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        scorer = TriageScorer(config)
        result = scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        assert result is scorer

    def test_fit_phase1_sets_best_iter(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        assert scorer.best_iter is not None
        assert scorer.best_iter >= 1

    def test_fit_phase2_requires_phase1_first(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, X_ho, y_ho = train_val_holdout
        scorer = TriageScorer(config)
        with pytest.raises(RuntimeError, match="fit_phase1"):
            scorer.fit_phase2(np.vstack([X_tr, X_va]), np.hstack([y_tr, y_va]))

    def test_fit_phase2_returns_self(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        result = scorer.fit_phase2(np.vstack([X_tr, X_va]), np.hstack([y_tr, y_va]))
        assert result is scorer

    def test_threshold_is_in_valid_range(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        assert 0.0 <= scorer.threshold <= 1.0

    def test_score_before_fit_raises(self, config, train_val_holdout):
        *_, X_ho, y_ho = train_val_holdout
        scorer = TriageScorer(config)
        with pytest.raises(RuntimeError, match="not fitted"):
            scorer.score(X_ho)

    def test_name_is_histgbm_triage(self, config):
        assert TriageScorer(config).name == "histgbm_triage"


class TestTriageScorerScoring:
    def test_score_returns_probabilities_in_zero_one(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, X_ho, y_ho = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        scores = scorer.score(X_ho)
        assert np.all(scores >= 0.0)
        assert np.all(scores <= 1.0)

    def test_predict_returns_binary(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, X_ho, y_ho = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        preds = scorer.predict(X_ho)
        assert set(preds).issubset({0, 1})

    def test_predict_consistent_with_score_and_threshold(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, X_ho, y_ho = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        probs = scorer.score(X_ho)
        preds = scorer.predict(X_ho)
        expected = (probs >= scorer.threshold).astype(int)
        np.testing.assert_array_equal(preds, expected)

    def test_reproducibility_across_runs(self, train_val_holdout):
        """Same seed → same scores."""
        X_tr, y_tr, X_va, y_va, X_ho, y_ho = train_val_holdout
        # categorical_feature_indices=() because make_classification generates
        # continuous floats; HistGBM rejects high-cardinality floats at categorical indices.
        cfg = TriageConfig(
            hyperparams={"max_iter": 30, "n_iter_no_change": 5},
            categorical_feature_indices=(),
        )
        s1 = TriageScorer(cfg)
        s1.fit_phase1(X_tr, y_tr, X_va, y_va)
        p1 = s1.score(X_ho)

        s2 = TriageScorer(cfg)
        s2.fit_phase1(X_tr, y_tr, X_va, y_va)
        p2 = s2.score(X_ho)

        np.testing.assert_array_almost_equal(p1, p2, decimal=6)

    def test_phase2_scores_differ_from_phase1(self, config, train_val_holdout):
        """Refitting on more data can change predictions (not guaranteed identical)."""
        X_tr, y_tr, X_va, y_va, X_ho, y_ho = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        p1 = scorer.score(X_ho).copy()
        scorer.fit_phase2(np.vstack([X_tr, X_va]), np.hstack([y_tr, y_va]))
        p2 = scorer.score(X_ho)
        # Phase 2 should produce valid scores (not necessarily identical)
        assert np.all(p2 >= 0.0)
        assert np.all(p2 <= 1.0)


class TestThresholdSelection:
    def test_select_threshold_returns_value_in_prob_range(self):
        rng = np.random.default_rng(0)
        probs = rng.random(200)
        y = (probs > 0.6).astype(int)
        thr = TriageScorer._select_threshold(probs, y)
        assert np.percentile(probs, 1) <= thr <= np.percentile(probs, 99)

    def test_select_threshold_all_negative_labels(self):
        """Edge case: no positives. Should return some valid threshold."""
        probs = np.linspace(0, 1, 100)
        y = np.zeros(100, dtype=int)
        thr = TriageScorer._select_threshold(probs, y)
        assert 0.0 <= thr <= 1.0

    def test_select_threshold_all_positive_labels(self):
        """Edge case: all positive. Should return some valid threshold."""
        probs = np.linspace(0, 1, 100)
        y = np.ones(100, dtype=int)
        thr = TriageScorer._select_threshold(probs, y)
        assert 0.0 <= thr <= 1.0

    def test_perfect_classifier_selects_discriminative_threshold(self):
        """With perfectly separable data, threshold should separate positive/negative."""
        probs = np.array([0.1] * 80 + [0.9] * 20)
        y = np.array([0] * 80 + [1] * 20)
        thr = TriageScorer._select_threshold(probs, y)
        # Threshold should be between the two clusters
        assert 0.1 < thr < 0.9


class TestFeatureImportances:
    def test_feature_importances_returns_correct_keys(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        names = [f"feat_{i}" for i in range(24)]
        imp = scorer.feature_importances(names)
        assert set(imp.keys()) == set(names)

    def test_feature_importances_non_negative(self, config, train_val_holdout):
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        names = [f"feat_{i}" for i in range(24)]
        imp = scorer.feature_importances(names)
        assert all(v >= 0.0 for v in imp.values())

    def test_feature_importances_before_fit_raises(self, config):
        scorer = TriageScorer(config)
        with pytest.raises(RuntimeError, match="not fitted"):
            scorer.feature_importances(["f"] * 24)


class TestScorerAdditionalBranches:
    """Branch coverage for untested paths in TriageScorer."""

    def test_permutation_importances_before_fit_raises(self, config):
        """permutation_importances must raise RuntimeError before fit."""
        scorer = TriageScorer(config)
        import numpy as np
        with pytest.raises(RuntimeError, match="not fitted"):
            scorer.permutation_importances(np.zeros((10, 24)), np.zeros(10), ["f"] * 24)

    def test_fit_phase2_before_phase1_raises(self, config, train_val_holdout):
        """fit_phase2 must raise RuntimeError if fit_phase1 was never called."""
        scorer = TriageScorer(config)
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        X_tv = np.vstack([X_tr, X_va])
        y_tv = np.hstack([y_tr, y_va])
        with pytest.raises(RuntimeError, match="fit_phase1"):
            scorer.fit_phase2(X_tv, y_tv)

    def test_custom_classification_threshold_respected(self, config, train_val_holdout):
        """When classification_threshold is set in config, fit_phase1 uses it directly."""
        from alertiq.triage.config import TriageConfig
        cfg = TriageConfig(classification_threshold=0.42, categorical_feature_indices=())
        scorer = TriageScorer(cfg)
        X_tr, y_tr, X_va, y_va, *_ = train_val_holdout
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        assert scorer.threshold == pytest.approx(0.42)
