# AlertIQ — Deployment Guide

AlertIQ deploys to Google Cloud Run as a containerised scoring API.
Cloud Run provides scale-to-zero, automatic HTTPS, and pay-per-request billing — appropriate for a project with variable scoring demand and no requirement for persistent connections.

---

## Architecture

```
GitHub Actions (CI/CD)
        │
        │ WIF keyless auth
        ▼
Google Artifact Registry
europe-west1-docker.pkg.dev/<project>/alertiq/api:<sha>
        │
        │ gcloud run services replace
        │ (3 traceability placeholders substituted)
        ▼
Cloud Run Staging (europe-west1)
        │
        │ smoke tests pass → manual promotion
        ▼
Cloud Run Production (europe-west1)
```

The model artifact is baked into the Docker image at build time (not fetched from an external store at runtime). This means:

- Cold start time is deterministic (no network fetch during startup)
- Rolling back the API also rolls back the model
- Model and application versions are always in sync

### Deployment traceability

Every deployed revision carries three traceability values, injected at deploy time by the CD workflow and exposed via `GET /health`:

| Field | Source | Example |
|-------|--------|---------|
| `git_sha` | 40-char Git commit SHA | `a1b2c3d4...` |
| `image_digest` | Container content digest | `sha256:abc123...` |
| `model_version` | Baked into model artifact | `1.0.0` |

This means any revision can be fully audited: which commit built it, which bytes were deployed, and which model version scored each alert.

---

## Prerequisites

- Google Cloud project with billing enabled
- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- Terraform ≥ 1.6 installed (for one-time infra setup — see `infra/terraform/`)
- Docker installed (for local testing)
- Python 3.11+ (for scripts)

---

## One-time GCP setup

The GCP infrastructure is provisioned with Terraform. Run once per project.

### Option A — Terraform (recommended)

```bash
cd infra/terraform

# Review what will be created
terraform init
terraform plan \
  -var="project_id=<YOUR_PROJECT_ID>" \
  -var="github_owner=<YOUR_GITHUB_ORG_OR_USER>"

# Apply
terraform apply \
  -var="project_id=<YOUR_PROJECT_ID>" \
  -var="github_owner=<YOUR_GITHUB_ORG_OR_USER>"
```

The `terraform apply` output prints the exact values to copy into GitHub secrets.

### Option B — gcloud CLI (manual equivalent)

If you prefer not to use Terraform, the equivalent commands are:

```bash
export PROJECT_ID=<YOUR_PROJECT_ID>
export GITHUB_OWNER=<YOUR_GITHUB_ORG_OR_USER>
export REGION=europe-west1

# 1. Enable required APIs
gcloud services enable \
    artifactregistry.googleapis.com \
    run.googleapis.com \
    iam.googleapis.com \
    iamcredentials.googleapis.com \
    sts.googleapis.com \
    --project "${PROJECT_ID}"

# 2. Create Artifact Registry repository
gcloud artifacts repositories create alertiq \
    --repository-format=docker \
    --location="${REGION}" \
    --description="AlertIQ API container images" \
    --project "${PROJECT_ID}"

# 3. Create the CD service account
gcloud iam service-accounts create alertiq-cd \
    --display-name="AlertIQ CD" \
    --project "${PROJECT_ID}"

# 4. Grant permissions
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:alertiq-cd@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:alertiq-cd@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.developer"

# Allow Cloud Run to pull images (default Compute SA)
COMPUTE_SA="$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="roles/artifactregistry.reader"

# 5. Workload Identity Federation
gcloud iam workload-identity-pools create alertiq-pool \
    --location=global \
    --display-name="AlertIQ GitHub Actions" \
    --project "${PROJECT_ID}"

gcloud iam workload-identity-pools providers create-oidc alertiq-github-provider \
    --location=global \
    --workload-identity-pool=alertiq-pool \
    --display-name="GitHub" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository == '${GITHUB_OWNER}/alertiq'" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --project "${PROJECT_ID}"

POOL_ID=$(gcloud iam workload-identity-pools describe alertiq-pool \
    --location=global --project "${PROJECT_ID}" --format='value(name)')

gcloud iam service-accounts add-iam-policy-binding \
    alertiq-cd@${PROJECT_ID}.iam.gserviceaccount.com \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${GITHUB_OWNER}/alertiq" \
    --project "${PROJECT_ID}"

# Print the provider name (use as GCP_WORKLOAD_IDENTITY_PROVIDER secret)
gcloud iam workload-identity-pools providers describe alertiq-github-provider \
    --location=global \
    --workload-identity-pool=alertiq-pool \
    --project "${PROJECT_ID}" \
    --format='value(name)'
```

### Set GitHub repository secrets

In **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|--------|-------|
| `GCP_PROJECT_ID` | Your GCP project ID |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Output of the provider describe command above |
| `GCP_SERVICE_ACCOUNT` | `alertiq-cd@<PROJECT_ID>.iam.gserviceaccount.com` |

> **Note:** `GCP_REGION` is no longer a secret — the region is hardcoded as `europe-west1` in the CD workflow to match the Artifact Registry location and the service YAMLs.

---

## Local development

### Run with Docker

```bash
# Build
docker build -t alertiq-api:local .

# Run (without a model — degraded mode)
docker run -p 8080:8080 alertiq-api:local

# Run with a model (mount model_registry from host)
docker run -p 8080:8080 \
    -v "$(pwd)/model_registry:/app/model_registry:ro" \
    -e ALERTIQ_REGISTRY_PATH=/app/model_registry \
    alertiq-api:local

# Verify
curl http://localhost:8080/health
```

### Train and load a model locally

```bash
# Generate synthetic dataset
python scripts/run_simulation.py

# Train and register a model (champion)
python scripts/train_and_serialize.py \
    --version "1.0.0" \
    --notes "local training" \
    --promote

# Start the API (it will load the champion automatically)
uvicorn alertiq.serving.app:app --host 0.0.0.0 --port 8080

# Run smoke tests
python scripts/smoke_test.py --base-url http://localhost:8080
```

---

## Staging deployment (automated)

Staging deployment is triggered automatically by the CD pipeline whenever CI passes on `main`.

The CD pipeline:
1. Authenticates to GCP via Workload Identity Federation (no stored key)
2. Builds and pushes the image to Artifact Registry with two tags: `latest` and `<git-sha>`
3. Substitutes three traceability placeholders in the staging YAML:
   - `IMAGE_TAG_PLACEHOLDER` → full Artifact Registry URL with SHA tag
   - `GIT_SHA_PLACEHOLDER` → 40-character Git commit SHA
   - `DIGEST_PLACEHOLDER` → `sha256:...` image content digest
4. Deploys with `gcloud run services replace`
5. Runs smoke tests against the live service URL

To deploy manually to staging:

```bash
export PROJECT_ID=<YOUR_PROJECT_ID>
export REGION=europe-west1
export GIT_SHA=$(git rev-parse HEAD)
export IMAGE_TAG="europe-west1-docker.pkg.dev/${PROJECT_ID}/alertiq/api:${GIT_SHA}"

# Build and push
gcloud auth configure-docker europe-west1-docker.pkg.dev
docker build -t "${IMAGE_TAG}" .
docker push "${IMAGE_TAG}"

# Capture digest
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${IMAGE_TAG}" | cut -d@ -f2)

# Substitute all three traceability placeholders
sed \
    -e "s|IMAGE_TAG_PLACEHOLDER|${IMAGE_TAG}|g" \
    -e "s|GIT_SHA_PLACEHOLDER|${GIT_SHA}|g" \
    -e "s|DIGEST_PLACEHOLDER|${DIGEST}|g" \
    deploy/cloudrun-staging.yaml > /tmp/staging-deploy.yaml

# Deploy
gcloud run services replace /tmp/staging-deploy.yaml \
    --region "${REGION}" \
    --project "${PROJECT_ID}"

# Run smoke tests
STAGING_URL=$(gcloud run services describe alertiq-api-staging \
    --region "${REGION}" --project "${PROJECT_ID}" \
    --format='value(status.url)')
python scripts/smoke_test.py --base-url "${STAGING_URL}"
```

---

## Production promotion (manual)

Production deployment is deliberately manual. The recommended workflow:

1. Confirm staging smoke tests passed in the CI/CD pipeline.
2. Inspect the staging metrics and audit logs:
   ```bash
   curl "${STAGING_URL}/metrics" | python -m json.tool
   # Verify git_sha and image_digest match the commit you want to promote
   curl "${STAGING_URL}/health" | python -m json.tool
   ```
3. Run the performance benchmark against staging:
   ```bash
   python scripts/performance_benchmark.py --base-url "${STAGING_URL}"
   ```
4. Promote the same image to production:

```bash
export PROJECT_ID=<YOUR_PROJECT_ID>
export REGION=europe-west1

# Get the image, SHA, and digest currently serving in staging
PROD_IMAGE=$(gcloud run services describe alertiq-api-staging \
    --region "${REGION}" --project "${PROJECT_ID}" \
    --format='value(spec.template.spec.containers[0].image)')

PROD_SHA=$(gcloud run services describe alertiq-api-staging \
    --region "${REGION}" --project "${PROJECT_ID}" \
    --format='value(spec.template.metadata.annotations["run.googleapis.com/client-version"])')

# Use the staging health response if the annotation is absent
# curl "${STAGING_URL}/health" and extract git_sha manually if needed

PROD_DIGEST=$(gcloud artifacts docker images describe "${PROD_IMAGE}" \
    --format='value(image_summary.digest)' 2>/dev/null || echo "unknown")

# Substitute all three traceability placeholders
sed \
    -e "s|IMAGE_TAG_PLACEHOLDER|${PROD_IMAGE}|g" \
    -e "s|GIT_SHA_PLACEHOLDER|${PROD_SHA}|g" \
    -e "s|DIGEST_PLACEHOLDER|${PROD_DIGEST}|g" \
    deploy/cloudrun-production.yaml > /tmp/prod-deploy.yaml

# Deploy
gcloud run services replace /tmp/prod-deploy.yaml \
    --region "${REGION}" \
    --project "${PROJECT_ID}"

# Run smoke tests against production
PROD_URL=$(gcloud run services describe alertiq-api-production \
    --region "${REGION}" --project "${PROJECT_ID}" \
    --format='value(status.url)')
python scripts/smoke_test.py --base-url "${PROD_URL}"
```

---

## Application rollback

To roll back to a previous revision, redeploy using an earlier SHA tag stored in Artifact Registry:

```bash
export PROJECT_ID=<YOUR_PROJECT_ID>
export REGION=europe-west1
export ROLLBACK_SHA=<previous-git-sha>

# Confirm the image exists
gcloud artifacts docker images list \
    "europe-west1-docker.pkg.dev/${PROJECT_ID}/alertiq/api" \
    --filter="tags:${ROLLBACK_SHA}"

ROLLBACK_IMAGE="europe-west1-docker.pkg.dev/${PROJECT_ID}/alertiq/api:${ROLLBACK_SHA}"

sed \
    -e "s|IMAGE_TAG_PLACEHOLDER|${ROLLBACK_IMAGE}|g" \
    -e "s|GIT_SHA_PLACEHOLDER|${ROLLBACK_SHA}|g" \
    -e "s|DIGEST_PLACEHOLDER|unknown-rollback|g" \
    deploy/cloudrun-staging.yaml > /tmp/rollback-deploy.yaml

gcloud run services replace /tmp/rollback-deploy.yaml \
    --region "${REGION}" --project "${PROJECT_ID}"
```

> **Immutable tags:** SHA tags (e.g. `api:a1b2c3...`) are immutable — a re-push to the same tag is rejected by Artifact Registry. The `latest` tag is mutable and is only used for cache warming, never for rollback. Always use SHA tags in rollback and production promotion commands.

## Model rollback (independent of app rollback)

The model registry supports promoting a previous version to champion without redeploying the application:

```python
from alertiq.serving.registry import ModelRegistry
from pathlib import Path

registry = ModelRegistry(Path("model_registry"))

# List available versions
for v in registry.list_versions():
    print(v.model_version, "champion" if v.is_champion else "")

# Restore a previous champion
registry.promote("1.0.0")  # replace with the version to restore
```

Since the model artifact is baked into the Docker image, a true model rollback also requires a matching application rollback. Use the model rollback API for same-image model switching (when multiple versions were registered before the current image was built).

---

## Audit Durability Classification

AlertIQ's audit logging behaviour depends on the deployment configuration. This section documents the durability properties so that engineers and reviewers can make informed decisions about production suitability.

### Current behaviour (portfolio deployment)

Audit records are written to **stdout → Cloud Logging** via structured Python logging.

| Property | Value |
|----------|-------|
| Durability | Non-durable at the Cloud Run layer |
| On instance termination | Records in the instance's stdout buffer that have not been flushed to Cloud Logging may be lost |
| On Cloud Logging ingestion failure | Records lost (no local buffer, no retry) |
| On audit write error | Error is caught, logged to stderr, counted in `GET /metrics` as `audit_failures`; scoring succeeds (fail-open) |
| Retention | Cloud Logging default (30 days for _Default log bucket) |

**Fail-open policy:** An audit write failure never blocks a scoring response. This is appropriate for a portfolio/demonstration system and is explicitly tested. It means audit completeness is best-effort, not guaranteed.

### What a regulated financial institution would require

For a system processing real AML decisions in a regulated environment, the following upgrades would typically be required before go-live:

1. **Durable write-ahead log** — Write audit records to Cloud Spanner, BigQuery, or a WORM-protected Cloud Storage bucket before returning the scoring response (fail-closed), or to an append-only Pub/Sub topic with guaranteed delivery.
2. **Fail-closed option** — For high-stakes decisions, the system should return an error rather than a score if the audit record cannot be written, to prevent untracked scoring.
3. **Tamper-evident storage** — Write records to an immutable or auditor-accessible store (Cloud Spanner with version history, BigQuery with `require_partition_filter`, or GCS with object hold policies).
4. **Retention policy** — Audit records should be retained for the period required by local regulation (5–7 years is common for AML records in EU/UK jurisdictions).
5. **Data Processing Agreement** — Cloud Logging and any audit store must be covered by a signed DPA with Google Cloud.

The current audit module's `AuditLogger` interface is designed to accept alternative `_emit()` implementations. The upgrade path is to replace the file/logging emit with a Spanner or BigQuery write, behind the same fail-open wrapper.

> **Compliance note:** Running on `europe-west1` keeps data within the EU at the Cloud Run layer. EU region alone does **not** establish GDPR compliance, a Data Processing Agreement, or any banking/AML regulatory compliance. Consult legal counsel before processing real financial or personal data in any environment.

---

## Cost Safeguards

AlertIQ uses **request-based billing** in both staging and production:

- `minScale: "0"` — scale to zero when idle (no idle cost)
- `cpu-throttling: "true"` — CPU allocated only during request processing

**Cold-start trade-off:** The first request after the service goes idle incurs a cold start of approximately 3–10 seconds (container launch + ~1–3 s LightGBM artifact load). Subsequent requests within the same instance are warm. For a portfolio deployment with occasional traffic, this trade-off eliminates idle spend.

**Instance cap:** `maxScale: "10"` limits parallel container instances. This is a soft limit — it caps autoscaling but is not a hard billing stop.

**Billing alert (recommended):** Cloud Run billing alerts send notifications when projected spend crosses a threshold. They do **not** automatically stop the service.

```
Cloud Console → Billing → Budgets & alerts → Create budget
Recommended: $10/month threshold with e-mail notification
```

A hard spending cap requires a Cloud Function that disables the service when a billing alert fires. This is not implemented in the portfolio configuration; engineers deploying to a production environment with cost SLOs should evaluate whether a hard cap is necessary.

### Cost estimate (europe-west1, request-based billing)

| Environment | Configuration | Estimated monthly cost |
|-------------|--------------|----------------------|
| Staging | min=0, 1 CPU / 512 Mi, cpu-throttling=true | **$0** (within 2M free requests) |
| Production | min=0, 1 CPU / 512 Mi, cpu-throttling=true | **$0** at portfolio traffic (< 2M req/month) |

Artifact Registry storage: ~$0.10/GB/month after the 0.5 GB free tier. A typical AlertIQ image is ~300–500 MB, so storage cost is negligible for a handful of versions.

---

## Environment variables reference

See `.env.example` for the full list with descriptions.

| Variable | Default | Description |
|----------|---------|-------------|
| `ALERTIQ_ENV` | `development` | Environment name (`development`/`staging`/`production`) |
| `ALERTIQ_LOG_LEVEL` | `INFO` | Log verbosity |
| `ALERTIQ_REGISTRY_PATH` | `./model_registry` | Path to model registry directory |
| `ALERTIQ_AUDIT_LOG_PATH` | `""` (Python logging) | Audit log destination |
| `ALERTIQ_MAX_PAYLOAD_BYTES` | `10485760` (10 MB) | Maximum request body size |
| `ALERTIQ_WORKERS` | `1` | Uvicorn worker count |
| `ALERTIQ_GIT_SHA` | `""` | Git commit SHA injected by CD workflow; exposed via `/health` |
| `ALERTIQ_IMAGE_DIGEST` | `""` | Image content digest injected by CD workflow; exposed via `/health` |
