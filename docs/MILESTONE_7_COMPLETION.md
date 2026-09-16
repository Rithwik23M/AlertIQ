# Milestone 7 Completion  -  Portfolio Launch, Demo & Recruiter Readiness

**Completed:** 2026-09-13  
**Previous milestone:** M6.1  -  Temporal Evidence Integrity Hardening  
**Status:** COMPLETE  -  v1.0.0 ship recommendation  

---

## What Was Built in M7

M7 converted AlertIQ from a technically complete project into a portfolio-presentable product. No new features were added. All changes are documentation, presentation, and repository governance.

### Deliverables

| Item | Status | File |
|---|---|---|
| Repository audit | ✅ | This document  -  see audit section |
| .gitignore | ✅ | `.gitignore` |
| README rebuild | ✅ | `README.md`  -  4 architecture diagrams, performance tables, quick start, tech stack |
| pyproject.toml version | ✅ | `pyproject.toml` → 1.0.0 |
| docs/history/ migration | ✅ | 8 milestone completion docs moved |
| docs/README.md index | ✅ | `docs/README.md`  -  8 categories |
| LICENSE | ✅ | `LICENSE`  -  MIT |
| CONTRIBUTING.md | ✅ | `CONTRIBUTING.md`  -  setup, branching, tests, formatting, PR requirements |
| SECURITY.md | ✅ | `SECURITY.md`  -  security controls, synthetic data disclaimer, known limitations |
| CHANGELOG.md | ✅ | `CHANGELOG.md`  -  v1.0.0 release notes, internal milestone history |
| GitHub PR template | ✅ | `.github/PULL_REQUEST_TEMPLATE.md` |
| GitHub issue template | ✅ | `.github/ISSUE_TEMPLATE/bug_report.md` |
| DEMO_SCRIPT.md | ✅ | `docs/DEMO_SCRIPT.md`  -  3–5 min structured demo + Q&A |
| INTERVIEW_GUIDE.md | ✅ | `docs/INTERVIEW_GUIDE.md`  -  22+ Q&A with 30s/2min/5min answers |
| PORTFOLIO_DESCRIPTION.md | ✅ | `docs/PORTFOLIO_DESCRIPTION.md`  -  50/100/250-word, 8 CV bullets, LinkedIn |
| OWNER_HANDOVER.md | ✅ | `docs/OWNER_HANDOVER.md`  -  personal reference, known issues, what's next |

---

## Repository Audit Findings

### Files Archived (moved to docs/history/)

8 milestone completion docs (M1 through M6) moved to `docs/history/`. These are build evidence  -  do not delete.

### Files Created (net new)

`.gitignore`, `README.md`, `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/README.md`, `docs/DEMO_SCRIPT.md`, `docs/INTERVIEW_GUIDE.md`, `docs/PORTFOLIO_DESCRIPTION.md`, `docs/OWNER_HANDOVER.md`, `docs/history/` directory, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug_report.md`

### Files Modified

`pyproject.toml`  -  version 0.1.0 → 1.0.0

### Files That Should Be Gitignored (not in this repo)

`.venv/`, `__pycache__/`, `.pytest_cache/`, `data/alert_store.db`  -  all now covered by `.gitignore`.

### Files Retained As-Is

All source code, all tests, all robustness data, model artefacts, infrastructure code, scripts  -  no changes.

### Known Issue Deferred

`SELECT a.*` fragility in `alert_store.get_alert()`  -  documented in OWNER_HANDOVER.md, guarded by test. Deferred to v1.1.0.

---

## Adversarial Review  -  Recruiter (60-Second Assessment)

A technical recruiter scanning the repository for 60 seconds would see:

**First glance (10 seconds):** Clean root  -  README, LICENSE, CONTRIBUTING, SECURITY, CHANGELOG. Repository structure looks professional, not tutorial-like.

**README hero (20 seconds):** Problem statement is clear in two sentences. Performance table is concrete and specific. Quick start is copy-pasteable. Architecture diagrams load inline.

**Concerns:** No live demo URL  -  Cloud Run deployment is documented but not confirmed live in this environment. No screenshots  -  README references screenshots but none are embedded (the M7 spec item "screenshot/demo preparation" requires running the application; screenshots cannot be generated in the cloud build environment without a browser).

**What works:** The data disclosure box is the right move  -  it's proactive transparency about synthetic data and high performance figures. A recruiter who reads it will trust the rest more.

**Assessment:** The repository looks like professional work, not a tutorial project. The absence of screenshots is the biggest gap. Add screenshots before sending this to recruiters.

---

## Senior Engineer Review

### Architecture  -  7/10

**Strengths:**
- `InvestigationRepository` ABC is a clean production-swap design
- Temporal split design is correct and well-documented
- Two-phase training is principled and reproducible

**Issues:**
- `SELECT a.*` in `get_alert()`  -  defence by exclusion for `true_sar`. Fragile. The test guards it but the fix is explicit column enumeration.
- `alert_store.py` handles both raw alert storage (immutable) and investigation state (mutable). These are different concerns. A future `AlertRepository` / `InvestigationRepository` separation would be cleaner.
- SQLite on Cloud Run with ephemeral storage  -  documented limitation, but makes the "deployed" claim misleading if the DB resets on restart.

### Correctness  -  9/10

- Temporal split logic is correct: no leakage verified by integration test
- Temporal evidence filter is correct: `WHERE txn_date <= alert_date` verified by 12 tests
- `true_sar` suppression is correct: verified by automated test
- Two-phase training logic is correct: best_iter from phase 1 applied in phase 2

**Issues:**
- Score calibration: the model outputs raw sigmoid probabilities, not calibrated probabilities. Calling them "SAR probability" is slightly misleading  -  they're scores, not calibrated probabilities. Platt scaling or isotonic regression would fix this.

### Testing  -  8/10

- 663 passing tests is strong for a portfolio project
- E2E journey tests demonstrate understanding of integration testing
- Temporal integrity tests are comprehensive (12 tests)
- Walk-forward validation is reproducible

**Issues:**
- Jest tests not running in CI due to egress restriction  -  UI test coverage is unverified in automated context
- No load or performance tests  -  the API response time claim in the smoke test isn't part of the test suite

### Security  -  7/10

- `true_sar` suppression: correct implementation, verified by test
- Temporal evidence integrity: correct implementation, comprehensive tests
- No authentication: documented, appropriate for demo

**Issues:**
- No input sanitisation tests  -  route handlers accept arbitrary strings for analyst_id, note_text, etc.
- No rate limiting  -  API can be flooded
- `SELECT a.*` as discussed above

### Data Integrity  -  9/10

- SHA-256 dataset fingerprinting is correct and tested
- Version history is documented in DATA_PROVENANCE.md
- Model lineage is tracked in MODEL_LINEAGE.md and registry.json

### Documentation  -  10/10

- README is exceptional for a portfolio project
- DATA_PROVENANCE.md, MODEL_CARD.md, MODEL_LINEAGE.md, PERSISTENCE_ARCHITECTURE.md  -  each covers its domain completely
- OWNER_HANDOVER.md is unusually thorough

---

## Final Scorecard

| Category | Score | Notes |
|---|---|---|
| Problem significance | 88/100 | Real AML alert overload problem; synthetic data caveat |
| Originality | 82/100 | End-to-end build with investigation workspace; temporal integrity is a genuine differentiator |
| Technical depth | 85/100 | Two-phase training, temporal splits, PSI monitoring, ABC persistence design |
| Real-world usefulness | 72/100 | Strong conceptually; synthetic data and no auth limit direct utility |
| Portfolio strength | 88/100 | Coherent narrative, multiple skill areas, honest limitations |
| Recruiter appeal | 85/100 | AML/fintech niche maps to financial services roles; needs screenshots |
| Data quality | 78/100 | Simulated; provenance well-documented |
| Feasibility | 95/100 | Fully functional and testable |
| Demonstrability | 80/100 | Demo script exists; needs live screenshots; no deployed demo confirmed |
| Scalability | 70/100 | ABC design enables scaling; current SQLite is a bottleneck |
| Security depth | 75/100 | Core controls implemented and tested; no auth, no rate limiting |
| Testing | 82/100 | 663 tests; Jest gap in CI |
| Documentation | 95/100 | Exceptional for a portfolio project |

**Overall readiness: 83/100**

---

## What Prevents 100/100

1. **Screenshots missing**  -  The README describes a UI but no screenshots are embedded. This is the single biggest visual gap.
2. **No confirmed live deployment**  -  Cloud Run deployment is configured but not confirmed live in this environment. A live demo URL would significantly improve the landing experience.
3. **`SELECT a.*` fragility**  -  Minor code quality issue, documented and guarded.
4. **Synthetic data ceiling**  -  Inherent to the project; well-documented but limits direct comparability to production systems.
5. **No score calibration**  -  Model outputs are scores, not calibrated probabilities. Minor but technically important.
6. **Jest tests not in CI**  -  UI test coverage is not automated in the CI pipeline.

---

## Ship Recommendation

**Recommendation: SHIP as v1.0.0**

AlertIQ is ready for portfolio use. The codebase is technically sound, well-tested (663 passing tests), and honestly documented. The README is strong. The interview guide covers every likely challenge.

**Before sending to recruiter targets, complete:**
1. Add 3–6 screenshots to the README (alert queue, investigation workspace, explainability panel, decision panel)
2. Confirm a live Cloud Run deployment URL and add it to the README
3. Optionally: fix `SELECT a.*` → explicit column list (10-minute change)

**v1.1.0 backlog (after first interviews):**
- JWT authentication middleware
- PostgreSQL swap via `InvestigationRepository` ABC
- Score calibration (Platt scaling)
- Load test results
- SHAP-based explainability as alternative to threshold-based signals

---

## Test Summary at M7 Completion

All tests from prior milestones remain passing:

```
663 passed, 4 integration skipped (require alerts.csv)
```

No new tests were added in M7 (documentation-only milestone).

---

## Final Project Story

"We discovered that AML compliance teams face an alert overload problem  -  they can only review 15–20% of alerts daily, so most potentially suspicious activity goes uninvestigated.

The existing approach  -  first-in-first-out or severity-sorted review  -  is a weak baseline.

We hypothesised that a model trained on behavioural features could rank alerts so that the reviewed fraction contained a disproportionate share of true SARs.

We built AlertIQ: a transaction simulator (55,896 alerts, 8 typologies), a LightGBM triage engine (24 features, temporal splits, two-phase training), and a full investigation workspace (Starlette API, SQLite investigation store, Next.js frontend).

We evaluated it using Recall@K  -  the fraction of true SARs caught at a given investigator capacity limit. Against severity-only ranking (the practical baseline), AlertIQ improved Recall@20% from 34.8% to 100% on held-out simulated data.

That translates to: at the same investigator headcount, every genuine SAR is captured within the daily review quota  -  on this dataset.

The main limitations are: synthetic data (real-world performance would be 70–80% AUC-ROC, not 0.979), no authentication, SQLite not suitable for production scale, and no adversarial scenario testing.

In production I would next implement authentication, swap SQLite for PostgreSQL via the existing repository interface, add calibrated probabilities, and conduct adversarial testing against a money launderer who knows the feature set."
