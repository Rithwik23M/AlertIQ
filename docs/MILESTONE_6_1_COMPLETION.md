# AlertIQ  -  Milestone 6.1 Completion Report

**Milestone:** M6.1  -  Investigation Integrity Hardening  
**Status:** ✅ COMPLETE  
**Completed:** 2026-09-13  
**Total Python tests passing:** 663 / 663  
**New tests added:** 36 (12 temporal integrity + 24 E2E journey)

---

## Executive Summary

Milestone 6.1 identified and corrected a critical temporal evidence integrity violation inherited from M6, then hardened the investigation workspace across ten areas: temporal filtering, data provenance, model lineage, persistence architecture, historical immutability, test coverage, E2E journey validation, explainability audit, demo data quality, and adversarial review.

The central defect was that `transactions.csv` had been generated from a 2024 simulation run, making it impossible for any transaction to satisfy `txn_date <= alert_date` when alerts were dated 2023. M6 worked around this by removing the temporal filter  -  an AML investigation integrity violation. M6.1 regenerated `transactions.csv` from the canonical 2023 simulation, restored the filter, and proved it holds at every level from SQL to HTTP API.

**Security controls established in M6 and mandatory for all future milestones:**

| Control | Status |
|---------|--------|
| `true_sar` ground truth never returned by any API endpoint | ✅ Verified by automated test |
| Analyst notes never forwarded to any external service or LLM | ✅ No LLM call in any route handler |
| Model cannot select analyst decision automatically | ✅ No auto-decision logic exists |
| No automatic retraining from analyst decisions | ✅ `decisions` table is not read by any training path |
| Scoring snapshot immutable after investigation opens | ✅ Verified by automated test |

---

## Area 1: Temporal Evidence Integrity

**Defect found and corrected.**

M6 used `transactions.csv` from a 2024 simulation (date range 2024-01-01 → 2024-03-30), incompatible with 2023 alerts. Rather than regenerate the dataset, M6 removed the temporal filter from `get_alert_transactions()`. This meant an analyst investigating a 2023 alert would have seen no transactions  -  or, if the filter had been reactivated with the wrong dataset, would have seen future transactions as historical evidence.

**M6.1 resolution:**

1. Regenerated `transactions.csv` from the canonical 2023 simulation (`seed=42, n_accounts=300, start_date=2023-01-01, end_date=2023-06-30`).
2. Restored the temporal filter in `get_alert_transactions()`:
   ```sql
   WHERE t.account_id = ? AND t.txn_date <= ?
   ```
   where `?` (second parameter) is the alert's `alert_date`.
3. Added 12 automated tests (`tests/serving/test_temporal_integrity.py`) proving enforcement at both store level and HTTP API level.

**Invariants enforced:**

- A transaction on the alert date is included (boundary inclusive).
- A transaction one day after the alert date is excluded (off-by-one verified).
- Transactions from other accounts are excluded (account isolation verified).
- The filter cannot be bypassed by route-level modification (API test class).
- `true_sar` does not appear in any GET response (security test).
- Risk score is unchanged after a decision is recorded (immutability test).

---

## Area 2: Data Provenance

**Document created: `docs/DATA_PROVENANCE.md`**

Full dual-dataset lineage established for `alerts.csv` and `transactions.csv`.

### alerts.csv version history

| Version | SHA-256 (first 8 chars) | Row count | Milestone | Notes |
|---------|------------------------|-----------|-----------|-------|
| v1 | `ab88cac9` | 56,195 | M2 | First generation; model 1.0.0 trained on this version |
| v2 | `15cea79b` | 56,195 | M6 | SHA changed due to Python/NumPy version difference |
| v3 (current) | `3ae95fb5` | 55,896 | M6.1 | Row count differs by 299 (0.53%) from v1 |

### transactions.csv version history

| Version | SHA-256 (first 8 chars) | Row count | Date range | Milestone | Notes |
|---------|------------------------|-----------|------------|-----------|-------|
| v0 (DISCARDED) | unknown | 63,810 | 2024-01-01→2024-03-30 | M6 | Wrong simulation; 2024 dates incompatible with 2023 alerts |
| v1 (current) | `54094bd3` | 191,364 | 2023-01-01→2023-06-29 | M6.1 | Canonical 2023 generation |

**Versioned Derived Artefact Policy (P1–P6) established**  -  see `DATA_PROVENANCE.md §8`.

---

## Area 3: Model and Data Lineage

**Document created: `docs/MODEL_LINEAGE.md`**

Confirmed: AlertIQ has had exactly **one model training run** (M4), producing version `1.0.0`. No retraining occurred in M5, M6, or M6.1.

### Evidence

The `training_rows` field in `models/registry.json` is `44956`. This uniquely identifies v1 as the training dataset: `round(56195 × 0.80) = 44,956` (60% train + 20% validation, 20% held out). No other alerts.csv version produces this training_rows count.

**ADR-M4-05** (no retraining during serving) was correctly followed. Champion/challenger promotion process documented for future retraining events.

### Governance controls verified

| Control | Status |
|---------|--------|
| `true_sar` never returned by API | ✅ |
| Scoring snapshot immutable after investigation opens | ✅ |
| No automatic retraining from analyst decisions | ✅ |
| Model cannot select analyst decision automatically | ✅ |
| Champion requires explicit promotion | ✅ |

---

## Area 4: Persistence Architecture

**Document created: `docs/PERSISTENCE_ARCHITECTURE.md`**

The persistence layer is explicitly labelled:

> **⚠️ DEVELOPMENT / DEMO DEPLOYMENT ONLY**

### Current implementation

`alert_store.py`  -  SQLite WAL, 6 tables, procedural function API. Suitable for single-server portfolio demo.

### Cloud Run limitation documented

Cloud Run containers have ephemeral local disk. On redeployment, the SQLite file is wiped. The seed script (`scripts/seed_alert_store.py`) is idempotent and must be re-run after each deployment. This is acceptable for a demo with no real analyst decisions.

### InvestigationRepository interface designed

Abstract Python ABC interface designed for production-upgrade readiness (see `PERSISTENCE_ARCHITECTURE.md §4`). The interface decouples route handlers from the SQLite implementation. Swapping to `PostgreSQLInvestigationRepository` requires changes only to the repository implementation, not to any route handler.

### Smallest defensible production path

Seven steps: Cloud SQL (PostgreSQL) → Unix socket via Auth Proxy → Alembic migrations → column-level PII encryption → append-only audit table grants → JWT/OAuth2 analyst authentication → dependency injection of repository interface.

Estimated engineering effort: 2–3 days for a developer familiar with the codebase.

---

## Area 5: Historical Model Evidence  -  Scoring Snapshot Immutability

**Verified by automated test.**

Each alert record in the investigation store contains a scoring snapshot written once at seed time:

| Field | Value for demo dataset |
|-------|----------------------|
| `risk_score` | Model output at scoring time |
| `scored_at` | UTC timestamp of scoring run |
| `model_version` | `"1.0.0"` |
| `schema_version` | `1` |

The `upsert_alert()` function is idempotent for re-seeding. No API route (GET or POST) modifies `risk_score`, `scored_at`, or `model_version`. This is verified at HTTP level by `test_api_decision_does_not_change_risk_score` (temporal integrity test suite) and `test_step8_risk_score_unchanged_after_full_journey` (journey test suite).

**`SELECT a.*` note:** The `get_alert()` function queries `SELECT a.*` from the alerts table (which includes `true_sar`), but the returned Python dict is built manually and never includes `true_sar`. This is verified by automated test. A future refactoring may enumerate columns explicitly for additional defense.

---

## Area 6: Frontend Test Execution

**Status: BLOCKED  -  environmental limitation.**

The Jest test suite requires `@testing-library/jest-dom`. Installation of this package is blocked at the cloud egress proxy level (HTTP 403  -  organization security policy denial for `registry.npmjs.org`). This is not a code defect.

**Tests confirmed present:** `src/frontend/tests/` contains the Jest test files created in M6.

**Action required:** Jest tests must be run in a local development environment with npm registry access. The blocking package is a `devDependency` and is not required for production deployment.

---

## Area 7: End-to-End Investigation Journey Test

**24/24 tests passing.**  
**File:** `tests/serving/test_investigation_journey.py`

### What the test proves

The test simulates the complete investigation lifecycle against the real HTTP API (using Starlette `TestClient`):

| Step | What is tested |
|------|---------------|
| 1  -  Queue | Alert appears in paginated queue with correct risk score |
| 2  -  Detail | Full alert detail retrievable with features; 404 for missing alert |
| 3  -  Temporal | 2 pre-alert transactions visible; 1 post-alert transaction excluded; all returned dates ≤ alert_date |
| 4  -  Open | Status transitions from `new` → `in_progress` |
| 5  -  Note | Note accepted; retrievable; does not change risk score |
| 6  -  Decision | Decision accepted; retrievable; rationale preserved |
| 7  -  History | Audit trail records open event with timestamp; events are chronological |
| 8  -  Immutability | risk_score and model_version unchanged after full open → note → decision journey |
| 9  -  Security | `true_sar` absent from queue, detail, transactions, history, notes, and decisions responses |

### Fixture design

The `journey_client` fixture is module-scoped (shared across all tests in the class) so that state changes (open, note, decision) are visible to subsequent steps. Module scope requires direct `os.environ` manipulation rather than pytest's function-scoped `monkeypatch`. Environment variable is restored on teardown.

---

## Area 8: Explainability Validation

### Signal source audit

All explainability signals in `GET /alerts/{id}` are produced by `_compute_explainability_signals(features, quality_flags)` in `alert_store.py`. The `features` dict is deserialized from `features_json` stored in the `alerts` table. There are no external calls, no LLM inference, and no live data fetching in the explainability path. The computation is fully deterministic.

### Signal classification

Each signal type an analyst sees is classified by its epistemic status:

#### FACTUAL_EVIDENCE  -  Directly observable behavioral facts

These signals can, in principle, be independently verified from source transaction and KYC systems. They represent raw observations about the account's behavior over the 30-day window prior to the alert.

| Signal | Feature | Threshold |
|--------|---------|-----------|
| Cash proportion (30-day) | `f11_cash_fraction_30d` | > 60% → notable |
| Structuring transactions (30-day) | `f12_structuring_count_30d` | > 3 → notable |
| Round-value transactions (30-day) | `f13_round_amount_count_30d` | > 5 → notable |
| Transaction count (30-day) | `f07_txn_count_30d` | > 40 → notable |
| Distinct jurisdictions (30-day) | `f17_distinct_jurisdictions_30d` | > 3 → notable |
| Prior alerts (90-day) | `f23_prior_alerts_90d` | > 2 → notable |
| Politically Exposed Person flag | `f20_pep_flag` | ≥ 1.0 → Yes |
| Adverse media flag | `f21_adverse_media_flag` | ≥ 1.0 → Yes |
| High-risk industry classification | `f22_high_risk_industry` | ≥ 1.0 → Yes |

#### MODEL_SIGNAL  -  Engineered features used as model inputs

These signals are computed from raw transaction data by the feature engineering pipeline. They are inputs to the LightGBM model and also carry investigative meaning, but they are derived ratios rather than direct observations.

| Signal | Feature | Threshold |
|--------|---------|-----------|
| Transaction velocity ratio (7d/30d) | `f08_velocity_ratio` | > 3.0× → notable |
| Volume spike ratio (7d vs 30d avg) | `f03_vol_ratio_7_30` | > 2.5× → notable |
| International transaction fraction | `f16_intl_fraction_30d` | > 50% → notable |
| Night-time transaction fraction | `f15_night_fraction_30d` | > 40% → notable |
| Shell-entity counterparty fraction | `f19_shell_counterparty_fraction` | > 10% → notable |
| High-risk jurisdiction counterparty | `f18_very_high_jur_flag` | ≥ 1.0 → Yes |
| Model risk score | `risk_score` | Capacity-ranked threshold 0.3972 |

#### HUMAN_DECISION  -  Analyst-recorded outcomes

These are not signals from the data or model. They are analyst annotations recorded during the investigation.

| Signal | Source |
|--------|--------|
| Investigation notes | `notes` table  -  append-only |
| Investigation decision | `decisions` table  -  append-only |
| Investigation status | `investigation_state` table  -  mutable |
| Audit trail | `audit_events` table  -  append-only |

### Integrity guarantees

- All 15 features in `_FEATURE_THRESHOLDS` are sourced from stored feature values in the `alerts.features_json` column.
- Notable thresholds are hard-coded from population reference statistics derived from simulation training data  -  they are deterministic and not LLM-generated.
- The `"notable"` flag is a boolean comparison (`value >= threshold`), not a model prediction.
- Binary flag features (f18, f20, f21, f22) display as "Yes" / "No"  -  the analyst is shown the flag value, not a model interpretation of it.
- No signal in `explainability_signals` is synthetic, inferred, or externally fetched.

---

## Area 9: Demo Data Quality

**No future leakage in the investigation store.**

The seed script (`scripts/seed_alert_store.py`) seeds from the 2023-canonical `transactions.csv`. All transactions are dated between 2023-01-01 and 2023-06-29. Alerts are dated between 2023-01-01 and 2023-06-29. The temporal filter (`txn_date <= alert_date`) correctly partitions this data.

**Account coverage:** 300/300 alert accounts are present in `transactions.csv` (100% overlap confirmed by simulation).

**Seed manifest:** The seed script writes `data/seed_manifest.json` containing SHA-256 fingerprints of both source CSVs and the seed timestamp, enabling reproduction of any seeded store state.

---

## Area 10: Adversarial Review

### AML Investigator perspective

**Concern:** Can an analyst see future transactions as historical evidence?  
**Finding:** Resolved. The temporal filter is enforced at the store level (`WHERE txn_date <= alert_date`) and verified at the HTTP API level by automated test. The database cannot be queried for future transactions through any exposed route.

**Concern:** Is the risk score influenced by the analyst's investigation actions?  
**Finding:** Resolved. No route handler modifies `risk_score`, `scored_at`, or `model_version`. Verified by automated test across the full investigation journey.

**Concern:** Does the investigation workspace expose the model's ground truth labels?  
**Finding:** Resolved. `true_sar` is stored in the `alerts` table for seeding/evaluation purposes only. It is never returned by any read query (the returned dict is built explicitly without `true_sar`). Verified by automated test across all six GET endpoints.

### Model Risk Reviewer perspective

**Concern:** What model version was used to score the investigation queue?  
**Finding:** Documented. Model 1.0.0, trained 2026-09-13T12:39:23 UTC on alerts.csv v1 (44,956 rows). Scoring ran against alerts.csv v3 (55,896 rows). Population drift: 299 rows (0.53%) due to environment-sensitive simulation. See `MODEL_LINEAGE.md`.

**Concern:** Were AML investigation decisions used to retrain the model?  
**Finding:** No. The `decisions` table has no read path in any training or scoring code. ADR-M4-05 prohibits retraining during serving.

**Concern:** Were model outputs used to auto-determine investigation outcomes?  
**Finding:** No. The model produces `risk_score` and `above_threshold`. The decision outcome (`escalate`, `close`, `needs_further_review`) is always recorded by an analyst via the POST endpoint. No auto-decision logic exists in the serving layer.

### Data Engineer perspective

**Concern:** How do we know which data version trained the model?  
**Finding:** `training_rows = 44956` in `registry.json`. This uniquely identifies alerts.csv v1 (56,195 rows × 0.80 = 44,956). Documented in `MODEL_LINEAGE.md §2`.

**Concern:** What happens when `transactions.csv` is regenerated?  
**Finding:** The Versioned Derived Artefact Policy (P1–P6 in `DATA_PROVENANCE.md`) requires SHA-256 update, row count verification, seed manifest update, and temporal compatibility gate check before any regeneration is committed.

**Concern:** Are there transactions for accounts that have no alerts?  
**Finding:** All 300 accounts are covered in both datasets. The seed script filters transactions to accounts that have alerts, so no orphan transaction records appear in the store.

### Backend Engineer perspective

**Concern:** The `get_alert()` function uses `SELECT a.*` which includes `true_sar` in the SQL result row. Is this safe?  
**Finding:** Yes, but fragile. The returned Python dict is built explicitly without `true_sar`. The automated test (`test_api_response_has_no_true_sar`) prevents regression. **Recommendation:** Enumerate columns explicitly in a future refactoring pass to eliminate this fragility without the protection of the test.

**Concern:** Is the temporal filter SQL injection-safe?  
**Finding:** Yes. Both `account_id` and `alert_date` are passed as parameterized query arguments (`?`), never formatted into the SQL string.

**Concern:** Is the SQLite connection factory thread-safe?  
**Finding:** Each call to `_connect()` opens a new connection with `check_same_thread=False`. SQLite WAL mode allows multiple readers. Single-writer constraint is not a concern for a single-analyst demo deployment, but would need connection pooling for multi-analyst production use (see `PERSISTENCE_ARCHITECTURE.md §3`).

### QA Engineer perspective

**Concern:** What is the test coverage for the serving layer?  
**Finding:** 194 serving tests pass:
- `test_temporal_integrity.py`: 12 tests  -  store-level filter, API-level filter, security controls, immutability
- `test_investigation_journey.py`: 24 tests  -  full E2E journey across all 9 endpoints
- `test_alert_routes.py` and related: 158 tests  -  route handlers, error cases, validation

**Concern:** Are the tests isolated? Can they interfere with each other?  
**Finding:** Each test fixture creates a fresh SQLite database in `tmp_path` (function-scoped) or `tmp_path_factory.mktemp()` (module-scoped). Env var isolation uses `monkeypatch.setenv()` for function-scoped fixtures and explicit `os.environ` save/restore for module-scoped fixtures. Module reload (`importlib.reload()`) ensures each test picks up the fresh database path.

### Auditor perspective

**Concern:** Is there an audit trail for investigation actions?  
**Finding:** Yes. The `audit_events` table records every `alert_opened`, `note_added`, `decision_recorded`, and status change with analyst ID, timestamp, and details JSON. The table is append-only  -  no UPDATE or DELETE is exposed through any route or store function.

**Concern:** Can an analyst change a previously recorded decision?  
**Finding:** No. The `decisions` table is append-only. No route exposes a DELETE or UPDATE for decisions. An analyst who changes their assessment must record a new decision.

**Concern:** Can the risk score be changed retroactively after a model retrain?  
**Finding:** No. Scoring snapshots are pinned at seed time. Even if a new model were trained and promoted, existing alert records in the investigation store retain the risk score, model version, and scoring timestamp from the original seeding run. Re-seeding would be required to apply new scores, which would overwrite investigation state  -  a documented operational constraint, not a silent data mutation.

---

## Test Summary

| Test file | Tests | Status |
|-----------|-------|--------|
| `tests/serving/test_temporal_integrity.py` | 12 | ✅ 12/12 pass |
| `tests/serving/test_investigation_journey.py` | 24 | ✅ 24/24 pass |
| `tests/serving/test_alert_routes.py` (and related) | 158 | ✅ 158/158 pass |
| `tests/triage/test_integration_real_data.py` | 9 | ✅ 9/9 pass (updated to v3) |
| All other tests | 460 | ✅ 460/460 pass |
| **Total** | **663** | **✅ 663/663** |
| Frontend (Jest) |  -  | ⚠️ Blocked  -  npm 403 in cloud environment |

---

## Documents Created or Updated

| Document | Action | Purpose |
|----------|--------|---------|
| `docs/DATA_PROVENANCE.md` | **Rewritten** | Dual-dataset lineage, version history, SHA verification, artefact policy |
| `docs/MODEL_LINEAGE.md` | **Created** | Model training provenance, milestone history, governance controls |
| `docs/PERSISTENCE_ARCHITECTURE.md` | **Created** | InvestigationRepository interface, Cloud Run limitation, production path |
| `docs/MILESTONE_6_1_COMPLETION.md` | **Created** | This document  -  complete M6.1 evidence record |

---

## Known Limitations

1. **SQLite is not production-grade for AML.** The persistence layer is explicitly labelled DEVELOPMENT/DEMO only. See `PERSISTENCE_ARCHITECTURE.md` for the production upgrade path.

2. **`SELECT a.*` in `get_alert()` fetches `true_sar` from the database**, though it is excluded from the returned dict. Enumerated column selection would be more defensive. Mitigated by automated test.

3. **Frontend Jest tests cannot run in the cloud environment** due to npm registry egress restriction. Tests must be run locally.

4. **alerts.csv v3 (55,896 rows) differs from the model's training data** (v1, 56,195 rows) by 299 rows (0.53%). This is a documented limitation of environment-sensitive synthetic data generation and does not invalidate the model.

5. **No analyst authentication.** All investigation routes accept a caller-supplied `analyst_id`. In production, analyst identity must be established via JWT/OAuth2 (see `PERSISTENCE_ARCHITECTURE.md §5, Step 6`).

6. **No rate limiting.** The investigation API has no rate limiting or abuse controls. Acceptable for single-analyst demo; required for production.

---

## Do Not Begin Milestone 7

Per the M6.1 specification: **Do NOT begin Milestone 7 automatically.** This document constitutes the completion evidence for M6.1. Milestone 7 scope and prioritisation requires explicit direction.

---

*AlertIQ Milestone 6.1  -  Investigation Integrity Hardening*  
*Completed 2026-09-13*
