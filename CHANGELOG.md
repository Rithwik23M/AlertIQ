# Changelog

All notable changes to AlertIQ are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2026-09-13

First stable release. AlertIQ is an AML alert triage engine and investigation workspace built on synthetic transaction data.

### Added

**Data layer**
- Transaction simulator with 3,000 synthetic accounts across a 6-month window (Jan–Jul 2023)
- 8 money-laundering typologies: structuring, cash-intensive business, professional ML, shell company layering, real estate, cross-border, trade-based, virtual assets
- 55,896 synthetic alerts, 191,364 transactions; SHA-256 dataset fingerprinting (see DATA_PROVENANCE.md)
- Dataset versioning policy — alerts.csv v3, transactions.csv v1

**ML triage engine**
- 24 behavioural features: velocity ratios, jurisdiction entropy, structuring indicators, PEP/adverse-media flags, round-number clustering
- HistGradientBoostingClassifier (scikit-learn) with two-phase training: phase 1 early stopping on validation, phase 2 refit on train+val
- Leakage-safe temporal splits: 60% train / 20% val / 20% holdout, strictly time-ordered
- Capacity-based threshold: score at 80th percentile of validation scores — keeps exactly 20% of queue above threshold
- Holdout performance: AUC-ROC 0.979, Recall@20% 100%, F1 0.810
- Walk-forward validation: 3 expanding windows, AUC-ROC stable at 0.978–0.981
- Baseline comparisons: random (AUC 0.509) and severity-only (AUC 0.564) scorers

**Robustness and monitoring**
- Population Stability Index (PSI) drift detection per feature
- Score calibration analysis
- Walk-forward validation framework
- Champion/challenger model comparison framework
- Stress scenario analysis

**Model registry**
- Versioned model artefacts: `models/{version}/model.joblib`
- SHA-256 artefact verification
- `models/registry.json` with training metadata and champion flag

**Serving layer**
- Starlette async REST API, 9 endpoints
- `InvestigationRepository` ABC for production-upgrade-ready persistence
- SQLite WAL investigation store (alerts, transactions, notes, decisions, state)
- Deterministic explainability signals: 15 features classified as FACTUAL_EVIDENCE / MODEL_SIGNAL / HUMAN_DECISION
- Health (`/health`) and metrics (`/metrics`) endpoints
- Structured Python logging throughout

**Security controls**
- `true_sar` never exposed via any API endpoint (verified by automated test)
- Temporal evidence integrity: `WHERE txn_date <= alert_date` enforced in transaction history
- Analyst notes never forwarded to any external service

**Investigation workspace (Next.js)**
- Alert queue sorted by risk score with status filters
- Alert detail view: explainability signals, transaction timeline, risk badge
- Note-taking panel with append-only display
- Decision panel: escalate / close / needs-further-review with audit log
- QualityWarning component for data quality flag display
- TypeScript types for all API response shapes

**Infrastructure and DevOps**
- Dockerfile (multi-stage build)
- Google Cloud Run deployment: staging and production manifests
- Terraform configuration: Cloud Run services, IAM, networking
- GitHub Actions CI: pytest, ruff, mypy on push and PR
- GitHub Actions CD: Docker build, push to Artifact Registry, deploy to Cloud Run

**Testing**
- 663 passing tests across simulation, triage, robustness, serving, and operational suites
- E2E investigation journey: 24 tests covering the full analyst workflow
- Temporal integrity: 12 dedicated tests for `WHERE txn_date <= alert_date` and `true_sar` suppression
- Integration tests: holdout evaluation against provenance-verified dataset

**Documentation**
- Root README with architecture diagrams (4 Mermaid), performance tables, quick start, tech stack
- MODEL_CARD.md, MODEL_LINEAGE.md, DATA_PROVENANCE.md, SERVING_ARCHITECTURE.md
- PERSISTENCE_ARCHITECTURE.md, MODEL_MONITORING.md, MODEL_RISK_ARCHITECTURE.md
- DEPLOYMENT.md, CI_CD.md, OPERATIONS_RUNBOOK.md
- DEMO_SCRIPT.md, INTERVIEW_GUIDE.md, PORTFOLIO_DESCRIPTION.md, OWNER_HANDOVER.md
- docs/README.md documentation index
- docs/history/ — 8 milestone completion records (M1–M6.1)

### Changed

- `pyproject.toml` version: 0.1.0 → 1.0.0

### Known Issues

- SQLite persistence resets on Cloud Run container restart (ephemeral storage)
- No authentication or authorisation layer
- No rate limiting
- Jest tests blocked in cloud CI environment due to npm registry egress restrictions (must run locally)

---

## [0.6.1] — 2026-09-13 (internal milestone)

Temporal evidence integrity hardening. See [docs/MILESTONE_6_1_COMPLETION.md](docs/MILESTONE_6_1_COMPLETION.md).

## [0.6.0] — 2026-09-13 (internal milestone)

SQLite investigation store, explainability signals, investigation workspace backend. See [docs/history/MILESTONE_6_COMPLETION.md](docs/history/MILESTONE_6_COMPLETION.md).

## [0.5.1] — 2026-09-13 (internal milestone)

Next.js investigation workspace frontend. See [docs/history/MILESTONE_5_1_COMPLETION.md](docs/history/MILESTONE_5_1_COMPLETION.md).

## [0.5.0] — 2026-09-13 (internal milestone)

Starlette serving layer with 9 REST endpoints. See [docs/history/MILESTONE_5_COMPLETION.md](docs/history/MILESTONE_5_COMPLETION.md).

## [0.4.0] — 2026-09-13 (internal milestone)

Model registry and serialisation. See [docs/history/MILESTONE_4_COMPLETION.md](docs/history/MILESTONE_4_COMPLETION.md).

## [0.3.0] — 2026-09-13 (internal milestone)

Robustness suite: walk-forward, PSI drift, calibration, stress. See [docs/history/MILESTONE_3_COMPLETION.md](docs/history/MILESTONE_3_COMPLETION.md).

## [0.2.1] — 2026-09-13 (internal milestone)

Evaluation framework: Recall@K, capacity threshold, AUC-ROC vs. AUC-PR. See [docs/history/MILESTONE_2_1_COMPLETION.md](docs/history/MILESTONE_2_1_COMPLETION.md).

## [0.2.0] — 2026-09-13 (internal milestone)

ML triage engine: 24 features, LightGBM, leakage-safe temporal splits. See [docs/history/MILESTONE_2_COMPLETION.md](docs/history/MILESTONE_2_COMPLETION.md).

## [0.1.0] — 2026-09-13 (internal milestone)

Transaction simulator: 3,000 accounts, 8 typologies, SAR labelling. See [docs/history/MILESTONE_1_COMPLETION.md](docs/history/MILESTONE_1_COMPLETION.md).
