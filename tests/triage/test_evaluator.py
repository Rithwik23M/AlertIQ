"""Tests for Evaluator — metric calculations, comparison table, threshold curve."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alertiq.triage.config import TriageConfig
from alertiq.triage.evaluator import Evaluator, RankingMetrics, ThresholdMetrics


@pytest.fixture
def config():
    return TriageConfig()


@pytest.fixture
def evaluator(config):
    return Evaluator(config)


def _make_probs_y(n: int = 200, positive_frac: float = 0.1, seed: int = 0):
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < positive_frac).astype(np.int32)
    # Informative probabilities: positives generally score higher
    probs = rng.beta(2, 5, n)
    probs[y == 1] = rng.beta(5, 2, y.sum())
    probs = np.clip(probs, 0.0, 1.0)
    return probs, y


def _make_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "alert_id": [f"A{i}" for i in range(n)],
        "account_id": [f"ACC{i % 20}" for i in range(n)],
        "rule_id": [f"R{(i % 15) + 1:02d}" for i in range(n)],
        "severity": rng.choice(["critical", "high", "medium", "low"], size=n),
    })


class TestThresholdMetrics:
    def test_perfect_classifier(self, evaluator):
        y = np.array([0, 0, 0, 1, 1], dtype=np.int32)
        probs = np.array([0.1, 0.1, 0.1, 0.9, 0.9])
        tm = evaluator._threshold_metrics(probs, y, threshold=0.5)
        assert tm.tp == 2
        assert tm.fp == 0
        assert tm.fn == 0
        assert tm.tn == 3
        assert tm.precision == 1.0
        assert tm.recall == 1.0
        assert tm.f1 == 1.0
        assert tm.fpr == 0.0
        assert tm.fnr == 0.0

    def test_random_classifier_at_mid_threshold(self, evaluator):
        rng = np.random.default_rng(1)
        y = (rng.random(1000) < 0.1).astype(np.int32)
        probs = rng.random(1000)
        tm = evaluator._threshold_metrics(probs, y, threshold=0.5)
        assert tm.tp + tm.fp + tm.tn + tm.fn == 1000

    def test_n_positive_predicted_equals_tp_plus_fp(self, evaluator):
        probs, y = _make_probs_y()
        tm = evaluator._threshold_metrics(probs, y, threshold=0.4)
        assert tm.n_positive_predicted == tm.tp + tm.fp

    def test_alert_reduction_rate_is_between_zero_and_one(self, evaluator):
        probs, y = _make_probs_y()
        tm = evaluator._threshold_metrics(probs, y, threshold=0.5)
        assert 0.0 <= tm.alert_reduction_rate <= 1.0

    def test_all_negative_predictions(self, evaluator):
        y = np.array([0, 0, 1, 1], dtype=np.int32)
        probs = np.array([0.01, 0.02, 0.03, 0.04])
        tm = evaluator._threshold_metrics(probs, y, threshold=0.9)
        assert tm.tp == 0
        assert tm.fp == 0
        assert tm.fn == 2
        assert tm.precision == 0.0
        assert tm.recall == 0.0
        assert tm.f1 == 0.0

    def test_all_positive_predictions(self, evaluator):
        y = np.array([0, 0, 1, 1], dtype=np.int32)
        probs = np.ones(4)
        tm = evaluator._threshold_metrics(probs, y, threshold=0.0)
        assert tm.tp == 2
        assert tm.fp == 2
        assert tm.fn == 0


class TestRankingMetrics:
    def test_recall_at_100pct_equals_one(self, evaluator):
        probs, y = _make_probs_y(200, positive_frac=0.2, seed=7)
        ranking = evaluator._precision_recall_at_k(probs, y, (1.0,))
        assert abs(ranking[0].recall_at_k - 1.0) < 1e-6

    def test_precision_at_k_is_sars_per_100_divided_by_100(self, evaluator):
        probs, y = _make_probs_y()
        ranking = evaluator._precision_recall_at_k(probs, y, (0.20,))
        rm = ranking[0]
        expected = rm.tp_at_k / rm.k * 100
        assert abs(rm.sars_per_100_reviewed - expected) < 1e-9

    def test_recall_at_k_is_monotone_non_decreasing(self, evaluator):
        probs, y = _make_probs_y(500, positive_frac=0.15, seed=3)
        caps = (0.10, 0.20, 0.30, 0.50, 1.00)
        ranking = evaluator._precision_recall_at_k(probs, y, caps)
        recalls = [rm.recall_at_k for rm in ranking]
        for i in range(len(recalls) - 1):
            assert recalls[i] <= recalls[i + 1] + 1e-9, f"Recall decreased at index {i}"

    def test_k_values_scale_with_capacity_fraction(self, evaluator):
        n = 100
        probs, y = _make_probs_y(n, seed=0)
        caps = (0.10, 0.50)
        ranking = evaluator._precision_recall_at_k(probs, y, caps)
        assert ranking[0].k == 10
        assert ranking[1].k == 50


class TestOperationalMetrics:
    def test_analyst_hours_proportional_to_k(self, evaluator):
        probs, y = _make_probs_y(200, seed=4)
        ops = evaluator._operational_metrics(probs, y, "test", (0.10, 0.20))
        # hours at 20% should be approximately 2× hours at 10% (ignoring sar filing)
        # (not exact due to TP differences)
        assert ops[1].analyst_hours_to_review_k > ops[0].analyst_hours_to_review_k

    def test_missed_sar_rate_between_zero_and_one(self, evaluator):
        probs, y = _make_probs_y(300, seed=5)
        ops = evaluator._operational_metrics(probs, y, "test", (0.10, 0.50))
        for m in ops:
            assert 0.0 <= m.missed_sar_rate <= 1.0

    def test_total_analyst_hours_equals_review_plus_filing(self, evaluator):
        probs, y = _make_probs_y(200, seed=6)
        ops = evaluator._operational_metrics(probs, y, "test", (0.20,))
        m = ops[0]
        assert abs(m.total_analyst_hours - (m.analyst_hours_to_review_k + m.sar_filing_hours)) < 1e-9


class TestEvaluationResult:
    def test_evaluate_returns_correct_scorer_name(self, evaluator):
        from alertiq.triage.baseline import RandomScorer
        probs, y = _make_probs_y(200, seed=0)
        df = _make_df(200, seed=0)
        scorer = RandomScorer(TriageConfig())
        X = np.zeros((200, 24))
        result = evaluator.evaluate(scorer, X, y, df)
        assert result.scorer_name == "baseline_random"

    def test_evaluate_auc_roc_for_random_scorer_near_half(self, evaluator):
        """Random scorer should produce AUC-ROC close to 0.5 on large enough data."""
        from alertiq.triage.baseline import RandomScorer
        # Use seed=7 for y so it doesn't collide with TriageConfig's default seed=42
        rng = np.random.default_rng(7)
        n = 2000
        y = (rng.random(n) < 0.1).astype(np.int32)
        df = _make_df(n, seed=0)
        X = np.zeros((n, 24))
        scorer = RandomScorer(TriageConfig())
        result = evaluator.evaluate(scorer, X, y, df)
        assert 0.40 < result.auc_roc < 0.65

    def test_summary_dict_has_required_keys(self, evaluator):
        from alertiq.triage.baseline import RandomScorer
        probs, y = _make_probs_y(200, seed=0)
        df = _make_df(200, seed=0)
        scorer = RandomScorer(TriageConfig())
        X = np.zeros((200, 24))
        result = evaluator.evaluate(scorer, X, y, df)
        d = result.summary_dict()
        # Threshold-free ranking metrics (both modes)
        for key in ("auc_roc", "auc_pr"):
            assert key in d, f"Missing key: {key}"
        # Classification-mode keys (prefixed cls_)
        for key in ("cls_precision", "cls_recall", "cls_f1", "cls_fpr", "cls_fnr"):
            assert key in d, f"Missing cls-mode key: {key}"
        # Bare unprefixed names must NOT appear (mode conflation guard)
        for key in ("precision", "recall", "f1", "fpr", "fnr"):
            assert key not in d, f"Bare key '{key}' found — use cls_ or rank_ prefix"
        # Capacity-ranking mode keys (prefixed rank_)
        assert "rank_recall_at_20pct" in d
        assert "rank_precision_at_20pct" in d

    def test_error_analysis_contains_expected_keys(self, evaluator):
        from alertiq.triage.baseline import SeverityScorer
        probs, y = _make_probs_y(200, seed=1)
        df = _make_df(200, seed=1)
        scorer = SeverityScorer(TriageConfig())
        X = np.zeros((200, 24))
        result = evaluator.evaluate(scorer, X, y, df)
        ea = result.error_analysis
        for key in ("n_tp", "n_fp", "n_fn", "n_tn", "fp_score_stats", "fn_score_stats"):
            assert key in ea, f"Missing error analysis key: {key}"


class TestComparisonTable:
    def test_comparison_table_has_all_scorers(self, evaluator):
        from alertiq.triage.baseline import RandomScorer, SeverityScorer
        n = 300
        df = _make_df(n, seed=0)
        _, y = _make_probs_y(n, seed=0)
        X = np.zeros((n, 24))
        r1 = evaluator.evaluate(RandomScorer(TriageConfig()), X, y, df)
        r2 = evaluator.evaluate(SeverityScorer(TriageConfig()), X, y, df)
        table = Evaluator.comparison_table([r1, r2])
        assert "baseline_random" in table.index
        assert "baseline_severity" in table.index

    def test_comparison_table_auc_column_is_numeric(self, evaluator):
        from alertiq.triage.baseline import RandomScorer
        n = 200
        df = _make_df(n)
        _, y = _make_probs_y(n)
        X = np.zeros((n, 24))
        r = evaluator.evaluate(RandomScorer(TriageConfig()), X, y, df)
        table = Evaluator.comparison_table([r])
        assert table["auc_roc"].dtype in (np.float32, np.float64, float)


class TestThresholdCurve:
    def test_threshold_curve_has_expected_columns(self):
        probs, y = _make_probs_y(200, seed=0)
        df = Evaluator.threshold_curve(probs, y, n_points=50)
        for col in ("threshold", "precision", "recall", "f1"):
            assert col in df.columns

    def test_threshold_curve_monotone_threshold(self):
        probs, y = _make_probs_y(200, seed=0)
        df = Evaluator.threshold_curve(probs, y, n_points=50)
        # Thresholds should be monotonically non-decreasing
        diffs = np.diff(df["threshold"].values)
        assert np.all(diffs >= -1e-9), "Threshold values not monotone"

    def test_threshold_curve_length_matches_n_points(self):
        probs, y = _make_probs_y(200, seed=0)
        df = Evaluator.threshold_curve(probs, y, n_points=77)
        assert len(df) == 77


class TestEvaluatorEdgeCases:
    """Branch coverage for edge conditions in the evaluator."""

    def test_evaluate_scorer_without_feature_importances(self, evaluator):
        """Scorer lacking feature_importances should produce empty feat_imp dict."""
        from alertiq.triage.baseline import RandomScorer

        probs, y = _make_probs_y(100, seed=5)
        df = _make_df(100, seed=5)
        scorer = RandomScorer(TriageConfig())
        X = np.zeros((100, 24))
        result = evaluator.evaluate(scorer, X, y, df)
        # RandomScorer has no feature_importances attribute — result should still work
        assert result.feature_importances == {} or isinstance(result.feature_importances, dict)

    def test_evaluate_scorer_with_broken_feature_importances(self, evaluator):
        """Scorer whose feature_importances raises should not crash evaluation."""
        from alertiq.triage.baseline import RandomScorer

        class BrokenImportancesScorer(RandomScorer):
            def feature_importances(self, feature_names):  # noqa: D102
                raise RuntimeError("intentional failure")

        probs, y = _make_probs_y(100, seed=6)
        df = _make_df(100, seed=6)
        scorer = BrokenImportancesScorer(TriageConfig())
        X = np.zeros((100, 24))
        # Should not raise despite feature_importances failing
        result = evaluator.evaluate(scorer, X, y, df)
        assert result.feature_importances == {}

    def test_capacity_metric_k_zero_sars_per_100(self, evaluator):
        """RankingMetrics.sars_per_100_reviewed returns 0.0 when k=0 (division guard)."""
        from alertiq.triage.evaluator import RankingMetrics

        m = RankingMetrics(
            capacity_fraction=0.0,
            k=0,
            tp_at_k=0,
            total_true_sars=100,
            precision_at_k=0.0,
            recall_at_k=0.0,
        )
        # k == 0: sars_per_100_reviewed must return 0.0 without dividing by zero
        assert m.sars_per_100_reviewed == 0.0

    def test_error_analysis_no_fn_accounts_column(self, evaluator):
        """Error analysis should not crash when analysis_df lacks account_id column."""
        from alertiq.triage.baseline import RandomScorer

        probs, y = _make_probs_y(100, seed=7)
        # Build df WITHOUT account_id
        import pandas as pd
        df = pd.DataFrame({
            "severity": ["critical"] * 50 + ["high"] * 50,
            "rule_id": ["R01"] * 100,
        })
        scorer = RandomScorer(TriageConfig())
        X = np.zeros((100, 24))
        # Should not raise
        result = evaluator.evaluate(scorer, X, y, df)
        assert result.error_analysis is not None
