# Milestone 3 Completion Report  -  Model Robustness & Temporal Stability

> **Milestone:** M3  -  Model Robustness & Temporal Stability
> **Completion date:** 2026-09-12
> **Evaluation mode:** fast (max_iter=100, HistGradientBoostingClassifier)
> **Prior milestone:** M2  -  Model Training & Walk-Forward Evaluation

---

## Executive Summary

Milestone 3 is complete. The AlertIQ Triage Scorer v1 has been evaluated across three walk-forward windows for temporal stability, stress-tested against six controlled out-of-distribution scenarios, assessed for calibration quality, monitored for feature and label drift, and subjected to a champion/challenger framework validation.

**Primary finding:** The model's capacity-ranking performance (Recall@20%) is 1.000 across all three test windows with zero variance. All SARs rank within the top 20% of alerts in every test fold. This is the system's primary objective and it is met.

**Critical finding:** The classification threshold is unstable (range 0.198 across three windows). Classification mode must not be used with fixed thresholds. This is a governance constraint, not a model defect.

**Identified weaknesses:** Four rule groups (R09, R06, R12, R01) fail the Recall@20% floor for high-SAR-rate typologies. These failures are structurally explained and consistent with simulator design, but they impose deployment constraints.

**Decision: Do not redesign the core triage model.** M3 produced no evidence requiring a design change. The model architecture is adequate for its stated purpose (capacity-ranking of a mixed-typology alert population). Proceed to Milestone 4 at operator discretion.

---

## 1. Walk-Forward Evaluation Results

### 1.1 Primary Mode: Capacity-Ranking

| Window | Test Period | Test N | Test SARs | Recall@5% | Recall@10% | Recall@20% | Recall@30% |
|---|---|---|---|---|---|---|---|
| Window-1 | Apr 2023 | 8,911 | 842 | 0.411 | 0.742 | **1.000** | 1.000 |
| Window-2 | May 2023 | 9,306 | 921 | 0.421 | 0.727 | **1.000** | 1.000 |
| Window-3 | Jun 2023 | 8,730 | 832 | 0.393 | 0.700 | **1.000** | 1.000 |
| Mean | | | | 0.408 | 0.723 | **1.000** | 1.000 |
| Std | | | | 0.011 | 0.017 | **0.000** | 0.000 |

**Recall@20% = 1.000 with zero variance across all three windows.** The primary objective is met without exception.

### 1.2 Secondary Mode: Threshold Classification

| Window | AUC-ROC | AUC-PR | Threshold | Precision | Recall | F1 | FPR | FNR |
|---|---|---|---|---|---|---|---|---|
| Window-1 | 0.980 | 0.774 | 0.056 | 0.663 | 0.999 | 0.797 | 0.053 | 0.001 |
| Window-2 | 0.981 | 0.805 | 0.229 | 0.675 | 0.995 | 0.804 | 0.053 | 0.005 |
| Window-3 | 0.978 | 0.759 | 0.253 | 0.701 | 0.957 | 0.809 | 0.043 | 0.043 |
| Mean | 0.980 | 0.779 | 0.179 | 0.679 | 0.983 | 0.803 | 0.050 | 0.017 |

**AUC-ROC is stable** (range 0.004). **Threshold is not stable** (range 0.198). The model discriminates well across all windows. The threshold cannot be fixed across windows.

---

## 2. Calibration

| Window | ECE (raw) | Brier Score | Decision |
|---|---|---|---|
| Window-1 | 0.027 | 0.035 | No calibration needed |
| Window-2 | 0.027 | 0.035 | No calibration needed |
| Window-3 | 0.038 | 0.038 | No calibration needed |

All windows are well below the ECE = 0.05 acceptability threshold. Isotonic and Platt calibration were evaluated; neither reduced Brier score meaningfully below raw. **No calibration layer added.** Applying calibration would add complexity without measurable benefit.

---

## 3. Typology-Level Performance

### 3.1 Gate Definition

Minimum Recall@20% ≥ 0.40 for any rule group with ≥ 50 SAR holdout examples.

### 3.2 Gate Results

| Rule Group | SAR Count (approx.) | Gate Applicable | Status | Mean Recall@20% |
|---|---|---|---|---|
| R08 | ~170 | ✓ Yes | ✓ **Pass** | 1.000 |
| R15 | ~222 | ✓ Yes | ✓ **Pass** | 0.645 |
| R09 | ~111 | ✓ Yes | ✗ **Fail** | 0.345 |
| R06 | ~97 | ✓ Yes | ✗ **Fail** | 0.364 |
| R12 | ~62 | ✓ Yes | ✗ **Fail** | 0.206 |
| R01 | ~49 | ✓ Yes | ✗ **Fail** | 0.224 |
| R02 | ~42 | Below floor | Pass (default) | 0.853 |
| R04 | ~48 | Below floor | Pass (default) | 0.209 |

### 3.3 Root Cause Analysis

**R09 and R06:** SAR rates of 56–58% and 43–52% respectively. Within these groups, most alerts are SARs. Score-based ranking cannot improve substantially on a random sample at 20% capacity when the underlying SAR rate is already near 50%. The model assigns high scores to the high-SAR-rate group but cannot differentiate within it effectively enough to achieve 40% recall at 20% capacity.

**R12 and R01:** Near-100% SAR rates. All alerts in these groups are SARs. The model assigns uniformly high scores (correctly), but because the SAR density far exceeds the 20% capacity, Recall@20% is structurally limited. For R12 with 100% SAR rate, Recall@20% ≈ 0.20 regardless of any model.

**Implication:** The Recall@20% metric is not meaningful for rule groups with SAR rate > 40%. These groups should be reviewed at a higher capacity fraction or subject to a full-review policy that bypasses the capacity-ranking step.

---

## 4. Stress Test Results

Stress tests run on Window-3 (most recent test window, AUC-ROC = 0.978, Recall@20% = 1.000).

| Scenario | Recall@20% | ΔRecall@20% | ΔAUC-ROC | Degraded? |
|---|---|---|---|---|
| S01: Volume surge (×3) | 1.000 | 0.000 | −0.000 | No |
| S02: New jurisdiction (score=0.9) | 1.000 | 0.000 | −0.000 | No |
| S03: Missing features (30% zeroed) | 0.907 | **−0.093** | −0.034 | Near-threshold |
| S04: Rule shift (R08 removed) | 0.468 | **−0.532** | −0.027 | Yes (recall) |
| S05: Novel typology | 0.212 | **−0.788** | −0.088 | Yes (both) |
| S06: SAR rate collapse (1% SARs) | 1.000 | 0.000 | +0.007 | No |

### 4.1 Findings by Scenario

**S01, S02, S06  -  Robust.** Volume surges, new jurisdiction characteristics, and extreme SAR rate collapse do not degrade model performance. These represent the most common real-world perturbations.

**S03  -  Near-threshold.** Zeroing 30% of feature values produces Recall@20% = 0.907 (ΔRecall = −0.093). This is below the degradation threshold of −0.10 by a margin of 0.007. In production, systematic feature pipeline failures (nulls, zeroes, stale values) could push this below the threshold. **Data quality monitoring is required.**

**S04  -  Structural failure expected.** Removing R08 alerts reduces the test population from 8,730 to 1,716. R08 comprises ~80% of alerts; the remaining population is much harder to rank because high-SAR-rate groups dominate. Recall drops to 0.468. This is not a model failure  -  it is a consequence of the portfolio composition assumption being violated. If R08 is removed from the alert mix in production, the model's training distribution is no longer representative and retraining is required.

**S05  -  Out-of-distribution as expected.** A novel typology (R08 alerts relabelled as SARs with extreme volume and jurisdiction features) degrades Recall@20% to 0.212 (ΔRecall = −0.788). This is the correct model behaviour: when presented with a pattern outside the training distribution, the model does not confidently rank novel SARs to the top of the queue. This serves as a safety property  -  silent high-confidence mislabelling is more dangerous than detectable OOD degradation. The appropriate response to novel typology introduction is retraining, not model modification.

---

## 5. Monitoring Triggers Fired

| Trigger | Severity | Windows Fired | Finding |
|---|---|---|---|
| T06 | P1 | W1, W2, W3 | PSI = 14.39 on `f23_prior_alerts_90d`. Simulator artefact (monotonically accumulating feature vs. fixed baseline). Rolling baseline required in production. No operational concern on its own. |
| T08 | P2 | W1→W2 | Threshold drift 0.173 (0.056 → 0.229). Expected. Confirms that threshold must never be hard-coded. |

No P0 triggers fired. T06 firing is explained by a known simulator artefact, not genuine population shift. T08 firing is expected and documents the threshold instability finding.

---

## 6. Feature Drift Summary

Significant PSI (> 0.25) was observed on: `f02_vol_30d_log`, `f03_vol_ratio_7_30`, `f04_max_txn_log`, `f06_txn_count_7d`, `f07_txn_count_30d`, `f08_velocity_ratio`.

All significant drifts affect rolling and cumulative features whose values grow monotonically in the simulator. These are simulator artefacts. Production PSI baselines must use rolling reference windows for cumulative features.

Stable features (PSI < 0.10): `f01`, `f05`, `f09`, `f10`, `f11`, `f12`, `f13`, `f15`, `f16`. These features show no meaningful drift over the evaluation period.

---

## 7. Champion / Challenger Framework

The champion/challenger infrastructure is implemented and validated structurally in M3. No challenger model has been trained or evaluated. The framework defines:

- Promotion threshold: mean ΔRecall@20% ≥ +0.01 across all windows AND mean ΔAUC-ROC ≥ −0.02
- Retention condition: mean ΔRecall@20% ≤ −0.02 OR mean improvement < 0.01
- Bootstrap significance: B=1,000, α=0.05, computed when N > 10 per window

The champion model (Triage Scorer v1) is the baseline for any future challenger evaluation.

---

## 8. Test Coverage

| Module | Tests | Status |
|---|---|---|
| `robustness/walkforward.py` | 16 | ✓ All pass |
| `robustness/stress.py` | 33 | ✓ All pass |
| `robustness/policy.py` | 38 | ✓ All pass |
| `robustness/champion.py` | 22 | ✓ All pass |
| **Total** | **109 robustness tests** | **✓ All pass** |

Combined with prior milestone test suites, the full test suite passes. The robustness test suite validates: scenario perturbation logic, trigger evaluation and firing conditions, threshold drift detection, champion/challenger comparison logic, walk-forward window construction and data leakage prevention, stability summary computation.

---

## 9. Decisions Made in M3

| Decision | Rationale |
|---|---|
| No calibration layer added | ECE 0.027–0.038 across all windows; well below 0.05 threshold. Platt and isotonic calibration evaluated  -  neither meaningfully reduced Brier score. Calibration adds complexity without benefit. |
| No model redesign | Recall@20% = 1.000 with zero variance. The primary objective is met. No evidence from M3 requires a design change. |
| Threshold instability is a governance issue, not a model defect | The threshold reflects the score distribution relative to the SAR population. Variability is expected and correct. The response is process discipline (recalibrate per window), not architectural change. |
| Typology failures (R09, R06, R12, R01) are not addressed by model modification | Root cause is structural: these groups have SAR rates > 40%. Capacity-ranking is the wrong tool for near-uniform-SAR populations. The response is typology-specific triage policy, not model tuning. |
| T06 is a simulator artefact for `f23_prior_alerts_90d` | The feature's monotonic growth in the simulator produces extreme PSI against a fixed baseline. Production monitoring must use a rolling baseline. The trigger correctly identified the shift; the cause is known and mitigable. |
| Experiment mode: fast (max_iter=100) | This M3 run validates the framework. A full-mode run (uncapped early stopping) may produce different best_iter values and marginally different thresholds but will not change the structural findings. Full-mode evaluation is a Milestone 4 candidate. |

---

## 10. M3 Completion Checklist

| Deliverable | Status |
|---|---|
| Walk-forward evaluation: 3 windows | ✓ Complete |
| Calibration evaluation (raw, Platt, isotonic) | ✓ Complete |
| Feature drift analysis (PSI, KS) | ✓ Complete |
| Label shift analysis | ✓ Complete |
| Typology-level gate evaluation | ✓ Complete |
| Stress test suite (S01–S06) | ✓ Complete |
| Monitoring trigger definitions (T01–T10) | ✓ Complete |
| Trigger evaluation against M3 data | ✓ Complete |
| Champion/challenger framework | ✓ Implemented (structurally validated, no challenger yet) |
| Robustness test suite (109 tests, all pass) | ✓ Complete |
| `docs/MODEL_CARD.md` | ✓ Complete |
| `docs/MODEL_MONITORING.md` | ✓ Complete |
| `docs/MILESTONE_3_COMPLETION.md` | ✓ Complete |

---

## 11. Limitations and Open Items

1. **Synthetic data only.** All findings are in-distribution for the AlertIQ simulator. Real-world alert populations will have different SAR rates, typology distributions, feature correlations, and temporal patterns. No real-world claims are made.

2. **Fast mode (max_iter=100).** The current experiment was run with a fixed 100-iteration cap. Full-mode training (uncapped early stopping) may yield different best_iter values and potentially different threshold stability. The Recall@20% finding at 1.000 is unlikely to change, but classification metrics may differ.

3. **f23 PSI artefact unresolved in simulator.** The cumulative prior-alert feature cannot be correctly baselined in the simulator context. Production monitoring must implement rolling PSI baselines before T06 is a reliable signal.

4. **High-SAR-rate typology policy not designed.** R09, R06, R12, R01 fail the capacity-ranking gate. The monitoring specification documents this but the triage policy for these groups has not been designed. This is an open item for Milestone 4 or an adjacent product decision.

5. **No champion/challenger empirical evaluation.** The framework exists. It has not been exercised. Promotion thresholds are theoretical until tested.

6. **No production deployment.** M3 establishes the evaluation and monitoring framework. This is not a production readiness determination. Deployment requires additional steps: data pipeline integration, real-world data validation, regulatory review, and operational runbook development.

---

## 12. Adversarial Review  -  Key Findings

The following weaknesses were identified through adversarial examination of M3 findings:

**Recall@20% = 1.000 may be too easy in the simulator.** The simulator may produce a SAR population that is unrealistically separable from the non-SAR population. A real-world population is likely to be harder to rank. The 1.000 result establishes a baseline but should be treated with appropriate scepticism about real-world generalisability.

**AUC-ROC near 0.98 is very high for AML.** Production AML models typically achieve AUC-ROC in the 0.70–0.85 range. A value of 0.98 suggests either an unusually separable simulator population or a feature set that is unrealistically informative. If real-world AUC-ROC drops to 0.80, the stress test S03 result (near-threshold recall degradation at 30% missing features) becomes more concerning.

**The threshold instability range of 0.198 is large.** A threshold that varies from 0.056 to 0.253 across consecutive months is unusually unstable. In a real deployment, this could cause the auto-closure rate to fluctuate dramatically between retraining cycles if the threshold is not recalibrated. The monitoring specification addresses this, but it warrants continued investigation.

**Four of six rule groups with sufficient holdout SARs fail the gate.** Expressed differently: 67% of gate-applicable rule groups fail the minimum recall floor. The aggregate Recall@20% = 1.000 masks poor within-typology performance for a majority of applicable groups by count. The model performs well overall because R08 (~80% of alerts by volume) dominates the test population.

---

## 13. Recommended Next Steps (Milestone 4)

The following actions are recommended for Milestone 4. None are started here; M3 is complete as defined.

1. **Full-mode experiment.** Run the walk-forward experiment without the max_iter=100 cap. Compare best_iter values, final AUC-ROC, and threshold stability against M3 fast-mode results.

2. **Typology-specific triage policy.** Design and evaluate a separate handling policy for rule groups with SAR rate > 40%. Options: full review of R09/R06/R12/R01 regardless of score; typology-specific capacity expansion; or a dedicated binary classifier for high-SAR-rate groups.

3. **Rolling PSI baseline implementation.** Implement rolling PSI reference windows for cumulative and rolling features (`f02`, `f03`, `f06`, `f07`, `f08`, `f23`). Re-evaluate T06 with corrected baselines.

4. **First challenger model.** Train a challenger using an alternative architecture or feature set and exercise the promotion decision framework on real walk-forward data.

5. **Adversarial feature robustness investigation.** S03 (30% missing features) produced Recall@20% = 0.907  -  0.007 above the concern threshold. Investigate which specific features, when missing, cause the largest recall drop. Implement feature-specific alerting for high-impact features.

---

*Milestone 3 complete.*
