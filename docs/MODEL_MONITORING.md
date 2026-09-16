# Model Monitoring Specification  -  AlertIQ AML Alert Triage Scorer

> **Version:** Milestone 3 (M3)
> **Effective from:** 2026-09-12
> **Model:** AlertIQ Triage Scorer v1  -  HistGradientBoostingClassifier
> **Operating mode:** Capacity-ranking (primary); threshold-classification (secondary)

---

## 1. Purpose

This document specifies the monitoring obligations, trigger definitions, escalation procedures, and recalibration policies required to operate the AlertIQ Triage Scorer in a supervised deployment. It is not a deployment authorisation; it defines the monitoring regime that must be active during any deployment.

The central risk this regime guards against is **silent model degradation**  -  a state in which the model continues to produce scores without alerting operators that those scores are no longer ranking SARs effectively.

---

## 2. Monitoring Cadence

| Monitoring activity | Frequency | Responsible |
|---|---|---|
| Core performance metrics (Recall@20%, AUC-ROC) | Every retraining cycle (minimum monthly) | Model Risk |
| Feature drift (PSI) | Every retraining cycle | ML Engineering |
| Classification threshold drift (T08) | Every retraining cycle | ML Engineering |
| SAR rate baseline comparison (T09) | Every retraining cycle | Model Risk |
| Calibration check (ECE) | Every retraining cycle | ML Engineering |
| Typology-level gate check | Quarterly or post-retraining | Model Risk |
| Champion/challenger evaluation (if challenger exists) | At promotion candidate review | Model Risk |
| Full monitoring report | Quarterly | Model Risk |

**Minimum monitoring frequency is monthly** (aligned with retraining cadence). Shorter intervals apply whenever a P1 trigger is open.

---

## 3. Monitoring Trigger Definitions

All ten triggers are evaluated on the validation set of each retraining window. Triggers fire when the stated condition is met.

### 3.1 P0 Triggers  -  Halt Deployment

P0 triggers indicate the model has failed its minimum performance requirement. **Deployment must halt immediately upon P0 firing. Scores must not be used to prioritise analyst review until the trigger is cleared.**

| Trigger | Metric | Condition | Threshold | Action |
|---|---|---|---|---|
| T01 | `recall_at_20pct` | < | 0.40 | Halt deployment. Model cannot meet minimum recall requirement. |
| T02 | `auc_roc` | < | 0.65 | Halt deployment. Ranking ability is near-random. |

**P0 resolution procedure:**
1. Immediately suspend model scoring.
2. Revert to manual queue ordering (chronological or rule-priority-based fallback).
3. Notify model risk committee within 24 hours.
4. Diagnose: feature pipeline failure, label shift, retraining bug, or data corruption.
5. Retrain from updated data with corrected pipeline.
6. Do not re-deploy until trigger condition clears on validation data.

### 3.2 P1 Triggers  -  Escalate to Model Risk

P1 triggers indicate performance is degrading or the score distribution is unstable. **The model may continue operating while investigation is in progress, but investigation must begin within 5 business days.**

| Trigger | Metric | Condition | Threshold | Action |
|---|---|---|---|---|
| T03 | `recall_at_20pct` | < | 0.50 | Escalate to model risk team. Review feature pipeline and label quality. |
| T04 | `auc_roc` | < | 0.70 | Escalate to model risk team. Review score distribution and model staleness. |
| T05 | `ece` | > | 0.05 | Escalate. Apply Platt or isotonic calibration on recent validation data. |
| T06 | `max_feature_psi` | > | 0.25 | Escalate. Identify shifted features; assess whether retraining is required. |

**T06  -  Feature PSI note:** During the M3 evaluation, T06 fired on all three windows because `f23_prior_alerts_90d` (prior alerts in the last 90 days) has a PSI of 14.39. This is a simulator artefact: the feature accumulates monotonically across the training window, generating an extreme PSI value when compared against a fixed historical baseline. In production this feature should be measured against a **rolling 90-day baseline** rather than a fixed historical window. Once correctly baselined, T06 firing on `f23_prior_alerts_90d` alone should not trigger escalation. T06 remains a valid signal for other features.

### 3.3 P2 Triggers  -  Investigate

P2 triggers are early-warning signals. They do not require immediate escalation but must be logged, reviewed in the next monitoring report, and escalated if they persist across two consecutive windows.

| Trigger | Metric | Condition | Reference | Threshold | Action |
|---|---|---|---|---|---|
| T07 | `recall_at_20pct` | `\|Δ\|` > | `prev_recall_at_20pct` | 0.08 | Investigate. Monitor for continued trend; consider partial retraining. |
| T08 | `cls_threshold` | `\|Δ\|` > | `prev_cls_threshold` | 0.10 | Investigate. Threshold instability may indicate score distribution shift. |
| T09 | `test_sar_rate` | `\|Δ\|` > | `baseline_sar_rate` | 0.03 | Investigate. Alert label shift may indicate process or regulatory change. |
| T10 | `auc_roc` | `\|Δ\|` > | `prev_auc_roc` | 0.05 | Investigate. Monitor score quality; consider feature monitoring expansion. |

**T08  -  Threshold instability note:** The classification threshold varied from 0.056 (Window-1) to 0.253 (Window-3) across the M3 evaluation  -  a range of 0.198. T08 fired between Window-1 and Window-2 (drift = 0.173). This is not a model defect. It is an expected consequence of using a val-set-derived threshold in a population that changes month to month. The governance response is to **never hard-code a classification threshold**. The threshold must always be set from the current validation period. If T08 fires persistently (>3 consecutive windows), investigate whether score scale is shifting.

---

## 4. Trigger Status: M3 Baseline (September 2026)

| Trigger | Status in M3 | Windows Fired | Notes |
|---|---|---|---|
| T01 | ✓ Not fired |  -  | Recall@20% = 1.000 across all windows |
| T02 | ✓ Not fired |  -  | AUC-ROC 0.978–0.981 across all windows |
| T03 | ✓ Not fired |  -  | |
| T04 | ✓ Not fired |  -  | |
| T05 | ✓ Not fired |  -  | ECE 0.027–0.038; all below 0.05 |
| **T06** | **⚠ FIRED (P1)** | **W1, W2, W3** | PSI = 14.39 on `f23_prior_alerts_90d`. Simulator artefact  -  rolling baseline fix required in production. |
| T07 | ✓ Not fired |  -  | |
| **T08** | **⚠ FIRED (P2)** | **W2** | Threshold drift 0.173 (0.056→0.229). Expected; confirms fixed-threshold prohibition. |
| T09 | ✓ Not fired |  -  | SAR rate range 9.4–9.9%; well within 3pp band |
| T10 | ✓ Not fired |  -  | AUC-ROC range 0.978–0.981 |

---

## 5. Feature Drift Monitoring

Feature drift is measured using Population Stability Index (PSI) with a fixed January 2023 reference window.

**PSI interpretation:**
- PSI < 0.10: Stable  -  no action required
- 0.10 ≤ PSI < 0.25: Minor shift  -  log and monitor
- PSI ≥ 0.25: Significant shift  -  T06 fires; escalate

### 5.1 Feature PSI Summary (M3 Evaluation)

| Feature | Max PSI | Classification | Note |
|---|---|---|---|
| `f01_vol_7d_log` | 0.071 | Stable | |
| `f02_vol_30d_log` | 1.625 | **Significant** | Cumulative volume growth in simulator |
| `f03_vol_ratio_7_30` | 3.173 | **Significant** | Ratio of accumulating quantities |
| `f04_max_txn_log` | 0.311 | **Significant** | |
| `f05_vol_vs_revenue` | 0.095 | Stable | |
| `f06_txn_count_7d` | 0.441 | **Significant** | |
| `f07_txn_count_30d` | 4.578 | **Significant** | Highly cumulative |
| `f08_velocity_ratio` | 4.483 | **Significant** | Highly cumulative |
| `f09_recency_gap_days` | 0.041 | Stable | |
| `f10_account_age_days` | 0.065 | Stable | |
| `f11_cash_fraction_30d` | 0.029 | Stable | |
| `f12_structuring_count_30d` | 0.090 | Stable | |
| `f13_round_amount_count_30d` | 0.053 | Stable | |
| `f14_digital_channel_fraction` | 0.204 | Minor | |
| `f15_night_fraction_30d` | 0.000 | Stable | |
| `f16_intl_fraction_30d` | 0.022 | Stable | |
| `f17_distinct_jurisdictions_30d` | 0.155 | Minor | |
| `f18_very_high_jur_flag` |  -  | Categorical | |
| `f19_shell_counterparty_fraction` | 0.179 | Minor | |

Features with PSI ≥ 0.25 in this evaluation are primarily cumulative rolling window features. In the simulator, these grow monotonically. In production, these should be computed relative to a customer's rolling baseline. The absolute PSI values reported here should not be interpreted as signals of production instability.

### 5.2 Features Requiring Special Handling in Production

`f23_prior_alerts_90d`  -  This feature counts prior alert activity in the last 90 days. In the simulator it grows monotonically, producing PSI = 14.39 when compared against a fixed January baseline. In production this feature must be evaluated relative to a rolling institutional baseline (i.e. the PSI reference window should advance in lockstep with the monitoring window).

Any rolling or cumulative feature (f02, f03, f06, f07, f08, f23) should be evaluated against a rolling reference baseline for PSI purposes. Using a fixed historical baseline will produce inflated PSI values that do not represent genuine distribution shift.

---

## 6. Calibration Monitoring

The model's probability outputs are well-calibrated in M3. No calibration layer is active.

| Window | ECE (raw) | Brier Score | Well-Calibrated? |
|---|---|---|---|
| Window-1 | 0.027 | 0.035 | ✓ Yes |
| Window-2 | 0.027 | 0.035 | ✓ Yes |
| Window-3 | 0.038 | 0.038 | ✓ Yes |

**Monitoring action:** If T05 fires (ECE ≥ 0.05), apply Platt calibration on the validation set. Do not apply calibration pre-emptively. Isotonic calibration achieves near-perfect ECE in-sample but overfits on small validation sets; prefer Platt unless validation N > 5,000.

---

## 7. Classification Threshold Policy

This section governs the secondary (classification) operating mode only. The capacity-ranking mode (primary) does not use a threshold.

**Critical rule: No hard-coded thresholds.**

The classification threshold must be recalibrated at every retraining cycle from the current validation set. The threshold observed in M3 ranged from 0.056 to 0.253 across three consecutive windows  -  a spread of 0.198. Any operational system that hard-codes a threshold from a prior period risks either missing SARs (threshold too high) or generating excessive false positives (threshold too low).

**Recalibration procedure:**
1. After retraining, generate scores on the validation set.
2. Compute the threshold that maximises F1 (or the organisation's preferred criterion) on the validation set.
3. Apply this threshold to classify test-set and production alerts.
4. Log the threshold alongside each retraining run for drift monitoring.
5. T08 fires if the new threshold deviates from the prior threshold by more than 0.10.

---

## 8. Typology-Level Monitoring

The model's performance is heterogeneous across rule groups. Overall Recall@20% at the portfolio level may mask failure in individual typologies.

### 8.1 Gate Definition

For any rule group with ≥ 50 SAR instances in the holdout set, Recall@20% ≥ 0.40 is the minimum acceptable floor.

### 8.2 Gate Status: M3 Baseline

| Rule Group | SAR Count (mean) | Gate Applicable | Gate Status | Recall@20% (mean) |
|---|---|---|---|---|
| R08 | ~170 | ✓ Yes | ✓ Pass | 1.000 |
| R15 | ~222 | ✓ Yes | ✓ Pass | 0.645 |
| R09 | ~111 | ✓ Yes | ✗ **FAIL** | ~0.345 |
| R06 | ~97 | ✓ Yes | ✗ **FAIL** | ~0.364 |
| R12 | ~62 | ✓ Yes | ✗ **FAIL** | ~0.206 |
| R01 | ~49 | ✓ Yes | ✗ **FAIL** | ~0.224 |
| R02 | ~42 | Below floor | Pass (default) | ~0.853 |
| R04 | ~48 | Below floor | Pass (default) | ~0.209 |

**Interpretation of failures:** R09, R06 fail because their SAR rates exceed 40%. Within these rule groups, almost every alert is a SAR; score-based ranking does not improve on reviewing all alerts within the group. R12 and R01 have near-100% SAR rates; the Recall@20% metric is structurally penalised because capacity is fixed at 20% while SAR density far exceeds it.

**Implication for deployment:** These rule groups should not rely on the capacity-ranking mode for triage. Options include:
- Review all alerts from R09, R06, R12, R01 regardless of score (flag groups with SAR rate > 40% for full review).
- Apply a typology-specific capacity expansion for these groups.
- Develop separate typology-specific models or rule-based priority policies.

### 8.3 Typology Monitoring Procedure

At each retraining cycle:
1. Compute per-rule-group Recall@20% on the test set.
2. Apply the gate to all rule groups with ≥ 50 test-set SARs.
3. Log pass/fail status for each applicable group.
4. Escalate if a previously passing group now fails.
5. Track whether the set of failing groups is expanding or stable.

---

## 9. Stress Test Monitoring

Stress tests should be re-run at every major retraining cycle (minimum quarterly). They test model robustness under controlled out-of-distribution conditions. Results are not directly actionable but establish a degradation baseline.

| Scenario | Trigger condition for concern |
|---|---|
| S01 Volume surge | Recall@20% < 0.90 or ΔRecall@20% < −0.10 |
| S02 New jurisdiction | Recall@20% < 0.90 or ΔRecall@20% < −0.10 |
| S03 Missing features (30%) | Recall@20% < 0.80 or ΔRecall@20% < −0.20 |
| S04 Rule shift (R08 removed) | No threshold  -  structural scenario, document delta |
| S05 Novel typology | No threshold  -  degradation expected, document delta |
| S06 SAR rate collapse | Recall@20% < 0.90 |

**M3 baseline stress results (Window-3):**
- S01: ΔRecall = 0.000, ΔAuC = −0.000 (robust)
- S02: ΔRecall = 0.000, ΔAUC = −0.000 (robust)
- S03: ΔRecall = −0.093, ΔAUC = −0.034 (near-threshold; monitor data quality)
- S04: ΔRecall = −0.532, ΔAUC = −0.027 (expected structural degradation)
- S05: ΔRecall = −0.788, ΔAUC = −0.088 (expected OOD degradation; model correctly signals unfamiliar pattern)
- S06: ΔRecall = 0.000, ΔAUC = +0.007 (robust)

**S03 note:** Missing features (30% of values zeroed) produces a Recall@20% of 0.907  -  below the 1.000 baseline but above the 0.80 concern threshold. Data quality monitoring is required in production. Any feature pipeline failure that produces high rates of missing or zeroed values must trigger immediate investigation.

---

## 10. Champion / Challenger Framework

The champion/challenger framework exists structurally in M3 but has not been exercised (no challenger model currently exists). The following protocol applies when a challenger is introduced.

### 10.1 Promotion Criteria

A challenger model may replace the champion only if:
- Mean Recall@20% delta across all evaluation windows ≥ +0.01 (challenger better)
- Mean AUC-ROC delta across all evaluation windows ≥ −0.02 (challenger does not regress)
- No individual window shows recall regression exceeding −0.02

### 10.2 Retention Criteria (champion retained)

The champion is retained if:
- Mean Recall@20% delta ≤ −0.02 (challenger regresses), OR
- Mean improvement across both metrics < 0.01 (no meaningful gain demonstrated)

### 10.3 Bootstrap Significance

When challenger N > 10 alerts per test window, bootstrap p-values (B=1,000, α=0.05) are computed for Recall@20% and AUC-ROC. A statistically insignificant improvement does not block promotion but must be documented. An insignificant result means the observed delta may be noise; a significant result means the delta is reliable.

### 10.4 Promotion Process

1. Run both models on all walk-forward windows.
2. Compute `compare_window()` for each window.
3. Call `promotion_decision()` on all window comparisons.
4. If recommendation is `promote_challenger`, submit for model risk sign-off.
5. Document reasons, metrics, and p-values in an ADR.
6. Former champion becomes the new challenger for future cycles.

---

## 11. Model Retirement Criteria

The model should be considered for retirement when any of the following are observed:

- **P0 trigger fires and cannot be cleared** after one full retraining cycle with a corrected pipeline.
- **Typology gate failures expand** to include rule groups that previously passed, with no clear data-quality explanation.
- **S03 (missing features) stress Recall@20% falls below 0.70**, suggesting the feature pipeline has degraded to the point where robustness assumptions no longer hold.
- **Production typology distribution changes substantially**  -  a new rule group accounting for > 20% of alerts and not represented in training is introduced. In this case the model should be considered out-of-distribution until retrained on the new typology.
- **Structural business change**  -  e.g. regulatory reporting requirements change the definition of SAR, making historical labels invalid.

---

## 12. Escalation Chain

| Severity | Trigger | Response time | Escalation path |
|---|---|---|---|
| **P0** | T01, T02 | Immediate | ML Engineering → Model Risk Committee → Compliance |
| **P1** | T03–T06 | ≤ 5 business days | ML Engineering → Model Risk |
| **P2** | T07–T10 | ≤ 10 business days | ML Engineering |
| **Stress anomaly** | S01–S06 vs baseline | Next monitoring cycle | ML Engineering → Model Risk (if expanding) |

---

## 13. Monitoring Artefacts

Each monitoring cycle should produce:

| Artefact | Description |
|---|---|
| Performance table | Per-window Recall@20%, AUC-ROC, ECE, threshold |
| Trigger firing log | All triggers evaluated; fired triggers with metric values |
| Feature PSI report | Per-feature PSI and drift classification |
| Typology gate report | Per-rule-group recall and gate pass/fail |
| Calibration report | ECE and Brier score; calibration decision |
| Stress test report | ΔRecall and ΔAUC per scenario vs M3 baseline |
| Threshold log | New threshold value; delta from prior |
| Champion/challenger report | (when challenger active) Promotion decision and rationale |

All artefacts should be version-controlled and retained for the model's operational lifetime.

---

## 14. Known Limitations of This Monitoring Regime

1. **Synthetic data baseline.** All thresholds and baseline values are derived from simulator data. Real-world distributions will differ; trigger thresholds should be recalibrated once 6+ months of production data are available.

2. **f23 PSI artefact.** The `f23_prior_alerts_90d` PSI signal of 14.39 is a simulator artefact. Production monitoring must use rolling PSI baselines for cumulative features.

3. **Typology gate for high-SAR-rate groups.** The Recall@20% gate does not adequately capture model behaviour for rule groups with SAR rates > 40%. These groups require a different metric (e.g. Recall@50% or full-review policy) rather than capacity-ranking evaluation.

4. **No champion challenger baseline yet.** Promotion thresholds are defined but untested. They should be reviewed after the first actual challenger evaluation.

5. **No production latency or throughput monitoring.** This specification covers model quality only. Operational SLAs (scoring latency, batch throughput) require a separate instrumentation plan.
