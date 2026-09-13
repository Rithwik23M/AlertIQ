# AlertIQ — Milestone 1 Completion Report

**Date:** 2026-09-11  
**Milestone:** Simulation Engine & TMS Rule Engine  
**Status:** ✅ COMPLETE — all quality gates passed

---

## 1. Definition of Done Checklist

| Gate | Criterion | Result |
|------|-----------|--------|
| ✅ | 15 TMS rules implemented (R01–R15) | 15 rules |
| ✅ | 8 FATF typology transaction generators | 8 generators |
| ✅ | 24 alert features computed (F01–F24) | 24 features |
| ✅ | Ground truth label assigned to every alert | 0 None leaks |
| ✅ | No feature-level ground-truth leakage | architecture boundary verified |
| ✅ | Structural reproducibility from seed | fingerprint match confirmed |
| ✅ | Zero duplicate (account, rule, date) alert keys | 0 dupes |
| ✅ | Zero feature gaps across all alerts | 0 missing values |
| ✅ | All 158 unit + integration tests pass | 158/158 |
| ✅ | Ground truth integrity errors | 0 errors |
| ✅ | SAR rate in realistic range (5–15%) | 7.9% |
| ✅ | Active-ML alert density > legitimate | 4.7× confirmed |
| ✅ | R05 (Dormant Account) fires in simulation | 2 alerts / 200-account run |

---

## 2. Codebase Summary

### Simulation package (`src/alertiq/simulation/`)

| Module | Lines | Purpose |
|--------|-------|---------|
| `config.py` | 223 | `SimulationConfig` — single frozen config, Pydantic v2, validated |
| `entities.py` | 332 | `Account`, `Transaction`, `Alert`, `SimulationResult`, enums |
| `population.py` | 293 | Seeded account population generator with risk-stratified sampling |
| `transactions.py` | 214 | Daily transaction generator (routine + typology activation) |
| `features.py` | 292 | 24 alert feature computations (F01–F24), no label leakage |
| `ground_truth.py` | 116 | SAR label assignment + integrity verification |
| `runner.py` | 375 | Orchestrator: day loop, rule evaluation, deduplication, output CSVs |
| `tms/rules.py` | 911 | 15 TMS rule implementations (R01–R15) |
| `tms/base.py` | 77 | `TMSRule` abstract base class |
| `typologies/` (8 files) | 711 | FATF typology transaction generators |

**Total simulation code: ~3,547 lines**

### Tests (`tests/simulation/`)

| Test file | Tests | Coverage |
|-----------|-------|----------|
| `test_config.py` | 20 | Config validation, edge cases, field constraints |
| `test_features.py` | 12 | Feature computation, leakage absence |
| `test_ground_truth.py` | 10 | SAR label logic, integrity verification |
| `test_population.py` | 14 | Population distribution, reproducibility |
| `test_runner.py` | 30 | Runner orchestration, deduplication, state ordering |
| `test_tms_rules.py` | 25 | Per-rule unit tests (R01–R15) |
| `test_typologies.py` | 47 | Typology generators, transaction properties |

**Total: 158 tests, 13.1s runtime**

---

## 3. Architecture Decisions

### ADR-01: Frozen Pydantic config passed through pipeline
**Decision:** `SimulationConfig(model_config={"frozen": True})` passed to every module.  
**Rationale:** Eliminates hidden state changes; enables hash-based reproducibility guarantee; makes configs serialisable for experiment tracking.

### ADR-02: Child RNG seeded from (master_seed, account_index)
**Decision:** Each account uses `np.random.default_rng([seed, idx])`.  
**Rationale:** Adding accounts never changes existing account properties. Population is stable given (seed, index) regardless of n_accounts.

### ADR-03: 30-day rolling window passed to TMS rules
**Decision:** Runner slices `window_txns` (last 30 days) and passes both `window_txns` and `all_account_txns` to each rule.  
**Rationale:** Most rules operate on a rolling window; R05 (dormancy) and a few others need the full history. Avoids individual rules re-slicing.

### ADR-04: Account state updated AFTER rule evaluation each day
**Decision:** `_update_account_state()` (which sets `last_txn_date`) runs at step 4e, after `_evaluate_rules_for_account()` at step 4d.  
**Rationale:** R05 (Dormant Account Sudden Activity) must compare today's transactions against the account's pre-today `last_txn_date`. If state were updated first, the gap would be 0 days and R05 would never fire.

### ADR-05: Global (account_id, rule_id, triggered_date) deduplication
**Decision:** `seen_alert_keys: set[tuple[str, str, date]]` maintained across the full simulation run.  
**Rationale:** Transaction-based rules (e.g., R06 Round Amounts) set `triggered_date = txn.txn_date` rather than the evaluation date. As the 30-day rolling window slides, the same triggering transaction re-appears each day, causing the rule to re-fire with the same triggered_date — producing thousands of duplicates without global deduplication. Within-day deduplication (the `seen_rules` set) only blocks same-date re-fires within a single evaluation call.

### ADR-06: R03 ratio-based velocity spike detection
**Decision:** R03 fires when `recent_7d_count / (baseline_30d × 7/30) >= 2.5`, with minimum absolute count of 10.  
**Rationale:** Absolute count thresholds fire for all accounts with normal transaction rates. Ratio-based detection is scale-invariant: it only fires when an account's recent rate significantly exceeds its own baseline, matching how production TMS velocity rules work.

### ADR-07: Ground truth formula
**Decision:** `true_sar = (account.risk_category == ACTIVE_ML) AND (alert.triggered_by_typology_txn == True)`  
**Rationale:** Reflects the simulation's internal oracle — only accounts known to be running a ML typology, and only alerts triggered by those typology transactions, are labelled positive. This gives the ML triage model a meaningful signal while keeping the label conservative (typology-free alerts from ML accounts are negative, matching analyst reality).

### ADR-08: Features contain no ground-truth labels
**Decision:** `features.py` computes only observable transaction statistics; `account.risk_category`, `txn.is_typology`, and `alert.true_sar` are explicitly excluded.  
**Rationale:** Any leakage of these fields would make triage model evaluation meaningless — the model would memorise rather than learn. Verified by architecture boundary inspection.

### ADR-09: Dormancy pre-assignment in population generator
**Decision:** Accounts with probability `_DORMANT_PROB[risk]` receive a `last_txn_date` set to 90–200 days before simulation start.  
**Rationale:** Without pre-simulation dormancy, R05 can only fire if an account goes 90+ days without a transaction during the 365-day simulation — rare and uncontrollable. Pre-assignment gives the simulation control over how many dormant-account scenarios exist.

---

## 4. Quality Gate Results

### Pass 1 & 2 — Staff Engineer + Data Scientist Review

**Label balance:** true_sar=7.9%, false_sar=92.1% — realistic for AML alert review workloads.  
**ML density ratio:** Active-ML accounts generate 4.7× more alerts than legitimate accounts — signal is present and learnable.  
**Feature completeness:** All 24 features computed for every alert, zero gaps.  
**Feature ranges:** All features verified finite (no NaN/Inf) on seed=42 run.

### Pass 3 — QA Review

**Finding (Critical):** 5,339 duplicate (account, rule, triggered_date) combos.  
**Root cause:** Transaction-based rules re-fired daily as triggering transactions stayed in the rolling 30-day window.  
**Fix:** Global `seen_alert_keys` set in runner. Duplicates eliminated to 0.

### Pass 4 — Adversarial Review

**Finding (Critical):** R03 fired 16,874 times for 200 accounts — effectively every account every day.  
**Root cause:** `velocity_threshold_count=20` is far below typical transaction volumes (~83–153 transactions per 30 days).  
**Fix:** Replaced absolute count check with ratio-based spike detection (`velocity_spike_ratio=2.5`). R03 counts reduced to 1,857 (realistic spike detection).

### Pass 5 — Architecture Boundaries

**Ground-truth leakage scan:** Zero. `is_typology`, `risk_category`, `true_sar` references in `features.py` are module docstring only — not in computation code.  
**Confirmed boundary:** Feature computation uses only transaction amounts, dates, channels, jurisdictions, and counterparty flags.

### Pass 6 — Ground Truth Integrity

**`verify_ground_truth_integrity()` result:** 0 errors across 19,277 alerts.  
**Invariants verified:** No alert labelled `true_sar=True` from a non-active-ML account; no alert labelled `true_sar=None` after assignment; no alert with `triggered_by_typology_txn=True` from a non-active-ML account labelled `false`.

### Pass 7 — Reproducibility

**Structural fingerprint (sha256[:16]):** `0311687a81d805ab` — identical across two independent runs with the same config.  
**Fields compared:** account_id, rule_id, triggered_date, true_sar, triggered_by_typology_txn, f01_txn_count_30d.  
**Alert UUIDs:** Intentionally non-seeded (random per run). Documented in `runner.py` module docstring.

### Pass 8 — Fix All Criticals

| Finding | Severity | Status |
|---------|----------|--------|
| R05 Path 2 checks only first-inserted txn (amount bias) | Critical | ✅ Fixed |
| Duplicate (account, rule, date) alerts from sliding window | Critical | ✅ Fixed |
| R03 fires for all accounts (absolute count too low) | Critical | ✅ Fixed |
| Determinism docstring claimed "bitwise-identical" | Medium | ✅ Fixed |
| R11/R13 silent in small runs | Non-issue | ✅ Confirmed expected |

---

## 5. Simulation Metrics (seed=42, n=200, 90 days)

```
Accounts:        200
Transactions:    63,810
Alerts:          19,277
True SARs:       1,526  (7.9%)
False SARs:      17,751 (92.1%)
Active ML accs:  10
Runtime:         8.0s

Rule trigger counts:
  R01 (CTR/Structuring):          132
  R02 (Large Cash):               442
  R03 (Velocity Spike):         1,857
  R04 (Round Amount):              22
  R05 (Dormant Account):            2
  R06 (Round Amount - large):     379
  R07 (High-Risk Jurisdiction):   293
  R08 (PEP/Adverse Media):     13,877
  R09 (Rapid Fund Movement):      274
  R10 (Layering):                 114
  R11 (Trade-Based ML):             0  ← expected for this seed/size
  R12 (Virtual Assets):            69
  R13 (Real Estate):                0  ← expected for this seed/size
  R14 (Shell Company):             58
  R15 (Cross-Border):           1,758

Typology transactions by type:
  structuring:        457
  shell_company:      118
  cross_border:       123
  virtual_assets:     211
  professional_ml:     83
```

**Note on R08:** High count reflects that PEP/adverse-media rule fires on every transaction above €2,000 for flagged accounts. This is architecturally correct — the rule is an account-level risk flag, not a pattern detector. In a production setting this rule would typically suppress after the first alert per account per review period; this is listed as technical debt below.

---

## 6. Known Limitations

1. **R08 dominates alert volume** — PEP/adverse-media rule fires on every qualifying transaction. Production TMS systems suppress subsequent alerts after review. No suppression logic exists in Milestone 1.

2. **R11, R13 require larger populations** — trade_based and real_estate typologies have 10% and 12% assignment probability among ~5% active-ML accounts. In a 200-account run (~10 ML accounts), these typologies often aren't assigned. They do fire correctly at 500+ accounts.

3. **No inter-account network modelling** — typology transactions are generated within the account's own transaction stream. Layering (R10) detects within-account rapid movement, not true multi-hop fund flows across accounts.

4. **Synthetic data quality ceiling** — Ground truth is defined by simulation oracle, not labelled by domain experts. Real AML data is required to validate that simulated typologies produce realistic patterns.

5. **Runtime scales super-linearly** — 200 accounts × 90 days runs in 8s; 500 accounts × 180 days times out at >90s on this container. The inner loop iterates all accounts × all rules per day with O(n) transaction list scans. Production use requires account-bucketed incremental evaluation or vectorised rule engines.

6. **No multi-account structuring** — structuring detection (R01) looks at one account's own deposits. Real structuring often spans multiple accounts at the same institution; the current model cannot detect this.

---

## 7. Technical Debt

| ID | Description | Priority | Effort |
|----|-------------|----------|--------|
| TD-01 | R08 alert suppression per review period | High | 1 day |
| TD-02 | Vectorised rule evaluation (pandas/polars) | High | 3 days |
| TD-03 | R10 layering via multi-account transaction graph | Medium | 3 days |
| TD-04 | Alert suppression across rule families (avoid multi-rule pile-on) | Medium | 2 days |
| TD-05 | Config serialisation to/from JSON for experiment registry | Low | 0.5 days |
| TD-06 | Per-rule coverage reporting in test suite | Low | 1 day |

---

## 8. Files Created / Modified

### New files
```
src/alertiq/simulation/__init__.py
src/alertiq/simulation/config.py
src/alertiq/simulation/entities.py
src/alertiq/simulation/features.py
src/alertiq/simulation/ground_truth.py
src/alertiq/simulation/population.py
src/alertiq/simulation/runner.py
src/alertiq/simulation/transactions.py
src/alertiq/simulation/tms/__init__.py
src/alertiq/simulation/tms/base.py
src/alertiq/simulation/tms/rules.py
src/alertiq/simulation/typologies/__init__.py
src/alertiq/simulation/typologies/base.py
src/alertiq/simulation/typologies/cash_intensive.py
src/alertiq/simulation/typologies/cross_border.py
src/alertiq/simulation/typologies/professional_ml.py
src/alertiq/simulation/typologies/real_estate.py
src/alertiq/simulation/typologies/shell_company.py
src/alertiq/simulation/typologies/structuring.py
src/alertiq/simulation/typologies/trade_based.py
src/alertiq/simulation/typologies/virtual_assets.py
tests/simulation/__init__.py
tests/simulation/conftest.py
tests/simulation/test_config.py
tests/simulation/test_features.py
tests/simulation/test_ground_truth.py
tests/simulation/test_population.py
tests/simulation/test_runner.py
tests/simulation/test_tms_rules.py
tests/simulation/test_typologies.py
conftest.py
pyproject.toml
docs/MILESTONE_1_COMPLETION.md  (this file)
```

---

## 9. Recommended Git Commit

```
feat(simulation): Milestone 1 — deterministic AML simulation engine

Implements the complete simulation engine for AlertIQ Milestone 1:

- SimulationConfig: frozen Pydantic v2 config, single source of truth
  for all simulation parameters; fully validated.

- Account population generator: seeded, risk-stratified, reproducible.
  Pre-assigns dormancy for R05 testing. Child RNGs seeded by
  (master_seed, account_idx) for population stability.

- Transaction generator: routine + FATF typology transactions per day.
  8 typology generators (structuring, shell_company, real_estate,
  trade_based, cash_intensive, professional_ml, virtual_assets,
  cross_border).

- TMS rule engine: 15 rule implementations (R01–R15) with configurable
  thresholds. R03 uses ratio-based velocity spike detection to avoid
  firing on all normal-volume accounts.

- Ground truth: SAR labels assigned by oracle rule
  (active_ml AND triggered_by_typology_txn). Zero ground-truth leakage
  in computed features.

- 24 alert features (F01–F24): all observable, no label leakage.

- Runner: day-by-day orchestration, 30-day rolling window per rule,
  global (account, rule, date) deduplication to prevent transaction-
  based rules from re-alerting as the window slides.

- 158 tests (100% pass): config, entities, population, transactions,
  typologies, TMS rules (per-rule), features, ground truth, runner.

Quality gate results:
  - 0 duplicate alert keys
  - 0 feature gaps
  - 0 ground truth integrity errors
  - Structural reproducibility confirmed (fingerprint match)
  - SAR rate: 7.9% (200 accs, 90 days, seed=42)
  - Active-ML alert density: 4.7× legitimate accounts

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016BpQCLqBwEfBcTQibqVPT1
```

---

## 10. Milestone 2 Prerequisites

Milestone 2 (ML Triage Model) requires:

1. A simulation run producing `data/simulation/alerts.csv` with ≥5,000 alerts.
2. Feature columns F01–F24 verified present and finite.
3. `true_sar` column populated (no nulls).
4. SAR rate between 5–15% to avoid class imbalance issues.
5. Train/test split must respect temporal ordering (split by `triggered_date`, not random).

All prerequisites are met by the current simulation engine. **Milestone 2 may begin.**
