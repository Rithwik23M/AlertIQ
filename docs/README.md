# AlertIQ  -  Documentation Index

This directory contains all project documentation. Start with the [root README](../README.md) for a project overview, architecture diagrams, and performance results.

---

## 1. Data

| Document | Description |
|---|---|
| [DATA_PROVENANCE.md](DATA_PROVENANCE.md) | Dataset fingerprints (SHA-256), version history for alerts.csv and transactions.csv, derived artefact policy |

---

## 2. Machine Learning

| Document | Description |
|---|---|
| [MODEL_CARD.md](MODEL_CARD.md) | Full model documentation: 24 features, training protocol, evaluation results, intended use, limitations |
| [MODEL_LINEAGE.md](MODEL_LINEAGE.md) | Model version history, training provenance, parameter record, retraining governance |
| [MODEL_MONITORING.md](MODEL_MONITORING.md) | PSI drift detection, walk-forward validation, retraining governance, alert thresholds |
| [MODEL_RISK_ARCHITECTURE.md](MODEL_RISK_ARCHITECTURE.md) | Model risk framework, validation methodology, compensating controls |

---

## 3. System Architecture

| Document | Description |
|---|---|
| [SERVING_ARCHITECTURE.md](SERVING_ARCHITECTURE.md) | API design, 9 endpoint reference, request/response schemas, security controls |
| [PERSISTENCE_ARCHITECTURE.md](PERSISTENCE_ARCHITECTURE.md) | Investigation store design, `InvestigationRepository` ABC, SQLite WAL, production upgrade path |

---

## 4. Operations

| Document | Description |
|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | Cloud Run deployment, Terraform configuration, staging/production manifests, rollback |
| [CI_CD.md](CI_CD.md) | GitHub Actions CI/CD pipeline, workflow configuration, quality gates |
| [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) | Incident response, health checks, debugging procedures, alerting |

---

## 5. Portfolio & Presentation

| Document | Description |
|---|---|
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md) | 3–5 minute structured demonstration covering ML ranking, investigation workspace, explainability |
| [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md) | 22+ technical interview Q&A with 30-second, 2-minute, and 5-minute answer variants |
| [PORTFOLIO_DESCRIPTION.md](PORTFOLIO_DESCRIPTION.md) | 50/100/250-word descriptions, 8 CV bullet variants, LinkedIn summary, role targeting |

---

## 6. Engineering Reference

| Document | Description |
|---|---|
| [OWNER_HANDOVER.md](OWNER_HANDOVER.md) | Comprehensive personal reference: architecture decisions, known issues, production upgrade path, what to build next |

---

## 7. Milestone Completion Records

Current milestone:

| Document | Description |
|---|---|
| [MILESTONE_6_1_COMPLETION.md](MILESTONE_6_1_COMPLETION.md) | Temporal evidence integrity hardening  -  663/663 tests, E2E journey validation |
| [MILESTONE_7_COMPLETION.md](MILESTONE_7_COMPLETION.md) | Portfolio launch, demo readiness, recruiter review, final scorecard |

Historical milestone records (build evidence, do not delete):

| Document | Description |
|---|---|
| [history/MILESTONE_1_COMPLETION.md](history/MILESTONE_1_COMPLETION.md) | Transaction simulator |
| [history/MILESTONE_2_COMPLETION.md](history/MILESTONE_2_COMPLETION.md) | ML triage engine |
| [history/MILESTONE_2_1_COMPLETION.md](history/MILESTONE_2_1_COMPLETION.md) | Evaluation framework |
| [history/MILESTONE_3_COMPLETION.md](history/MILESTONE_3_COMPLETION.md) | Robustness suite |
| [history/MILESTONE_4_COMPLETION.md](history/MILESTONE_4_COMPLETION.md) | Model registry |
| [history/MILESTONE_5_COMPLETION.md](history/MILESTONE_5_COMPLETION.md) | Starlette serving layer |
| [history/MILESTONE_5_1_COMPLETION.md](history/MILESTONE_5_1_COMPLETION.md) | Next.js investigation workspace |
| [history/MILESTONE_6_COMPLETION.md](history/MILESTONE_6_COMPLETION.md) | SQLite investigation store + explainability |

---

## 8. Root Project Files

| File | Description |
|---|---|
| [../README.md](../README.md) | Project overview, architecture, performance results, quick start |
| [../LICENSE](../LICENSE) | MIT License |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Development setup, branching convention, test requirements, PR process |
| [../SECURITY.md](../SECURITY.md) | Security policy, vulnerability reporting, synthetic data disclaimer |
| [../CHANGELOG.md](../CHANGELOG.md) | Version history and release notes |
| [../pyproject.toml](../pyproject.toml) | Python package metadata, dependencies, tool configuration |
