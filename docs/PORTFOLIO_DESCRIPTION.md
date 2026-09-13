# AlertIQ — Portfolio Description

Material for CV, LinkedIn, portfolio sites, and recruiter outreach. Choose the version appropriate to the audience and word-count limit.

---

## One-Line Pitch

**AlertIQ** — AML alert triage engine that ranks 55,000+ synthetic financial crime alerts using LightGBM, achieving 100% SAR recall at 20% investigator capacity.

---

## 50-Word Description (Portfolio card / project brief)

Built an end-to-end AML alert triage engine on synthetic transaction data. LightGBM model ranks 55,896 alerts by SAR probability with AUC-ROC 0.979. Investigators reviewing the top 20% of the ranked queue capture 100% of true SARs vs. 20% at random. Includes a full Starlette API and Next.js investigation workspace.

---

## 100-Word Description (Portfolio site / GitHub bio)

AlertIQ is an Anti-Money Laundering alert triage and investigation platform. The core problem: banks generate more AML alerts than investigators can review. AlertIQ ranks alerts by estimated SAR probability using LightGBM trained on 24 behavioural features — velocity ratios, jurisdiction entropy, structuring indicators, PEP flags — engineered from a purpose-built transaction simulator with 55,896 alerts across 8 money-laundering typologies.

The ML engine achieves AUC-ROC 0.979 and Recall@20% of 100% on held-out simulated data. A Starlette REST API and Next.js frontend provide a full investigation workspace with temporal evidence integrity, deterministic explainability signals, and an immutable audit trail. Deployed on Google Cloud Run via Terraform.

---

## 250-Word Description (Technical portfolio / project case study)

**The Problem**

Anti-Money Laundering compliance teams generate thousands of alerts daily. Investigators can realistically review only 15–25% of the queue. Without prioritisation, alert review is first-in-first-out — SAR-bearing cases have the same probability of review as false positives.

**The Solution**

AlertIQ is a full-stack AML alert triage and investigation system. The ML engine trains a LightGBM gradient boosting classifier on 24 behavioural features engineered from a purpose-built transaction simulator: 55,896 alerts, 191,364 transactions, 3,000 accounts, 8 money-laundering typologies (structuring, layering, shell company, trade-based, virtual assets, and others).

The training protocol uses leakage-safe temporal splits — training data is strictly older than validation and holdout — and a two-phase training approach that maximises labelled data usage. The threshold is set at the 80th percentile of validation scores, directly implementing a "review top 20%" capacity policy. On held-out data the model achieves AUC-ROC 0.979 and Recall@20% of 100%, compared to 20.3% for random and 34.8% for a severity-only baseline.

**The Investigation Workspace**

A Starlette REST API (9 endpoints) and Next.js frontend provide a complete investigation environment. Compliance with AML evidence standards is enforced by design: transaction history uses a `WHERE txn_date <= alert_date` filter (temporal integrity), ground truth labels are never returned via any endpoint, and analyst notes are never forwarded externally. Explainability signals are computed deterministically from stored features — no LLM, no external calls.

**Engineering**

663 passing tests including E2E journey tests, walk-forward validation, PSI drift detection, abstract repository interface for production database swap-in, Terraform-managed Google Cloud Run deployment.

---

## Role-Targeted CV Bullets

Choose the bullets most relevant to the role you're applying for. All figures are from held-out simulated data.

### Data Science / ML Engineer Roles

- Built end-to-end ML pipeline for AML alert prioritisation: feature engineering (24 features), leakage-safe temporal splits, two-phase LightGBM training, capacity-based threshold calibration; achieved AUC-ROC 0.979 and Recall@20% of 100% on held-out data
- Designed capacity-based decision threshold (80th percentile of validation scores) operationalising a business constraint — "review top 20% of alerts" — rather than optimising F1; improved SAR detection rate from 20% (random) to 100% at same analyst capacity
- Implemented walk-forward validation across 3 expanding time windows; AUC-ROC stable at 0.978–0.981 demonstrating model temporal stability on synthetic data
- Engineered PSI-based feature drift monitoring system detecting distribution shifts across 24 behavioural features with interpretable alert thresholds (PSI > 0.2 = investigate)

### Backend / API Engineer Roles

- Built Starlette async REST API (9 endpoints) for AML investigation workflow; implemented `InvestigationRepository` ABC enabling production database swap from SQLite to PostgreSQL without route handler changes
- Enforced temporal evidence integrity via SQL filter (`WHERE txn_date <= alert_date`) on transaction history endpoint; verified by 12 dedicated integration tests
- Designed append-only investigation audit trail (notes, decisions, status transitions) with `true_sar` ground truth suppression — ground truth never exposed via any API endpoint
- Implemented deterministic explainability signals from stored feature values (15 signals, 3 classification types: FACTUAL_EVIDENCE/MODEL_SIGNAL/HUMAN_DECISION) — no LLM dependency, fully reproducible

### Full-Stack Engineer Roles

- Delivered full-stack AML triage platform: Python/Starlette backend, Next.js 14/TypeScript frontend, SQLite investigation store; 663 passing tests including 24 E2E journey tests covering the full analyst workflow
- Built React investigation workspace (TypeScript, Recharts) with ranked alert queue, transaction timeline, explainability signal display, note-taking panel, and audit-logged decision recording

### DevOps / Platform Engineer Roles

- Containerised AML triage application with multi-stage Docker build; deployed to Google Cloud Run (staging + production) via Terraform; CI/CD pipeline on GitHub Actions (test → lint → build → deploy)
- Implemented model artefact registry with versioned `model.joblib` files, SHA-256 verification, and JSON registry tracking training provenance; supports champion/challenger model comparison

### Data Engineering Roles

- Built AML transaction simulator generating 191,364 synthetic transactions across 3,000 accounts with 8 money-laundering typologies; implemented SHA-256 dataset fingerprinting and versioned derived artefact policy
- Designed 3-layer temporal data pipeline: simulation → feature engineering → training splits with strict chronological ordering and holdout embargo; documented in DATA_PROVENANCE.md with full version history

### Quantitative / Risk Model Roles

- Designed evidence-based AML triage model with explicit baseline ladder (random → severity → ML); demonstrated 5x improvement in SAR detection efficiency at 20% analyst capacity on held-out simulated data
- Documented model limitations, overfitting risks, and production performance gap (simulated AUC 0.979 vs. expected 0.70–0.85 on real data) in MODEL_CARD.md; implemented PSI-based monitoring and human-in-the-loop retraining governance

### Fintech / Compliance Technology Roles

- Built AML alert triage engine enforcing regulatory-grade evidence standards: pre-alert transaction filtering, ground truth suppression, immutable audit trail, analyst-opaque scoring — architected to mirror production compliance requirements
- Evaluated capacity-based alert prioritisation quantitatively: Recall@20% improved from 20.3% (random) to 100.0% (ML) on synthetic data, with severity baseline at 34.8% — demonstrating 2.9× improvement over the practical baseline

---

## LinkedIn Summary (200 words)

I'm a software engineer focused on applied ML and data engineering. My recent portfolio project is AlertIQ — an AML (Anti-Money Laundering) alert triage and investigation platform.

The core engineering challenge was building a system that investigates correctly: temporal evidence integrity (investigators only see pre-alert transactions), ground truth suppression (the model's label never leaked to analysts), deterministic explainability (no LLM, no black box), and an immutable audit trail. These constraints shaped the entire architecture.

The ML side used LightGBM with leakage-safe temporal splits, two-phase training, and a capacity-based threshold calibrated to a 20% investigator workload. On held-out simulated data: AUC-ROC 0.979, Recall@20% of 100% (vs. 34.8% severity-only, 20.3% random).

The stack: Starlette API, Next.js frontend, SQLite investigation store behind an abstract repository interface, Google Cloud Run via Terraform, GitHub Actions CI/CD. 663 passing tests including E2E journey tests for the full analyst workflow.

I build things that work, document what they don't, and can explain every architectural decision in an interview.

GitHub: github.com/rithwikm7/alertiq
