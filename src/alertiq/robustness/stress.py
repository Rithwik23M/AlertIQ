"""
Controlled out-of-distribution stress scenarios for AlertIQ Milestone 3.

Purpose
-------
Test whether the model degrades gracefully under controlled distribution shifts.
Each scenario perturbs the SCORING data only — the model is never retrained.

Scenarios implemented
---------------------
S01  High-volume surge      — Volume features (f01–f03) scaled ×3
S02  New jurisdiction       — Jurisdiction score set to 0.9 (novel country)
S03  Missing features       — 30 pct of non-categorical features set to 0
S04  Rule shift             — R08 alerts removed; only minority rules remain
S05  Novel typology         — Pattern absent in training (rule group + volume spike)
S06  SAR rate collapse      — Only 1 pct of SAR labels retained (label imbalance)

Interpretation rules
--------------------
- Recall@20% drop > 0.10 from baseline → flag as significant degradation.
- AUC-ROC drop > 0.05 → flag as significant degradation.
- Scenarios that reduce n_sars below 5 are skipped (insufficient signal).

These scenarios test robustness, NOT production performance.
Synthetic perturbation ≠ future data distribution.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

log = logging.getLogger(__name__)

# Drop in Recall@20% that constitutes a significant degradation
RECALL_DROP_THRESHOLD = 0.10

# Drop in AUC-ROC that constitutes a significant degradation
AUC_DROP_THRESHOLD = 0.05


@dataclasses.dataclass
class StressResult:
    """Result for one stress scenario in one evaluation window."""

    scenario_id: str           # "S01", "S02", etc.
    scenario_name: str
    window_label: str

    # Baseline (unperturbed) metrics
    baseline_auc_roc: float
    baseline_recall_at_20: float
    baseline_n: int
    baseline_n_sars: int

    # Perturbed metrics
    perturbed_auc_roc: float | None
    perturbed_recall_at_20: float | None
    perturbed_n: int
    perturbed_n_sars: int

    # Delta
    delta_auc_roc: float | None       # perturbed − baseline
    delta_recall_at_20: float | None  # perturbed − baseline

    # Flags
    skipped: bool
    skip_reason: str
    auc_degraded: bool
    recall_degraded: bool

    @property
    def any_degraded(self) -> bool:
        return self.auc_degraded or self.recall_degraded

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _recall_at_k(scores: np.ndarray, labels: np.ndarray, capacity: float) -> float:
    n = len(scores)
    k = max(1, int(np.ceil(n * capacity)))
    k = min(k, n)
    top_idx = np.argsort(scores)[::-1][:k]
    tp = int(labels[top_idx].sum())
    total_sars = int(labels.sum())
    return tp / total_sars if total_sars > 0 else 0.0


def _metrics(scores: np.ndarray, labels: np.ndarray) -> dict[str, float | None]:
    n_sars = int(labels.sum())
    n_nonsars = int((labels == 0).sum())
    if n_sars < 2 or n_nonsars < 2:
        return {"auc_roc": None, "recall_20": None}
    try:
        auc_roc = float(roc_auc_score(labels, scores))
    except Exception:
        auc_roc = None
    recall_20 = _recall_at_k(scores, labels, 0.20)
    return {"auc_roc": auc_roc, "recall_20": recall_20}


# ---------------------------------------------------------------------------
# Scenario perturbation functions
# Each receives (X: np.ndarray, y: np.ndarray, rule_ids: np.ndarray | None,
#                feature_names: list[str]) and returns (X_perturbed, y_perturbed, mask)
# mask selects which original rows survive the perturbation (None = all rows).
# ---------------------------------------------------------------------------

def _s01_volume_surge(
    X: np.ndarray,
    y: np.ndarray,
    rule_ids: np.ndarray | None,
    feature_names: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Volume features ×3 (f01_vol_7d_log, f02_vol_30d_log, f03_vol_90d_log)."""
    X2 = X.copy()
    vol_cols = ["f01_vol_7d_log", "f02_vol_30d_log", "f03_vol_90d_log"]
    for col in vol_cols:
        if col in feature_names:
            idx = feature_names.index(col)
            X2[:, idx] = np.clip(X2[:, idx] + np.log(3), 0, None)
    return X2, y.copy(), None


def _s02_new_jurisdiction(
    X: np.ndarray,
    y: np.ndarray,
    rule_ids: np.ndarray | None,
    feature_names: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Account jurisdiction score forced to 0.9 (novel high-risk country)."""
    X2 = X.copy()
    col = "f24_account_jurisdiction_score"
    if col in feature_names:
        idx = feature_names.index(col)
        X2[:, idx] = 0.9
    return X2, y.copy(), None


def _s03_missing_features(
    X: np.ndarray,
    y: np.ndarray,
    rule_ids: np.ndarray | None,
    feature_names: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """30 % of non-categorical values zeroed (simulates data quality issues)."""
    X2 = X.copy()
    cat_cols = {"f18_rule_category", "f20_channel_type", "f21_product_type", "f22_alert_severity"}
    rng = np.random.default_rng(42)
    for i, col in enumerate(feature_names):
        if col not in cat_cols:
            mask = rng.random(len(X2)) < 0.30
            X2[mask, i] = 0.0
    return X2, y.copy(), None


def _s04_rule_shift(
    X: np.ndarray,
    y: np.ndarray,
    rule_ids: np.ndarray | None,
    feature_names: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Remove R08 (high-volume, low-SAR) — leaves minority high-SAR rules."""
    if rule_ids is None:
        return X.copy(), y.copy(), None
    mask = rule_ids != "R08"
    return X[mask].copy(), y[mask].copy(), mask


def _s05_novel_typology(
    X: np.ndarray,
    y: np.ndarray,
    rule_ids: np.ndarray | None,
    feature_names: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """
    Inject novel typology: R08 alerts with extreme volume surge.

    Simulates a new typology that was absent from training:
    high-volume R08 alerts with jurisdiction score 0.95.
    These are labelled as SARs (worst-case for the model).
    """
    X2 = X.copy()
    y2 = y.copy()

    # Select R08 alerts (if rule_ids available) or use first 20%
    if rule_ids is not None:
        novel_mask = rule_ids == "R08"
    else:
        novel_mask = np.zeros(len(X2), dtype=bool)
        novel_mask[:max(1, len(X2) // 5)] = True

    if novel_mask.sum() == 0:
        return X2, y2, None

    # Perturb: volume surge + high jurisdiction score
    for col in ["f01_vol_7d_log", "f02_vol_30d_log", "f03_vol_90d_log"]:
        if col in feature_names:
            idx = feature_names.index(col)
            X2[novel_mask, idx] = np.clip(X2[novel_mask, idx] + np.log(5), 0, None)

    col_jur = "f24_account_jurisdiction_score"
    if col_jur in feature_names:
        idx = feature_names.index(col_jur)
        X2[novel_mask, idx] = 0.95

    # Label them as SARs (the model has never seen this combination)
    y2[novel_mask] = 1

    return X2, y2, None


def _s06_sar_rate_collapse(
    X: np.ndarray,
    y: np.ndarray,
    rule_ids: np.ndarray | None,
    feature_names: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """
    Retain only 1 % of SAR labels — simulates extreme class imbalance shift.

    Non-SAR alerts are retained unchanged.
    """
    rng = np.random.default_rng(0)
    sar_idx = np.where(y == 1)[0]
    nonsar_idx = np.where(y == 0)[0]

    n_keep_sars = max(1, int(len(sar_idx) * 0.01))
    keep_sars = rng.choice(sar_idx, size=n_keep_sars, replace=False)

    keep_idx = np.sort(np.concatenate([nonsar_idx, keep_sars]))
    mask = np.zeros(len(X), dtype=bool)
    mask[keep_idx] = True
    return X[mask].copy(), y[mask].copy(), mask


# Registry of scenarios
_SCENARIOS: list[tuple[str, str, Callable]] = [
    ("S01", "Volume surge (×3)", _s01_volume_surge),
    ("S02", "New jurisdiction (score=0.9)", _s02_new_jurisdiction),
    ("S03", "Missing features (30 pct zeroed)", _s03_missing_features),
    ("S04", "Rule shift (R08 removed)", _s04_rule_shift),
    ("S05", "Novel typology (R08 + volume + jurisdiction)", _s05_novel_typology),
    ("S06", "SAR rate collapse (1 pct SARs retained)", _s06_sar_rate_collapse),
]


def run_stress_scenarios(
    scorer_score_fn: Callable[[np.ndarray], np.ndarray],
    X_test: np.ndarray,
    y_test: np.ndarray,
    feature_names: list[str],
    window_label: str,
    rule_ids: np.ndarray | None = None,
) -> list[StressResult]:
    """
    Run all stress scenarios on the test set using a fitted scorer.

    Args:
        scorer_score_fn:  Callable that takes X (n×p) and returns scores (n,).
                          This is the fitted TriageScorer.score method.
        X_test:           Test feature matrix (unperturbed).
        y_test:           Test labels (unperturbed).
        feature_names:    Feature column names corresponding to X_test columns.
        window_label:     Label for the evaluation window.
        rule_ids:         Optional array of rule_ids for each test alert.
                          Required for S04 and S05 scenarios to work correctly.

    Returns:
        List of StressResult, one per scenario.

    Notes:
        The scorer is never retrained — only the INPUTS are perturbed.
        This isolates how the model responds to distribution shift.
    """
    # Baseline metrics (unperturbed)
    baseline_scores = scorer_score_fn(X_test)
    baseline_m = _metrics(baseline_scores, y_test)
    baseline_auc = baseline_m["auc_roc"] or 0.0
    baseline_r20 = baseline_m["recall_20"] or 0.0
    baseline_n_sars = int(y_test.sum())

    results = []
    for sid, sname, perturb_fn in _SCENARIOS:
        log.info("  Stress %s: %s", sid, sname)

        try:
            X_p, y_p, _mask = perturb_fn(X_test, y_test, rule_ids, feature_names)
        except Exception as exc:
            log.warning("  Scenario %s perturbation failed: %s", sid, exc)
            results.append(StressResult(
                scenario_id=sid, scenario_name=sname, window_label=window_label,
                baseline_auc_roc=baseline_auc, baseline_recall_at_20=baseline_r20,
                baseline_n=len(y_test), baseline_n_sars=baseline_n_sars,
                perturbed_auc_roc=None, perturbed_recall_at_20=None,
                perturbed_n=0, perturbed_n_sars=0,
                delta_auc_roc=None, delta_recall_at_20=None,
                skipped=True, skip_reason=str(exc),
                auc_degraded=False, recall_degraded=False,
            ))
            continue

        n_sars_p = int(y_p.sum())
        if n_sars_p < 5:
            log.warning("  Scenario %s: insufficient SARs after perturbation (%d) — skipping", sid, n_sars_p)
            results.append(StressResult(
                scenario_id=sid, scenario_name=sname, window_label=window_label,
                baseline_auc_roc=baseline_auc, baseline_recall_at_20=baseline_r20,
                baseline_n=len(y_test), baseline_n_sars=baseline_n_sars,
                perturbed_auc_roc=None, perturbed_recall_at_20=None,
                perturbed_n=len(y_p), perturbed_n_sars=n_sars_p,
                delta_auc_roc=None, delta_recall_at_20=None,
                skipped=True, skip_reason=f"insufficient SARs after perturbation ({n_sars_p})",
                auc_degraded=False, recall_degraded=False,
            ))
            continue

        try:
            p_scores = scorer_score_fn(X_p)
            p_m = _metrics(p_scores, y_p)
            p_auc = p_m["auc_roc"]
            p_r20 = p_m["recall_20"]
        except Exception as exc:
            log.warning("  Scenario %s scoring failed: %s", sid, exc)
            results.append(StressResult(
                scenario_id=sid, scenario_name=sname, window_label=window_label,
                baseline_auc_roc=baseline_auc, baseline_recall_at_20=baseline_r20,
                baseline_n=len(y_test), baseline_n_sars=baseline_n_sars,
                perturbed_auc_roc=None, perturbed_recall_at_20=None,
                perturbed_n=len(y_p), perturbed_n_sars=n_sars_p,
                delta_auc_roc=None, delta_recall_at_20=None,
                skipped=True, skip_reason=str(exc),
                auc_degraded=False, recall_degraded=False,
            ))
            continue

        d_auc = (p_auc - baseline_auc) if p_auc is not None else None
        d_r20 = (p_r20 - baseline_r20) if p_r20 is not None else None

        auc_degraded = d_auc is not None and d_auc < -AUC_DROP_THRESHOLD
        recall_degraded = d_r20 is not None and d_r20 < -RECALL_DROP_THRESHOLD

        if auc_degraded or recall_degraded:
            log.warning(
                "  Scenario %s | %s: DEGRADATION DETECTED — "
                "ΔAUC=%.3f  ΔRecall@20%%=%.3f",
                sid, window_label,
                d_auc if d_auc is not None else float("nan"),
                d_r20 if d_r20 is not None else float("nan"),
            )

        results.append(StressResult(
            scenario_id=sid, scenario_name=sname, window_label=window_label,
            baseline_auc_roc=baseline_auc, baseline_recall_at_20=baseline_r20,
            baseline_n=len(y_test), baseline_n_sars=baseline_n_sars,
            perturbed_auc_roc=p_auc, perturbed_recall_at_20=p_r20,
            perturbed_n=len(y_p), perturbed_n_sars=n_sars_p,
            delta_auc_roc=d_auc, delta_recall_at_20=d_r20,
            skipped=False, skip_reason="",
            auc_degraded=auc_degraded, recall_degraded=recall_degraded,
        ))

    return results


def stress_summary_df(results: list[StressResult]) -> pd.DataFrame:
    """Convert list of StressResult to a tidy DataFrame."""
    return pd.DataFrame([r.to_dict() for r in results])
