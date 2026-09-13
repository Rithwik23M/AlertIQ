# AlertIQ — Interview Guide

This guide prepares answers at three depths for the most likely technical and behavioural interview questions about AlertIQ. Have the 30-second answer ready for every question; expand to 2-minute or 5-minute when the interviewer asks "tell me more" or "go deeper."

---

## Project Overview Answers

### What is AlertIQ?

**30 seconds:**
> "AlertIQ is an AML alert triage engine. Banks generate more money-laundering alerts than investigators can review. I built a LightGBM model that ranks alerts by SAR probability so investigators catch the most suspicious cases within their capacity limit. There's also a full investigation workspace — transaction history, explainability signals, note-taking, and audit-logged decisions."

**2 minutes:**
> "AlertIQ has two parts. The ML triage engine scores every alert with a SAR probability using 24 behavioural features — velocity ratios, jurisdiction entropy, structuring indicators, PEP flags. Investigators work through the sorted queue and stop at their capacity limit. The key metric I designed around was Recall@K: if an investigator reviews the top 20% of alerts, what fraction of real SARs do they catch? On held-out data the model achieved 100% — compared to 20% for random and 35% for a severity-only baseline.

> The second part is the investigation workspace: a Starlette REST API with 9 endpoints, a SQLite investigation store with append-only notes and decisions, and a Next.js frontend. A key design constraint was temporal evidence integrity — the transaction history endpoint enforces a strict temporal filter so investigators only see pre-alert evidence. The ground truth label is never returned via the API — analysts work blind, as in real investigation."

---

## ML Engineering Questions

### Why a capacity-based threshold rather than F1-optimal?

**30 seconds:**
> "F1 assumes equal cost for false positives and false negatives. In AML, a missed SAR is far more costly — regulatory fines, enforcement action, reputational risk. Setting the threshold at the 80th percentile of validation scores directly implements the 'review top 20%' policy without assuming equal costs."

**2 minutes:**
> "The standard approach is to pick the threshold that maximises F1 on a validation set. That's appropriate when recall and precision failures have similar costs. In AML they don't — a missed SAR can result in regulatory enforcement and potentially criminal liability, while a false positive costs analyst time. The capacity-based threshold operationalises this directly: the threshold is set at the score corresponding to the 80th percentile of validation set scores. This guarantees that exactly 20% of alerts land above the threshold in the validation distribution. Recall@20% is then the metric that directly measures whether the right 20% was selected."

### Why two training phases?

**30 seconds:**
> "Phase 1 uses early stopping on a held-out validation set to find the optimal number of gradient boosting iterations. Phase 2 refits on train+val combined using that iteration count. This lets us use all available labelled data for the final model without leaking the holdout set."

**2 minutes:**
> "Early stopping requires a held-out set to evaluate iteration quality. If you include the validation set in training during phase 1, you can't use it for stopping — the loss metric would be in-sample and would never stop growing. So phase 1 uses only the training split. Once we know the best iteration number, there's no reason to withhold the validation data — it contains valuable labelled examples. Phase 2 refits with the validation labels included and stops at the best_iter from phase 1. The holdout set is never touched until final evaluation. This is a common pattern in Kaggle competition meta-learning and is documented in the scikit-learn HistGBM docs."

### Why temporal splits and not random splits?

**30 seconds:**
> "Random splits leak future patterns into training. If my test set contains alerts from March and my training set contains alerts from June, the model sees future transaction behaviour during training. Temporal splits ensure training data is strictly older than test data."

**2 minutes:**
> "Random splits are appropriate when observations are exchangeable — when there's no time structure. AML data has strong time structure: transaction patterns shift, alert rules get updated, money laundering typologies evolve. If you train on randomly selected alerts from across the full period and test on another random sample, your model implicitly benefits from patterns from the 'future' test period. In production the model is always trained on historical data and scored on future alerts — temporal splits replicate this exactly. The split boundaries in AlertIQ are April 15 for train/val and May 23 for val/holdout, strictly ordered."

### Why is AUC-ROC 0.979? That's suspiciously high.

**30 seconds:**
> "It's because the data is synthetic. The simulator generates clean typology labels, so the ML model learns unrealistically clear patterns. I'd expect 70–80% AUC on real alerts. I document this explicitly in the README."

**2 minutes:**
> "Real AML data has three problems that simulation hides. First, label noise: a SAR filing is often based on analyst judgment, not ground truth. Second, adversarial adaptations: money launderers change behaviour to avoid detection, so the past is a weaker predictor of the future than it would be in simulation. Third, class imbalance: real SAR rates are often 1–3%, compared to 9.5% in my simulator. Higher class imbalance makes ranking harder. The 0.979 AUC demonstrates that the pipeline is correctly built — data flows through without leakage, the model is trained and evaluated properly — but it's not a benchmark for real AML system performance. I call this out in the README, DATA_PROVENANCE.md, and MODEL_CARD.md."

### How does PSI drift detection work?

**30 seconds:**
> "PSI — Population Stability Index — measures how much the distribution of a feature has shifted between a reference window and a current window. Values below 0.1 are stable, 0.1–0.2 are moderate drift, above 0.2 require investigation."

**2 minutes:**
> "PSI compares the binned distribution of a feature at training time versus inference time. You divide the feature range into bins, compute the fraction of observations in each bin for both the reference and current windows, then compute PSI = sum((ref_frac - curr_frac) * ln(ref_frac / curr_frac)). The log ratio penalises both over- and under-representation. AlertIQ computes PSI per feature on a monthly rolling window. If velocity_90d shifts significantly — say because a recession changes baseline transaction behaviour — PSI will flag it before model performance degrades."

---

## System Design Questions

### Why Starlette instead of FastAPI?

**30 seconds:**
> "FastAPI is built on Starlette. Using Starlette directly demonstrates understanding of ASGI, routing, middleware, and lifespan events at a lower abstraction level — which is more interesting for a portfolio project."

**2 minutes:**
> "FastAPI adds automatic schema generation, request validation via Pydantic, and dependency injection. These are valuable in production. For AlertIQ, I'm already using Pydantic for schema definitions and I have explicit request validation in the route handlers — so the DI and auto-schema features aren't buying much. Starlette gives me explicit control over lifespan events (startup/shutdown hooks for loading the model and opening the DB connection), middleware ordering, and routing priority. It's also easier to reason about what exactly happens on each request without framework magic. In a production system I'd evaluate FastAPI's DI system seriously for its testability benefits."

### Why SQLite instead of PostgreSQL?

**30 seconds:**
> "SQLite with WAL mode is adequate for a demo with one writer. The `InvestigationRepository` abstract class means I can swap to PostgreSQL without changing any route handler — the persistence layer is hidden behind an interface."

**2 minutes:**
> "The key design decision was to define an `InvestigationRepository` abstract base class with methods like `get_alert()`, `append_note()`, `append_decision()`, and `list_alerts()`. The `SQLiteInvestigationStore` implements this interface. Route handlers call `self._store.append_note(...)` — they never call any SQLite-specific API. A `PostgresInvestigationRepository` implementing the same ABC would slot in without any route change. The SQLite limitation — ephemeral storage on Cloud Run, no true concurrent writes — is documented in PERSISTENCE_ARCHITECTURE.md with a 7-step production upgrade path."

### How does the temporal evidence filter work and why does it matter?

**30 seconds:**
> "The transaction history endpoint filters to `WHERE txn_date <= alert_date`. Investigators can only see transactions that existed when the alert was raised. This is an AML compliance requirement — you can't use future information to justify a past SAR filing."

**2 minutes:**
> "Imagine an investigator reviewing an alert raised on April 10th. The account makes three additional suspicious transactions on April 14th. If the investigator's screen showed those April 14th transactions, they'd be making a hindsight decision — using evidence that didn't exist when the alert was triggered. In real AML compliance, a SAR must be based on information available at the time of the suspicious activity. The temporal filter enforces this by design. Importantly, it's also a data integrity guarantee: if we ever retrain the model using analyst decisions, those decisions must be based on the same evidence the model used to score the alert — not information that leaked in afterward. The filter is verified by 12 dedicated tests in `test_temporal_integrity.py`."

### What's the `InvestigationRepository` ABC and why use an ABC?

**30 seconds:**
> "It's an abstract base class that defines the contract for all persistence operations. Route handlers program against the ABC, not against SQLite. Swapping to PostgreSQL means writing a new implementation of the ABC, not touching the routes."

**2 minutes:**
> "ABCs enforce a contract at definition time — if a concrete implementation doesn't implement every abstract method, Python raises a `TypeError` at instantiation. This catches incomplete implementations earlier than duck typing would. More importantly, it documents what the persistence interface is supposed to do — it's a design specification, not just an implementation detail. For a portfolio project this demonstrates awareness of SOLID principles (specifically the dependency inversion principle: route handlers depend on an abstraction, not a concrete database). In a production system the ABC also enables testing route handlers against a mock implementation without touching any database."

---

## Architecture Questions

### How would you scale AlertIQ to handle 100,000 alerts per day?

**Answer:**
> "The current bottleneck is the single SQLite file. At 100,000 alerts/day I'd make these changes in order of priority:

> 1. Replace SQLite with PostgreSQL on a managed service (Cloud SQL or RDS). The `InvestigationRepository` swap is already designed for this.
> 2. Separate the read and write paths. The ranked queue query is a read; note submissions are writes. PostgreSQL read replicas can scale read traffic.
> 3. Move model inference to a separate service. The current design scores alerts on-demand in the API process. At scale, batch scoring on a scheduled job with results cached in the DB is more appropriate.
> 4. Add a Redis cache for the alert list — it changes infrequently (only when new alerts are ingested or decisions are recorded).
> 5. Consider Kafka for alert ingestion — rather than writing directly to Postgres, the ingestion pipeline publishes alert events and the scoring service consumes them.

> The Terraform configuration already handles Cloud Run scaling — min-instances: 1 in production keeps cold starts from affecting the first investigator of the day."

### What would you change about the architecture if starting over?

**Answer:**
> "Three things:

> First, I'd define an explicit `AlertRepository` ABC alongside the `InvestigationRepository` ABC from the start — one for the raw alert store (immutable, simulation-generated) and one for the investigation state (mutable, analyst-driven). Currently `alert_store.py` does both, which is a mild violation of single responsibility.

> Second, I'd use explicit column selection in `get_alert()` instead of `SELECT a.*`. The current implementation uses `SELECT a.*` in SQL but then explicitly excludes `true_sar` when building the return dict. That's a 'defence by exclusion' pattern — if a new column is added to the alerts table, it would appear in the response unless someone remembers to exclude it. Explicit column enumeration in the SQL prevents this.

> Third, I'd add structured request IDs and tracing from day one. Every request should generate a UUID that appears in all log entries for that request. Currently logging is structured but doesn't correlate entries within a request."

---

## Business and Product Questions

### How do you measure whether AlertIQ is actually helping?

**Answer:**
> "The primary metric is Recall@K — the fraction of true SARs caught at the investigator's capacity limit. A secondary metric is SAR-to-alert ratio: if AlertIQ is working, the SAR rate in the reviewed portion of the queue should be significantly higher than the overall SAR rate.

> In production you'd also measure analyst efficiency metrics: time-to-decision per alert, decision reversal rate (an indicator of investigation quality), and false positive rate in escalations (how many escalated cases were actually filed as SARs by the compliance officer).

> A controlled experiment would be ideal: randomly assign 20% of alerts to the current process (random or severity-sorted queue) and 80% to the AlertIQ-ranked queue, then compare SAR yield."

### Why would a bank trust an ML model for SAR-related decisions?

**Answer:**
> "They wouldn't trust it for decisions — they'd trust it for prioritisation. The model doesn't decide whether to file a SAR. A human analyst investigates every alert above the threshold and makes the decision. The model only determines which alerts get reviewed first.

> This is an important distinction. Automated SAR filing would require regulatory approval and a much higher bar of model validation. Automated prioritisation is a workflow efficiency tool — if the model is wrong about a high-priority alert, the analyst will discover this during investigation. The governance model is: the model surfaces, humans decide.

> I also document the limitations explicitly — simulated data, no adversarial testing, no real population validation. A bank's model risk management team would require much more validation before any production use."

---

## What Went Wrong (Show You Can Debug)

### Describe a bug you had to debug during this project.

**Answer:**
> "The most instructive bug was the ScopeMismatch in the E2E journey tests. I had a pytest fixture at module scope — it creates one test database per module, shared across all 24 test cases in the journey. The problem was it used `monkeypatch.setenv()` to set the database path environment variable. `monkeypatch` is function-scoped by default, so using it inside a module-scoped fixture raised a `ScopeMismatch` error.

> The fix was to replace `monkeypatch.setenv()` with direct `os.environ` manipulation using a save/restore pattern: save the old value, set the new value, yield the client, then restore the original value in the teardown. This gives the same isolation guarantee as monkeypatch but works at module scope.

> The second bug was more subtle: two of the 24 E2E tests were failing because they looked for `data['alerts']` in the API response, but the list_alerts endpoint returns `data['items']`. The key name had been changed during a refactor but the tests hadn't been updated. This kind of drift is exactly why having E2E tests is valuable — they catch interface contract changes that unit tests don't see."

---

## 5-Minute Deep Dive Questions

### Walk me through the full data pipeline from raw transactions to a ranked alert queue.

> "Starting from the raw data: the simulator generates 191,364 transactions across 3,000 accounts over 6 months. Each account has a behavioural profile — baseline transaction volume, jurisdiction exposure, industry risk level. Eight money laundering typologies generate anomalous patterns: structuring transactions just below reporting thresholds, shell company layering, rapid round-trip transfers, etc.

> From transactions, the simulation generates alert events using a transaction monitoring system — threshold-based rules that fire on suspicious patterns. Each alert gets a true SAR label: 1 if the account is running a laundering typology, 0 if the alert is a false positive from legitimate but unusual activity.

> Feature engineering runs on the alerts: for each alert, we compute 24 features using transaction history up to the alert date. Velocity ratios compare 30-day and 90-day volumes to baseline. Jurisdiction entropy measures geographic concentration of counterparty accounts. Structuring indicators count deposits in the 9,000–9,999 range relative to total deposits. PEP, adverse media, and high-risk industry flags come from account-level attributes.

> The feature matrix goes into temporal training splits: 60% train, 20% val, 20% holdout. Training uses HistGradientBoostingClassifier in two phases: phase 1 with early stopping finds the best iteration count, phase 2 refits on train+val combined at that count. The threshold is set at the 80th percentile of validation scores.

> At inference time, the serving layer loads the model from `models/registry.json`, identifies the champion version, loads `model.joblib`, and scores alerts on demand. The scored alerts are stored in the SQLite investigation store and surfaced via the `/alerts` endpoint sorted by risk score. The investigator sees a ranked queue and works top-down."
