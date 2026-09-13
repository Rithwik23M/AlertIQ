"""
Distribution shift detection for AlertIQ Milestone 3.

Techniques
----------
Continuous features:
  - Population Stability Index (PSI): standard FinTech drift measure.
    PSI = Σ (actual% − expected%) × ln(actual% / expected%)
    PSI < 0.10  → stable
    PSI 0.10–0.25 → minor shift
    PSI > 0.25  → significant shift (alert)

  - Kolmogorov-Smirnov statistic: non-parametric two-sample distance.
    Reports statistic + p-value.

Categorical features:
  - Proportion change: chi-squared statistic and max absolute proportion
    change per category.

Usage
-----
Use the baseline (training) distribution as reference; compare each
test window's distribution against it.

Do NOT use every method indiscriminately.  Interpretations are provided
but causal claims require additional investigation.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger(__name__)

# PSI severity thresholds
PSI_STABLE   = 0.10
PSI_MINOR    = 0.25

# KS p-value threshold
KS_SIGNIFICANT_P = 0.05


@dataclasses.dataclass
class FeatureDriftResult:
    """Drift metrics for one feature in one comparison window."""

    feature: str
    window_label: str
    feature_type: str          # "continuous" or "categorical"

    # Continuous metrics
    psi: float | None
    ks_stat: float | None
    ks_pvalue: float | None

    # Categorical metrics
    max_proportion_change: float | None
    chi2_stat: float | None
    chi2_pvalue: float | None

    # Descriptive stats (continuous only)
    baseline_mean: float | None
    window_mean: float | None
    baseline_std: float | None
    window_std: float | None

    @property
    def psi_severity(self) -> str:
        if self.psi is None:
            return "n/a"
        if self.psi < PSI_STABLE:
            return "stable"
        if self.psi < PSI_MINOR:
            return "minor"
        return "significant"

    @property
    def is_significant(self) -> bool:
        """True if any drift metric signals meaningful shift."""
        if self.psi is not None and self.psi >= PSI_MINOR:
            return True
        if self.ks_pvalue is not None and self.ks_pvalue < KS_SIGNIFICANT_P:
            return True
        if self.chi2_pvalue is not None and self.chi2_pvalue < KS_SIGNIFICANT_P:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _psi(baseline: np.ndarray, window: np.ndarray, n_bins: int = 10) -> float:
    """
    Compute Population Stability Index.

    Bins are determined from the baseline distribution.  Window values outside
    baseline range are clipped to the edge bins.
    """
    eps = 1e-6
    min_val = float(np.nanmin(baseline))
    max_val = float(np.nanmax(baseline))
    if max_val == min_val:
        return 0.0  # constant feature — no drift possible

    bins = np.linspace(min_val, max_val, n_bins + 1)
    bins[0]  -= 1e-9   # include min value
    bins[-1] += 1e-9   # include max value

    baseline_counts = np.histogram(baseline, bins=bins)[0].astype(float)
    window_counts   = np.histogram(np.clip(window, min_val, max_val), bins=bins)[0].astype(float)

    # Smooth zero bins
    baseline_counts = np.where(baseline_counts == 0, eps, baseline_counts)
    window_counts   = np.where(window_counts   == 0, eps, window_counts)

    baseline_pct = baseline_counts / baseline_counts.sum()
    window_pct   = window_counts   / window_counts.sum()

    psi = float(np.sum((window_pct - baseline_pct) * np.log(window_pct / baseline_pct)))
    return max(psi, 0.0)


def _categorical_drift(
    baseline: np.ndarray,
    window: np.ndarray,
) -> tuple[float, float, float]:
    """
    Categorical proportion drift.

    Returns (max_proportion_change, chi2_stat, chi2_pvalue).
    """
    all_cats = np.union1d(np.unique(baseline), np.unique(window))
    eps = 1e-9

    def _proportions(arr: np.ndarray) -> np.ndarray:
        counts = np.array([np.sum(arr == c) for c in all_cats], dtype=float)
        total = counts.sum()
        return counts / total if total > 0 else counts

    bp = _proportions(baseline)
    wp = _proportions(window)
    max_change = float(np.max(np.abs(wp - bp)))

    # Chi-squared goodness of fit: observed=window_counts, expected=baseline proportions
    window_counts = np.array([np.sum(window == c) for c in all_cats], dtype=float)
    expected = bp * window_counts.sum() + eps
    chi2_stat, chi2_pvalue = stats.chisquare(window_counts + eps, expected)

    return max_change, float(chi2_stat), float(chi2_pvalue)


def compute_feature_drift(
    baseline_df: pd.DataFrame,
    window_df: pd.DataFrame,
    feature_cols: list[str],
    categorical_feature_indices: tuple[int, ...] = (),
    window_label: str = "unknown",
) -> list[FeatureDriftResult]:
    """
    Compute drift metrics for every feature column.

    Args:
        baseline_df:                 Reference (training) DataFrame.
        window_df:                   Comparison (test window) DataFrame.
        feature_cols:                Feature column names.
        categorical_feature_indices: 0-based indices into feature_cols that are categorical.
        window_label:                Label for logging/output.

    Returns:
        List of FeatureDriftResult, one per feature.
    """
    cat_idxs = set(categorical_feature_indices)
    results: list[FeatureDriftResult] = []

    for idx, feat in enumerate(feature_cols):
        if feat not in baseline_df.columns or feat not in window_df.columns:
            log.warning("Feature %s missing from dataframe — skipping drift", feat)
            continue

        baseline_vals = baseline_df[feat].dropna().to_numpy()
        window_vals   = window_df[feat].dropna().to_numpy()

        if len(baseline_vals) < 10 or len(window_vals) < 5:
            log.warning("Feature %s has too few values for drift analysis", feat)
            continue

        is_cat = idx in cat_idxs

        if is_cat:
            max_change, chi2_s, chi2_p = _categorical_drift(baseline_vals, window_vals)
            results.append(FeatureDriftResult(
                feature=feat,
                window_label=window_label,
                feature_type="categorical",
                psi=None,
                ks_stat=None,
                ks_pvalue=None,
                max_proportion_change=max_change,
                chi2_stat=chi2_s,
                chi2_pvalue=chi2_p,
                baseline_mean=None,
                window_mean=None,
                baseline_std=None,
                window_std=None,
            ))
        else:
            psi_val = _psi(baseline_vals, window_vals)
            ks_res  = stats.ks_2samp(baseline_vals, window_vals)
            results.append(FeatureDriftResult(
                feature=feat,
                window_label=window_label,
                feature_type="continuous",
                psi=psi_val,
                ks_stat=float(ks_res.statistic),
                ks_pvalue=float(ks_res.pvalue),
                max_proportion_change=None,
                chi2_stat=None,
                chi2_pvalue=None,
                baseline_mean=float(np.mean(baseline_vals)),
                window_mean=float(np.mean(window_vals)),
                baseline_std=float(np.std(baseline_vals)),
                window_std=float(np.std(window_vals)),
            ))

    return results


def drift_summary(
    all_results: list[FeatureDriftResult],
    feature_cols: list[str],
) -> pd.DataFrame:
    """
    Summarise drift across all windows per feature.

    Returns a DataFrame with one row per feature and columns for
    max PSI, mean KS stat, significant-window count, and drift classification.
    """
    rows: dict[str, dict] = {f: {
        "feature": f,
        "psi_values": [],
        "ks_stats": [],
        "n_significant": 0,
        "n_windows": 0,
    } for f in feature_cols}

    for dr in all_results:
        if dr.feature not in rows:
            continue
        rows[dr.feature]["n_windows"] += 1
        if dr.psi is not None:
            rows[dr.feature]["psi_values"].append(dr.psi)
        if dr.ks_stat is not None:
            rows[dr.feature]["ks_stats"].append(dr.ks_stat)
        if dr.is_significant:
            rows[dr.feature]["n_significant"] += 1

    summary_rows = []
    for feat, r in rows.items():
        psi_vals = r["psi_values"]
        ks_vals  = r["ks_stats"]
        max_psi = max(psi_vals) if psi_vals else None
        mean_ks = np.mean(ks_vals) if ks_vals else None

        if max_psi is None:
            drift_cat = "categorical"
        elif max_psi < PSI_STABLE:
            drift_cat = "stable"
        elif max_psi < PSI_MINOR:
            drift_cat = "minor"
        else:
            drift_cat = "significant"

        summary_rows.append({
            "feature": feat,
            "max_psi": max_psi,
            "mean_ks_stat": mean_ks,
            "n_significant_windows": r["n_significant"],
            "n_windows": r["n_windows"],
            "drift_classification": drift_cat,
        })

    return pd.DataFrame(summary_rows).set_index("feature")


def label_shift_analysis(
    baseline_df: pd.DataFrame,
    windows: list[tuple[str, pd.DataFrame]],  # [(label, df), ...]
) -> pd.DataFrame:
    """
    Measure SAR prevalence, rule frequency, and severity distribution shift
    across temporal windows.

    Args:
        baseline_df:  Reference (training) DataFrame.
        windows:      List of (label, window_df) tuples.

    Returns:
        DataFrame with one row per window showing SAR rate, rule entropy,
        top-rule fraction, severity entropy.
    """
    def _rule_stats(df: pd.DataFrame) -> dict:
        vc = df["rule_id"].value_counts(normalize=True)
        top_frac = float(vc.iloc[0]) if len(vc) > 0 else 0.0
        n_rules = df["rule_id"].nunique()
        # Shannon entropy of rule distribution
        probs = vc.values
        entropy = float(-np.sum(probs * np.log(probs + 1e-12)))
        return {"top_rule_fraction": top_frac, "rule_entropy": entropy, "n_distinct_rules": n_rules}

    def _sev_stats(df: pd.DataFrame) -> dict:
        if "severity" not in df.columns:
            return {"severity_entropy": None}
        vc = df["severity"].value_counts(normalize=True)
        probs = vc.values
        entropy = float(-np.sum(probs * np.log(probs + 1e-12)))
        return {"severity_entropy": entropy}

    rows = []
    for label, wdf in [("baseline_train", baseline_df)] + list(windows):
        sar_rate = float(wdf["true_sar"].mean()) if "true_sar" in wdf.columns else None
        row = {"window": label, "sar_rate": sar_rate, "n_alerts": len(wdf)}
        row.update(_rule_stats(wdf))
        row.update(_sev_stats(wdf))
        rows.append(row)

    return pd.DataFrame(rows).set_index("window")
