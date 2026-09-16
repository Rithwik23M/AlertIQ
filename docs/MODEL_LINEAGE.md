# AlertIQ  -  Model Lineage Record

**Document type:** Model lineage and training provenance  
**Created:** 2026-09-13 (M6.1  -  Investigation Integrity Hardening)

---

## 1. Summary

| Field | Value |
|-------|-------|
| Current champion | `1.0.0` |
| Trained | 2026-09-13T12:39:23 UTC |
| Training rows | 44,956 (train + validation from alerts.csv v1) |
| Schema version | 1 |
| Threshold | 0.3972 (capacity-ranked; see below) |
| Operating mode | `capacity_ranking` |
| Governing ADR | ADR-M4-05: No retraining during serving |
| Retrained in M6? | **No** |
| Retrained in M6.1? | **No** |

---

## 2. Training Data Lineage

| Property | Value |
|----------|-------|
| Source file | `data/simulation/alerts.csv` **v1** |
| SHA-256 (v1) | `15cea79b033dee015e20f432040f5cb71d891a1ad52c482c5296a5c0dd94f67d` |
| Row count (v1) | 56,195 |
| Split used | 60% train / 20% validation / 20% holdout (time-ordered) |
| Train rows | 33,717 |
| Validation rows | 11,239 |
| Train + Val rows | 44,956 ← matches `training_rows` in registry |
| Holdout rows | 11,239 (held out; not used for training or threshold selection) |
| Temporal boundary (train/val) | 2023-01-01 → 2023-05-23 |
| Temporal boundary (holdout) | 2023-05-24 → 2023-06-30 |

**Training/serving population drift:** The current on-disk `alerts.csv` is v3 (55,896 rows, SHA `3ae95fb5`)  -  a re-simulation of the same parameters. Row count differs by 299 (0.53%). All 300 accounts are present in both versions. Features are computed from the same simulation logic. This drift does not invalidate the model but is a known limitation of environment-sensitive synthetic data. See `DATA_PROVENANCE.md` for version history.

---

## 3. Milestone History

| Milestone | Action | Model version | Training data |
|-----------|--------|--------------|---------------|
| M4 | Train and register champion | 1.0.0 (new) | alerts.csv v1 (56,195 rows) |
| M5 | Deploy serving API | 1.0.0 (loaded) | No change |
| M6 | Build investigation workspace | 1.0.0 (loaded) | No change  -  scored on alerts.csv v3 (55,896 rows) |
| M6.1 | Integrity hardening | 1.0.0 (loaded) | No change  -  re-seeded store from alerts.csv v3 |

**Finding:** AlertIQ has had exactly one model training run, producing version 1.0.0. No retraining, fine-tuning, or version bump has occurred since M4.

---

## 4. Why M6 Did Not Retrain

M6 (Analyst Investigation Workspace) added investigation UI and API routes. Retraining during serving is prohibited by ADR-M4-05, which establishes:

> *"Model version promotion must be decoupled from feature releases. The serving layer loads a registered champion artifact. Retraining requires a new experiment, a new registered version, champion/challenger evaluation, and explicit promotion  -  not an implicit side effect of UI work."*

There was no business or technical trigger for retraining in M6. The model was loaded unchanged from `models/1.0.0/model.joblib`.

---

## 5. Model Artifact Inventory

| File | Purpose |
|------|---------|
| `models/registry.json` | Champion/challenger registry; version index |
| `models/1.0.0/model.joblib` | Serialised model artifact (dict containing scorer, metadata) |

**Artifact contents:**

| Field | Value |
|-------|-------|
| `model_version` | `1.0.0` |
| `schema_version` | `1` |
| `trained_at` | `2026-09-13T12:39:23.840308+00:00` |
| `training_rows` | `44956` |
| `best_iter` | `120` |
| `threshold` | `0.3972` |
| `operating_mode` | `capacity_ranking` |
| `notes` | `"Trained on 44956 rows (train+val)"` |
| `feature_columns` | 24 features: f01_vol_7d_log … f24_account_jurisdiction_score |

---

## 6. Threshold Derivation

The threshold `0.3972` is derived by capacity ranking, not a fixed prior. At training time, the threshold is set to the score at the 80th percentile of the validation set  -  i.e., the score that places 20% of alerts above it. This ensures the top-20% priority band is maintained regardless of score distribution drift.

At seed time, the seed script applies this threshold to the full alerts population to identify the capacity band (100 of 500 sampled alerts in the top-20% band for the demo dataset).

---

## 7. Immutability of Historical Scoring Snapshots

Each alert record in the investigation store includes:

| Field | Purpose |
|-------|---------|
| `risk_score` | The calibrated probability at scoring time |
| `scored_at` | UTC timestamp of the scoring run |
| `model_version` | `"1.0.0"`  -  pinned at seed time |
| `schema_version` | `1`  -  feature schema version used |

These fields are written once at seed time by `seed_alert_store.py` and are **never updated by the investigation API**. The `upsert_alert()` function will overwrite them if the seed is re-run, but no API route (GET or POST) modifies `risk_score`, `scored_at`, or `model_version`.

This enforces the principle that the model's assessment of an alert at the time of investigation must not be retroactively changed by a later model version or re-scoring. The E2E test in `tests/serving/test_investigation_journey.py` verifies that the risk score is unchanged after an investigation decision is recorded.

---

## 8. Champion/Challenger Framework Status

At M4, the registry was designed to support champion/challenger evaluation. At M6.1 there is only one registered version (1.0.0). Future retraining must follow this process:

1. Train new model → register as candidate (not champion) with a new version
2. Run evaluation on holdout or out-of-time dataset
3. Compare AUC-ROC, precision@K, FPR against current champion
4. If challenger wins by ≥ 2% AUC-ROC margin: promote to champion
5. Keep prior champion in registry for rollback; do not delete it
6. Update `registry.json` champion flag; redeploy serving API
7. Re-seed investigation store with new champion scores (alert scores are model-version-pinned)

---

## 9. Governance

| Control | Status |
|---------|--------|
| `true_sar` ground truth never returned by API | ✅ Verified  -  not present in any GET response |
| Scoring snapshot immutable after investigation opens | ✅ No API route modifies risk_score |
| No automatic retraining from analyst decisions | ✅ `decisions` table is not read by any model training path |
| Model cannot select analyst decision automatically | ✅ No auto-decision logic in serving layer |
| Champion requires explicit promotion | ✅ `is_champion` flag must be set manually in registry |

---

*This document was created by Milestone 6.1 to fulfil the model lineage requirement of the Investigation Integrity Hardening review. It must be updated whenever a new model version is trained or promoted.*
