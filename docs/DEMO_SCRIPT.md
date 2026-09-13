# AlertIQ — Demo Script

**Target audience:** Technical recruiter, hiring manager, or senior engineer  
**Duration:** 3–5 minutes  
**Setup required:** API running on `localhost:8000`, UI running on `localhost:3000`, demo data seeded

---

## Pre-Demo Setup (Before Audience Arrives)

```bash
# 1. Seed the investigation store with demonstration alerts
python scripts/seed_alert_store.py

# 2. Start API server
uvicorn alertiq.serving.app:app --port 8000

# 3. Start UI
cd ui && npm run dev
```

Verify health: `curl http://localhost:8000/health` → `{"status": "ok"}`

Open browser to `http://localhost:3000`

---

## Demo Narrative (3–5 minutes)

### Opening (30 seconds)

> "This is AlertIQ — an AML alert triage engine. The core problem it solves is alert overload. Banks generate thousands of AML alerts daily, but investigators can realistically review maybe 15–20% of them. Today I'll show you two things: the ML ranking engine that prioritises the queue, and the investigation workspace where analysts actually work a case."

---

### Part 1: The Ranked Queue (1 minute)

**Show:** The alert queue page sorted by risk score (high to low)

> "The model scores every alert with a SAR probability — how likely is this activity to be genuine money laundering. Investigators work top-down. The key design question wasn't 'how accurate is the model' in the abstract — it was 'if an investigator stops at their capacity limit, what fraction of real SARs did they catch?' That's Recall at K."

**Show:** Performance numbers in the README or a results summary

> "On held-out data the model achieved Recall@20% of 100% — meaning if investigators reviewed the top 20% of ranked alerts, they caught every true SAR. Compared to reviewing randomly, that's a 5x improvement."

**Pause for questions if any.**

---

### Part 2: The Investigation Workspace (90 seconds)

**Click into a high-risk alert**

> "When an investigator opens an alert, they see three things: the risk score and confidence, the transaction history, and explainability signals explaining what drove the risk score."

**Scroll to transaction timeline**

> "The transaction history enforces a temporal filter — investigators only see transactions that occurred before the alert was raised. This sounds obvious but it's actually a compliance requirement. If you're investigating whether a series of transactions was suspicious in April, you can't use information that became available in June. The filter is `WHERE txn_date <= alert_date` and it's verified by a dedicated test suite."

**Scroll to explainability signals**

> "These signals are completely deterministic — no LLM, no black box. Each one maps to a specific feature the model used. '90-day velocity ratio' of 4.2 means transaction volume in the last 90 days was 4.2x the account's baseline. 'Structuring indicator' means 3+ deposits just below the reporting threshold. An analyst can trace every signal back to a specific transaction in the timeline above."

---

### Part 3: Making a Decision (30 seconds)

**Show the notes panel and decision panel**

> "The analyst adds notes — append-only, never editable after submission, full audit trail. Then records a decision: escalate for SAR filing, close as false positive, or flag for further review. Critically, the ground truth label is never shown — the analyst doesn't know whether this alert is a real SAR. That's intentional — it mirrors real investigation practice."

---

### Part 4: Engineering Story (60 seconds)

> "A few engineering decisions worth noting:

> First, the threshold is set at the 80th percentile of validation scores — not at F1-optimal. This directly operationalises the 'review top 20%' capacity policy rather than assuming equal costs for false positives and false negatives.

> Second, the training uses two phases. Phase 1 uses early stopping on a held-out validation set to find the right number of iterations. Phase 2 refits on train+val combined using that number — so all labelled data is used without leaking the holdout.

> Third, the persistence layer uses an abstract repository interface. The demo runs on SQLite, but the API has no SQLite-specific calls — the interface can be swapped to PostgreSQL without touching any route handler.

> The test suite has 663 passing tests including E2E journey tests that simulate the full analyst workflow from queue to decision."

---

### Closing (30 seconds)

> "AlertIQ was built in 7 milestones over the course of this project. The simulation, ML engine, serving layer, frontend, and investigation store were all built from scratch. The GitHub repository has architecture diagrams, the full data provenance chain, model lineage, and an operations runbook. The README has reproduction instructions for every performance figure shown today — I can run them live if you want."

---

## Anticipated Questions and Answers

**Q: Why is Recall@20% 100%? That seems too good.**

> "You're right to be suspicious. This is simulated data — the simulator generates data with clean typology labels, so the ML model can learn patterns that are unrealistically clean. Real AML alert data has noisy labels, adversarial actors, and severe class imbalance problems that don't show up in simulation. I'd expect 70–80% Recall@20% on real data, which is already a significant improvement over manual review. I document this explicitly in the README."

**Q: What happens when the model goes stale?**

> "The robustness module computes PSI — Population Stability Index — per feature on a rolling window. A PSI above 0.2 is flagged as a significant drift requiring investigation. Walk-forward validation showed the model is stable across the three time windows we tested. For retraining, I've documented a human-in-the-loop governance framework — the model shouldn't retrain automatically from analyst decisions without a formal validation step."

**Q: Why SQLite instead of a real database?**

> "SQLite with WAL mode handles concurrent reads well for a demo. The `InvestigationRepository` abstract class means the implementation can be swapped to PostgreSQL without changing any API route. I document this as a known limitation and the upgrade path in PERSISTENCE_ARCHITECTURE.md."

**Q: Can I see the code?**

> "Yes — the repository is at github.com/rithwikm7/alertiq. The ML training pipeline is in `src/alertiq/triage/`, the serving layer in `src/alertiq/serving/`, and the full test suite in `tests/`."

---

## Fallback (if UI is unavailable)

Run API demo entirely via curl:

```bash
# Health check
curl http://localhost:8000/health

# List alerts (sorted by risk)
curl "http://localhost:8000/alerts?sort=risk_score&order=desc" | python -m json.tool | head -40

# Get a specific alert
curl http://localhost:8000/alerts/DEMO-001 | python -m json.tool

# Get transactions (temporal filter active)
curl http://localhost:8000/alerts/DEMO-001/transactions | python -m json.tool

# Add a note
curl -X POST http://localhost:8000/alerts/DEMO-001/notes \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "demo", "note_text": "Three structuring transactions below $10k. Escalating."}'

# Record a decision
curl -X POST http://localhost:8000/alerts/DEMO-001/decision \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "demo", "outcome": "escalate", "rationale": "Strong structuring indicators"}'
```
