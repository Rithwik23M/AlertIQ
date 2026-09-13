"""
Tests for src/alertiq/robustness/drift.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alertiq.robustness.drift import (
    PSI_MINOR,
    PSI_STABLE,
    FeatureDriftResult,
    _categorical_drift,
    _psi,
    compute_feature_drift,
    drift_summary,
    label_shift_analysis,
)


# ---------------------------------------------------------------------------
# PSI helpers
# ---------------------------------------------------------------------------

class TestPSI:
    def test_identical_distributions(self):
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 500)
        assert _psi(x, x) == pytest.approx(0.0, abs=1e-3)

    def test_constant_feature_zero_psi(self):
        base = np.ones(100) * 5.0
        window = np.ones(80) * 5.0
        assert _psi(base, window) == pytest.approx(0.0)

    def test_shifted_distribution_nonzero_psi(self):
        rng = np.random.default_rng(42)
        base = rng.normal(0, 1, 500)
        window = rng.normal(5, 1, 500)  # large shift
        psi = _psi(base, window)
        assert psi > PSI_MINOR, f"Expected significant PSI, got {psi}"

    def test_slight_shift_stable(self):
        rng = np.random.default_rng(0)
        base = rng.normal(0, 1, 1000)
        window = rng.normal(0.02, 1, 1000)  # tiny shift
        psi = _psi(base, window)
        assert psi < PSI_STABLE, f"Expected stable PSI, got {psi}"

    def test_psi_non_negative(self):
        rng = np.random.default_rng(7)
        base = rng.normal(0, 1, 200)
        window = rng.normal(1, 2, 200)
        assert _psi(base, window) >= 0.0

    def test_window_clipped_to_baseline_range(self):
        base = np.linspace(0, 10, 100)
        # Window entirely outside baseline range — clipped to edge bins
        window = np.linspace(20, 30, 100)
        psi = _psi(base, window)
        assert psi >= 0.0  # should not raise


# ---------------------------------------------------------------------------
# Categorical drift
# ---------------------------------------------------------------------------

class TestCategoricalDrift:
    def test_identical_categories(self):
        base = np.array(["A", "B", "C", "A", "B"])
        window = np.array(["A", "B", "C", "A", "B"])
        max_change, chi2_s, chi2_p = _categorical_drift(base, window)
        assert max_change == pytest.approx(0.0, abs=1e-6)

    def test_novel_category_in_window(self):
        base = np.array(["A", "A", "B", "B"])
        window = np.array(["A", "B", "C", "C"])  # C is novel
        max_change, chi2_s, chi2_p = _categorical_drift(base, window)
        assert max_change > 0.0

    def test_returns_three_values(self):
        base = np.array(["A", "B"])
        window = np.array(["A", "B"])
        result = _categorical_drift(base, window)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# compute_feature_drift
# ---------------------------------------------------------------------------

class TestComputeFeatureDrift:
    def _make_df(self, n: int, mean: float = 0.0, seed: int = 0) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        return pd.DataFrame({
            "f_cont": rng.normal(mean, 1, n),
            "f_cat": rng.choice(["A", "B", "C"], n),
        })

    def test_returns_one_result_per_feature(self):
        base = self._make_df(200)
        window = self._make_df(100)
        results = compute_feature_drift(base, window, ["f_cont", "f_cat"], (1,))
        assert len(results) == 2

    def test_continuous_has_psi(self):
        base = self._make_df(200)
        window = self._make_df(100)
        results = compute_feature_drift(base, window, ["f_cont"])
        cont = [r for r in results if r.feature == "f_cont"][0]
        assert cont.psi is not None
        assert cont.ks_stat is not None

    def test_categorical_has_chi2(self):
        base = self._make_df(200)
        window = self._make_df(100)
        results = compute_feature_drift(base, window, ["f_cat"], (0,))
        cat = [r for r in results if r.feature == "f_cat"][0]
        assert cat.chi2_stat is not None
        assert cat.max_proportion_change is not None
        assert cat.psi is None

    def test_missing_feature_skipped(self):
        base = self._make_df(200)
        window = self._make_df(100)
        results = compute_feature_drift(base, window, ["f_cont", "nonexistent_feature"])
        assert len(results) == 1

    def test_insufficient_values_skipped(self):
        base = self._make_df(200)
        tiny_window = self._make_df(3)  # only 3 rows
        results = compute_feature_drift(base, tiny_window, ["f_cont"])
        assert len(results) == 0

    def test_psi_severity_property(self):
        rng = np.random.default_rng(0)
        r = FeatureDriftResult(
            feature="x", window_label="w", feature_type="continuous",
            psi=0.05, ks_stat=None, ks_pvalue=None,
            max_proportion_change=None, chi2_stat=None, chi2_pvalue=None,
            baseline_mean=0.0, window_mean=0.0, baseline_std=1.0, window_std=1.0,
        )
        assert r.psi_severity == "stable"
        r2 = FeatureDriftResult(
            feature="x", window_label="w", feature_type="continuous",
            psi=0.15, ks_stat=None, ks_pvalue=None,
            max_proportion_change=None, chi2_stat=None, chi2_pvalue=None,
            baseline_mean=0.0, window_mean=0.0, baseline_std=1.0, window_std=1.0,
        )
        assert r2.psi_severity == "minor"
        r3 = FeatureDriftResult(
            feature="x", window_label="w", feature_type="continuous",
            psi=0.30, ks_stat=None, ks_pvalue=None,
            max_proportion_change=None, chi2_stat=None, chi2_pvalue=None,
            baseline_mean=0.0, window_mean=0.0, baseline_std=1.0, window_std=1.0,
        )
        assert r3.psi_severity == "significant"

    def test_is_significant_psi(self):
        r = FeatureDriftResult(
            feature="x", window_label="w", feature_type="continuous",
            psi=0.30, ks_stat=0.1, ks_pvalue=0.5,
            max_proportion_change=None, chi2_stat=None, chi2_pvalue=None,
            baseline_mean=0.0, window_mean=0.0, baseline_std=1.0, window_std=1.0,
        )
        assert r.is_significant

    def test_is_significant_ks(self):
        r = FeatureDriftResult(
            feature="x", window_label="w", feature_type="continuous",
            psi=0.01, ks_stat=0.5, ks_pvalue=0.001,
            max_proportion_change=None, chi2_stat=None, chi2_pvalue=None,
            baseline_mean=0.0, window_mean=0.0, baseline_std=1.0, window_std=1.0,
        )
        assert r.is_significant


# ---------------------------------------------------------------------------
# drift_summary
# ---------------------------------------------------------------------------

class TestDriftSummary:
    def test_shape(self):
        rng = np.random.default_rng(0)
        base = pd.DataFrame({"x": rng.normal(0, 1, 200)})
        w1 = pd.DataFrame({"x": rng.normal(0.5, 1, 100)})
        w2 = pd.DataFrame({"x": rng.normal(1.0, 1, 100)})
        r1 = compute_feature_drift(base, w1, ["x"], window_label="W1")
        r2 = compute_feature_drift(base, w2, ["x"], window_label="W2")
        summary = drift_summary(r1 + r2, ["x"])
        assert "x" in summary.index
        assert "max_psi" in summary.columns
        assert "drift_classification" in summary.columns


# ---------------------------------------------------------------------------
# label_shift_analysis
# ---------------------------------------------------------------------------

class TestLabelShiftAnalysis:
    def _make_alert_df(self, n: int, sar_rate: float = 0.10) -> pd.DataFrame:
        rng = np.random.default_rng(0)
        return pd.DataFrame({
            "true_sar": rng.random(n) < sar_rate,
            "rule_id": rng.choice(["R08", "R15", "R01"], n),
        })

    def test_returns_dataframe(self):
        base = self._make_alert_df(200)
        w1 = self._make_alert_df(100, sar_rate=0.12)
        df = label_shift_analysis(base, [("Window-1", w1)])
        assert isinstance(df, pd.DataFrame)
        assert "baseline_train" in df.index
        assert "Window-1" in df.index

    def test_sar_rate_column(self):
        base = self._make_alert_df(200, sar_rate=0.10)
        w1 = self._make_alert_df(100, sar_rate=0.20)
        df = label_shift_analysis(base, [("W1", w1)])
        assert df.loc["W1", "sar_rate"] == pytest.approx(0.20, abs=0.05)
