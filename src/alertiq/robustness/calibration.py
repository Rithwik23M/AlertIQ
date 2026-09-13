"""
Probability calibration analysis for AlertIQ Milestone 3.

Metrics
-------
- Brier Score (lower = better; 0.0 = perfect, 0.25 = random at 50% base rate)
- Expected Calibration Error (ECE): mean |observed rate − predicted prob| per bin
  Acceptable: ECE < 0.05
- Reliability curve data (decile-binned)

Calibration methods evaluated
------------------------------
- No calibration (raw HistGBM probabilities)
- Platt scaling (logistic regression on val set scores)
- Isotonic regression (piecewise constant on val set scores)

Rule: any calibrator must be fitted on validation data ONLY.
The final evaluation window's test set must remain untouched until scoring.

Note: GBDT models are often well-calibrated due to the probabilistic nature
of histogram-based training.  Do NOT add a calibration layer unless ECE ≥ 0.05.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

log = logging.getLogger(__name__)

ECE_THRESHOLD = 0.05   # ECE below this → calibration acceptable


@dataclasses.dataclass
class CalibrationResult:
    """Calibration metrics for one scorer/window combination."""

    label: str             # e.g. "Window-2 (no calibration)"
    brier_score: float
    ece: float
    n_bins: int

    # Reliability curve (fraction_positive, mean_predicted_prob, counts per bin)
    bin_fraction_positive: list[float]
    bin_mean_predicted_prob: list[float]
    bin_counts: list[int]

    @property
    def is_well_calibrated(self) -> bool:
        return self.ece < ECE_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "brier_score": self.brier_score,
            "ece": self.ece,
            "n_bins": self.n_bins,
            "is_well_calibrated": self.is_well_calibrated,
        }


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Mean squared error between predicted probabilities and binary outcomes."""
    return float(np.mean((y_prob - y_true.astype(float)) ** 2))


def expected_calibration_error(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> tuple[float, list[float], list[float], list[int]]:
    """
    Compute Expected Calibration Error and reliability curve data.

    Returns:
        (ece, fraction_positives, mean_predicted_probs, bin_counts)
    """
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_indices = np.digitize(y_prob, bins[1:-1])  # 0-indexed bucket

    frac_pos: list[float] = []
    mean_pred: list[float] = []
    counts: list[int] = []

    n = len(y_true)
    weighted_error = 0.0

    for i in range(n_bins):
        mask = bin_indices == i
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        fp = float(y_true[mask].mean())
        mp = float(y_prob[mask].mean())
        frac_pos.append(fp)
        mean_pred.append(mp)
        counts.append(cnt)
        weighted_error += cnt * abs(fp - mp)

    ece = weighted_error / n if n > 0 else 0.0
    return float(ece), frac_pos, mean_pred, counts


def calibration_curve_df(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
    label: str = "",
) -> pd.DataFrame:
    """Return a DataFrame suitable for plotting the reliability curve."""
    ece, fp, mp, cnt = expected_calibration_error(y_true, y_prob, n_bins)
    return pd.DataFrame({
        "label": label,
        "mean_predicted_prob": mp,
        "fraction_positive": fp,
        "count": cnt,
        "ece": ece,
    })


def evaluate_calibration(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    label: str,
    n_bins: int = 10,
) -> CalibrationResult:
    """Compute all calibration metrics for one set of predictions."""
    bs = brier_score(y_true, y_prob)
    ece, fp, mp, cnt = expected_calibration_error(y_true, y_prob, n_bins)
    return CalibrationResult(
        label=label,
        brier_score=bs,
        ece=ece,
        n_bins=n_bins,
        bin_fraction_positive=fp,
        bin_mean_predicted_prob=mp,
        bin_counts=cnt,
    )


def fit_platt_calibrator(
    val_scores: np.ndarray,
    val_labels: np.ndarray,
) -> LogisticRegression:
    """
    Fit a Platt scaling calibrator (logistic regression) on validation scores.

    MUST be fitted on validation data only — never on the test window.
    """
    lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    lr.fit(val_scores.reshape(-1, 1), val_labels)
    return lr


def fit_isotonic_calibrator(
    val_scores: np.ndarray,
    val_labels: np.ndarray,
) -> IsotonicRegression:
    """
    Fit an isotonic regression calibrator on validation scores.

    MUST be fitted on validation data only — never on the test window.
    """
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(val_scores, val_labels.astype(float))
    return iso


def apply_calibrator(
    calibrator: Any,
    scores: np.ndarray,
) -> np.ndarray:
    """Apply a fitted calibrator to raw model scores."""
    if isinstance(calibrator, LogisticRegression):
        return calibrator.predict_proba(scores.reshape(-1, 1))[:, 1]
    if isinstance(calibrator, IsotonicRegression):
        return np.clip(calibrator.predict(scores), 0.0, 1.0)
    raise TypeError(f"Unknown calibrator type: {type(calibrator)}")


def compare_calibration_strategies(
    val_scores: np.ndarray,
    val_labels: np.ndarray,
    test_scores: np.ndarray,
    test_labels: np.ndarray,
    window_label: str,
    n_bins: int = 10,
) -> list[CalibrationResult]:
    """
    Fit calibrators on val; evaluate all strategies on test.

    Returns one CalibrationResult per strategy:
    - No calibration (raw scores)
    - Platt scaling
    - Isotonic regression

    Calibrators are ALWAYS fitted on val_scores/val_labels.
    test_scores/test_labels are used ONLY for final evaluation.
    """
    results = []

    # Strategy 1: raw probabilities
    results.append(evaluate_calibration(
        test_labels, test_scores,
        label=f"{window_label} (raw)",
        n_bins=n_bins,
    ))

    # Strategy 2: Platt scaling
    try:
        platt = fit_platt_calibrator(val_scores, val_labels)
        platt_scores = apply_calibrator(platt, test_scores)
        results.append(evaluate_calibration(
            test_labels, platt_scores,
            label=f"{window_label} (Platt)",
            n_bins=n_bins,
        ))
    except Exception as exc:
        log.warning("Platt calibration failed for %s: %s", window_label, exc)

    # Strategy 3: Isotonic regression
    try:
        iso = fit_isotonic_calibrator(val_scores, val_labels)
        iso_scores = apply_calibrator(iso, test_scores)
        results.append(evaluate_calibration(
            test_labels, iso_scores,
            label=f"{window_label} (isotonic)",
            n_bins=n_bins,
        ))
    except Exception as exc:
        log.warning("Isotonic calibration failed for %s: %s", window_label, exc)

    return results
