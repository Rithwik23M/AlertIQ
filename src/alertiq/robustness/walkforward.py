"""
Walk-forward (expanding-window) temporal evaluation for AlertIQ.

Design
------
We have 181 days of simulator data (2023-01-01 → 2023-06-30, ~56 k alerts).
Three chronological evaluation windows are constructed with expanding training
sets and non-overlapping test periods:

  Window 1  Train=Jan–Feb  Val=Mar   Test=Apr
  Window 2  Train=Jan–Mar  Val=Apr   Test=May
  Window 3  Train=Jan–Apr  Val=May   Test=Jun

No future information enters earlier windows.  The threshold is selected from
each window's own validation set — it is NEVER selected from the test period.

The objective is NOT to maximise average performance.
The objective is to detect instability across windows.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from alertiq.triage.config import TriageConfig
from alertiq.triage.evaluator import Evaluator
from alertiq.triage.scorer import TriageScorer

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Window definition
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class WindowDefinition:
    """Describes one walk-forward evaluation window."""

    label: str                      # "Window-1", "Window-2", "Window-3"
    train_start: datetime.date
    train_end: datetime.date        # inclusive
    val_start: datetime.date
    val_end: datetime.date          # inclusive
    test_start: datetime.date
    test_end: datetime.date         # inclusive


def build_monthly_windows(
    df: pd.DataFrame,
    date_col: str = "triggered_date",
) -> list[WindowDefinition]:
    """
    Build three expanding-window definitions from the 6-month simulator dataset.

    Returns list of WindowDefinition with boundaries derived from actual dates
    in df — no hardcoding of calendar boundaries beyond the month level.

    Window 1: Train months [0,1], Val month [2], Test month [3]
    Window 2: Train months [0,2], Val month [3], Test month [4]
    Window 3: Train months [0,3], Val month [4], Test month [5]
    """
    dates = pd.to_datetime(df[date_col])
    months = sorted(dates.dt.to_period("M").unique())

    if len(months) < 6:
        raise ValueError(
            f"Need at least 6 months of data to build 3 walk-forward windows; "
            f"got {len(months)} months"
        )

    def _month_start(p: "pd.Period") -> datetime.date:
        return p.to_timestamp(how="S").date()

    def _month_end(p: "pd.Period") -> datetime.date:
        return p.to_timestamp(how="E").date()

    windows: list[WindowDefinition] = []
    configs = [
        # (train_month_indices, val_month_idx, test_month_idx)
        ([0, 1],    2, 3),
        ([0, 1, 2], 3, 4),
        ([0, 1, 2, 3], 4, 5),
    ]
    for i, (train_idxs, val_idx, test_idx) in enumerate(configs, start=1):
        w = WindowDefinition(
            label=f"Window-{i}",
            train_start=_month_start(months[train_idxs[0]]),
            train_end=_month_end(months[train_idxs[-1]]),
            val_start=_month_start(months[val_idx]),
            val_end=_month_end(months[val_idx]),
            test_start=_month_start(months[test_idx]),
            test_end=_month_end(months[test_idx]),
        )
        windows.append(w)
        log.debug(
            "Window %d: train=%s→%s  val=%s→%s  test=%s→%s",
            i,
            w.train_start, w.train_end,
            w.val_start, w.val_end,
            w.test_start, w.test_end,
        )
    return windows


# ---------------------------------------------------------------------------
# Per-window result
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class WindowResult:
    """All metrics for one walk-forward evaluation window."""

    window: WindowDefinition

    # --- Split sizes ---
    train_n: int
    val_n: int
    test_n: int
    train_sars: int
    val_sars: int
    test_sars: int
    train_sar_rate: float
    val_sar_rate: float
    test_sar_rate: float

    # --- Threshold (selected on val, never on test) ---
    cls_threshold: float

    # --- Threshold-free ranking quality ---
    auc_roc: float
    auc_pr: float

    # --- Classification-mode metrics (at selected threshold) ---
    cls_precision: float
    cls_recall: float
    cls_f1: float
    cls_fpr: float
    cls_fnr: float

    # --- Capacity-ranking mode metrics ---
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

    # --- Score distribution on test set ---
    score_mean: float
    score_std: float
    score_p10: float
    score_p50: float
    score_p90: float

    # --- Best iteration from early stopping ---
    best_iter: int

    # --- Raw arrays (not serialised but available in memory) ---
    test_scores: np.ndarray = dataclasses.field(repr=False)
    test_labels: np.ndarray = dataclasses.field(repr=False)
    test_df_meta: pd.DataFrame = dataclasses.field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a flat dict of all scalar metrics (excludes raw arrays)."""
        d: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            if f.name in ("test_scores", "test_labels", "test_df_meta", "window"):
                continue
            d[f.name] = getattr(self, f.name)
        d["window_label"] = self.window.label
        d["train_start"] = str(self.window.train_start)
        d["train_end"] = str(self.window.train_end)
        d["val_start"] = str(self.window.val_start)
        d["val_end"] = str(self.window.val_end)
        d["test_start"] = str(self.window.test_start)
        d["test_end"] = str(self.window.test_end)
        return d


# ---------------------------------------------------------------------------
# Walk-forward runner
# ---------------------------------------------------------------------------

def _slice_window(
    df: pd.DataFrame,
    start: datetime.date,
    end: datetime.date,
    date_col: str = "triggered_date",
) -> pd.DataFrame:
    return df.loc[(df[date_col] >= start) & (df[date_col] <= end)].copy()


def _to_Xy(subset: pd.DataFrame, feature_cols: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    X = subset[list(feature_cols)].to_numpy(dtype=np.float64)
    y = subset["true_sar"].to_numpy(dtype=np.int32)
    return X, y


def _recall_precision_at_k(
    scores: np.ndarray, labels: np.ndarray, capacity: float
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


def _classification_metrics(
    scores: np.ndarray, labels: np.ndarray, threshold: float
) -> dict[str, float]:
    preds = (scores >= threshold).astype(int)
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    fn = int(((preds == 0) & (labels == 1)).sum())
    tn = int(((preds == 0) & (labels == 0)).sum())
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    return dict(precision=prec, recall=rec, f1=f1, fpr=fpr, fnr=fnr)


def run_walk_forward(
    df: pd.DataFrame,
    config: TriageConfig,
    windows: list[WindowDefinition] | None = None,
    date_col: str = "triggered_date",
    hyperparams_override: dict | None = None,
) -> list[WindowResult]:
    """
    Run the full walk-forward evaluation.

    For each window:
    1. Slice train / val / test splits (strict temporal ordering, no overlap).
    2. Fit TriageScorer phase 1 on train; threshold selected from val.
    3. Fit TriageScorer phase 2 on train+val.
    4. Score test split and record all metrics.

    Test data is NEVER touched for threshold selection or hyperparameter tuning.

    Args:
        df:                 Full alert DataFrame (must include triggered_date, true_sar, features).
        config:             TriageConfig — defines feature columns, hyperparams, seed.
        windows:            Optional explicit list of WindowDefinition.  Defaults to
                            build_monthly_windows(df).
        date_col:           Date column name in df.
        hyperparams_override: Dict of HistGBM hyperparameters to override for faster runs
                            (e.g. {"max_iter": 100}).  For experiments, use None.

    Returns:
        List of WindowResult, one per window.
    """
    if windows is None:
        windows = build_monthly_windows(df, date_col=date_col)

    if hyperparams_override:
        from pydantic import model_validator
        from alertiq.triage.config import ModelHyperparams
        hp_dict = dict(config.hyperparams)
        hp_dict.update(hyperparams_override)
        config = config.model_copy(update={"hyperparams": ModelHyperparams(**hp_dict)})

    feature_cols = config.feature_columns
    capacities = [0.05, 0.10, 0.20, 0.30, 0.50]

    results: list[WindowResult] = []

    for w in windows:
        log.info("=== Walk-forward: %s ===", w.label)

        # -- Slice data ---------------------------------------------------
        train_df = _slice_window(df, w.train_start, w.train_end, date_col)
        val_df   = _slice_window(df, w.val_start,   w.val_end,   date_col)
        test_df  = _slice_window(df, w.test_start,  w.test_end,  date_col)

        X_tr, y_tr = _to_Xy(train_df, feature_cols)
        X_va, y_va = _to_Xy(val_df, feature_cols)
        X_te, y_te = _to_Xy(test_df, feature_cols)
        X_tv = np.vstack([X_tr, X_va])
        y_tv = np.hstack([y_tr, y_va])

        log.info(
            "  train=%d (SARs=%d, %.1f%%)  val=%d (SARs=%d)  test=%d (SARs=%d)",
            len(y_tr), y_tr.sum(), y_tr.mean() * 100,
            len(y_va), y_va.sum(),
            len(y_te), y_te.sum(),
        )

        if y_tr.sum() < 10 or y_te.sum() < 5:
            log.warning("  Skipping %s — insufficient SARs in train or test", w.label)
            continue

        # -- Train --------------------------------------------------------
        scorer = TriageScorer(config)
        scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
        threshold = scorer.threshold
        scorer.fit_phase2(X_tv, y_tv)

        # -- Score test (NEVER threshold-selected from test) ---------------
        test_scores = scorer.score(X_te)

        # -- AUC metrics --------------------------------------------------
        auc_roc = float(roc_auc_score(y_te, test_scores))
        auc_pr  = float(average_precision_score(y_te, test_scores))

        # -- Classification metrics at val-selected threshold --------------
        cls = _classification_metrics(test_scores, y_te, threshold)

        # -- Capacity-ranking metrics --------------------------------------
        cap_metrics: dict[str, tuple[float, float]] = {}
        for cap in capacities:
            rec, prec = _recall_precision_at_k(test_scores, y_te, cap)
            cap_metrics[f"{int(cap*100)}pct"] = (rec, prec)

        # -- Score distribution -------------------------------------------
        score_p = np.percentile(test_scores, [10, 50, 90])

        results.append(WindowResult(
            window=w,
            train_n=len(y_tr),
            val_n=len(y_va),
            test_n=len(y_te),
            train_sars=int(y_tr.sum()),
            val_sars=int(y_va.sum()),
            test_sars=int(y_te.sum()),
            train_sar_rate=float(y_tr.mean()),
            val_sar_rate=float(y_va.mean()),
            test_sar_rate=float(y_te.mean()),
            cls_threshold=float(threshold),
            auc_roc=auc_roc,
            auc_pr=auc_pr,
            cls_precision=cls["precision"],
            cls_recall=cls["recall"],
            cls_f1=cls["f1"],
            cls_fpr=cls["fpr"],
            cls_fnr=cls["fnr"],
            recall_at_5pct=cap_metrics["5pct"][0],
            recall_at_10pct=cap_metrics["10pct"][0],
            recall_at_20pct=cap_metrics["20pct"][0],
            recall_at_30pct=cap_metrics["30pct"][0],
            recall_at_50pct=cap_metrics["50pct"][0],
            precision_at_5pct=cap_metrics["5pct"][1],
            precision_at_10pct=cap_metrics["10pct"][1],
            precision_at_20pct=cap_metrics["20pct"][1],
            precision_at_30pct=cap_metrics["30pct"][1],
            precision_at_50pct=cap_metrics["50pct"][1],
            score_mean=float(test_scores.mean()),
            score_std=float(test_scores.std()),
            score_p10=float(score_p[0]),
            score_p50=float(score_p[1]),
            score_p90=float(score_p[2]),
            best_iter=scorer.best_iter or 0,
            test_scores=test_scores,
            test_labels=y_te,
            test_df_meta=test_df,
        ))
        log.info(
            "  AUC-ROC=%.3f  AUC-PR=%.3f  F1=%.3f  Recall@20%%=%.3f  threshold=%.4f",
            auc_roc, auc_pr, cls["f1"], cap_metrics["20pct"][0], threshold,
        )

    return results


# ---------------------------------------------------------------------------
# Stability summary
# ---------------------------------------------------------------------------

def stability_summary(results: list[WindowResult]) -> pd.DataFrame:
    """
    Compute mean / median / min / max / std for key metrics across windows.

    The objective is to detect instability, NOT to maximise average.
    """
    metrics = [
        "auc_roc", "auc_pr",
        "cls_f1", "cls_precision", "cls_recall", "cls_fpr", "cls_fnr",
        "cls_threshold",
        "recall_at_10pct", "recall_at_20pct", "recall_at_30pct", "recall_at_50pct",
        "precision_at_10pct", "precision_at_20pct",
        "test_sar_rate",
    ]

    rows = []
    for metric in metrics:
        vals = [getattr(r, metric) for r in results]
        rows.append({
            "metric": metric,
            "mean": float(np.mean(vals)),
            "median": float(np.median(vals)),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "std": float(np.std(vals)),
            "range": float(np.max(vals) - np.min(vals)),
        })

    return pd.DataFrame(rows).set_index("metric")


def results_to_dataframe(results: list[WindowResult]) -> pd.DataFrame:
    """Convert list of WindowResult to a tidy DataFrame for analysis."""
    return pd.DataFrame([r.to_dict() for r in results])
