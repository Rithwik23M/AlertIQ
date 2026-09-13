"""
Champion / Challenger comparison framework for AlertIQ Milestone 3.

Design
------
A champion model is the currently approved/deployed variant.
A challenger model is any proposed replacement.

This module provides:
  - Side-by-side metric comparison across evaluation windows
  - Statistical significance test (paired bootstrap) for key metrics
  - Decision recommendation: promote challenger / retain champion / inconclusive

Rules for promotion (ALL must hold on the test windows):
  1. Challenger Recall@20% ≥ champion Recall@20% − 0.02 (no meaningful regression)
  2. Challenger AUC-ROC ≥ champion AUC-ROC − 0.02
  3. At least one of Recall@20% or AUC-ROC is improved ≥ 0.01

The bootstrap test uses B=1000 resamples at α=0.05.

Limitations
-----------
- These thresholds are illustrative; a real deployment uses governance-approved gates.
- Statistical significance with 3 windows is very low-powered; treat the bootstrap
  as a directional sanity check, not a definitive answer.
- No concept drift is modelled between champion and challenger training periods.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Promotion thresholds
MAX_REGRESSION_RECALL20 = -0.02   # challenger may not be worse than this
MAX_REGRESSION_AUC     = -0.02
MIN_IMPROVEMENT_EITHER = 0.01     # at least one metric must improve by this

# Bootstrap settings
BOOTSTRAP_N = 1000
BOOTSTRAP_ALPHA = 0.05


@dataclasses.dataclass
class ModelComparison:
    """Comparison of champion and challenger on one window."""

    window_label: str

    # --- Champion ---
    champ_auc_roc: float
    champ_auc_pr: float
    champ_recall_at_20: float
    champ_precision_at_20: float
    champ_f1: float

    # --- Challenger ---
    chal_auc_roc: float
    chal_auc_pr: float
    chal_recall_at_20: float
    chal_precision_at_20: float
    chal_f1: float

    # --- Deltas (challenger − champion) ---
    delta_auc_roc: float
    delta_auc_pr: float
    delta_recall_at_20: float
    delta_precision_at_20: float
    delta_f1: float

    # Bootstrap p-values (two-sided, metric = chal − champ)
    pvalue_recall_at_20: float | None
    pvalue_auc_roc: float | None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class PromotionDecision:
    """Aggregate promotion recommendation across all windows."""

    recommendation: str        # "promote_challenger" | "retain_champion" | "inconclusive"
    mean_delta_recall20: float
    mean_delta_auc_roc: float
    windows_challenger_better_recall20: int
    windows_challenger_better_auc_roc: int
    n_windows: int
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["reasons"] = self.reasons
        return d


def _recall_at_k(
    scores: np.ndarray, labels: np.ndarray, capacity: float
) -> float:
    n = len(scores)
    k = max(1, int(np.ceil(n * capacity)))
    k = min(k, n)
    top_idx = np.argsort(scores)[::-1][:k]
    tp = int(labels[top_idx].sum())
    total_sars = int(labels.sum())
    return tp / total_sars if total_sars > 0 else 0.0


def _bootstrap_pvalue(
    a_scores: np.ndarray,
    b_scores: np.ndarray,
    labels: np.ndarray,
    metric_fn,
    n_bootstrap: int = BOOTSTRAP_N,
    rng: np.random.Generator | None = None,
) -> float | None:
    """
    Paired bootstrap p-value (two-sided) for metric_fn(b) − metric_fn(a).

    Returns None if computation fails.
    """
    rng = rng or np.random.default_rng(0)
    n = len(labels)
    if n < 10:
        return None

    try:
        observed_delta = metric_fn(b_scores, labels) - metric_fn(a_scores, labels)
    except Exception:
        return None

    deltas = []
    for _ in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        try:
            d = metric_fn(b_scores[idx], labels[idx]) - metric_fn(a_scores[idx], labels[idx])
            deltas.append(d)
        except Exception:
            pass

    if len(deltas) < 10:
        return None

    deltas = np.array(deltas)
    # Two-sided p-value: proportion of bootstrap deltas more extreme than observed
    p = float(np.mean(np.abs(deltas - deltas.mean()) >= abs(observed_delta)))
    return p


def compare_window(
    window_label: str,
    champ_scores: np.ndarray,
    chal_scores: np.ndarray,
    labels: np.ndarray,
    run_bootstrap: bool = True,
) -> ModelComparison:
    """
    Compare champion and challenger on one test window.

    Args:
        window_label:  Identifier for the evaluation window.
        champ_scores:  Champion model's scores on the test set.
        chal_scores:   Challenger model's scores on the test set.
        labels:        True binary labels (test set).
        run_bootstrap: If True, compute bootstrap p-values (slower).

    Returns:
        ModelComparison with all metrics and deltas.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score

    def _safe(fn, *args) -> float:
        try:
            return float(fn(*args))
        except Exception:
            return float("nan")

    def _r20(scores, y):
        return _recall_at_k(scores, y, 0.20)

    def _p20(scores, y):
        n = len(scores)
        k = max(1, int(np.ceil(n * 0.20)))
        k = min(k, n)
        top = np.argsort(scores)[::-1][:k]
        tp = int(y[top].sum())
        return tp / k if k > 0 else 0.0

    def _f1_at_05(scores, y):
        preds = (scores >= 0.5).astype(int)
        tp = int(((preds == 1) & (y == 1)).sum())
        fp = int(((preds == 1) & (y == 0)).sum())
        fn = int(((preds == 0) & (y == 1)).sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        return 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    champ = {
        "auc_roc": _safe(roc_auc_score, labels, champ_scores),
        "auc_pr":  _safe(average_precision_score, labels, champ_scores),
        "r20":     _r20(champ_scores, labels),
        "p20":     _p20(champ_scores, labels),
        "f1":      _f1_at_05(champ_scores, labels),
    }
    chal = {
        "auc_roc": _safe(roc_auc_score, labels, chal_scores),
        "auc_pr":  _safe(average_precision_score, labels, chal_scores),
        "r20":     _r20(chal_scores, labels),
        "p20":     _p20(chal_scores, labels),
        "f1":      _f1_at_05(chal_scores, labels),
    }

    pvalue_r20 = None
    pvalue_auc = None
    if run_bootstrap:
        from sklearn.metrics import roc_auc_score as _roc

        def _auc_fn(scores, y):
            return float(_roc(y, scores))

        pvalue_r20 = _bootstrap_pvalue(champ_scores, chal_scores, labels, _r20)
        pvalue_auc = _bootstrap_pvalue(champ_scores, chal_scores, labels, _auc_fn)

    return ModelComparison(
        window_label=window_label,
        champ_auc_roc=champ["auc_roc"],
        champ_auc_pr=champ["auc_pr"],
        champ_recall_at_20=champ["r20"],
        champ_precision_at_20=champ["p20"],
        champ_f1=champ["f1"],
        chal_auc_roc=chal["auc_roc"],
        chal_auc_pr=chal["auc_pr"],
        chal_recall_at_20=chal["r20"],
        chal_precision_at_20=chal["p20"],
        chal_f1=chal["f1"],
        delta_auc_roc=chal["auc_roc"] - champ["auc_roc"],
        delta_auc_pr=chal["auc_pr"] - champ["auc_pr"],
        delta_recall_at_20=chal["r20"] - champ["r20"],
        delta_precision_at_20=chal["p20"] - champ["p20"],
        delta_f1=chal["f1"] - champ["f1"],
        pvalue_recall_at_20=pvalue_r20,
        pvalue_auc_roc=pvalue_auc,
    )


def promotion_decision(comparisons: list[ModelComparison]) -> PromotionDecision:
    """
    Aggregate comparison results and recommend a promotion decision.

    Args:
        comparisons: One ModelComparison per evaluation window.

    Returns:
        PromotionDecision with recommendation and supporting reasons.
    """
    if not comparisons:
        return PromotionDecision(
            recommendation="inconclusive",
            mean_delta_recall20=float("nan"),
            mean_delta_auc_roc=float("nan"),
            windows_challenger_better_recall20=0,
            windows_challenger_better_auc_roc=0,
            n_windows=0,
            reasons=["No comparison windows provided."],
        )

    n = len(comparisons)
    d_r20s = [c.delta_recall_at_20 for c in comparisons]
    d_aucs = [c.delta_auc_roc for c in comparisons]

    mean_dr20 = float(np.mean(d_r20s))
    mean_dauc = float(np.mean(d_aucs))
    n_better_r20 = sum(1 for d in d_r20s if d > 0)
    n_better_auc = sum(1 for d in d_aucs if d > 0)

    reasons: list[str] = []

    # Check regressions
    worst_r20 = min(d_r20s)
    worst_auc = min(d_aucs)

    if worst_r20 < MAX_REGRESSION_RECALL20:
        reasons.append(
            f"Challenger regressed Recall@20% by {worst_r20:.3f} on at least one window "
            f"(threshold {MAX_REGRESSION_RECALL20})"
        )
    if worst_auc < MAX_REGRESSION_AUC:
        reasons.append(
            f"Challenger regressed AUC-ROC by {worst_auc:.3f} on at least one window "
            f"(threshold {MAX_REGRESSION_AUC})"
        )

    # Check improvement
    recall_improved = mean_dr20 >= MIN_IMPROVEMENT_EITHER
    auc_improved = mean_dauc >= MIN_IMPROVEMENT_EITHER

    if not recall_improved and not auc_improved:
        reasons.append(
            f"Challenger did not improve Recall@20% (Δ={mean_dr20:.3f}) "
            f"or AUC-ROC (Δ={mean_dauc:.3f}) by ≥{MIN_IMPROVEMENT_EITHER}"
        )

    # Decision
    no_regression = worst_r20 >= MAX_REGRESSION_RECALL20 and worst_auc >= MAX_REGRESSION_AUC
    some_improvement = recall_improved or auc_improved

    if no_regression and some_improvement:
        recommendation = "promote_challenger"
        reasons.append(
            f"Challenger improves without regression — "
            f"ΔRecall@20%={mean_dr20:+.3f}  ΔAUC={mean_dauc:+.3f}"
        )
    elif no_regression and not some_improvement:
        recommendation = "retain_champion"
        reasons.append("Challenger shows no meaningful improvement.")
    elif not no_regression:
        recommendation = "retain_champion"
    else:
        recommendation = "inconclusive"

    return PromotionDecision(
        recommendation=recommendation,
        mean_delta_recall20=mean_dr20,
        mean_delta_auc_roc=mean_dauc,
        windows_challenger_better_recall20=n_better_r20,
        windows_challenger_better_auc_roc=n_better_auc,
        n_windows=n,
        reasons=reasons,
    )


def comparisons_to_dataframe(comparisons: list[ModelComparison]) -> pd.DataFrame:
    """Convert list of ModelComparison to a tidy DataFrame."""
    return pd.DataFrame([c.to_dict() for c in comparisons])
