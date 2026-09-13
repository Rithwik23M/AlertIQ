# AlertIQ — Operations Runbook

This runbook covers the operational procedures for the AlertIQ scoring API running on Google Cloud Run. It is structured as a decision tree: identify the symptom, follow the diagnosis steps, apply the appropriate remediation.

---

## Quick reference

| Symptom | Likely cause | Section |
|---------|-------------|---------|
| All requests return 503 | No model loaded; cold start failure | [Degraded mode](#degraded-mode-no-model-loaded) |
| `/health` returns 200 but `model_loaded: false` | Champion model missing from registry | [Degraded mode](#degraded-mode-no-model-loaded) |
| Latency spike (p95 > 200 ms) | Cold start or resource contention | [Latency issues](#latency-issues) |
| Audit failures counter rising (`/metrics`) | Stdout flushing failure or Cloud Logging ingestion error | [Audit log failures](#audit-log-failures) |
| 413 errors from clients | Payload exceeds `ALERTIQ_MAX_PAYLOAD_BYTES` | [Payload errors](#payload-errors) |
| Coverage report shows drop | New code without tests | [Test coverage](#test-coverage) |
| Security scan found CVEs | Outdated dependency | [CVE remediation](#cve-remediation) |
| `git_sha` in `/health` is null | Env var not injected by CD pipeline | [Traceability](#deployment-traceability) |

---

## Monitoring

### Health endpoint

```bash
curl https://alertiq-api-staging-<project>.a.run.app/health | python -m json.tool
```

Expected healthy response:
```json
{
  "status": "ok",
  "model_loaded": true,
  "model_version": "1.0.0",
  "schema_version": 1,
  "checked_at": "2025-01-01T00:00:00+00:00",
  "git_sha": "a1b2c3d4e5f6...",
  "image_digest": "sha256:abc123..."
}
```

`status: "degraded"` means the API is running but no model is loaded. Scoring endpoints return 503.

`git_sha` and `image_digest` are `null` in local development. In a deployed Cloud Run revision, both should be populated — a `null` value indicates the CD pipeline did not inject the traceability environment variables correctly.

### Metrics endpoint

```bash
curl https://alertiq-api-staging-<project>.a.run.app/metrics | python -m json.tool
```

Key fields to monitor:

| Field | Alert threshold | Meaning |
|-------|----------------|---------|
| `audit_failures` | > 0 | Audit records not being written; see §Audit Durability |
| `latency_ms./score.p95_ms` | > 200 ms | Single-alert scoring is slow |
| `latency_ms./score/batch.p95_ms` | > 1000 ms | Batch scoring is slow |
| `requests[status_code=500]` | > 0 | Unexpected internal errors |
| `requests[status_code=503]` | > 0 | Model not loaded |

### Cloud Run metrics (GCP Console)

Cloud Run automatically exposes:
- Request count (by response code)
- Request latency (p50, p95, p99)
- Container instance count
- CPU and memory utilisation

Navigate to: **Cloud Run → alertiq-api-staging → Metrics** (region: europe-west1)

---

## Runbook procedures

### Degraded mode — no model loaded

**Symptom:** `/health` returns `"model_loaded": false` or scoring endpoints return 503.

**Cause:** The model registry does not contain a champion model, or the model artifact was not baked into the Docker image correctly.

**Diagnosis:**
```bash
# Inspect the model registry inside the deployed image
IMAGE=$(gcloud run services describe alertiq-api-staging \
    --region europe-west1 --project <PROJECT_ID> \
    --format='value(spec.template.spec.containers[0].image)')

docker pull "${IMAGE}"
docker run --rm "${IMAGE}" ls /app/model_registry/
```

**Remediation:**
1. If the `model_registry/` directory is empty, the training script was not run before building the image. Run `scripts/train_and_serialize.py --promote` locally and rebuild the image.
2. If the directory exists but has no champion, run:
   ```python
   from alertiq.serving.registry import ModelRegistry
   from pathlib import Path
   r = ModelRegistry(Path("model_registry"))
   versions = r.list_versions()
   print(versions)
   r.promote(versions[0].model_version)  # promote the most recent
   ```
   Then rebuild and redeploy.

---

### Application rollback

**When to use:** Smoke tests fail after deployment, or error rates spike in production.

**Procedure:**

```bash
export PROJECT_ID=<YOUR_PROJECT_ID>
export REGION=europe-west1
export ROLLBACK_SHA=<previous-git-sha>

# 1. Confirm the image exists in Artifact Registry
gcloud artifacts docker images list \
    "europe-west1-docker.pkg.dev/${PROJECT_ID}/alertiq/api" \
    --filter="tags:${ROLLBACK_SHA}"

# 2. Deploy the rollback revision
ROLLBACK_IMAGE="europe-west1-docker.pkg.dev/${PROJECT_ID}/alertiq/api:${ROLLBACK_SHA}"

sed \
    -e "s|IMAGE_TAG_PLACEHOLDER|${ROLLBACK_IMAGE}|g" \
    -e "s|GIT_SHA_PLACEHOLDER|${ROLLBACK_SHA}|g" \
    -e "s|DIGEST_PLACEHOLDER|rollback|g" \
    deploy/cloudrun-staging.yaml > /tmp/rollback.yaml

gcloud run services replace /tmp/rollback.yaml \
    --region "${REGION}" --project "${PROJECT_ID}"

# 3. Verify
SERVICE_URL=$(gcloud run services describe alertiq-api-staging \
    --region "${REGION}" --project "${PROJECT_ID}" \
    --format='value(status.url)')
python scripts/smoke_test.py --base-url "${SERVICE_URL}"
```

**Time to recover:** Typically 2–3 minutes (Cloud Run redeploys a new revision).

---

### Model rollback

**When to use:** A newly deployed model produces unexpected scores (too many or too few high-risk outputs) but the application itself is healthy.

**When NOT to use:** If the application has a bug, roll back the application instead — a model rollback in the same image does not fix application bugs.

**Procedure:**

Model rollback is performed at runtime without redeploying the image. The `ModelRegistry.promote()` call changes which artifact is returned on the next cold start.

> **Note:** Cloud Run containers cache the loaded model in memory for the lifetime of the instance. To force the new champion to load, trigger a new revision (e.g. update an environment variable by 1 character) so all instances are replaced.

```python
from alertiq.serving.registry import ModelRegistry
from pathlib import Path

registry = ModelRegistry(Path("/app/model_registry"))

# List available versions
for v in registry.list_versions():
    champion = " ← champion" if v.is_champion else ""
    print(f"{v.model_version} (registered: {v.registered_at}){champion}")

# Promote the previous version
registry.promote("1.0.0")
print("Champion set to 1.0.0")
```

After promoting, trigger a new revision to flush in-memory model caches:
```bash
gcloud run services update alertiq-api-staging \
    --update-env-vars ALERTIQ_ROLLBACK_TS="$(date +%s)" \
    --region europe-west1 --project <PROJECT_ID>
```

---

### Latency issues

**Symptom:** p95 latency exceeds 200 ms for single-alert scoring or 1 s for batch scoring.

**Diagnosis:**

```bash
# Check the /metrics snapshot
curl https://alertiq-api.../metrics | python -m json.tool

# Run the performance benchmark against staging
python scripts/performance_benchmark.py \
    --base-url https://alertiq-api-staging-<project>.a.run.app \
    --warmup 5 --iterations 50
```

**Common causes and remediations:**

| Cause | Remediation |
|-------|-------------|
| Cold start (first request after scale-to-zero) | Expected with `minScale: 0`; latency improves after warm-up. For SLO-sensitive deployments, consider `minScale: 1` — see §Billing Trade-off. |
| Batch size too large | Reduce batch size; 100 alerts is a reasonable maximum |
| Model artifact too large | Check model size; retrain with fewer trees if necessary |
| Container memory pressure | Increase `memory` limit in the service YAML |

**Cold-start billing trade-off:**

| Setting | Idle cost | Cold-start p99 |
|---------|-----------|----------------|
| `minScale: 0` (current) | ~$0/month | ~3–10 s |
| `minScale: 1` | ~$5–10/month | ~0 ms |

For a portfolio deployment, `minScale: 0` is the correct default. Change `minScale` to `"1"` and `cpu-throttling` to `"false"` in the service YAML only if cold-start latency becomes a documented operational problem with real traffic.

---

### Audit log failures

**Symptom:** `/metrics` shows `audit_failures > 0`.

**What this means:** One or more audit records failed to write. The scoring response was still returned to the caller — the failure was absorbed (fail-open). Missing audit records are a compliance concern in any environment where audit completeness is required.

#### Audit Durability Classification

AlertIQ uses **stdout → Cloud Logging** as its audit transport. This is **non-durable** at the Cloud Run layer:

| Condition | Outcome |
|-----------|---------|
| Instance terminated mid-flush | Buffered stdout may be lost |
| Cloud Logging ingestion failure | Records lost (no local buffer) |
| Audit `_emit()` raises an exception | Caught, logged to stderr, `audit_failures` incremented; scoring succeeds |

For the portfolio deployment, this is an accepted trade-off. Audit writes are fail-open: a write failure never blocks a scoring response. The `audit_failures` counter in `GET /metrics` is the operational signal that audit completeness has degraded.

**For a regulated financial institution deployment:** The audit transport must be upgraded to a durable write-ahead store (Cloud Spanner, BigQuery append-only table, or GCS WORM bucket) before processing real financial data. See `docs/DEPLOYMENT.md §Audit Durability Classification` for the upgrade path.

**Diagnosis:**

```bash
# Check Cloud Run structured logs for audit errors
gcloud logging read \
    'resource.type="cloud_run_revision" AND severity=ERROR AND (textPayload:"audit" OR jsonPayload.message:"audit")' \
    --project <PROJECT_ID> \
    --limit 20 \
    --format='table(timestamp, textPayload, jsonPayload.message)'
```

**Common causes and remediations:**

| Cause | Remediation |
|-------|-------------|
| `ALERTIQ_AUDIT_LOG_PATH` points to a read-only path | Ensure it is set to `""` (Python logging) in Cloud Run env vars |
| Cloud Logging quota exhausted | Check GCP quotas; structured stdout is the lowest-overhead path |
| Bug in audit serialisation | Check error message in Cloud Logging; may require code fix |

---

### Deployment traceability

**Symptom:** `GET /health` returns `"git_sha": null` or `"image_digest": null` in a Cloud Run deployment.

**What this means:** The environment variables `ALERTIQ_GIT_SHA` and/or `ALERTIQ_IMAGE_DIGEST` were not injected into the Cloud Run revision at deploy time.

**Cause:** The service YAML was deployed with un-substituted placeholders (`GIT_SHA_PLACEHOLDER` / `DIGEST_PLACEHOLDER`), or the deployment was performed manually without the three-placeholder `sed` substitution.

**Diagnosis:**
```bash
# Check the current environment in the deployed revision
gcloud run services describe alertiq-api-staging \
    --region europe-west1 --project <PROJECT_ID> \
    --format='yaml(spec.template.spec.containers[0].env)'
```

**Remediation:** Re-run the deployment using the three-placeholder substitution documented in `docs/DEPLOYMENT.md §Staging deployment`.

---

### Payload errors

**Symptom:** Clients receive 413 responses.

**Cause:** The request body exceeds `ALERTIQ_MAX_PAYLOAD_BYTES` (default 10 MB ≈ 200 alerts with full feature vectors).

**Remediation:**

Option A — Reduce batch size on the client side (recommended for most cases).

Option B — Increase the limit in the Cloud Run service YAML:
```yaml
env:
  - name: ALERTIQ_MAX_PAYLOAD_BYTES
    value: "20971520"  # 20 MB
```

Do not exceed 32 MB. Cloud Run has a 32 MB HTTP request size limit.

---

### Test coverage

**Symptom:** CI fails with `FAIL Required test coverage of 70% not reached`.

**Procedure:**

```bash
# Run coverage report locally to find uncovered lines
ALERTIQ_AUDIT_LOG_PATH="" python -m pytest tests/ \
    --ignore=tests/operational \
    --cov=alertiq \
    --cov-report=term-missing

# Add tests for the uncovered lines, then re-run.
```

The coverage threshold is set in `pyproject.toml` (`fail_under = 70`). Do not lower this threshold — add tests instead.

---

### CVE remediation

**Symptom:** `security-report.md` (uploaded as a CI artifact) lists CVEs with a fix available.

**Procedure:**

1. Download the security report artifact from GitHub Actions.
2. Identify packages with fixable CVEs (marked `fix_version` in the report).
3. Update `pyproject.toml` to pin to a fixed version.
4. Run `pip-audit` locally to confirm the CVE is resolved:
   ```bash
   pip install -e ".[dev]"
   pip-audit --requirement <(pip freeze) --skip-editable
   ```
5. Push the update and verify CI passes.

For CVEs in transitive dependencies with no fix available, document the CVE in `SECURITY.md` and set a reminder to check again in 30 days.

---

## Scheduled operational checks

Perform these checks weekly in a production deployment:

- [ ] Review `/metrics` `audit_failures` counter. A non-zero value requires investigation before the next review cycle.
- [ ] Review Cloud Run error rate in GCP Console (europe-west1).
- [ ] Review `security-report.md` from the latest CI run.
- [ ] Run `python scripts/smoke_test.py` against production.
- [ ] Confirm `GET /health` shows the expected `git_sha` and `image_digest` for the current revision.
- [ ] Check model score distribution hasn't drifted (compare recent batch output histograms against the training distribution).

---

## Contacts and escalation

> This section is intentionally minimal for an open-source portfolio project. In a real deployment, list the on-call rotation, escalation path, and incident management tool here.

For issues with the scoring model or AML typology coverage, the model owner is responsible for retraining and re-registration. Operational incidents (API down, latency spike) follow the standard infrastructure escalation path.
