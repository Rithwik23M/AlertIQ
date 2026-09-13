"""
Tests for src/alertiq/robustness/walkforward.py
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from alertiq.robustness.walkforward import (
    WindowDefinition,
    WindowResult,
    _classification_metrics,
    _recall_precision_at_k,
    build_monthly_windows,
    stability_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_monthly_df(n_months: int = 6, n_per_month: int = 100) -> pd.DataFrame:
    """Create a synthetic DataFrame with n_months of alert data."""
    rows = []
    base = datetime.date(2023, 1, 1)
    rng = np.random.default_rng(0)
    for m in range(n_months):
        for d in range(n_per_month):
            day = base + datetime.timedelta(days=m * 30 + d)
            rows.append({
                "triggered_date": day,
                "true_sar": int(rng.random() < 0.10),
                "alert_id": f"A{m}_{d}",
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# build_monthly_windows
# ---------------------------------------------------------------------------

class TestBuildMonthlyWindows:
    def test_produces_three_windows(self):
        df = _make_monthly_df(6)
        windows = build_monthly_windows(df)
        assert len(windows) == 3

    def test_window_labels(self):
        df = _make_monthly_df(6)
        windows = build_monthly_windows(df)
        assert [w.label for w in windows] == ["Window-1", "Window-2", "Window-3"]

    def test_no_overlap_between_val_and_test(self):
        df = _make_monthly_df(6)
        windows = build_monthly_windows(df)
        for w in windows:
            assert w.val_end < w.test_start, f"{w.label}: val_end={w.val_end} >= test_start={w.test_start}"

    def test_expanding_train_sets(self):
        df = _make_monthly_df(6)
        windows = build_monthly_windows(df)
        # Each window's training set should end later (expanding)
        train_ends = [w.train_end for w in windows]
        assert train_ends[0] < train_ends[1] < train_ends[2]

    def test_raises_on_insufficient_months(self):
        # Build a dataset that genuinely spans only 3 calendar months
        import datetime
        rows = []
        base = datetime.date(2023, 1, 1)
        rng = np.random.default_rng(99)
        for m in range(3):
            for d in range(10):
                day = datetime.date(2023, 1 + m, 1 + d)
                rows.append({
                    "triggered_date": day,
                    "true_sar": int(rng.random() < 0.10),
                    "alert_id": f"X{m}_{d}",
                })
        df = pd.DataFrame(rows)
        with pytest.raises(ValueError, match="at least 6 months"):
            build_monthly_windows(df)

    def test_no_future_leakage(self):
        """Training end must always precede validation start."""
        df = _make_monthly_df(6)
        windows = build_monthly_windows(df)
        for w in windows:
            assert w.train_end < w.val_start

    def test_test_windows_non_overlapping(self):
        """Test periods across windows must not overlap."""
        df = _make_monthly_df(6)
        windows = build_monthly_windows(df)
        # Window i's test end must be before window i+1's test start
        for i in range(len(windows) - 1):
            assert windows[i].test_end < windows[i + 1].test_start


# ---------------------------------------------------------------------------
# _recall_precision_at_k
# ---------------------------------------------------------------------------

class TestRecallPrecisionAtK:
    def test_perfect_ranking_full_capacity(self):
        # All SARs ranked first, k = n
        scores = np.array([0.9, 0.8, 0.1, 0.05])
        labels = np.array([1, 1, 0, 0])
        rec, prec = _recall_precision_at_k(scores, labels, 1.0)
        assert rec == pytest.approx(1.0)
        assert prec == pytest.approx(0.5)

    def test_perfect_ranking_20_pct(self):
        # 10 alerts: top 2 (20%) are both SARs
        scores = np.array([0.9, 0.8, 0.5, 0.4, 0.3, 0.2, 0.1, 0.09, 0.08, 0.07])
        labels = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
        rec, prec = _recall_precision_at_k(scores, labels, 0.20)
        assert rec == pytest.approx(1.0)
        assert prec == pytest.approx(1.0)

    def test_no_sars_in_top_k(self):
        scores = np.array([0.9, 0.8, 0.1, 0.05])
        labels = np.array([0, 0, 1, 1])
        rec, prec = _recall_precision_at_k(scores, labels, 0.50)
        assert rec == pytest.approx(0.0)

    def test_no_sars_total(self):
        scores = np.array([0.9, 0.8, 0.1])
        labels = np.array([0, 0, 0])
        rec, prec = _recall_precision_at_k(scores, labels, 0.50)
        assert rec == pytest.approx(0.0)

    def test_capacity_ceil(self):
        # 3 alerts, capacity=0.5 → k=ceil(1.5)=2
        scores = np.array([0.9, 0.8, 0.1])
        labels = np.array([1, 0, 0])
        rec, _ = _recall_precision_at_k(scores, labels, 0.50)
        assert rec == pytest.approx(1.0)

    def test_capacity_at_least_one(self):
        # capacity=0.01 with 5 alerts → k=1
        scores = np.array([0.9, 0.5, 0.4, 0.3, 0.1])
        labels = np.array([1, 0, 0, 0, 0])
        rec, _ = _recall_precision_at_k(scores, labels, 0.01)
        assert rec == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _classification_metrics
# ---------------------------------------------------------------------------

class TestClassificationMetrics:
    def test_perfect_predictions(self):
        scores = np.array([0.9, 0.8, 0.1, 0.05])
        labels = np.array([1, 1, 0, 0])
        m = _classification_metrics(scores, labels, threshold=0.5)
        assert m["precision"] == pytest.approx(1.0)
        assert m["recall"] == pytest.approx(1.0)
        assert m["f1"] == pytest.approx(1.0)
        assert m["fpr"] == pytest.approx(0.0)
        assert m["fnr"] == pytest.approx(0.0)

    def test_all_predicted_positive(self):
        scores = np.array([0.9, 0.9, 0.9, 0.9])
        labels = np.array([1, 0, 1, 0])
        m = _classification_metrics(scores, labels, threshold=0.5)
        assert m["recall"] == pytest.approx(1.0)
        assert m["fpr"] == pytest.approx(1.0)
        assert m["fnr"] == pytest.approx(0.0)

    def test_all_predicted_negative(self):
        scores = np.array([0.1, 0.1, 0.1, 0.1])
        labels = np.array([1, 0, 1, 0])
        m = _classification_metrics(scores, labels, threshold=0.5)
        assert m["recall"] == pytest.approx(0.0)
        assert m["fnr"] == pytest.approx(1.0)

    def test_no_tp_no_fp(self):
        scores = np.array([0.1])
        labels = np.array([0])
        m = _classification_metrics(scores, labels, threshold=0.5)
        assert m["precision"] == pytest.approx(0.0)
        assert m["f1"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# stability_summary
# ---------------------------------------------------------------------------

class TestStabilitySummary:
    def _dummy_result(self, auc: float, recall20: float, label: str) -> WindowResult:
        w = WindowDefinition(
            label=label,
            train_start=datetime.date(2023, 1, 1),
            train_end=datetime.date(2023, 2, 28),
            val_start=datetime.date(2023, 3, 1),
            val_end=datetime.date(2023, 3, 31),
            test_start=datetime.date(2023, 4, 1),
            test_end=datetime.date(2023, 4, 30),
        )
        scores = np.random.default_rng(0).random(100)
        labels = (scores > 0.5).astype(int)
        return WindowResult(
            window=w,
            train_n=200, val_n=100, test_n=100,
            train_sars=20, val_sars=10, test_sars=10,
            train_sar_rate=0.10, val_sar_rate=0.10, test_sar_rate=0.10,
            cls_threshold=0.5,
            auc_roc=auc, auc_pr=auc * 0.8,
            cls_precision=0.7, cls_recall=0.8, cls_f1=0.75,
            cls_fpr=0.05, cls_fnr=0.20,
            recall_at_5pct=0.3, recall_at_10pct=0.5,
            recall_at_20pct=recall20, recall_at_30pct=0.9,
            recall_at_50pct=1.0,
            precision_at_5pct=0.6, precision_at_10pct=0.5,
            precision_at_20pct=0.45, precision_at_30pct=0.4,
            precision_at_50pct=0.3,
            score_mean=0.5, score_std=0.2, score_p10=0.2,
            score_p50=0.5, score_p90=0.8,
            best_iter=100,
            test_scores=scores, test_labels=labels,
            test_df_meta=pd.DataFrame(),
        )

    def test_shape(self):
        results = [
            self._dummy_result(0.90, 0.80, "Window-1"),
            self._dummy_result(0.85, 0.75, "Window-2"),
            self._dummy_result(0.88, 0.78, "Window-3"),
        ]
        df = stability_summary(results)
        assert "auc_roc" in df.index
        assert "recall_at_20pct" in df.index
        assert "mean" in df.columns
        assert "std" in df.columns
        assert "range" in df.columns

    def test_single_window_zero_std(self):
        results = [self._dummy_result(0.90, 0.80, "Window-1")]
        df = stability_summary(results)
        assert df.loc["auc_roc", "std"] == pytest.approx(0.0)
        assert df.loc["auc_roc", "range"] == pytest.approx(0.0)

    def test_mean_correctness(self):
        results = [
            self._dummy_result(0.90, 1.0, "Window-1"),
            self._dummy_result(0.80, 1.0, "Window-2"),
        ]
        df = stability_summary(results)
        assert df.loc["auc_roc", "mean"] == pytest.approx(0.85)
