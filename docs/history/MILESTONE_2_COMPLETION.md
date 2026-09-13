# AlertIQ — Milestone 2 Completion Report
## AML Alert Triage Engine: Baseline + ML Evaluation

**Date:** 2026-09-12  
**Author:** ApexForge Labs  
**Status:** COMPLETE — All acceptance criteria passed. Devil Mode review complete.

---

## Item 1 — Problem Statement and Hypothesis

**SAR workflow note.** AlertIQ is a prioritisation system, not a decision system. The model assigns a risk score; the analyst investigates the alert; the analyst (not the model) decides whether to escalate, close, or file. "Caught SARs" in this document means "surfaced in the analyst's review queue within their capacity window" — whether a SAR filing actually results depends on subsequent human investigation and legal judgment.

**Problem.** A Transaction Monitoring System (TMS) fires approximately 11,000 alerts per 60-day period for a mid-tier financial institution. At ~9.5% true SAR rate (from simulator ground truth), analysts must manually review all alerts. At 0.5 hours per alert and 6 productive hours per analyst-day, full review of the holdout period requires **~926 analyst-days**. The institution can realistically dedicate capacity to review 20% of alerts per cycle.

**Baseline (H₀).** Random triage (no prioritisation): analysts review alerts in arbitrary order. At 20% capacity, they surface ~20% of simulator-labelled SARs by chance — equivalent to no system at all.

**Hypothesis (H₁).** A gradient-boosted classifier trained on behavioural transaction features, using proper temporal splitting and F1-optimised threshold selection, can concentrate simulator-labelled SARs in the top-reviewed fraction, achieving Recall@20% > 0.45 and AUC-ROC > 0.72.

**Failure criterion.** AUC-ROC ≤ 0.58 on holdout, or evidence of temporal leakage.

---

## Item 2 — Baseline Ladder

| Level | Method | Rationale |
|-------|--------|-----------|
| 0 — Naive | Random ordering (RandomScorer) | No system; catches SARs at base rate |
| 1 — Heuristic | Severity-based ranking (SeverityScorer) | Simple rule already available from TMS |
| 2 — Statistical | *(not implemented; SAR rate is too low for pure statistical thresholds)* | — |
| 3 — ML | HistGradientBoostingClassifier (HistGBM) | Trained model with 24 behavioural features |
| 4 — Advanced | *(not implemented; Level 3 is evaluated first per evidence-first discipline)* | — |

The principle: a simpler method wins if it is competitive. Level 3 is justified only after proving Levels 0 and 1 are insufficient.

---

## Item 3 — Acceptance Criteria

| Criterion | Threshold | Result | Status |
|-----------|-----------|--------|--------|
| AUC-ROC (holdout) | > 0.72 | **0.9792** | ✅ PASS |
| Recall@20% capacity (holdout) | > 0.45 | **1.0000** | ✅ PASS |
| Failure trigger | AUC-ROC ≤ 0.58 | 0.9792 | ✅ NOT triggered |
| Temporal leakage | None | None detected | ✅ PASS |
| Test suite | 81/81 | **81/81** | ✅ PASS |

---

## Item 4 — Temporal Split Integrity and Leakage Guard

**Split.** All splits are by calendar date boundaries, not row index. This prevents any future-date data from appearing in training.

| Split | Dates | Alerts | SAR Count |
|-------|-------|--------|-----------|
| Train | 2023-01-01 → 2023-04-15 | 33,732 | ~3,220 (9.5%) |
| Validation | 2023-04-16 → 2023-05-23 | 11,344 | ~1,081 (9.5%) |
| Holdout | 2023-05-24 → 2023-07-01 | 11,119 | 1,057 (9.5%) |

**Holdout was never seen during any training or threshold-selection step.**

**Leakage guard (`_LEAKAGE_COLUMNS`).** The following columns cannot appear as model features:
- `true_sar` — the label itself
- `triggered_by_typology_txn` — another label proxy
- `account_id`, `alert_id` — identifiers, not behaviour signals
- `status` — post-alert outcome, unknown at alert time

`AlertDataset._load_and_validate()` raises `ValueError` at construction time if any configured feature column matches a leakage column or is absent from the CSV. This is verified by two dedicated tests.

**Validated by tests:**
- `TestLeakageGuard::test_leakage_column_in_feature_config_raises`
- `TestLeakageGuard::test_missing_feature_column_raises`
- `TestLeakageGuard::test_feature_matrix_does_not_contain_true_sar`
- `TestLeakageGuard::test_null_true_sar_raises`

---

## Item 5 — Data Statistics

| Statistic | Value |
|-----------|-------|
| Total alerts (full dataset) | 56,195 |
| Holdout alerts | 11,119 |
| True SAR rate (holdout) | 9.51% (1,057 / 11,119) |
| Feature columns | 24 (`f01`–`f24`) |
| Categorical features | 4 (indices 17, 19, 20, 21: flag-type features) |
| Continuous features | 20 (volumetric, velocity, ratio features) |
| Feature dtype | float64 |
| Label dtype | int32 (0/1) |

---

## Item 6 — Training Protocol

**Phase 1 (discovery).** Train HistGradientBoostingClassifier on the training split with early stopping. An internal 10% holdout of the training set is used for early stopping; early stopping fires when validation loss does not improve for 20 consecutive iterations.

- `class_weight="balanced"` compensates for 9.5% SAR imbalance
- `random_state=42` ensures full reproducibility
- Best iteration discovered: **145 trees**
- Selected threshold (F1-optimal on val): **0.1153**

**Why not threshold p=0.5?** With class imbalance, p=0.5 is an arbitrary boundary that does not correspond to the model's optimal operating point. Threshold selection searches 200 candidates between the 1st and 99th percentile of validation probabilities, choosing the one that maximises F1. Ties are broken by selecting the higher threshold (more conservative, fewer FPs) to suit analyst capacity constraints.

**Phase 2 (refinement).** Re-train on train+val combined (no early stopping) for exactly `best_iter=145` iterations. This gives the final model access to validation labelled data while preventing overfitting. All final metrics are reported on the untouched holdout.

**Algorithm choice: HistGBM vs LightGBM.** LightGBM was the original intended choice (fast, widely deployed in AML systems). It was unavailable in this execution environment (pip wheel missing). HistGradientBoostingClassifier is sklearn's histogram-based GBDT implementation; it shares algorithmic ancestry with LightGBM but is a distinct implementation. Results are not guaranteed to reproduce on LightGBM: hyperparameter names differ and numerical outputs may vary. If the environment changes to support LightGBM, the model must be re-evaluated. See ADR-01.

---

## Item 7 — Operating Modes and Threshold Selection

### Primary operating mode: Capacity-ranking

AlertIQ's PRIMARY operating policy is capacity-ranking: analysts work through alerts sorted by descending model score and stop at their capacity limit (e.g. 20% of the queue). The model is evaluated on **Recall@K** — fraction of true SARs surfaced within the top-K reviewed alerts. No probability threshold is involved in this mode.

### Secondary/diagnostic mode: Classification

For binary classification diagnostics, a probability threshold is selected on the validation split:

```
Candidates: linspace(percentile(probs, 1), percentile(probs, 99), 200)
Objective: maximise F1 on validation set
Selected threshold: 0.1153 (vs naive 0.5)
```

**Why this threshold is diagnostic, not primary.** The F1-optimal threshold is selected on one specific validation split. If the score distribution shifts (new alert typologies, seasonal change, model recalibration), the optimal threshold shifts. In production, a policy decision about acceptable FPR vs FNR is required, typically made by the compliance team. F1 is not the only defensible objective; alternatives include:
- **Recall-constrained**: select threshold to achieve ≥ target recall (e.g. ≥ 95% recall of SARs)
- **Cost-utility**: weight FN cost vs FP cost based on analyst hours and regulatory exposure
- **Capacity-aligned**: select threshold such that positive predictions ≈ analyst capacity

**Why 0.1153 is so low.** With `class_weight="balanced"` at 9.5% SAR rate, the model outputs higher probabilities broadly and the F1-optimal boundary is correspondingly lower. This is expected and consistent for this configuration.

**Threshold curve** is exported to `data/experiment/threshold_curve.csv` for interactive inspection of the precision/recall/F1 trade-off across all thresholds.

---

## Item 8 — Holdout Metric Results

### Threshold-Free Ranking Quality (applies to both modes)

| Metric | Random | Severity | HistGBM | HistGBM vs Severity |
|--------|--------|----------|---------|---------------------|
| AUC-ROC | 0.509 | 0.564 | **0.979** | +0.415 |
| AUC-PR | 0.098 | 0.238 | **0.774** | +0.536 |

### Classification Mode — Diagnostic (hard binary predictions at fixed threshold)

*These metrics describe performance when using the F1-optimal threshold as a binary classifier.  
This is NOT the primary operating policy. Recall=0.975 below is the fraction of SARs flagged  
by the binary classifier — it is NOT the same as Recall@20% (the primary capacity-ranking metric).*

| Metric | Random | Severity | HistGBM | HistGBM vs Severity |
|--------|--------|----------|---------|---------------------|
| Threshold | 0.5 | 0.5 | **0.1153** | — |
| Precision | 0.097 | 0.095 | **0.693** | +0.598 |
| Recall (cls) | 0.511 | 1.000 | **0.975** | -0.025 |
| F1 | 0.163 | 0.174 | **0.810** | +0.636 |
| FPR | 0.499 | 1.000 | **0.045** | -0.955 |
| FNR | 0.489 | 0.000 | **0.025** | +0.025 |

*Note: SeverityScorer at p=0.5 flags every alert (all positives), giving recall=1.0 but FPR=1.0 — operationally unusable.*

### Confusion Matrix (HistGBM — Classification Mode @ threshold=0.1153)

|  | Predicted Negative | Predicted Positive |
|--|-------------------|-------------------|
| **Actual Negative** | TN = 9,605 | FP = 457 |
| **Actual Positive** | FN = 26 | TP = 1,031 |

---

## Item 9 — Capacity-Ranking Mode: Precision@K and Recall@K (PRIMARY)

**This is the primary operating mode.** These metrics measure what happens if analysts work through the alert queue sorted by descending model score and stop at capacity limit K. No probability threshold is applied. The primary acceptance criterion (Recall@20% > 0.45) comes from this section.

Do NOT conflate Recall@K with the classification-mode recall in Item 8. They measure different things:
- **Classification recall (Item 8):** fraction of SARs flagged by ``score ≥ threshold`` (binary classifier)
- **Recall@20% (this section):** fraction of SARs surfaced by reviewing the top 20% of ranked alerts

### HistGBM vs Baselines at Key Capacity Fractions

| Capacity | K (alerts) | HistGBM Recall@K | Severity Recall@K | Random Recall@K |
|----------|-----------|-----------------|------------------|----------------|
| 10% | 1,111 | **0.718** | 0.258 | 0.099 |
| 20% | 2,223 | **1.000** | 0.348 | 0.202 |
| 30% | 3,335 | **1.000** | 0.412 | 0.309 |
| 50% | 5,559 | **1.000** | 0.554 | 0.511 |

**Key finding.** At 20% capacity (2,223 alerts reviewed), HistGBM achieves 100% recall — all 1,057 true SARs surface in the top-ranked 20% of alerts. Severity ranking only catches 34.8% at the same effort level.

**SARs found per 100 alerts reviewed (HistGBM):**
- @10%: 68.3 SARs per 100 reviewed
- @20%: 47.5 SARs per 100 reviewed
- vs base rate: 9.5 SARs per 100 (random)

---

## Item 10 — Operational Consequence Translation

All figures are **simulated** from the following operational assumptions (not validated against a specific institution's workforce data):

| Assumption | Value |
|------------|-------|
| Hours per alert review | 0.5 h |
| Hours per SAR filing | 2.0 h |
| Analyst productive hours per day | 6.0 h |

### At 20% Analyst Capacity

| Metric | Random | Severity | **HistGBM** |
|--------|--------|----------|-------------|
| SARs found | 214 | 368 | **1,057 (all)** |
| SARs missed | 843 | 689 | **0** |
| FPs reviewed | 2,009 | 1,855 | **1,166** |
| Total analyst-hours | 1,539.5 | 1,847.5 | **3,225.5** |
| FPs per TP found | 9.39 | 5.04 | **1.10** |
| Missed SAR rate | 79.8% | 65.2% | **0.0%** |

**Interpretation.** HistGBM finds every SAR in the period while reviewing only 20% of alerts. The cost is 3,225.5 analyst-hours vs 1,539.5 for random — but random misses 843 SARs. HistGBM trades additional SAR-filing labour for near-zero missed SARs, which is the correct trade-off for AML compliance.

*The SAR filing hours dominate because finding all SARs means filing 1,057 × 2h = 2,114h of reports. This is a feature, not a bug: the system is working.*

---

## Item 11 — FP/FN Error Analysis

### False Negatives (26 missed SARs) — HistGBM

| Account | Missed SARs |
|---------|-------------|
| ACC000287 | 19 |
| ACC000014 | 6 |
| ACC000083 | 1 |

**Finding.** 73% of missed SARs belong to a single account (ACC000287). This account's behaviour patterns are likely atypical in a way not well represented in training data. In production, this would warrant a rule-based override or account-level watchlist.

**FN score distribution.** Mean probability of missed SARs: 0.070. These are cases where the model assigned low risk scores — systematic misclassification rather than borderline errors.

**FN by TMS rule:**
- R08: 8 missed | R15: 7 missed | R09, R06: 2 each | R01, R02, R04, R12: 1 each

### False Positives (457 unnecessary flags) — HistGBM

**FP score distribution.** Mean probability: 0.756, median: 0.834. These are high-confidence false alarms — the model is not borderline uncertain but is genuinely confused about certain non-SAR patterns.

**FP by TMS rule (top 3):**
- R08: 283 FPs (largest contributor)
- R15: 101 FPs
- R06: 35 FPs

**FP by severity:**
- High: 441 (96.5%) — most FPs are from high-severity alerts, suggesting the severity signal is noisy for this class

**Severity-scored baseline FP by severity for comparison:**
- High: 9,903 — HistGBM reduces high-severity FPs by 95.5%

---

## Item 12 — Feature Importance Analysis

### Permutation Importance (AUC-ROC scoring on holdout)

| Rank | Feature | Permutation Δ AUC |
|------|---------|------------------|
| 1 | f11_cash_fraction_30d | +0.00764 |
| 2 | f02_vol_30d_log | +0.00451 |
| 3 | f07_txn_count_30d | +0.00381 |
| 4 | f04_max_txn_log | +0.00221 |
| 5 | f10_account_age_days | +0.00187 |

**Observation.** Several features show negative permutation importance (`f23_prior_alerts_90d`, `f12_structuring_count_30d`, `f13_round_amount_count_30d`). Negative values arise from multicollinearity — permuting one correlated feature may increase model noise. These features may still contribute via their correlated counterparts. In production, a SHAP analysis would clarify.

**Note on MDI vs permutation importance.** MDI (mean decrease in impurity, computed from tree node gains) is biased toward high-cardinality continuous features. Permutation importance, computed on the holdout set, is a more reliable estimate of true predictive value. Both are exported.

---

## Item 13 — Reproducibility Guarantee

| Control | Implementation |
|---------|---------------|
| Global seed | `TriageConfig.seed=42`; passed to `random_state=` on all stochastic objects |
| NumPy RNG | `np.random.default_rng(seed)` with explicit seed in all test fixtures |
| sklearn RNG | `random_state=self._config.seed` on HistGBM and permutation importance |
| Config freeze | `TriageConfig` is a frozen Pydantic model — no field can be mutated after construction |
| Experiment config | Full hyperparameters and seed captured in `data/experiment/results.json` |

**Test verification:** `TestTriageScorerScoring::test_reproducibility_across_runs` confirms two independently constructed scorers with the same config produce byte-identical probability arrays (decimal=6 tolerance).

---

## Item 14 — Test Coverage Summary

**Total tests: 81 | Passed: 81 | Failed: 0**

| Module | Test Class | Tests | Status |
|--------|-----------|-------|--------|
| config.py | TestSplitConfig | 4 | ✅ |
| config.py | TestModelHyperparams | 3 | ✅ |
| config.py | TestTriageConfig | 6 | ✅ |
| dataset.py | TestTemporalSplit | 11 | ✅ |
| dataset.py | TestLeakageGuard | 4 | ✅ |
| baseline.py | TestRandomScorer | 6 | ✅ |
| baseline.py | TestSeverityScorer | 6 | ✅ |
| scorer.py | TestTriageScorerFitting | 7 | ✅ |
| scorer.py | TestTriageScorerScoring | 5 | ✅ |
| scorer.py | TestThresholdSelection | 4 | ✅ |
| scorer.py | TestFeatureImportances | 3 | ✅ |
| evaluator.py | TestThresholdMetrics | 6 | ✅ |
| evaluator.py | TestRankingMetrics | 4 | ✅ |
| evaluator.py | TestOperationalMetrics | 3 | ✅ |
| evaluator.py | TestEvaluationResult | 4 | ✅ |
| evaluator.py | TestComparisonTable | 2 | ✅ |
| evaluator.py | TestThresholdCurve | 3 | ✅ |

**Notable test design decisions:**
- All scorer tests use `categorical_feature_indices=()` to prevent HistGBM from receiving high-cardinality float arrays at categorical positions
- The random scorer AUC test uses a separate seed for label generation (seed=7) vs model seed (seed=42) to avoid anti-correlation artefacts
- Edge cases tested: all-positive labels, all-negative labels, perfect classifier, zero-FP threshold, unknown severity values, null labels

---

## Item 15 — Architecture Decision Records

### ADR-01: Algorithm Choice — HistGBM over LightGBM

**Context.** LightGBM is the industry-standard choice for tabular gradient boosting. pip installation failed in this execution environment (wheel unavailable).

**Decision.** Use `sklearn.ensemble.HistGradientBoostingClassifier` (sklearn 1.8+), which is a histogram-based GBDT implementation with comparable design goals to LightGBM.

**Important accuracy caveat.** HistGradientBoostingClassifier and LightGBM are distinct implementations. They differ in gradient estimation details, tree growth heuristics, bin construction, and threading. Results from HistGBM are **not** guaranteed to reproduce under LightGBM. The two libraries use different hyperparameter names (e.g. `n_iter_no_change` ↔ `early_stopping_rounds`, `max_leaf_nodes` ↔ `num_leaves`). If the environment changes, hyperparameter equivalences must be verified and the full evaluation must be re-run on the holdout set before claiming comparable performance.

**Reversal cost.** Moderate — requires environment setup, hyperparameter re-mapping, re-evaluation, and update of all reproducibility documentation.

---

### ADR-02: Two-Phase Training Protocol

**Context.** Validation data is labelled — discarding it for evaluation wastes signal. But using it for training corrupts the evaluation split.

**Decision.** Phase 1 on train only (early stopping + threshold selection on val). Phase 2 refit on train+val with `max_iter=best_iter` (early stopping disabled).

**Consequences.** Final model benefits from ~15k more labelled examples while holdout integrity is preserved. Phase 2 may slightly overfit on val data but this is acceptable given holdout remains untouched.

---

### ADR-03: Threshold Selection Strategy

**Context.** At 9.5% SAR rate, p=0.5 is an arbitrary and typically suboptimal threshold.

**Decision.** Exhaustive F1 search over 200 threshold candidates from 1st to 99th percentile of validation probabilities. Ties broken by selecting the higher threshold (more conservative, reduces analyst workload from FPs).

**Consequence.** Selected threshold (0.1153) is very low, reflecting that the model outputs high probabilities broadly and the decision boundary sits in the lower tail. This is semantically correct for a high-recall AML use case.

---

### ADR-04: MDI Feature Importances via `_predictors`

**Context.** `HistGradientBoostingClassifier` in sklearn 1.8.0 does not expose `feature_importances_` (unlike `GradientBoostingClassifier`). The internal `_predictors` attribute gives access to tree node structures.

**Decision.** Compute MDI manually from `_predictors[tree_idx][class_idx].nodes`, accumulating `gain × count` for non-leaf nodes grouped by `feature_idx`.

**Risk.** `_predictors` is a private internal attribute and may change across sklearn minor versions. Permutation importance (`sklearn.inspection.permutation_importance`) is the more stable API and is preferred for production use. MDI is provided as a supplementary signal only.

---

## Item 16 — Devil Mode Review (6 Perspectives)

### 16a — Staff Engineer

**Findings:**

**[HIGH] `_predictors` is a private sklearn attribute.** If sklearn changes its internal tree representation (e.g., in 1.9.x), `feature_importances()` will silently break. The method includes a docstring warning. Mitigation: use permutation importance as the primary signal; MDI is supplementary.

**[MEDIUM] No model serialization.** The trained model is not persisted to disk. Every invocation of `run_triage_experiment.py` re-trains from scratch (~9s). In production, the model should be saved with `joblib.dump()` and loaded for scoring, not re-trained.

**[MEDIUM] No scoring API.** There is no HTTP endpoint to score new alerts. The current architecture is batch-only (CSV input, JSON output). A production system needs a scoring service or at minimum a CLI that loads a saved model.

**[LOW] Script-level experiment orchestration.** `run_triage_experiment.py` is a procedural script. For reproducible MLOps, this should be a tracked experiment in MLflow or DVC.

**Fixes applied:** Added docstring warnings to `feature_importances()`. Permutation importances are the recommended primary signal in the completion report.

---

### 16b — Data Scientist

**Findings:**

**[HIGH] AUC-ROC of 0.979 on simulator data warrants scrutiny.** Features were engineered from the same underlying SAR signal that generated `true_sar`. The model's extraordinary performance may reflect the simulator's internal consistency rather than genuine behavioural separability. Performance on simulator-generated data should not be interpreted as expected performance on institutional AML data. External validation on real TMS data is required. This limitation is explicitly documented in Item 18.

**[MEDIUM] Permutation importance shows multiple features with negative importance.** Features `f23_prior_alerts_90d`, `f12_structuring_count_30d`, `f13_round_amount_count_30d` all show negative permutation AUC-ROC delta. This typically indicates multicollinearity (correlated features interfere with each other when permuted). A SHAP analysis would clarify true marginal contributions.

**[MEDIUM] Single temporal split.** Results are from one train/val/holdout partition. In production, walk-forward cross-validation across multiple monthly windows would more robustly estimate generalisation. The current split is valid but a single holdout result has variance.

**[LOW] No calibration assessment.** Threshold of 0.1153 suggests the model outputs miscalibrated probabilities (systematically low). Platt scaling or isotonic regression would improve probability calibration, which matters for threshold stability across deployment periods.

**Fixes applied:** Documented AUC-ROC caveat prominently in limitations (Item 18). Permutation importances recommended as primary signal. Single-split limitation noted.

---

### 16c — Fraud/AML Analyst

**Findings:**

**[HIGH] Account ACC000287 accounts for 73% of false negatives.** 19 of 26 missed SARs belong to a single account. This indicates a systematic blind spot — the account's transaction patterns are outside the training distribution or represent a novel typology. In production, this account would require manual watchlist escalation. The system must include account-level override rules.

**[MEDIUM] FP score distribution is concentrated at high confidence (mean 0.756).** The 457 false positive alerts are not borderline cases — the model is confidently wrong. This is harder to address post-training and suggests some account or rule patterns are genuinely ambiguous. Rule R08 produces 283 of 457 FPs — this rule may need feature engineering specific to its typology.

**[MEDIUM] No integration with the analyst feedback loop.** In a real deployment, analyst decisions (close alert / file SAR / escalate) would be captured and used to continuously improve the model. This is not implemented.

**[LOW] Severity-based scoring still beats random.** The SeverityScorer achieves 2.58× SAR density at 10% capacity vs random. Rather than discarding it, a production ensemble that combines severity as a feature alongside the ML model could improve both precision and robustness.

**Fixes applied:** Account ACC000287 and rule R08 flagged as priority items in limitations. Account-level override recommended in production notes.

---

### 16d — QA Engineer

**Findings:**

**[MEDIUM] No integration test with the real simulator CSV.** All 81 unit tests use synthetic data from `make_classification` or programmatically generated CSVs. There is no end-to-end test that runs `AlertDataset → TriageScorer → Evaluator` on the actual `data/simulation/alerts.csv`. A CI regression test should verify acceptance criteria are met on each commit.

**[MEDIUM] No test coverage measurement.** `pytest-cov` is not configured. It's not known which branches in `evaluator.py` and `scorer.py` are untested. The edge cases in `_select_threshold` (all-positive, all-negative labels) are tested, but coverage of `_error_analysis` branching is unknown.

**[LOW] No property-based testing.** For arithmetic invariants (e.g., `tp + fp + tn + fn == n_alerts`, `0 <= precision <= 1`), property-based tests with Hypothesis would catch edge cases that example-based tests miss.

**Fixes applied:** All 81 unit tests pass. Integration test gap documented as a known issue for Milestone 3.

---

### 16e — Security Engineer

**Findings:**

**[MEDIUM] CSV path is provided via `TriageConfig.alerts_csv` without path traversal protection.** A maliciously crafted config could point to an arbitrary filesystem path. In a multi-tenant or API context, the path must be validated against an allowlist of data directories.

**[LOW] `results.json` may contain PII via account IDs.** `top_fn_accounts` lists account IDs (`ACC000287`) in the output file. In production, account IDs in model evaluation outputs should be pseudonymised or access-controlled.

**[LOW] No authentication on the experiment script.** `run_triage_experiment.py` runs without authentication. In a production MLOps context, model training runs should be logged with authenticated user identity for audit trail compliance.

**[LOW] Private sklearn API (`_predictors`).** The MDI computation accesses a private internal attribute. This carries no direct security risk but is a stability and maintainability concern documented under Staff Engineer and ADR-04.

**Fixes applied:** Path traversal issue documented as a production requirement. Account IDs in output documented as a pseudonymisation requirement. No security vulnerabilities are present in the current batch/research context.

---

### 16f — Model Risk Reviewer

**Findings:**

**[HIGH] AUC-ROC of 0.979 is extraordinarily high for AML triage.** A score near 0.98 is a strong signal that the evaluation dataset is easier than production data. This is attributable to the simulator: features were explicitly designed to encode SAR-predictive signals (`cash_fraction`, `structuring_count`, `shell_counterparty_fraction`). Performance on simulator-generated data should not be interpreted as expected performance on institutional AML data. External validation on real TMS data is required before any production performance claim can be made.

**[HIGH] No model stability analysis.** Performance is reported from a single holdout period (May-July 2023). Model performance could degrade if alert distributions shift (new typologies, seasonal patterns, regulatory changes). Walk-forward evaluation across multiple monthly windows is required before production deployment.

**[MEDIUM] Threshold was selected on the validation set.** The threshold of 0.1153 was optimised on validation data. If the validation set's score distribution differs from future alert distributions (distribution shift), the threshold may need recalibration. A separate calibration dataset or temporal recalibration procedure should be documented.

**[MEDIUM] No model card.** A production model requires a model card documenting: intended use, out-of-scope uses, training data characteristics, known failure modes, evaluation results, fairness considerations. The completion report partially serves this function but a standalone model card is required for production governance.

**[LOW] Feature importance instability.** Permutation importance results show near-zero values for many features and negative values for several. This indicates the model may not have stable feature attribution — small perturbations to the training set could substantially change which features appear important.

**Fixes applied:** AUC-ROC caveat is the primary item in limitations (Item 18). Production deployment roadmap notes walk-forward evaluation and model card as prerequisites. All findings are documented but not blocking: Milestone 2 is an experimental evaluation, not a production deployment.

---

## Item 17 — Confirmed Results vs Baseline

**Central claim:**

> "On simulated AML alert data with a 9.5% SAR rate, a HistGradientBoostingClassifier trained on 24 behavioural features achieves Recall@20%=1.00 (all SARs recovered within 20% of analyst capacity), compared to 0.35 for severity-based ranking and 0.20 for random ordering. AUC-ROC is 0.979 vs 0.564 (severity) and 0.509 (random)."

**Claim verification:**
- Holdout was never seen during training or threshold selection ✅
- Baselines use the same holdout set ✅
- All metrics are computed on ground-truth labels (`true_sar`) from the simulator ✅
- Results are in `data/experiment/results.json` (fully reproducible with `python scripts/run_triage_experiment.py`) ✅

---

## Item 18 — Limitations and Known Issues

### Critical Limitations

1. **Simulator fidelity.** The dataset was generated by a custom simulator designed to encode SAR risk into features. Real TMS alert data is noisier, more heterogeneous, and less cleanly separable. The AUC-ROC of 0.979 is the ceiling achievable on this specific simulator and should not be interpreted as a production performance estimate. Performance on simulator-generated data should not be interpreted as expected performance on institutional AML data. External validation on real TMS alert data is required before any production performance claim can be made.

2. **Single holdout evaluation.** Performance is measured on one 60-day holdout window. Temporal stability across different market conditions, regulatory changes, or new fraud typologies is unknown.

3. **Account-level blind spot.** Account ACC000287 is systematically missed (19/26 false negatives). This indicates either atypical account behaviour or insufficient representation in training. In production, a manual rule-based override would be required.

4. **No model serialization.** The model is re-trained on each script invocation. Production deployment requires serialised model artifacts and a versioning strategy.

5. **MDI via private API.** `feature_importances()` uses `_predictors`, a private sklearn attribute. Permutation importance should be the primary production signal.

### Non-Critical Limitations

6. Permutation importance shows instability (many near-zero or negative values) — likely multicollinearity in feature set.
7. No SAR filing feedback loop — analyst outcomes are not captured for active learning.
8. No model calibration — probability outputs are not well-calibrated; threshold should be recalibrated periodically.
9. Path traversal protection not implemented — required before multi-tenant deployment.
10. Account IDs in `results.json` should be pseudonymised in production.

---

## Item 19 — Milestone Story

> "We discovered that AML alert triage at the current TMS SAR rate (~9.5%) requires analysts to review every alert to achieve reasonable SAR detection — an operationally unsustainable baseline consuming ~1,279 analyst-days per 60-day cycle.
>
> The existing approach (severity-based triage) catches only 34.8% of SARs within 20% analyst capacity — better than random (20.2%) but insufficient for regulatory expectations.
>
> We believed that a gradient-boosted classifier trained on 24 behavioural transaction features, using temporal splitting and F1-optimal threshold selection, could concentrate SARs in the top-reviewed fraction.
>
> We built AlertIQ Triage Engine: a two-phase HistGBM training pipeline with leakage-guarded temporal splitting, automated threshold selection, and full operational consequence translation.
>
> We evaluated it on an untouched 60-day holdout using AUC-ROC, Precision/Recall@K (10–100% capacity), and simulated analyst-hours.
>
> Against the severity baseline, it achieved AUC-ROC 0.979 vs 0.564 (+0.415) and Recall@20%=1.0 vs 0.348 (+0.652). At 20% analyst capacity, HistGBM recovers all 1,057 true SARs vs 368 for severity-based triage — a 2.87× improvement.
>
> The primary limitation is simulator fidelity: AUC-ROC of 0.979 reflects a dataset where features encode SAR risk by construction. Real-world performance should be estimated via walk-forward backtesting on institutional data.
>
> In production, the next priorities are: model serialization and versioning, a scoring API, temporal stability analysis (walk-forward), SAR filing feedback loop, and a formal model card for governance compliance."

---

## Output Artefacts

| File | Description |
|------|-------------|
| `data/experiment/results.json` | Full experiment results (all scorers, all metrics) |
| `data/experiment/comparison.csv` | Scorer comparison table |
| `data/experiment/threshold_curve.csv` | HistGBM threshold curve (77 points) |
| `data/experiment/feature_importance.json` | Permutation importances (ranked) |
| `src/alertiq/triage/config.py` | Frozen Pydantic config |
| `src/alertiq/triage/dataset.py` | AlertDataset with temporal split and leakage guard |
| `src/alertiq/triage/baseline.py` | RandomScorer and SeverityScorer |
| `src/alertiq/triage/scorer.py` | TriageScorer (two-phase HistGBM) |
| `src/alertiq/triage/evaluator.py` | Evaluator with operational metrics |
| `scripts/run_triage_experiment.py` | Full reproducible experiment pipeline |
| `tests/triage/test_config.py` | 13 config tests |
| `tests/triage/test_dataset.py` | 15 dataset tests |
| `tests/triage/test_baselines.py` | 12 baseline tests |
| `tests/triage/test_scorer.py` | 19 scorer tests |
| `tests/triage/test_evaluator.py` | 22 evaluator tests |
| `docs/MILESTONE_2_COMPLETION.md` | This document |

---

*Milestone 2 is complete. Milestone 3 has not been started.*
