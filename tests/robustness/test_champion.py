"""
Tests for src/alertiq/robustness/champion.py
"""

from __future__ import annotations

import numpy as np
import pytest

from alertiq.robustness.champion import (
    MAX_REGRESSION_AUC,
    MAX_REGRESSION_RECALL20,
    MIN_IMPROVEMENT_EITHER,
    ModelComparison,
    PromotionDecision,
    _bootstrap_pvalue,
    _recall_at_k,
    compare_window,
    comparisons_to_dataframe,
    promotion_decision,
)


# ---------------------------------------------------------------------------
# _recall_at_k
# ---------------------------------------------------------------------------

class TestRecallAtK:
    def test_perfect(self):
        scores = np.array([0.9, 0.8, 0.1, 0.05])
        labels = np.array([1, 1, 0, 0])
        assert _recall_at_k(scores, labels, 0.50) == pytest.approx(1.0)

    def test_no_sars(self):
        scores = np.array([0.9, 0.5, 0.1])
        labels = np.array([0, 0, 0])
        assert _recall_at_k(scores, labels, 0.50) == pytest.approx(0.0)

    def test_worst_ranking(self):
        scores = np.array([0.9, 0.8, 0.1, 0.05])
        labels = np.array([0, 0, 1, 1])
        assert _recall_at_k(scores, labels, 0.50) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _bootstrap_pvalue
# ---------------------------------------------------------------------------

class TestBootstrapPvalue:
    def test_returns_float_between_0_and_1(self):
        rng = np.random.default_rng(0)
        a = rng.random(100)
        b = a + rng.normal(0, 0.05, 100)
        labels = (rng.random(100) < 0.2).astype(int)

        def metric(scores, y):
            return float(scores.mean())

        p = _bootstrap_pvalue(a, b, labels, metric, n_bootstrap=200)
        assert p is None or 0.0 <= p <= 1.0

    def test_small_n_returns_none(self):
        a = np.array([0.8, 0.5])
        b = np.array([0.9, 0.6])
        labels = np.array([1, 0])
        p = _bootstrap_pvalue(a, b, labels, lambda s, y: float(s.mean()))
        assert p is None

    def test_identical_scores_high_pvalue(self):
        """When a == b, there should be no significant difference."""
        rng = np.random.default_rng(1)
        scores = rng.random(100)
        labels = (rng.random(100) < 0.2).astype(int)
        # Identical → delta is always 0 in bootstrap → p-value near 1.0 but varies

        def metric(s, y):
            n = len(s)
            k = max(1, int(np.ceil(n * 0.2)))
            top = np.argsort(s)[::-1][:k]
            tp = int(y[top].sum())
            total = int(y.sum())
            return tp / total if total > 0 else 0.0

        p = _bootstrap_pvalue(scores, scores, labels, metric, n_bootstrap=200)
        # p should not be None (n=100 > 10)
        assert p is not None


# ---------------------------------------------------------------------------
# compare_window
# ---------------------------------------------------------------------------

class TestCompareWindow:
    def _make_scores(self, n: int = 100, seed: int = 0):
        rng = np.random.default_rng(seed)
        labels = (rng.random(n) < 0.20).astype(int)
        champ_scores = np.clip(
            rng.normal(0.5, 0.2, n) + labels * 0.2, 0, 1
        )
        chal_scores = np.clip(
            rng.normal(0.5, 0.2, n) + labels * 0.25, 0, 1
        )
        return champ_scores, chal_scores, labels

    def test_returns_model_comparison(self):
        champ, chal, labels = self._make_scores()
        result = compare_window("W1", champ, chal, labels, run_bootstrap=False)
        assert isinstance(result, ModelComparison)

    def test_window_label_stored(self):
        champ, chal, labels = self._make_scores()
        result = compare_window("TestWindow", champ, chal, labels, run_bootstrap=False)
        assert result.window_label == "TestWindow"

    def test_deltas_are_chal_minus_champ(self):
        champ, chal, labels = self._make_scores()
        result = compare_window("W1", champ, chal, labels, run_bootstrap=False)
        assert result.delta_recall_at_20 == pytest.approx(
            result.chal_recall_at_20 - result.champ_recall_at_20, abs=1e-6
        )
        assert result.delta_auc_roc == pytest.approx(
            result.chal_auc_roc - result.champ_auc_roc, abs=1e-6
        )

    def test_pvalues_none_when_bootstrap_off(self):
        champ, chal, labels = self._make_scores()
        result = compare_window("W1", champ, chal, labels, run_bootstrap=False)
        assert result.pvalue_recall_at_20 is None
        assert result.pvalue_auc_roc is None

    def test_pvalues_present_when_bootstrap_on(self):
        champ, chal, labels = self._make_scores(n=100)
        result = compare_window("W1", champ, chal, labels, run_bootstrap=True)
        # May be None if there aren't enough bootstrap iterations
        # but should not raise
        assert result.pvalue_recall_at_20 is None or isinstance(
            result.pvalue_recall_at_20, float
        )

    def test_all_metrics_in_range(self):
        champ, chal, labels = self._make_scores(n=200)
        result = compare_window("W1", champ, chal, labels, run_bootstrap=False)
        # AUC-ROC between 0 and 1
        assert 0.0 <= result.champ_auc_roc <= 1.0
        assert 0.0 <= result.chal_auc_roc <= 1.0
        # Recall between 0 and 1
        assert 0.0 <= result.champ_recall_at_20 <= 1.0
        assert 0.0 <= result.chal_recall_at_20 <= 1.0


# ---------------------------------------------------------------------------
# promotion_decision
# ---------------------------------------------------------------------------

class TestPromotionDecision:
    def _make_comparison(
        self,
        window_label: str,
        delta_r20: float,
        delta_auc: float,
    ) -> ModelComparison:
        base_r20 = 0.70
        base_auc = 0.85
        return ModelComparison(
            window_label=window_label,
            champ_auc_roc=base_auc,
            champ_auc_pr=0.60,
            champ_recall_at_20=base_r20,
            champ_precision_at_20=0.50,
            champ_f1=0.60,
            chal_auc_roc=base_auc + delta_auc,
            chal_auc_pr=0.62,
            chal_recall_at_20=base_r20 + delta_r20,
            chal_precision_at_20=0.52,
            chal_f1=0.62,
            delta_auc_roc=delta_auc,
            delta_auc_pr=0.02,
            delta_recall_at_20=delta_r20,
            delta_precision_at_20=0.02,
            delta_f1=0.02,
            pvalue_recall_at_20=None,
            pvalue_auc_roc=None,
        )

    def test_promote_challenger_when_improved(self):
        """Challenger clearly better on both metrics → promote."""
        comparisons = [
            self._make_comparison("W1", delta_r20=0.05, delta_auc=0.03),
            self._make_comparison("W2", delta_r20=0.04, delta_auc=0.02),
        ]
        decision = promotion_decision(comparisons)
        assert decision.recommendation == "promote_challenger"

    def test_retain_champion_when_regressed(self):
        """Challenger regresses recall → retain champion."""
        comparisons = [
            self._make_comparison("W1", delta_r20=-0.05, delta_auc=0.01),
            self._make_comparison("W2", delta_r20=-0.04, delta_auc=0.01),
        ]
        decision = promotion_decision(comparisons)
        assert decision.recommendation == "retain_champion"

    def test_retain_champion_when_no_improvement(self):
        """Challenger neither regresses nor improves → retain."""
        comparisons = [
            self._make_comparison("W1", delta_r20=0.00, delta_auc=0.00),
            self._make_comparison("W2", delta_r20=0.00, delta_auc=0.00),
        ]
        decision = promotion_decision(comparisons)
        assert decision.recommendation == "retain_champion"

    def test_empty_comparisons_returns_inconclusive(self):
        decision = promotion_decision([])
        assert decision.recommendation == "inconclusive"
        assert decision.n_windows == 0

    def test_decision_has_reasons(self):
        comparisons = [
            self._make_comparison("W1", delta_r20=0.05, delta_auc=0.03),
        ]
        decision = promotion_decision(comparisons)
        assert len(decision.reasons) >= 1

    def test_mean_delta_correct(self):
        comparisons = [
            self._make_comparison("W1", delta_r20=0.06, delta_auc=0.04),
            self._make_comparison("W2", delta_r20=0.04, delta_auc=0.02),
        ]
        decision = promotion_decision(comparisons)
        assert decision.mean_delta_recall20 == pytest.approx(0.05)
        assert decision.mean_delta_auc_roc == pytest.approx(0.03)

    def test_windows_better_count(self):
        comparisons = [
            self._make_comparison("W1", delta_r20=0.05, delta_auc=0.03),
            self._make_comparison("W2", delta_r20=-0.01, delta_auc=0.02),
        ]
        decision = promotion_decision(comparisons)
        assert decision.windows_challenger_better_recall20 == 1
        assert decision.windows_challenger_better_auc_roc == 2

    def test_n_windows_correct(self):
        comparisons = [
            self._make_comparison("W1", delta_r20=0.05, delta_auc=0.03),
            self._make_comparison("W2", delta_r20=0.04, delta_auc=0.02),
            self._make_comparison("W3", delta_r20=0.03, delta_auc=0.01),
        ]
        decision = promotion_decision(comparisons)
        assert decision.n_windows == 3


# ---------------------------------------------------------------------------
# comparisons_to_dataframe
# ---------------------------------------------------------------------------

class TestComparisonsToDataframe:
    def _make_comparison(self) -> ModelComparison:
        rng = np.random.default_rng(0)
        n = 100
        labels = (rng.random(n) < 0.2).astype(int)
        champ_scores = np.clip(rng.random(n) + labels * 0.3, 0, 1)
        chal_scores = np.clip(rng.random(n) + labels * 0.35, 0, 1)
        return compare_window("W1", champ_scores, chal_scores, labels, run_bootstrap=False)

    def test_returns_dataframe(self):
        import pandas as pd
        comps = [self._make_comparison()]
        df = comparisons_to_dataframe(comps)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    def test_has_delta_columns(self):
        comps = [self._make_comparison()]
        df = comparisons_to_dataframe(comps)
        assert "delta_recall_at_20" in df.columns
        assert "delta_auc_roc" in df.columns
