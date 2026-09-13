"""
Typology-level performance breakdown for AlertIQ Milestone 3.

Aggregates model performance by TMS rule group.

M3 requirement
--------------
No rule group with ≥ 50 holdout SARs should have Recall@20% < 0.40.
If any group fails this threshold the finding is surfaced as a warning.

Design
------
- Minimum support floor: MIN_SUPPORT_SARS = 50
- Primary metric: Recall@20% (capacity-ranking mode)
- Secondary: Recall@K for 5/10/30/50%, precision@K, AUC-ROC (where calculable)
- Groups with fewer than MIN_SUPPORT_SARS are reported but excluded from
  the policy threshold check.

Note: rule_id == "R05" has only 3 alerts in training — far below the floor.
      Only rules with sufficient holdout SAR support are gate-checked.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

log = logging.getLogger(__name__)

# Minimum holdout SARs for a rule to be gate-checked
MIN_SUPPORT_SARS = 50

# Recall@20% must be ≥ this for sufficiently-supported rule groups
RECALL_AT_20_FLOOR = 0.40

# Capacities to evaluate
CAPACITIES = [0.05, 0.10, 0.20, 0.30, 0.50]


@dataclasses.dataclass
class TypologyResult:
    """Performance metrics for one TMS rule group in one evaluation window."""

    rule_id: str
    window_label: str

    # Support
    n_alerts: int
    n_sars: int
    n_nonsars: int
    sar_rate: float

    # Capacity-ranking metrics (primary)
    recall_at_5pct: float
    recall_at_10pct: float
    recall_at_20pct: float
    recall_at_30pct: float
    recall_at_50pct: float
    precision_at_5pct: float
    precision_at_10pct: float
    precision_at_20pct: float
    precision_at_30pct: float
    precision_at_50pct: float

    # Score distribution
    score_mean_sar: float
    score_mean_nonsar: float
    score_mean_all: float

    # AUC-ROC (None if too few positives)
    auc_roc: float | None

    # Policy gate
    meets_floor: bool          # Recall@20% >= 0.40 (only relevant if n_sars >= MIN_SUPPORT_SARS)
    above_support_floor: bool  # n_sars >= MIN_SUPPORT_SARS

    @property
    def gate_applicable(self) -> bool:
        """True if this rule's support is sufficient for the policy gate."""
        return self.above_support_floor

    @property
    def gate_pass(self) -> bool:
        """True if gate is not applicable OR recall@20% meets the floor."""
        return (not self.gate_applicable) or self.meets_floor

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _recall_precision_at_k(
    scores: np.ndarray,
    labels: np.ndarray,
    capacity: float,
) -> tuple[float, float]:
    """Return (recall, precision) at top capacity-fraction of alerts."""
    n = len(scores)
    k = max(1, int(np.ceil(n * capacity)))
    k = min(k, n)
    top_idx = np.argsort(scores)[::-1][:k]
    tp = int(labels[top_idx].sum())
    total_sars = int(labels.sum())
    recall = tp / total_sars if total_sars > 0 else 0.0
    precision = tp / k if k > 0 else 0.0
    return recall, precision


def compute_typology_performance(
    scores: np.ndarray,
    labels: np.ndarray,
    rule_ids: np.ndarray,
    window_label: str,
    min_support_sars: int = MIN_SUPPORT_SARS,
) -> list[TypologyResult]:
    """
    Compute per-rule-group performance metrics.

    Args:
        scores:           Model scores for the test set.
        labels:           True labels (1=SAR, 0=non-SAR) for the test set.
        rule_ids:         TMS rule identifiers, one per alert.
        window_label:     Label for the evaluation window ("Window-1", ...).
        min_support_sars: Minimum SAR count for a rule to be gate-checked.

    Returns:
        List of TypologyResult, one per observed rule in this window.
        Results are sorted by n_sars descending.
    """
    results: list[TypologyResult] = []
    unique_rules = np.unique(rule_ids)

    for rule in unique_rules:
        mask = rule_ids == rule
        r_scores = scores[mask]
        r_labels = labels[mask]

        n_alerts = int(mask.sum())
        n_sars = int(r_labels.sum())
        n_nonsars = n_alerts - n_sars
        sar_rate = n_sars / n_alerts if n_alerts > 0 else 0.0

        if n_alerts < 2:
            log.debug("Rule %s: only %d alerts — skipping", rule, n_alerts)
            continue

        # Capacity-ranking metrics
        cap_rec: dict[str, float] = {}
        cap_prec: dict[str, float] = {}
        for cap in CAPACITIES:
            rec, prec = _recall_precision_at_k(r_scores, r_labels, cap)
            cap_rec[f"{int(cap * 100)}pct"] = rec
            cap_prec[f"{int(cap * 100)}pct"] = prec

        # Score distribution
        score_mean_all = float(r_scores.mean())
        sar_mask = r_labels == 1
        score_mean_sar = float(r_scores[sar_mask].mean()) if n_sars > 0 else float("nan")
        score_mean_nonsar = float(r_scores[~sar_mask].mean()) if n_nonsars > 0 else float("nan")

        # AUC-ROC (requires at least 1 positive and 1 negative)
        auc_roc: float | None = None
        if n_sars >= 1 and n_nonsars >= 1:
            try:
                auc_roc = float(roc_auc_score(r_labels, r_scores))
            except Exception:
                pass

        above_floor = n_sars >= min_support_sars
        meets_floor = cap_rec["20pct"] >= RECALL_AT_20_FLOOR

        if above_floor and not meets_floor:
            log.warning(
                "Rule %s | %s: Recall@20%% = %.3f — BELOW FLOOR (%.2f) | "
                "n_alerts=%d  n_sars=%d",
                rule, window_label, cap_rec["20pct"], RECALL_AT_20_FLOOR,
                n_alerts, n_sars,
            )

        results.append(TypologyResult(
            rule_id=str(rule),
            window_label=window_label,
            n_alerts=n_alerts,
            n_sars=n_sars,
            n_nonsars=n_nonsars,
            sar_rate=sar_rate,
            recall_at_5pct=cap_rec["5pct"],
            recall_at_10pct=cap_rec["10pct"],
            recall_at_20pct=cap_rec["20pct"],
            recall_at_30pct=cap_rec["30pct"],
            recall_at_50pct=cap_rec["50pct"],
            precision_at_5pct=cap_prec["5pct"],
            precision_at_10pct=cap_prec["10pct"],
            precision_at_20pct=cap_prec["20pct"],
            precision_at_30pct=cap_prec["30pct"],
            precision_at_50pct=cap_prec["50pct"],
            score_mean_sar=score_mean_sar,
            score_mean_nonsar=score_mean_nonsar,
            score_mean_all=score_mean_all,
            auc_roc=auc_roc,
            meets_floor=meets_floor,
            above_support_floor=above_floor,
        ))

    # Sort by SAR support descending
    results.sort(key=lambda r: r.n_sars, reverse=True)
    return results


def typology_summary_df(results: list[TypologyResult]) -> pd.DataFrame:
    """
    Convert list of TypologyResult to a tidy DataFrame.

    Includes a gate_pass column indicating whether the rule meets the M3 policy.
    """
    rows = [r.to_dict() for r in results]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["gate_pass"] = [r.gate_pass for r in results]
    return df


def account_fn_analysis(
    scores: np.ndarray,
    labels: np.ndarray,
    account_ids: np.ndarray,
    threshold: float,
    top_n: int = 20,
) -> pd.DataFrame:
    """
    Identify accounts with concentrated false negatives.

    Args:
        scores:      Model scores (test set).
        labels:      True labels (1=SAR, 0=non-SAR).
        account_ids: Account identifier per alert.
        threshold:   Classification threshold (selected from val, NOT test).
        top_n:       Number of top accounts to return.

    Returns:
        DataFrame with columns: account_id, total_sars, false_negatives,
        fn_rate, mean_score_on_sars, min_score_on_sars.
        Sorted by false_negatives descending.

    Notes:
        This analysis uses the classification threshold purely for labelling
        predictions.  The threshold was selected from the validation set.
        Do not use this analysis to re-select the threshold.
    """
    preds = (scores >= threshold).astype(int)

    unique_accounts = np.unique(account_ids)
    rows = []

    for acct in unique_accounts:
        mask = account_ids == acct
        a_labels = labels[mask]
        a_preds = preds[mask]
        a_scores = scores[mask]

        sar_mask = a_labels == 1
        n_sars = int(sar_mask.sum())

        if n_sars == 0:
            continue

        fn_mask = (a_labels == 1) & (a_preds == 0)
        n_fn = int(fn_mask.sum())
        fn_rate = n_fn / n_sars

        sar_scores = a_scores[sar_mask]
        rows.append({
            "account_id": acct,
            "total_sars": n_sars,
            "false_negatives": n_fn,
            "fn_rate": round(fn_rate, 4),
            "mean_score_on_sars": round(float(sar_scores.mean()), 4),
            "min_score_on_sars": round(float(sar_scores.min()), 4),
        })

    if not rows:
        return pd.DataFrame(columns=[
            "account_id", "total_sars", "false_negatives",
            "fn_rate", "mean_score_on_sars", "min_score_on_sars",
        ])

    df = pd.DataFrame(rows)
    df = df[df["false_negatives"] > 0].copy()
    df = df.sort_values("false_negatives", ascending=False).head(top_n)
    df = df.reset_index(drop=True)
    return df
