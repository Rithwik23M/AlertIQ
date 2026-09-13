"""
Tests for src/alertiq/robustness/calibration.py
"""

from __future__ import annotations

import numpy as np
import pytest

from alertiq.robustness.calibration import (
    ECE_THRESHOLD,
    CalibrationResult,
    apply_calibrator,
    brier_score,
    evaluate_calibration,
    expected_calibration_error,
    fit_isotonic_calibrator,
    fit_platt_calibrator,
)


# ---------------------------------------------------------------------------
# Brier score
# ---------------------------------------------------------------------------

class TestBrierScore:
    def test_perfect_predictions(self):
        y = np.array([1, 1, 0, 0])
        p = np.array([1.0, 1.0, 0.0, 0.0])
        assert brier_score(y, p) == pytest.approx(0.0)

    def test_random_at_50_pct_base_rate(self):
        # Constant 0.5 predictions at 50% base rate → Brier = 0.25
        y = np.array([1, 0, 1, 0])
        p = np.array([0.5, 0.5, 0.5, 0.5])
        assert brier_score(y, p) == pytest.approx(0.25)

    def test_worst_predictions(self):
        y = np.array([1, 0])
        p = np.array([0.0, 1.0])
        assert brier_score(y, p) == pytest.approx(1.0)

    def test_symmetry(self):
        rng = np.random.default_rng(0)
        y = (rng.random(100) > 0.5).astype(int)
        p = rng.random(100)
        bs1 = brier_score(y, p)
        bs2 = brier_score(y, p)
        assert bs1 == pytest.approx(bs2)


# ---------------------------------------------------------------------------
# ECE
# ---------------------------------------------------------------------------

class TestExpectedCalibrationError:
    def test_perfect_calibration(self):
        # Each bin: fraction_positive == mean_predicted_prob
        rng = np.random.default_rng(0)
        y_prob = rng.uniform(0, 1, 1000)
        y_true = (rng.uniform(0, 1, 1000) < y_prob).astype(int)
        ece, _, _, _ = expected_calibration_error(y_true, y_prob, n_bins=10)
        # Should be close to 0 for perfectly calibrated data
        assert ece < 0.10  # loose bound for stochastic test

    def test_overconfident_model(self):
        # Model always predicts 0.9 but true rate is 0.5
        y_true = np.array([1, 0] * 50)
        y_prob = np.ones(100) * 0.9
        ece, _, _, _ = expected_calibration_error(y_true, y_prob)
        # ECE ≈ |0.5 − 0.9| = 0.4
        assert ece == pytest.approx(0.4, abs=0.05)

    def test_empty_bins_skipped(self):
        # All probs in a narrow range — only one bin will have data
        y_true = np.array([1, 0, 1, 0])
        y_prob = np.array([0.55, 0.56, 0.54, 0.55])
        ece, fps, mps, counts = expected_calibration_error(y_true, y_prob)
        assert len(fps) == len(mps) == len(counts)
        assert len(counts) >= 1

    def test_returns_four_values(self):
        y_true = np.array([1, 0, 1, 0])
        y_prob = np.array([0.8, 0.3, 0.7, 0.2])
        result = expected_calibration_error(y_true, y_prob)
        assert len(result) == 4

    def test_ece_non_negative(self):
        rng = np.random.default_rng(5)
        y_true = rng.integers(0, 2, 200)
        y_prob = rng.random(200)
        ece, _, _, _ = expected_calibration_error(y_true, y_prob)
        assert ece >= 0.0


# ---------------------------------------------------------------------------
# CalibrationResult.is_well_calibrated
# ---------------------------------------------------------------------------

class TestCalibrationResultProperty:
    def test_below_threshold_is_well_calibrated(self):
        r = CalibrationResult(
            label="test", brier_score=0.05, ece=ECE_THRESHOLD - 0.01,
            n_bins=10, bin_fraction_positive=[], bin_mean_predicted_prob=[], bin_counts=[],
        )
        assert r.is_well_calibrated

    def test_at_threshold_not_well_calibrated(self):
        r = CalibrationResult(
            label="test", brier_score=0.05, ece=ECE_THRESHOLD,
            n_bins=10, bin_fraction_positive=[], bin_mean_predicted_prob=[], bin_counts=[],
        )
        assert not r.is_well_calibrated


# ---------------------------------------------------------------------------
# Platt calibrator
# ---------------------------------------------------------------------------

class TestPlattCalibrator:
    def test_fit_and_apply(self):
        rng = np.random.default_rng(0)
        scores = rng.random(200)
        labels = (rng.random(200) < scores).astype(int)
        cal = fit_platt_calibrator(scores, labels)
        calibrated = apply_calibrator(cal, scores)
        assert calibrated.shape == scores.shape
        assert (calibrated >= 0).all() and (calibrated <= 1).all()

    def test_outputs_are_probabilities(self):
        scores = np.linspace(0, 1, 50)
        labels = (scores > 0.5).astype(int)
        cal = fit_platt_calibrator(scores, labels)
        calibrated = apply_calibrator(cal, np.array([0.0, 0.5, 1.0]))
        assert all(0 <= p <= 1 for p in calibrated)


# ---------------------------------------------------------------------------
# Isotonic calibrator
# ---------------------------------------------------------------------------

class TestIsotonicCalibrator:
    def test_fit_and_apply(self):
        rng = np.random.default_rng(1)
        scores = rng.random(200)
        labels = (rng.random(200) < scores).astype(int)
        cal = fit_isotonic_calibrator(scores, labels)
        calibrated = apply_calibrator(cal, scores)
        assert calibrated.shape == scores.shape
        assert (calibrated >= 0).all() and (calibrated <= 1).all()

    def test_outputs_bounded(self):
        scores = np.array([0.0, 0.5, 1.0])
        labels = np.array([0, 1, 1])
        cal = fit_isotonic_calibrator(scores, labels)
        calibrated = apply_calibrator(cal, np.array([-0.5, 0.5, 1.5]))
        assert all(0 <= p <= 1 for p in calibrated)

    def test_isotonic_is_non_decreasing(self):
        """Isotonic calibrator output should be monotonically non-decreasing."""
        rng = np.random.default_rng(2)
        scores = rng.random(200)
        labels = (rng.random(200) < scores).astype(int)
        cal = fit_isotonic_calibrator(scores, labels)
        test_scores = np.linspace(0, 1, 20)
        calibrated = apply_calibrator(cal, test_scores)
        diffs = np.diff(calibrated)
        assert (diffs >= -1e-9).all()  # allow tiny floating-point noise


# ---------------------------------------------------------------------------
# apply_calibrator type dispatch
# ---------------------------------------------------------------------------

class TestApplyCalibrator:
    def test_unknown_type_raises(self):
        with pytest.raises(TypeError, match="Unknown calibrator type"):
            apply_calibrator("not_a_calibrator", np.array([0.5]))


# ---------------------------------------------------------------------------
# evaluate_calibration
# ---------------------------------------------------------------------------

class TestEvaluateCalibration:
    def test_returns_calibration_result(self):
        rng = np.random.default_rng(3)
        y_prob = rng.random(100)
        y_true = (rng.random(100) < y_prob).astype(int)
        result = evaluate_calibration(y_true, y_prob, label="test", n_bins=10)
        assert isinstance(result, CalibrationResult)
        assert result.label == "test"
        assert result.n_bins == 10
        assert result.brier_score >= 0.0
        assert result.ece >= 0.0
