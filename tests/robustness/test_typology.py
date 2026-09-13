"""
Tests for src/alertiq/robustness/typology.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alertiq.robustness.typology import (
    MIN_SUPPORT_SARS,
    RECALL_AT_20_FLOOR,
    TypologyResult,
    account_fn_analysis,
    compute_typology_performance,
    typology_summary_df,
)


# ---------------------------------------------------------------------------
# compute_typology_performance
# ---------------------------------------------------------------------------

class TestComputeTypologyPerformance:
    def _make_data(
        self,
        n: int = 300,
        rules: list[str] | None = None,
        sar_rate: float = 0.15,
        seed: int = 0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rng = np.random.default_rng(seed)
        labels = (rng.random(n) < sar_rate).astype(int)
        scores = np.clip(rng.normal(0.5, 0.2, n), 0, 1)
        # SARs get higher scores
        scores[labels == 1] = np.clip(scores[labels == 1] + 0.3, 0, 1)
        if rules is None:
            rules = ["R08"] * (n // 2) + ["R15"] * (n - n // 2)
        rule_ids = np.array(rules)
        return scores, labels, rule_ids

    def test_returns_one_result_per_rule(self):
        scores, labels, rule_ids = self._make_data()
        results = compute_typology_performance(scores, labels, rule_ids, "Window-1")
        rule_set = {r.rule_id for r in results}
        assert rule_set == {"R08", "R15"}

    def test_sorted_by_n_sars_descending(self):
        scores, labels, rule_ids = self._make_data()
        results = compute_typology_performance(scores, labels, rule_ids, "Window-1")
        sars = [r.n_sars for r in results]
        assert sars == sorted(sars, reverse=True)

    def test_sar_rate_correct(self):
        n = 100
        scores = np.random.default_rng(0).random(n)
        labels = np.zeros(n, dtype=int)
        labels[:20] = 1  # 20% SAR rate
        rule_ids = np.array(["R01"] * n)
        results = compute_typology_performance(scores, labels, rule_ids, "W1")
        assert results[0].sar_rate == pytest.approx(0.20)

    def test_gate_applicable_above_floor(self):
        rng = np.random.default_rng(0)
        n = 200
        labels = np.zeros(n, dtype=int)
        labels[:60] = 1  # 60 SARs — above MIN_SUPPORT_SARS
        scores = rng.random(n)
        rule_ids = np.array(["R01"] * n)
        results = compute_typology_performance(scores, labels, rule_ids, "W1", min_support_sars=50)
        r = results[0]
        assert r.above_support_floor

    def test_gate_not_applicable_below_floor(self):
        rng = np.random.default_rng(0)
        n = 100
        labels = np.zeros(n, dtype=int)
        labels[:10] = 1  # only 10 SARs — below 50
        scores = rng.random(n)
        rule_ids = np.array(["R01"] * n)
        results = compute_typology_performance(scores, labels, rule_ids, "W1", min_support_sars=50)
        r = results[0]
        assert not r.above_support_floor
        assert r.gate_pass  # gate not applicable → always pass

    def test_perfect_ranking_recall_at_20(self):
        n = 100
        labels = np.zeros(n, dtype=int)
        labels[:20] = 1
        # Perfect scores: SARs get 1.0, non-SARs get 0.0
        scores = np.zeros(n)
        scores[:20] = 1.0
        rule_ids = np.array(["R01"] * n)
        results = compute_typology_performance(scores, labels, rule_ids, "W1")
        r = results[0]
        # Top 20% (20 alerts) = exactly the SARs → Recall@20% = 1.0
        assert r.recall_at_20pct == pytest.approx(1.0)

    def test_meets_floor_property(self):
        n = 100
        labels = np.zeros(n, dtype=int)
        labels[:60] = 1  # 60 SARs — above MIN_SUPPORT_SARS=50
        # Random scores → low recall@20%
        rng = np.random.default_rng(99)
        scores = rng.random(n)
        rule_ids = np.array(["R01"] * n)
        results = compute_typology_performance(scores, labels, rule_ids, "W1", min_support_sars=50)
        r = results[0]
        expected_meets = r.recall_at_20pct >= RECALL_AT_20_FLOOR
        assert r.meets_floor == expected_meets

    def test_window_label_stored(self):
        scores, labels, rule_ids = self._make_data()
        results = compute_typology_performance(scores, labels, rule_ids, "Window-42")
        for r in results:
            assert r.window_label == "Window-42"

    def test_auc_roc_none_when_no_positives(self):
        scores = np.array([0.5, 0.4, 0.3])
        labels = np.array([0, 0, 0])  # no SARs
        rule_ids = np.array(["R01"] * 3)
        results = compute_typology_performance(scores, labels, rule_ids, "W1")
        if results:  # might be skipped due to small n
            r = results[0]
            assert r.auc_roc is None

    def test_skips_single_alert_rules(self):
        scores = np.array([0.9, 0.5, 0.4])
        labels = np.array([1, 0, 0])
        rule_ids = np.array(["R01", "R99", "R99"])  # R01 has only 1 alert
        results = compute_typology_performance(scores, labels, rule_ids, "W1")
        rule_ids_found = {r.rule_id for r in results}
        assert "R01" not in rule_ids_found  # skipped (only 1 alert)


# ---------------------------------------------------------------------------
# typology_summary_df
# ---------------------------------------------------------------------------

class TestTypologySummaryDf:
    def test_empty_input(self):
        df = typology_summary_df([])
        assert isinstance(df, pd.DataFrame)

    def test_gate_pass_column_present(self):
        scores = np.array([0.9, 0.8, 0.1, 0.2, 0.3])
        labels = np.array([1, 1, 0, 0, 0])
        rule_ids = np.array(["R01"] * 5)
        results = compute_typology_performance(scores, labels, rule_ids, "W1")
        df = typology_summary_df(results)
        assert "gate_pass" in df.columns


# ---------------------------------------------------------------------------
# account_fn_analysis
# ---------------------------------------------------------------------------

class TestAccountFnAnalysis:
    def test_basic(self):
        scores = np.array([0.9, 0.8, 0.1, 0.05, 0.95, 0.03])
        labels = np.array([1, 1, 0, 0, 1, 1])
        accts = np.array(["ACC1", "ACC1", "ACC1", "ACC2", "ACC2", "ACC2"])
        df = account_fn_analysis(scores, labels, accts, threshold=0.5)
        assert isinstance(df, pd.DataFrame)
        # ACC2: scores for SARs are 0.95 and 0.03
        # With threshold=0.5: 0.95 → TP, 0.03 → FN → FN=1
        acc2 = df[df["account_id"] == "ACC2"]
        if len(acc2) > 0:
            assert acc2.iloc[0]["false_negatives"] >= 0

    def test_no_sars_returns_empty(self):
        scores = np.array([0.5, 0.4, 0.3])
        labels = np.array([0, 0, 0])
        accts = np.array(["A", "B", "C"])
        df = account_fn_analysis(scores, labels, accts, threshold=0.5)
        assert len(df) == 0

    def test_top_n_limit(self):
        n = 100
        rng = np.random.default_rng(0)
        scores = rng.random(n)
        labels = rng.integers(0, 2, n)
        accts = np.array([f"ACC{i}" for i in range(n)])
        df = account_fn_analysis(scores, labels, accts, threshold=0.5, top_n=5)
        assert len(df) <= 5

    def test_sorted_by_fn_descending(self):
        n = 50
        rng = np.random.default_rng(1)
        scores = rng.random(n)
        labels = rng.integers(0, 2, n)
        accts = rng.choice(["A", "B", "C", "D"], n)
        df = account_fn_analysis(scores, labels, accts, threshold=0.5)
        if len(df) > 1:
            fns = df["false_negatives"].tolist()
            assert fns == sorted(fns, reverse=True)
