# AlertIQ  -  Milestone 5 Completion Report

**Milestone:** Deploy and Operate  
**Target platform:** Google Cloud Run  
**Status:** ✅ Complete  
**All tests:** 597 unit/integration + 26 operational = **623 passing, 0 failing**

---

## What was built

Milestone 5 transformed AlertIQ from a locally runnable scoring service into a
reproducibly deployable, operationally observable application.  Every
deliverable listed in the milestone specification was completed.

---

## Deliverables

### CI/CD pipeline (`.github/workflows/`)

| File | Purpose |
|------|---------|
| `ci.yml` | Runs on every push and PR: `quality` → `test` + `security` (parallel) → `build` |
| `cd.yml` | Runs on successful CI for `main`: `build-push` → `deploy` (staging + smoke tests) |

CI is self-contained  -  no `alerts.csv` or pre-trained model artifact is
needed.  All serving tests use synthetic numpy fixtures.

CD authenticates to GCP via Workload Identity Federation (no long-lived
service account key stored as a GitHub secret).  Images are pushed to
`ghcr.io` with two tags: `latest` (mutable) and `<git-sha>` (immutable,
used for rollback).

### Cloud Run service configuration (`deploy/`)

| File | Purpose |
|------|---------|
| `cloudrun-staging.yaml` | Staging: scale-to-zero (min=0), 1 CPU / 512 Mi |
| `cloudrun-production.yaml` | Production: min=1 warm instance, 2 CPU / 1 GiB, CPU throttling off |

Both files use `IMAGE_TAG_PLACEHOLDER` substituted by `sed` in the CD
workflow, avoiding a Helm or Terraform dependency.

Startup probe holds traffic for up to 65 seconds while the model loads from
the baked-in artifact.  Liveness probe restarts the container if the process
hangs after start-up.

### In-process metrics (`src/alertiq/serving/metrics.py`)

Thread-safe module-level singleton; no Prometheus dependency.  Exposed at
`GET /metrics` as plain JSON.

Key fields:

| Field | Meaning |
|-------|---------|
| `uptime_seconds` | Process lifetime since last reset |
| `requests[]` | Per-path × status-code request counts |
| `latency_ms` | p50/p95/p99 per endpoint, capped at 2 000 samples |
| `audit_failures` | Count of audit write errors absorbed by the API |

### Audit durability hardening (`src/alertiq/serving/app.py`)

Two layers of protection ensure audit failures never block scoring:

1. `_emit_single_audit()`  -  catches all exceptions from
   `AuditLogger.record_score()`, logs to stderr, increments the
   `audit_failures` counter.
2. The batch handler's `record_batch_score()` call is wrapped in the same
   pattern.

The same principle applies in `audit.py._emit()`: `OSError` is caught,
logged, and counted  -  the caller always gets a response.

### Operational scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `smoke_test.py` | 6 post-deployment checks (health, metrics, model info, score, batch, 413) |
| `performance_benchmark.py` | Sequential latency measurement; SLO targets: p95 ≤ 200 ms single, ≤ 1 000 ms batch |

### Operational test suite (`tests/operational/`)

26 tests across 7 failure categories:

| Category | Tests |
|----------|-------|
| Audit log failure | 4  -  OSError absorbed by single and batch endpoints; counter incremented |
| Degraded mode | 4  -  200/degraded from `/health`; 503 from scoring endpoints |
| Oversized payloads | 2  -  413 from body > 10 MB; 413 from Content-Length pre-check |
| Malformed JSON | 3  -  400 on truncated/invalid; 422 on wrong schema |
| Unsupported schema version | 1  -  422, not 500 |
| Metrics reliability | 3  -  request counting, latency recording, uptime |
| Data quality flags | 3  -  zero features, extreme values, normal features |
| Request ID header | 4  -  present on all GET and POST endpoints |
| No-label policy | 2  -  disclaimer present; forbidden disposition labels absent |

### Environment configuration (`.env.example`)

Documents all `ALERTIQ_*` environment variables with descriptions and safe
defaults.  Explicitly states that secrets belong in Google Secret Manager, not
this file.

### Documentation (`docs/`)

| File | Contents |
|------|---------|
| `CI_CD.md` | Pipeline diagram, job descriptions, local equivalents, concurrency control |
| `DEPLOYMENT.md` | One-time GCP setup (WIF), local Docker workflow, staging/production procedures, rollback, cost estimate |
| `OPERATIONS_RUNBOOK.md` | Symptom quick-reference table, monitoring guide, runbook procedures for all failure modes, weekly operational checklist |

---

## Test summary

```
Tier 1 + Tier 2 (unit and integration):  597 passed, 0 failed
Tier 3 (operational failure-mode):        26 passed, 0 failed
───────────────────────────────────────────────────────────
Total:                                    623 passed, 0 failed
```

---

## Audit durability contract

The following guarantee is tested and holds across all 26 operational tests:

> An audit write failure **MUST NOT** affect the HTTP response returned to the
> caller.  Every such failure is caught, logged to stderr at ERROR level, and
> counted in `GET /metrics` as `audit_failures`.

---

## Adversarial review findings and resolutions

| Finding | Resolution |
|---------|-----------|
| `record_batch_score()` was called without a try/except, creating a path where `OSError` in `_emit` could escape `_emit_single_audit()` and reach the ASGI stack | Wrapped in `try/except Exception` with logging and `_metrics.record_audit_failure()` |
| Uptime test was strict (`> 0`)  -  `reset()` in the autouse fixture could execute within the same wall-clock second, producing `0.0` | Changed assertion to `>= 0` |
| No-label policy test did a bare substring check for `"sar"`, which matched the disclaimer text ("does not constitute a SAR filing decision") | Revised test to exclude the `disclaimer` field from forbidden-label checks; the disclaimer's mention of SAR is the desired compliance communication |

---

## What was intentionally not changed

Per Milestone 5 constraints:

- ML system and API are unchanged (no operational defect was found that
  required changes to the scoring logic).
- No Kubernetes introduced.
- No MLflow or heavyweight model registry introduced.
- No retraining at API startup or scoring time.
- No arbitrary filesystem paths accessible to API clients.
- No raw sensitive information stored.
- Output labels do not imply autonomous compliance determination.

---

## Cost estimate (Cloud Run, europe-west1)

> **Note:** The initial cost estimate used us-central1 and production instance-based billing. Milestone 5.1 corrected both to europe-west1 and request-based billing for all environments.

| Environment | Configuration | Est. monthly cost |
|-------------|--------------|------------------|
| Staging | min=0, 1 CPU / 512 Mi, cpu-throttling=true | **$0** (within 2M free requests) |
| Production | min=0, 1 CPU / 512 Mi, cpu-throttling=true | **$0** at portfolio traffic |

---

## Next steps (not started  -  Milestone 6 not begun)

1. Wire up GCP secrets (connect `GCP_*` GitHub secrets to a real project).
2. Add GCP Cloud Monitoring alerting policy for `audit_failures > 0` and
   `p95 > 200 ms`.
3. Evaluate whether `minScale: 1` is appropriate for production once real
   traffic patterns are known.
4. Consider adding a `/readyz` probe distinct from `/health` if Cloud Run
   startup probe false-positives are observed at scale.
