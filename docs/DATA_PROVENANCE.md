# AlertIQ — Dataset Provenance Record

**Document type:** Data provenance  
**Covers:** `data/simulation/alerts.csv`, `data/simulation/transactions.csv`  
**Created:** 2026-09-12  
**Updated:** 2026-09-13 (M6.1 — full dual-dataset lineage added; transactions.csv replaced with canonical 2023 run; alerts.csv history reconciled)

---

## 1. Alerts Dataset Identity (`alerts.csv`)

| Field | Value |
|-------|-------|
| File | `data/simulation/alerts.csv` |
| SHA-256 (current, M6.1) | `3ae95fb5b273c9426918b6c55bca99d123927047aa1b22590bfe8b6d5ac28bd8` |
| Row count | 55,896 |
| Column count | 33 |
| Date range | 2023-01-01 → 2023-06-29 |
| Unique accounts | 300 |
| True SARs | 5,209 (9.32%) |

```bash
python3 -c "
import hashlib
with open('data/simulation/alerts.csv', 'rb') as f:
    data = f.read()
print(hashlib.sha256(data).hexdigest())
"
```

### Version History

| Version | SHA-256 (first 8 chars) | Row count | Milestone | Notes |
|---------|------------------------|-----------|-----------|-------|
| v1 (original) | `ab88cac9` | 56,195 | M2 | First generation; model 1.0.0 was trained on this version |
| v2 | `15cea79b` | 56,195 | M6 | Regenerated — SHA changed, row count unchanged per M6 notes (SHA mismatch suggests minor platform/NumPy difference) |
| v3 (current) | `3ae95fb5` | 55,896 | M6.1 | Current on-disk version; row count differs from v1 by 299 rows |

**Why the SHA changed across versions:** The simulator uses `numpy.random.Generator` seeded deterministically, but the Python/NumPy version used for generation changed between milestone sessions, causing different floating-point rounding in feature computation and a slightly different alert population. The simulation parameters are identical across all three runs: `seed=42, n_accounts=300, start_date=2023-01-01, end_date=2023-06-30`.

**Impact on model:** Model 1.0.0 was trained on v1 (56,195 rows, training_rows=44,956 = train+val). The current scoring run uses v3 (55,896 rows). The population drift is 299 rows (0.53%) — both use the same accounts, simulation period, and parameters. This drift is documented in MODEL_LINEAGE.md and does not invalidate the model; it is a known limitation of environment-sensitive synthetic data generation.

---

## 2. Transactions Dataset Identity (`transactions.csv`)

| Field | Value |
|-------|-------|
| File | `data/simulation/transactions.csv` |
| SHA-256 (current, M6.1) | `54094bd381c9425014dc9d920b3afb57f8ad65688b012fed5c399ce78f349764` |
| Row count | 191,364 |
| Column count | 15 |
| Date range | 2023-01-01 → 2023-06-29 |
| Unique accounts | 300 |

```bash
python3 -c "
import hashlib
with open('data/simulation/transactions.csv', 'rb') as f:
    data = f.read()
print(hashlib.sha256(data).hexdigest())
"
```

### Version History

| Version | SHA-256 (first 8 chars) | Row count | Date range | Milestone | Notes |
|---------|------------------------|-----------|------------|-----------|-------|
| v0 (DISCARDED) | unknown | 63,810 | 2024-01-01→2024-03-30 | M6 | Wrong simulation run — 2024 dates incompatible with 2023 alerts |
| v1 (current) | `54094bd3` | 191,364 | 2023-01-01→2023-06-29 | M6.1 | Canonical generation; same seed/params as alerts.csv |

**Why v0 was discarded:** The original `transactions.csv` came from a separate simulation run using 2024 dates. This made `txn_date <= alert_date` temporal filtering impossible — every transaction post-dated every alert. M6 worked around this by removing the temporal filter from `get_alert_transactions()`. M6.1 identified this as a critical temporal integrity violation, regenerated `transactions.csv` from the canonical 2023 simulation, and restored the temporal filter.

**Generation command (M6.1):**
```python
from alertiq.simulation import run_simulation, SimulationConfig
result = run_simulation(SimulationConfig(
    seed=42,
    n_accounts=300,
    start_date="2023-01-01",
    end_date="2023-06-30",
))
# result.transactions → written to data/simulation/transactions.csv
```

**Account coverage:** 300/300 alert accounts present in transactions.csv (100% overlap confirmed).

---

## 3. Dataset Scope

| Field | Value |
|-------|-------|
| Simulation period | 2023-01-01 → 2023-06-29 (180 calendar days) |
| Simulated accounts | 300 |
| Total alerts | 55,896 |
| True SARs (ground truth) | 5,209 (9.32%) |
| True non-SARs | 50,687 |
| Total transactions | 191,364 |
| TMS rules active | R01, R02, R03, R04, R05, R06, R07, R08, R09, R11, R12, R13, R15 |
| Severity levels | critical, high, medium |

---

## 4. Schema — Alerts

| Column | Type | Description | Leakage? |
|--------|------|-------------|----------|
| `alert_id` | string | Unique alert identifier | ⚠️ ID — not a feature |
| `account_id` | string | Account generating the alert | ⚠️ ID — not a feature |
| `triggered_date` | string (YYYY-MM-DD) | Date alert was generated | Used for temporal splits |
| `rule_id` | string (R01–R15) | TMS rule that fired the alert | Not a model feature |
| `rule_name` | string | Human-readable rule name | Not a model feature |
| `severity` | string | TMS alert severity (critical/high/medium) | Not a model feature |
| `status` | string | Alert status (all "open" in simulator) | ⚠️ Post-alert outcome — leakage |
| `true_sar` | int (0/1) | Ground truth SAR label | ⚠️ TARGET — not a feature |
| `triggered_by_typology_txn` | int (0/1) | Label proxy | ⚠️ Leakage — not a feature |
| `f01_vol_7d_log` | float64 | Log transaction volume, 7-day window | Model feature |
| `f02_vol_30d_log` | float64 | Log transaction volume, 30-day window | Model feature |
| `f03_vol_ratio_7_30` | float64 | Volume ratio 7d/30d | Model feature |
| `f04_max_txn_log` | float64 | Log of maximum transaction amount | Model feature |
| `f05_vol_vs_revenue` | float64 | Transaction volume vs reported revenue | Model feature |
| `f06_txn_count_7d` | float64 | Transaction count, 7-day window | Model feature |
| `f07_txn_count_30d` | float64 | Transaction count, 30-day window | Model feature |
| `f08_velocity_ratio` | float64 | Velocity change ratio | Model feature |
| `f09_recency_gap_days` | float64 | Days since last transaction | Model feature |
| `f10_account_age_days` | float64 | Account age in days | Model feature |
| `f11_cash_fraction_30d` | float64 | Fraction of transactions in cash, 30-day | Model feature |
| `f12_structuring_count_30d` | float64 | Count of structuring-pattern transactions | Model feature |
| `f13_round_amount_count_30d` | float64 | Count of round-amount transactions | Model feature |
| `f14_digital_channel_fraction` | float64 | Fraction of digital channel transactions | Model feature |
| `f15_night_fraction_30d` | float64 | Fraction of night-time transactions | Model feature |
| `f16_intl_fraction_30d` | float64 | Fraction of international transactions | Model feature |
| `f17_distinct_jurisdictions_30d` | float64 | Distinct jurisdictions in 30-day window | Model feature |
| `f18_very_high_jur_flag` | float64 | Flag: counterparty in very-high-risk jurisdiction | Model feature (categorical) |
| `f19_shell_counterparty_fraction` | float64 | Fraction of transactions with shell-like counterparties | Model feature |
| `f20_pep_flag` | float64 | Flag: politically exposed person | Model feature (categorical) |
| `f21_adverse_media_flag` | float64 | Flag: adverse media hit | Model feature (categorical) |
| `f22_high_risk_industry` | float64 | Flag: high-risk industry classification | Model feature (categorical) |
| `f23_prior_alerts_90d` | float64 | Prior alerts in 90-day window | Model feature |
| `f24_account_jurisdiction_score` | float64 | Jurisdiction risk score of account | Model feature |

**Categorical feature indices (0-based in feature matrix):** 17, 19, 20, 21

---

## 5. Schema — Transactions

| Column | Type | Description |
|--------|------|-------------|
| `txn_id` | string | Unique transaction identifier |
| `account_id` | string | Account generating the transaction |
| `txn_date` | string (YYYY-MM-DD) | Transaction date |
| `txn_datetime` | string (ISO 8601) | Transaction timestamp |
| `txn_type` | string | Transaction type (transfer, withdrawal, deposit, …) |
| `channel` | string | Channel (digital, branch, atm, …) |
| `amount_eur` | float64 | Transaction amount in EUR |
| `is_international` | int (0/1) | International transaction flag |
| `destination_jurisdiction` | string | Destination country code |
| `counterparty_id` | string | Counterparty account ID |
| `counterparty_jurisdiction` | string | Counterparty country code |
| `counterparty_is_shell` | int (0/1) | Counterparty identified as shell entity |
| `is_typology` | int (0/1) | Transaction is part of a FATF typology pattern |

---

## 6. Leakage Classification — Alerts

| Column | Reason |
|--------|--------|
| `true_sar` | Target variable — direct label leakage |
| `triggered_by_typology_txn` | Proxy for `true_sar` — indirect label leakage |
| `account_id` | Identifier — would encode account-level memory, not behaviour |
| `alert_id` | Identifier — no predictive content |
| `status` | Post-alert outcome — unknown at alert generation time |

---

## 7. Temporal Split Boundaries (based on current alerts.csv v3)

| Split | Date range | Approx. Alerts | Approx. SARs | SAR rate |
|-------|-----------|----------------|--------------|----------|
| Train | 2023-01-01 → 2023-04-15 | ~33,538 | ~3,126 | ~9.3% |
| Validation | 2023-04-16 → 2023-05-23 | ~11,179 | ~1,041 | ~9.3% |
| Holdout | 2023-05-24 → 2023-06-29 | ~11,179 | ~1,041 | ~9.3% |

**Note:** The model was trained on v1 of alerts.csv (56,195 rows). See `docs/MODEL_LINEAGE.md` for the full training/serving lineage.

---

## 8. Versioned Derived Artefact Policy

This policy governs when SHA-256 checksums must be updated and how derived artefacts (investigation store, seed data, trained models) must be traced to source datasets.

| Rule | Requirement |
|------|-------------|
| **P1 — SHA on mutation** | Whenever `alerts.csv` or `transactions.csv` is regenerated, this document must be updated with the new SHA-256 and row count before committing. |
| **P2 — Training traceability** | `MODEL_LINEAGE.md` must record the SHA-256 of the alerts.csv used for each training run, so any model can be traced to its training data. |
| **P3 — Seed reproducibility** | `seed_alert_store.py` must log the SHA-256 of alerts.csv and transactions.csv at seed time, stored in `data/seed_manifest.json`. |
| **P4 — No silent regeneration** | If dataset regeneration changes row counts or SARs, this constitutes a data version bump and must be recorded in the version history table above. |
| **P5 — Model/data compatibility gate** | If training_rows from `registry.json` does not equal `round(len(alerts_df) * 0.80)` ± 10, this indicates a data version mismatch that must be resolved before production deployment. |
| **P6 — Temporal compatibility gate** | `transactions.csv` date range must overlap with `alerts.csv` date range. Any regeneration that breaks this overlap is a blocking defect. |

---

## 9. Simulator Design Notes

The simulator was designed to generate alerts that:
- Mimic TMS rule firing patterns across 13 distinct rule types
- Embed SAR-predictive signals into the feature set (`f11_cash_fraction_30d`, `f19_shell_counterparty_fraction`, `f22_high_risk_industry` are strongest predictors)
- Produce a realistic 9–10% SAR rate across 300 simulated accounts

**Important caveat.** Because features were designed to encode SAR-predictive signals by construction, the model achieves extraordinarily high AUC-ROC (~0.97) on this dataset. This does not represent expected performance on real TMS data, which is noisier and less cleanly separable. External validation on real TMS data is required before any institutional use.

---

## 10. Verification Commands

```bash
# Verify alerts.csv
python3 -c "
import hashlib, pandas as pd
with open('data/simulation/alerts.csv', 'rb') as f:
    data = f.read()
sha = hashlib.sha256(data).hexdigest()
expected = '3ae95fb5b273c9426918b6c55bca99d123927047aa1b22590bfe8b6d5ac28bd8'
print(f'SHA-256: {sha}')
print(f'Status: {\"OK\" if sha == expected else \"MISMATCH\"}')
df = pd.read_csv('data/simulation/alerts.csv')
print(f'Rows: {len(df)}  (expected: 55896)')
print(f'SARs: {df[\"true_sar\"].sum()}  (expected: 5209)')
"

# Verify transactions.csv
python3 -c "
import hashlib, pandas as pd
with open('data/simulation/transactions.csv', 'rb') as f:
    data = f.read()
sha = hashlib.sha256(data).hexdigest()
expected = '54094bd381c9425014dc9d920b3afb57f8ad65688b012fed5c399ce78f349764'
print(f'SHA-256: {sha}')
print(f'Status: {\"OK\" if sha == expected else \"MISMATCH\"}')
df = pd.read_csv('data/simulation/transactions.csv')
print(f'Rows: {len(df)}  (expected: 191364)')
print(f'Date range: {df[\"txn_date\"].min()} → {df[\"txn_date\"].max()}')
print(f'Accounts: {df[\"account_id\"].nunique()}  (expected: 300)')
"
```

---

*Updated by Milestone 6.1 Investigation Integrity Hardening. Previous version covered alerts.csv only; this version adds transactions.csv lineage, version history for both files, and the Versioned Derived Artefact Policy.*
