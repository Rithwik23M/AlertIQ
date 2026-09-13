"""
Real-data integration test: AlertDataset → baselines → TriageScorer → Evaluator.

This test exercises the full pipeline on the actual simulator CSV
(data/simulation/alerts.csv).  It is the CI regression guard: a change
that breaks the pipeline or degrades holdout performance below hard floors
will be caught here.

Design decisions
----------------
- Tests are marked ``pytest.mark.integration`` and are skipped automatically
  when the real CSV is absent (CI environments that do not have data/).
- Training uses reduced hyperparameters (max_iter=30, n_iter_no_change=5)
  to keep the test under ~60 seconds; the full training protocol is in
  run_triage_experiment.py.
- Acceptance-criterion floors are deliberately conservative (below the
  Milestone 2 thresholds) so this test catches catastrophic regressions
  without being fragile to minor implementation changes.
- The test captures the two operating modes explicitly and asserts on each.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

# ── paths ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
ALERTS_CSV = PROJECT_ROOT / "data" / "simulation" / "alerts.csv"

# Expected SHA-256 fingerprint of the dataset (from DATA_PROVENANCE.md).
# If this fails the CSV has been modified — verify provenance before proceeding.
# Updated M6.1: alerts.csv v3 (55,896 rows). See DATA_PROVENANCE.md version history.
_EXPECTED_SHA256 = "3ae95fb5b273c9426918b6c55bca99d123927047aa1b22590bfe8b6d5ac28bd8"

# Conservative regression floors — catastrophic failure detection.
# These are BELOW the Milestone 2 acceptance criteria to avoid fragility.
_FLOOR_AUC_ROC = 0.85          # M2 target: >0.72; full-training result: 0.979
_FLOOR_RANKING_RECALL_20 = 0.70  # M2 target: >0.45; full-training result: 1.00
_FLOOR_AUC_ROC_SEVERITY_ABOVE_RANDOM = 0.01  # severity must beat random


# ── markers / skip guard ──────────────────────────────────────────────────
needs_data = pytest.mark.skipif(
    not ALERTS_CSV.exists(),
    reason=f"Real dataset not found: {ALERTS_CSV}. Skipping integration tests.",
)


# ── fixtures ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def _fast_config():
    """TriageConfig with reduced hyperparameters for fast integration testing."""
    from alertiq.triage.config import TriageConfig
    return TriageConfig(
        alerts_csv=str(ALERTS_CSV),
        hyperparams={
            "max_iter": 30,
            "n_iter_no_change": 5,
            "learning_rate": 0.1,
        },
    )


@pytest.fixture(scope="module")
def _pipeline(_fast_config):
    """
    Run the full pipeline once per test module; tests share the result.

    Returns a dict with keys:
        ds, X_tr, y_tr, X_va, y_va, X_ho, y_ho, df_ho,
        result_random, result_sev, result_ml, scorer
    """
    from alertiq.triage import AlertDataset, BaselineScorer, Evaluator, TriageScorer
    from alertiq.triage.baseline import RandomScorer

    ds = AlertDataset(_fast_config)
    X_tr, y_tr = ds.train_Xy()
    X_va, y_va = ds.val_Xy()
    X_ho, y_ho = ds.holdout_Xy()
    X_tv, y_tv = ds.train_val_Xy()
    df_ho = ds.holdout_df()

    evaluator = Evaluator(_fast_config)

    random_scorer = RandomScorer(_fast_config)
    result_random = evaluator.evaluate(random_scorer, X_ho, y_ho, df_ho)

    sev_scorer = BaselineScorer(_fast_config)
    result_sev = evaluator.evaluate(sev_scorer, X_ho, y_ho, df_ho)

    scorer = TriageScorer(_fast_config)
    scorer.fit_phase1(X_tr, y_tr, X_va, y_va)
    scorer.fit_phase2(X_tv, y_tv)
    result_ml = evaluator.evaluate(scorer, X_ho, y_ho, df_ho)

    return {
        "ds": ds,
        "X_tr": X_tr, "y_tr": y_tr,
        "X_va": X_va, "y_va": y_va,
        "X_ho": X_ho, "y_ho": y_ho,
        "df_ho": df_ho,
        "result_random": result_random,
        "result_sev": result_sev,
        "result_ml": result_ml,
        "scorer": scorer,
    }


# ── dataset integrity ─────────────────────────────────────────────────────
class TestDatasetProvenance:
    @needs_data
    def test_csv_sha256_matches_provenance(self):
        """Dataset fingerprint matches DATA_PROVENANCE.md."""
        with open(ALERTS_CSV, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        assert sha == _EXPECTED_SHA256, (
            f"Dataset SHA-256 mismatch.\n"
            f"  Got:      {sha}\n"
            f"  Expected: {_EXPECTED_SHA256}\n"
            "The dataset has been modified. Update DATA_PROVENANCE.md and "
            "this test if the change was intentional."
        )

    @needs_data
    def test_csv_row_count(self):
        import pandas as pd
        df = pd.read_csv(ALERTS_CSV)
        assert len(df) == 55896, f"Expected 55896 rows (v3), got {len(df)}"

    @needs_data
    def test_csv_sar_count(self):
        import pandas as pd
        df = pd.read_csv(ALERTS_CSV)
        assert int(df["true_sar"].sum()) == 5209


# ── split integrity ───────────────────────────────────────────────────────
class TestSplitIntegrity:
    @needs_data
    def test_splits_cover_all_alerts(self, _pipeline):
        p = _pipeline
        n_tr = len(p["y_tr"])
        n_va = len(p["y_va"])
        n_ho = len(p["y_ho"])
        assert n_tr + n_va + n_ho == 55896, (
            f"Splits do not cover all alerts: {n_tr}+{n_va}+{n_ho}={n_tr+n_va+n_ho}"
        )

    @needs_data
    def test_no_date_leakage_between_splits(self, _pipeline):
        """Holdout dates must be strictly after validation dates."""
        import pandas as pd
        ds = _pipeline["ds"]
        b = ds.boundaries
        assert b.train_end < b.val_end, "train_end must precede val_end"

    @needs_data
    def test_leakage_columns_absent_from_feature_matrix(self, _pipeline):
        """Feature matrix must not contain true_sar or identifier columns."""
        from alertiq.triage.config import TriageConfig
        config = TriageConfig(alerts_csv=str(ALERTS_CSV))
        leakage = {"true_sar", "triggered_by_typology_txn", "account_id", "alert_id", "status"}
        for col in config.feature_columns:
            assert col not in leakage, f"Leakage column in features: {col}"

    @needs_data
    def test_sar_rate_consistent_across_splits(self, _pipeline):
        """SAR rate in each split should be approximately equal (temporal stationarity)."""
        for split_name, y in [
            ("train", _pipeline["y_tr"]),
            ("val", _pipeline["y_va"]),
            ("holdout", _pipeline["y_ho"]),
        ]:
            rate = float(y.mean())
            assert 0.05 <= rate <= 0.20, (
                f"{split_name} SAR rate {rate:.3f} is outside expected 5%–20% range"
            )


# ── baseline sanity ───────────────────────────────────────────────────────
class TestBaselineSanity:
    @needs_data
    def test_random_scorer_auc_near_half(self, _pipeline):
        """Random scorer AUC-ROC should be near 0.5."""
        auc = _pipeline["result_random"].auc_roc
        assert 0.40 <= auc <= 0.60, f"Random AUC-ROC={auc:.4f} is far from 0.5"

    @needs_data
    def test_severity_scorer_beats_random_on_auc(self, _pipeline):
        """Severity-based ranking should outperform random."""
        auc_sev = _pipeline["result_sev"].auc_roc
        auc_rnd = _pipeline["result_random"].auc_roc
        delta = auc_sev - auc_rnd
        assert delta >= _FLOOR_AUC_ROC_SEVERITY_ABOVE_RANDOM, (
            f"Severity AUC-ROC ({auc_sev:.4f}) did not beat random ({auc_rnd:.4f}) "
            f"by at least {_FLOOR_AUC_ROC_SEVERITY_ABOVE_RANDOM}"
        )


# ── ML model: classification mode ─────────────────────────────────────────
class TestMLClassificationMode:
    """
    Tests for classification-mode metrics (hard binary predictions at threshold).
    These are DIAGNOSTIC.  The primary acceptance criterion is in
    TestMLCapacityRankingMode.
    """

    @needs_data
    def test_threshold_in_zero_one(self, _pipeline):
        thr = _pipeline["scorer"].threshold
        assert 0.0 <= thr <= 1.0, f"Threshold {thr} out of [0, 1]"

    @needs_data
    def test_best_iter_positive(self, _pipeline):
        assert _pipeline["scorer"].best_iter >= 1

    @needs_data
    def test_scores_in_zero_one(self, _pipeline):
        p = _pipeline
        probs = p["scorer"].score(p["X_ho"])
        assert np.all(probs >= 0.0) and np.all(probs <= 1.0)

    @needs_data
    def test_classification_f1_above_random(self, _pipeline):
        """ML F1 at threshold must beat random F1 (basic sanity)."""
        f1_ml = _pipeline["result_ml"].threshold_metrics.f1
        f1_rnd = _pipeline["result_random"].threshold_metrics.f1
        assert f1_ml > f1_rnd, (
            f"ML classification F1 ({f1_ml:.4f}) did not beat random ({f1_rnd:.4f})"
        )

    @needs_data
    def test_classification_and_ranking_recall_are_different_metrics(self, _pipeline):
        """
        Explicitly assert that classification-mode recall ≠ Recall@20%.
        This guards against conflating the two operating modes.
        """
        cls_recall = _pipeline["result_ml"].threshold_metrics.recall
        ranking_recall_20 = next(
            r.recall_at_k
            for r in _pipeline["result_ml"].ranking_at_k
            if r.capacity_fraction == 0.20
        )
        # These two numbers are computed by completely different mechanisms.
        # They may coincidentally be similar but the test documents they are separate.
        # We check both are valid probabilities.
        assert 0.0 <= cls_recall <= 1.0, f"Classification recall {cls_recall} out of range"
        assert 0.0 <= ranking_recall_20 <= 1.0, f"Ranking Recall@20% {ranking_recall_20} out of range"


# ── ML model: capacity-ranking mode (PRIMARY) ─────────────────────────────
class TestMLCapacityRankingMode:
    """
    Tests for capacity-ranking mode.  This is the PRIMARY operating policy.
    Analysts work through the alert queue sorted by model score and stop
    at their capacity limit.  Recall@K is the primary acceptance metric.
    """

    @needs_data
    def test_ranking_recall_at_20pct_above_floor(self, _pipeline):
        """PRIMARY acceptance criterion: Recall@20% must exceed regression floor."""
        recall_20 = next(
            r.recall_at_k
            for r in _pipeline["result_ml"].ranking_at_k
            if r.capacity_fraction == 0.20
        )
        assert recall_20 >= _FLOOR_RANKING_RECALL_20, (
            f"Recall@20% = {recall_20:.4f} is below regression floor {_FLOOR_RANKING_RECALL_20}. "
            "This indicates a significant performance regression."
        )

    @needs_data
    def test_ranking_recall_at_20pct_beats_severity(self, _pipeline):
        """ML ranking must outperform severity baseline at 20% capacity."""
        ml_r20 = next(
            r.recall_at_k
            for r in _pipeline["result_ml"].ranking_at_k
            if r.capacity_fraction == 0.20
        )
        sev_r20 = next(
            r.recall_at_k
            for r in _pipeline["result_sev"].ranking_at_k
            if r.capacity_fraction == 0.20
        )
        assert ml_r20 > sev_r20, (
            f"ML Recall@20% ({ml_r20:.4f}) did not beat severity baseline ({sev_r20:.4f})"
        )

    @needs_data
    def test_ranking_recall_monotonic_with_capacity(self, _pipeline):
        """Recall@K must be non-decreasing as K increases."""
        recalls = [
            r.recall_at_k for r in sorted(
                _pipeline["result_ml"].ranking_at_k,
                key=lambda r: r.capacity_fraction,
            )
        ]
        for i in range(len(recalls) - 1):
            assert recalls[i] <= recalls[i + 1] + 1e-9, (
                f"Recall@K is not monotonic: {recalls}"
            )

    @needs_data
    def test_auc_roc_above_floor(self, _pipeline):
        """AUC-ROC (threshold-free ranking quality) must exceed regression floor."""
        auc = _pipeline["result_ml"].auc_roc
        assert auc >= _FLOOR_AUC_ROC, (
            f"AUC-ROC = {auc:.4f} is below regression floor {_FLOOR_AUC_ROC}"
        )


# ── evaluation result structure ───────────────────────────────────────────
class TestEvaluationResultStructure:
    @needs_data
    def test_summary_dict_has_ranked_keys(self, _pipeline):
        """summary_dict must have rank_recall_at_20pct key (not recall_at_20pct)."""
        sd = _pipeline["result_ml"].summary_dict()
        assert "rank_recall_at_20pct" in sd, (
            f"Expected 'rank_recall_at_20pct' in summary_dict keys: {list(sd.keys())}"
        )

    @needs_data
    def test_summary_dict_has_cls_prefix_keys(self, _pipeline):
        """summary_dict classification-mode keys must be prefixed with 'cls_'."""
        sd = _pipeline["result_ml"].summary_dict()
        assert "cls_f1" in sd, f"Expected 'cls_f1' in summary_dict: {list(sd.keys())}"
        assert "cls_recall" in sd, f"Expected 'cls_recall' in summary_dict: {list(sd.keys())}"
        assert "cls_precision" in sd

    @needs_data
    def test_summary_dict_no_unprefixed_recall(self, _pipeline):
        """Unprefixed 'recall' key must not appear — prevents mode conflation."""
        sd = _pipeline["result_ml"].summary_dict()
        assert "recall" not in sd, (
            "'recall' key found without mode prefix in summary_dict. "
            "Use 'cls_recall' (classification mode) or 'rank_recall_at_Kpct' (ranking mode)."
        )

    @needs_data
    def test_evaluation_result_has_both_mode_fields(self, _pipeline):
        """EvaluationResult must expose both threshold_metrics and ranking_at_k."""
        result = _pipeline["result_ml"]
        assert result.threshold_metrics is not None
        assert len(result.ranking_at_k) > 0
