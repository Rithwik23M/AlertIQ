#!/usr/bin/env python
"""
Milestone 2 — AlertIQ Triage Experiment Runner
================================================
Runs the full baseline → ML pipeline and records all metrics to
data/experiment/results.json for reproducibility.

Usage
-----
    PYTHONPATH=src python scripts/run_triage_experiment.py

Outputs
-------
    data/experiment/results.json        — machine-readable full results
    data/experiment/comparison.csv      — scorer comparison table
    data/experiment/threshold_curve.csv — P/R/F1 vs threshold for ML model
    data/experiment/feature_importance.json

All simulated operational values are clearly labelled.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ── project root on PYTHONPATH ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alertiq.triage import (
    AlertDataset,
    BaselineScorer,
    Evaluator,
    TriageConfig,
    TriageScorer,
)
from alertiq.triage.baseline import RandomScorer

# ── logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("experiment")

OUTPUT_DIR = Path("data/experiment")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    t0 = time.time()

    # ── 1. Configuration ──────────────────────────────────────────────────
    config = TriageConfig(alerts_csv="data/simulation/alerts.csv")
    log.info("Config: seed=%d, features=%d", config.seed, len(config.feature_columns))

    # ── 2. Load dataset & splits ──────────────────────────────────────────
    log.info("Loading dataset …")
    ds = AlertDataset(config)
    log.info("Boundaries: %s", ds.boundaries)

    X_train, y_train = ds.train_Xy()
    X_val,   y_val   = ds.val_Xy()
    X_ho,    y_ho    = ds.holdout_Xy()
    X_tv,    y_tv    = ds.train_val_Xy()   # train+val for phase-2 refit
    df_ho            = ds.holdout_df()

    log.info(
        "Splits — train: %d (SAR=%.1f%%)  val: %d (SAR=%.1f%%)  holdout: %d (SAR=%.1f%%)",
        len(y_train), y_train.mean() * 100,
        len(y_val),   y_val.mean()   * 100,
        len(y_ho),    y_ho.mean()    * 100,
    )

    evaluator = Evaluator(config)

    # ── 3. Baseline: Random ───────────────────────────────────────────────
    log.info("Evaluating baseline_random …")
    random_scorer = RandomScorer(config)
    result_random = evaluator.evaluate(random_scorer, X_ho, y_ho, df_ho)
    log.info(
        "random  AUC-ROC=%.4f  R@20%%=%.4f",
        result_random.auc_roc,
        next(r.recall_at_k for r in result_random.ranking_at_k if r.capacity_fraction == 0.20),
    )

    # ── 4. Baseline: Severity ────────────────────────────────────────────
    log.info("Evaluating baseline_severity …")
    sev_scorer = BaselineScorer(config)
    result_sev = evaluator.evaluate(sev_scorer, X_ho, y_ho, df_ho)
    log.info(
        "severity  AUC-ROC=%.4f  R@20%%=%.4f",
        result_sev.auc_roc,
        next(r.recall_at_k for r in result_sev.ranking_at_k if r.capacity_fraction == 0.20),
    )

    # ── 5. ML model: HistGBM — Phase 1 ──────────────────────────────────
    log.info("Training HistGBM Phase 1 (train → val threshold selection) …")
    triage_scorer = TriageScorer(config)
    triage_scorer.fit_phase1(X_train, y_train, X_val, y_val)
    log.info(
        "Phase-1 done: n_iter=%d  threshold=%.4f",
        triage_scorer.best_iter,
        triage_scorer.threshold,
    )

    # Validate on val set (diagnostic — NOT reported as final)
    val_mask = (ds.df["triggered_date"] > ds.boundaries.train_end) & (
        ds.df["triggered_date"] <= ds.boundaries.val_end
    )
    df_val = ds.df.loc[val_mask].copy()
    val_probs = triage_scorer.score(X_val)
    from sklearn.metrics import roc_auc_score as _roc, f1_score as _f1
    val_preds = (val_probs >= triage_scorer.threshold).astype(int)
    log.info(
        "Phase-1 val AUC-ROC=%.4f  F1=%.4f  (diagnostic only — not final metric)",
        _roc(y_val, val_probs),
        _f1(y_val, val_preds),
    )

    # ── 6. ML model: HistGBM — Phase 2 refit on train+val ───────────────
    log.info("Training HistGBM Phase 2 (train+val refit, n_iter=%d) …", triage_scorer.best_iter)
    triage_scorer.fit_phase2(X_tv, y_tv)

    # ── 7. Evaluate ML model on holdout (FINAL) ───────────────────────────
    log.info("Evaluating HistGBM on holdout (FINAL) …")
    result_ml = evaluator.evaluate(triage_scorer, X_ho, y_ho, df_ho)
    # Primary acceptance criterion: capacity-ranking Recall@20% (not classification mode)
    recall_20 = next(r.recall_at_k for r in result_ml.ranking_at_k if r.capacity_fraction == 0.20)
    log.info(
        "histgbm  AUC-ROC=%.4f  AUC-PR=%.4f"
        "  [RANKING] R@20%%=%.4f"
        "  [CLASSIFICATION] F1=%.4f  threshold=%.4f",
        result_ml.auc_roc,
        result_ml.auc_pr,
        recall_20,
        result_ml.threshold_metrics.f1,
        result_ml.threshold_metrics.threshold,
    )
    log.info(
        "NOTE: R@20%% is a CAPACITY-RANKING metric (top-20%% of ranked alerts)."
        " It is not derived from the classification threshold."
    )

    # ── 8. Threshold curve (for the ML model on holdout) ─────────────────
    log.info("Computing threshold curve …")
    ho_probs = triage_scorer.score(X_ho)
    thr_curve = Evaluator.threshold_curve(ho_probs, y_ho, n_points=200)
    thr_curve.to_csv(OUTPUT_DIR / "threshold_curve.csv", index=False)
    log.info("Threshold curve → %s", OUTPUT_DIR / "threshold_curve.csv")

    # ── 9. Permutation importances ────────────────────────────────────────
    log.info("Computing permutation importances (n_repeats=5, holdout) …")
    perm_imp = triage_scorer.permutation_importances(
        X_ho, y_ho, list(config.feature_columns), n_repeats=5
    )
    log.info("Top-5 features: %s", list(perm_imp.keys())[:5])

    # ── 10. Comparison table ──────────────────────────────────────────────
    all_results = [result_random, result_sev, result_ml]
    table = Evaluator.comparison_table(all_results)
    table.to_csv(OUTPUT_DIR / "comparison.csv")
    log.info("\n%s", table.T.to_string())

    # ── 11. Feature importances JSON ──────────────────────────────────────
    feat_imp = result_ml.feature_importances
    with open(OUTPUT_DIR / "feature_importance.json", "w") as f:
        json.dump({"mdi": feat_imp, "permutation": perm_imp}, f, indent=2)

    # ── 12. Acceptance-criteria check ─────────────────────────────────────
    auc_roc     = result_ml.auc_roc
    recall_at20 = recall_20  # CAPACITY-RANKING metric — top-20% of ranked alerts
    sev_r20     = next(r.recall_at_k for r in result_sev.ranking_at_k if r.capacity_fraction == 0.20)

    log.info("=" * 60)
    log.info("ACCEPTANCE CRITERIA CHECK")
    log.info("AUC-ROC (ranking, threshold-free)   %.4f  (>0.72): %s",
             auc_roc, "PASS" if auc_roc > 0.72 else "FAIL")
    log.info("Recall@20%% [RANKING — top 20%% of alerts ranked by score]")
    log.info("  HistGBM=%.4f  Severity=%.4f  Random=%.4f  (>0.45 required): %s",
             recall_at20, sev_r20,
             next(r.recall_at_k for r in result_random.ranking_at_k if r.capacity_fraction == 0.20),
             "PASS" if recall_at20 > 0.45 else "FAIL")
    log.info("  delta vs severity baseline: +%.4f", recall_at20 - sev_r20)
    log.info("FAILURE criteria: AUC-ROC <=0.58: %s", "OK" if auc_roc > 0.58 else "TRIGGERED")
    log.info("Classification-mode F1 (diagnostic): %.4f  threshold=%.4f",
             result_ml.threshold_metrics.f1, result_ml.threshold_metrics.threshold)
    log.info("  (F1 is at the fixed classification threshold; NOT the same as Recall@20%%)")
    log.info("=" * 60)

    # ── 13. Machine-readable full results ────────────────────────────────
    def serialise_result(r):
        return {
            "scorer_name": r.scorer_name,
            "n_alerts": r.n_alerts,
            "n_true_sars": r.n_true_sars,
            "sar_rate": r.sar_rate,
            "auc_roc": r.auc_roc,
            "auc_pr": r.auc_pr,
            "threshold_metrics": {
                "threshold": r.threshold_metrics.threshold,
                "tp": r.threshold_metrics.tp,
                "fp": r.threshold_metrics.fp,
                "tn": r.threshold_metrics.tn,
                "fn": r.threshold_metrics.fn,
                "precision": r.threshold_metrics.precision,
                "recall": r.threshold_metrics.recall,
                "f1": r.threshold_metrics.f1,
                "fpr": r.threshold_metrics.fpr,
                "fnr": r.threshold_metrics.fnr,
            },
            "ranking_at_k": [
                {
                    "capacity_fraction": m.capacity_fraction,
                    "k": m.k,
                    "tp_at_k": m.tp_at_k,
                    "total_true_sars": m.total_true_sars,
                    "precision_at_k": m.precision_at_k,
                    "recall_at_k": m.recall_at_k,
                    "sars_per_100_reviewed": m.sars_per_100_reviewed,
                }
                for m in r.ranking_at_k
            ],
            "operational": [
                {
                    "capacity_fraction": m.capacity_fraction,
                    "k": m.k,
                    "tp_at_k": m.tp_at_k,
                    "fp_at_k": m.fp_at_k,
                    "missed_sars": m.missed_sars,
                    "analyst_hours_to_review_k": m.analyst_hours_to_review_k,
                    "sar_filing_hours": m.sar_filing_hours,
                    "total_analyst_hours": m.total_analyst_hours,
                    "analyst_days": m.analyst_days,
                    "fp_per_tp": m.fp_per_tp if m.fp_per_tp != float("inf") else None,
                    "missed_sar_rate": m.missed_sar_rate,
                }
                for m in r.operational
            ],
            "error_analysis": {
                k: v for k, v in r.error_analysis.items()
                if not isinstance(v, dict) or k in ("fp_score_stats", "fn_score_stats", "top_fn_accounts")
            },
            "error_analysis_by_rule": {
                "fp_by_rule": r.error_analysis.get("fp_by_rule", {}),
                "fn_by_rule": r.error_analysis.get("fn_by_rule", {}),
                "tp_by_rule": r.error_analysis.get("tp_by_rule", {}),
            },
            "error_analysis_by_severity": {
                "fp_by_severity": r.error_analysis.get("fp_by_severity", {}),
                "fn_by_severity": r.error_analysis.get("fn_by_severity", {}),
            },
        }

    full_results = {
        "experiment": {
            "seed": config.seed,
            "alerts_csv": config.alerts_csv,
            "split": {
                "train_frac": config.split.train_frac,
                "val_frac": config.split.val_frac,
                "holdout_frac": config.split.holdout_frac,
                "train_end": str(ds.boundaries.train_end),
                "val_end": str(ds.boundaries.val_end),
                "train_alerts": ds.boundaries.train_alerts,
                "val_alerts": ds.boundaries.val_alerts,
                "holdout_alerts": ds.boundaries.holdout_alerts,
            },
            "model": {
                "name": "HistGradientBoostingClassifier",
                "best_iter_phase1": triage_scorer.best_iter,
                "selected_threshold": triage_scorer.threshold,
                "hyperparams": config.hyperparams.model_dump(),
            },
            "elapsed_s": round(time.time() - t0, 1),
        },
        "results": {r.scorer_name: serialise_result(r) for r in all_results},
        "acceptance_criteria": {
            # NOTE ON OPERATING MODES:
            # auc_roc: threshold-free ranking quality (applies to both modes)
            # ml_ranking_recall_at_20pct: CAPACITY-RANKING mode — fraction of SARs
            #   recovered by reviewing the top 20% of alerts sorted by model score.
            #   This is the PRIMARY acceptance criterion.
            # ml_cls_f1_at_threshold: CLASSIFICATION mode (diagnostic only) — hard
            #   binary predictions at the selected probability threshold.
            "auc_roc_threshold": 0.72,
            "ranking_recall_at_20pct_threshold": 0.45,
            "failure_auc_roc": 0.58,
            "ml_auc_roc": auc_roc,
            "ml_ranking_recall_at_20pct": recall_at20,  # RANKING mode primary metric
            "ml_cls_f1_at_threshold": result_ml.threshold_metrics.f1,  # CLASSIFICATION mode diagnostic
            "ml_cls_threshold": result_ml.threshold_metrics.threshold,
            "auc_roc_pass": bool(auc_roc > 0.72),
            "ranking_recall_at_20pct_pass": bool(recall_at20 > 0.45),
            "failure_triggered": bool(auc_roc <= 0.58),
            "_mode_note": (
                "Recall@20% is a RANKING metric (top-K% of alerts sorted by score). "
                "It is independent of the classification threshold. "
                "Analysts do not apply a binary threshold in production; "
                "they work through the ranked queue up to their capacity limit."
            ),
        },
        "permutation_importances": perm_imp,
    }

    with open(OUTPUT_DIR / "results.json", "w") as f:
        json.dump(full_results, f, indent=2)
    log.info("Full results → %s", OUTPUT_DIR / "results.json")
    log.info("Experiment complete in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
