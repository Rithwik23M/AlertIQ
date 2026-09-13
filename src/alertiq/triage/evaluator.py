"""
Evaluator — computes all technical and operational metrics for a triage scorer.

Metrics computed
----------------
Technical:
  - AUC-ROC (area under ROC curve)
  - AUC-PR  (area under precision-recall curve; more informative than ROC for
             imbalanced classes)
  - F1, precision, recall at the selected threshold
  - FPR (false positive rate), FNR (false negative rate) at threshold
  - Precision@K, Recall@K at K = 10%, 20%, 30%, 50%, 100% of alert volume

Operational (simulated):
  - SARs caught per 100 alerts reviewed at each capacity level
  - Analyst-days to catch 80% of SARs
  - Unnecessary investigations per SAR filed (FP:TP ratio)
  - Alert reduction rate: how many fewer alerts need review vs. full queue

Error analysis:
  - Rule breakdown of FPs and FNs
  - Account breakdown of FPs and FNs
  - High-error patterns

All monetary/time values are SIMULATED using configurable assumptions.
They are labelled as simulated in all output and must not be presented
as real-world impact.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

from .config import TriageConfig

log = logging.getLogger(__name__)


@dataclasses.dataclass
class ThresholdMetrics:
    """Hard-label metrics at a specific probability threshold."""

    threshold: float
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    fpr: float
    fnr: float
    n_positive_predicted: int
    n_total: int

    @property
    def alert_reduction_rate(self) -> float:
        """Fraction of alerts NOT reviewed if only positives were reviewed."""
        if self.n_total == 0:
            return 0.0
        return 1.0 - self.n_positive_predicted / self.n_total


@dataclasses.dataclass
class RankingMetrics:
    """Precision@K and Recall@K at various capacity levels."""

    capacity_fraction: float
    k: int             # number of alerts reviewed
    tp_at_k: int       # true SARs in top-K
    total_true_sars: int
    precision_at_k: float
    recall_at_k: float

    @property
    def sars_per_100_reviewed(self) -> float:
        if self.k == 0:
            return 0.0
        return self.tp_at_k / self.k * 100


@dataclasses.dataclass
class OperationalMetrics:
    """Simulated analyst capacity and workload metrics."""

    scorer_name: str
    capacity_fraction: float
    k: int
    tp_at_k: int
    fp_at_k: int
    total_true_sars: int
    missed_sars: int
    # Simulated analyst-time (hours per alert × alerts reviewed)
    analyst_hours_to_review_k: float
    # Extra hours for SAR filing (tp_at_k × hours_per_sar)
    sar_filing_hours: float
    total_analyst_hours: float
    # Analyst-days (total_hours / analyst_daily_hours)
    analyst_days: float
    # Unnecessary investigations per SAR filed
    fp_per_tp: float
    # Missed-risk rate: fraction of SARs in the full queue that were missed
    missed_sar_rate: float


@dataclasses.dataclass
class EvaluationResult:
    """Complete evaluation output for one scorer on one dataset split.

    AlertIQ operates in two distinct modes.  Both are computed and stored
    here; only ``ranking_at_k`` drives the primary acceptance criterion.

    Operating modes
    ---------------
    CLASSIFICATION MODE (``threshold_metrics``)
        Hard binary predictions: ``score >= threshold → flag alert``.
        Metrics in this section describe what happens when the scorer is
        used as a binary classifier at a fixed probability cutoff.
        These are DIAGNOSTIC; the threshold was selected to maximise F1
        on the validation split and may not remain stable across periods.
        Do NOT interpret ``threshold_metrics.recall`` as Recall@K; it is
        the fraction of all true SARs flagged by the binary classifier.

    CAPACITY-RANKING MODE (``ranking_at_k``)
        Analysts work through the alert queue sorted by descending model
        score and stop when they reach their capacity limit K.  No
        threshold is applied; only the relative ranking of scores matters.
        This is the PRIMARY operating policy.  ``Recall@20%`` = fraction
        of true SARs recovered by reviewing the top 20% of ranked alerts.
        The primary acceptance criterion is Recall@20% > 0.45.

    AUC-ROC and AUC-PR (``auc_roc``, ``auc_pr``) are threshold-free
    ranking metrics — they measure discrimination ability across all
    possible thresholds / ranking depths and apply to both modes.
    """

    scorer_name: str
    n_alerts: int
    n_true_sars: int
    sar_rate: float

    # Threshold-free ranking quality
    auc_roc: float
    auc_pr: float

    # CLASSIFICATION MODE: hard-label metrics at the selected probability threshold.
    # Diagnostic only.  Do not use threshold_metrics.recall as a proxy for Recall@K.
    threshold_metrics: ThresholdMetrics

    # CAPACITY-RANKING MODE: Precision@K and Recall@K at each capacity fraction.
    # This is the primary operating metric.  ranking_at_k[i].recall_at_k at
    # capacity_fraction=0.20 is the primary acceptance-criterion metric.
    ranking_at_k: list[RankingMetrics]

    # Operational metrics at each capacity fraction (simulated)
    operational: list[OperationalMetrics]

    # Feature importances (empty for baselines)
    feature_importances: dict[str, float] = dataclasses.field(default_factory=dict)

    # Error analysis results
    error_analysis: dict[str, Any] = dataclasses.field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        """Flat dict suitable for a comparison table.

        Keys are prefixed to make the operating mode unambiguous:
          - ``cls_*``      : classification-mode metrics (at fixed threshold)
          - ``rank_*_Kpct``: capacity-ranking metrics at K% reviewed
        AUC-ROC and AUC-PR are threshold-free and need no prefix.
        """
        out: dict[str, Any] = {
            "scorer": self.scorer_name,
            "n_alerts": self.n_alerts,
            "n_true_sars": self.n_true_sars,
            "sar_rate_pct": round(self.sar_rate * 100, 2),
            # Threshold-free discrimination quality
            "auc_roc": round(self.auc_roc, 4),
            "auc_pr": round(self.auc_pr, 4),
            # CLASSIFICATION MODE (diagnostic) — hard predictions at fixed threshold
            "cls_threshold": round(self.threshold_metrics.threshold, 4),
            "cls_precision": round(self.threshold_metrics.precision, 4),
            "cls_recall": round(self.threshold_metrics.recall, 4),
            "cls_f1": round(self.threshold_metrics.f1, 4),
            "cls_fpr": round(self.threshold_metrics.fpr, 4),
            "cls_fnr": round(self.threshold_metrics.fnr, 4),
        }
        # CAPACITY-RANKING MODE (primary) — review top K% sorted by model score
        for km in self.ranking_at_k:
            pct = int(km.capacity_fraction * 100)
            out[f"rank_precision_at_{pct}pct"] = round(km.precision_at_k, 4)
            out[f"rank_recall_at_{pct}pct"] = round(km.recall_at_k, 4)
            out[f"rank_sars_per_100_at_{pct}pct"] = round(km.sars_per_100_reviewed, 2)
        return out


class Evaluator:
    """Computes all metrics for a scorer on a labelled alert dataset.

    Args:
        config: Frozen TriageConfig.
    """

    def __init__(self, config: TriageConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------ #
    # Main evaluation entry point                                          #
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        scorer,
        X: np.ndarray,
        y: np.ndarray,
        df: pd.DataFrame,
        threshold: float | None = None,
    ) -> EvaluationResult:
        """Evaluate scorer on X/y and the full alert DataFrame df.

        Args:
            scorer: Any scorer with a ``score(X, df) -> np.ndarray`` method.
            X: Feature matrix (n_alerts × n_features).
            y: Ground-truth binary labels (true_sar).
            df: Full alert DataFrame including metadata (rule_id, severity …).
            threshold: Override the classification threshold; if None, uses
                       the scorer's own threshold (TriageScorer) or 0.5
                       (baselines).
        """
        probs = scorer.score(X, df)
        n = len(y)
        n_true_sars = int(y.sum())

        # Ranking metrics (AUC)
        auc_roc = float(roc_auc_score(y, probs))
        auc_pr = float(average_precision_score(y, probs))

        # Threshold metrics
        thr = threshold if threshold is not None else getattr(scorer, "threshold", 0.5)
        thr_metrics = self._threshold_metrics(probs, y, thr)

        # Precision@K / Recall@K
        caps = self._config.operational.review_capacity_fractions
        ranking = self._precision_recall_at_k(probs, y, caps)

        # Operational metrics
        ops = self._operational_metrics(probs, y, scorer.name, caps)

        # Feature importances
        feat_imp: dict[str, float] = {}
        if hasattr(scorer, "feature_importances"):
            try:
                feat_imp = scorer.feature_importances(
                    list(self._config.feature_columns)
                )
            except Exception:
                pass

        # Error analysis
        error = self._error_analysis(probs, y, df, thr)

        return EvaluationResult(
            scorer_name=scorer.name,
            n_alerts=n,
            n_true_sars=n_true_sars,
            sar_rate=n_true_sars / n if n > 0 else 0.0,
            auc_roc=auc_roc,
            auc_pr=auc_pr,
            threshold_metrics=thr_metrics,
            ranking_at_k=ranking,
            operational=ops,
            feature_importances=feat_imp,
            error_analysis=error,
        )

    # ------------------------------------------------------------------ #
    # Metric helpers                                                       #
    # ------------------------------------------------------------------ #

    def _threshold_metrics(
        self, probs: np.ndarray, y: np.ndarray, threshold: float
    ) -> ThresholdMetrics:
        preds = (probs >= threshold).astype(int)
        tp = int(((preds == 1) & (y == 1)).sum())
        fp = int(((preds == 1) & (y == 0)).sum())
        tn = int(((preds == 0) & (y == 0)).sum())
        fn = int(((preds == 0) & (y == 1)).sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
        return ThresholdMetrics(
            threshold=threshold,
            tp=tp, fp=fp, tn=tn, fn=fn,
            precision=prec, recall=rec, f1=f1,
            fpr=fpr, fnr=fnr,
            n_positive_predicted=tp + fp,
            n_total=len(y),
        )

    def _precision_recall_at_k(
        self,
        probs: np.ndarray,
        y: np.ndarray,
        capacity_fractions: tuple[float, ...],
    ) -> list[RankingMetrics]:
        n = len(y)
        n_true_sars = int(y.sum())
        # Sort by descending score
        order = np.argsort(-probs)
        y_sorted = y[order]
        results = []
        for frac in capacity_fractions:
            k = max(1, int(n * frac))
            tp_at_k = int(y_sorted[:k].sum())
            prec_at_k = tp_at_k / k if k > 0 else 0.0
            rec_at_k = tp_at_k / n_true_sars if n_true_sars > 0 else 0.0
            results.append(
                RankingMetrics(
                    capacity_fraction=frac,
                    k=k,
                    tp_at_k=tp_at_k,
                    total_true_sars=n_true_sars,
                    precision_at_k=prec_at_k,
                    recall_at_k=rec_at_k,
                )
            )
        return results

    def _operational_metrics(
        self,
        probs: np.ndarray,
        y: np.ndarray,
        scorer_name: str,
        capacity_fractions: tuple[float, ...],
    ) -> list[OperationalMetrics]:
        n = len(y)
        n_true_sars = int(y.sum())
        order = np.argsort(-probs)
        y_sorted = y[order]
        op_cfg = self._config.operational
        results = []
        for frac in capacity_fractions:
            k = max(1, int(n * frac))
            top_k = y_sorted[:k]
            tp_at_k = int(top_k.sum())
            fp_at_k = k - tp_at_k
            missed = n_true_sars - tp_at_k
            review_hours = k * op_cfg.hours_per_alert
            filing_hours = tp_at_k * op_cfg.hours_per_sar_filing
            total_hours = review_hours + filing_hours
            analyst_days = total_hours / op_cfg.analyst_daily_hours
            fp_per_tp = fp_at_k / tp_at_k if tp_at_k > 0 else float("inf")
            missed_sar_rate = missed / n_true_sars if n_true_sars > 0 else 0.0
            results.append(
                OperationalMetrics(
                    scorer_name=scorer_name,
                    capacity_fraction=frac,
                    k=k,
                    tp_at_k=tp_at_k,
                    fp_at_k=fp_at_k,
                    total_true_sars=n_true_sars,
                    missed_sars=missed,
                    analyst_hours_to_review_k=review_hours,
                    sar_filing_hours=filing_hours,
                    total_analyst_hours=total_hours,
                    analyst_days=analyst_days,
                    fp_per_tp=fp_per_tp,
                    missed_sar_rate=missed_sar_rate,
                )
            )
        return results

    # ------------------------------------------------------------------ #
    # Error analysis                                                       #
    # ------------------------------------------------------------------ #

    def _error_analysis(
        self,
        probs: np.ndarray,
        y: np.ndarray,
        df: pd.DataFrame,
        threshold: float,
    ) -> dict[str, Any]:
        """Inspect false positives and false negatives by rule_id and severity."""
        preds = (probs >= threshold).astype(int)
        analysis_df = df.copy().reset_index(drop=True)
        analysis_df["score"] = probs
        analysis_df["pred"] = preds
        analysis_df["true_sar"] = y

        fp_mask = (preds == 1) & (y == 0)
        fn_mask = (preds == 0) & (y == 1)
        tp_mask = (preds == 1) & (y == 1)

        def rule_breakdown(mask: np.ndarray, label: str) -> pd.Series:
            sub = analysis_df.loc[mask]
            if sub.empty or "rule_id" not in sub.columns:
                return pd.Series(dtype=int)
            return sub["rule_id"].value_counts().rename(label)

        def severity_breakdown(mask: np.ndarray, label: str) -> pd.Series:
            sub = analysis_df.loc[mask]
            if sub.empty or "severity" not in sub.columns:
                return pd.Series(dtype=int)
            return sub["severity"].value_counts().rename(label)

        # Score distribution for FP and FN
        fp_score_stats = {
            "mean": float(probs[fp_mask].mean()) if fp_mask.any() else None,
            "median": float(np.median(probs[fp_mask])) if fp_mask.any() else None,
            "p90": float(np.percentile(probs[fp_mask], 90)) if fp_mask.any() else None,
        }
        fn_score_stats = {
            "mean": float(probs[fn_mask].mean()) if fn_mask.any() else None,
            "median": float(np.median(probs[fn_mask])) if fn_mask.any() else None,
            "p10": float(np.percentile(probs[fn_mask], 10)) if fn_mask.any() else None,
        }

        # Most-confused rules (highest FP count by rule)
        fp_by_rule = rule_breakdown(fp_mask, "fp_count")
        fn_by_rule = rule_breakdown(fn_mask, "fn_count")
        tp_by_rule = rule_breakdown(tp_mask, "tp_count")

        fp_by_severity = severity_breakdown(fp_mask, "fp_count")
        fn_by_severity = severity_breakdown(fn_mask, "fn_count")

        # Accounts with most FNs (missed SARs per account)
        fn_by_account: dict[str, int] = {}
        if fn_mask.any() and "account_id" in analysis_df.columns:
            fn_by_account = (
                analysis_df.loc[fn_mask, "account_id"]
                .value_counts()
                .head(10)
                .to_dict()
            )

        return {
            "n_tp": int(tp_mask.sum()),
            "n_fp": int(fp_mask.sum()),
            "n_fn": int(fn_mask.sum()),
            "n_tn": int(((preds == 0) & (y == 0)).sum()),
            "fp_score_stats": fp_score_stats,
            "fn_score_stats": fn_score_stats,
            "fp_by_rule": fp_by_rule.to_dict() if not fp_by_rule.empty else {},
            "fn_by_rule": fn_by_rule.to_dict() if not fn_by_rule.empty else {},
            "tp_by_rule": tp_by_rule.to_dict() if not tp_by_rule.empty else {},
            "fp_by_severity": fp_by_severity.to_dict()
            if not fp_by_severity.empty
            else {},
            "fn_by_severity": fn_by_severity.to_dict()
            if not fn_by_severity.empty
            else {},
            "top_fn_accounts": fn_by_account,
        }

    # ------------------------------------------------------------------ #
    # Comparison table                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def comparison_table(results: list[EvaluationResult]) -> pd.DataFrame:
        """Return a DataFrame comparing all scorers side-by-side."""
        rows = [r.summary_dict() for r in results]
        return pd.DataFrame(rows).set_index("scorer")

    @staticmethod
    def threshold_curve(
        probs: np.ndarray,
        y: np.ndarray,
        n_points: int = 100,
    ) -> pd.DataFrame:
        """Precision / Recall / F1 at every threshold for a threshold-selection plot."""
        precisions, recalls, thresholds = precision_recall_curve(y, probs)
        # precision_recall_curve adds a sentinel at the end; trim it
        precisions = precisions[:-1]
        recalls = recalls[:-1]
        f1s = np.where(
            (precisions + recalls) > 0,
            2 * precisions * recalls / (precisions + recalls),
            0.0,
        )
        # Downsample to n_points for storage efficiency
        idx = np.linspace(0, len(thresholds) - 1, n_points, dtype=int)
        return pd.DataFrame(
            {
                "threshold": thresholds[idx],
                "precision": precisions[idx],
                "recall": recalls[idx],
                "f1": f1s[idx],
            }
        )
