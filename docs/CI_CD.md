# AlertIQ — CI/CD Pipeline Reference

AlertIQ uses GitHub Actions for automated testing, security scanning, and deployment.
The pipeline is designed to be fail-fast, cheap to run, and safe for an AML compliance product.

---

## Pipeline overview

```
Push / Pull Request
        │
        ▼
┌──────────────┐
│   quality    │   ~3 min  black · ruff · mypy
└──────┬───────┘
       │ (fail-fast: cheapest checks first)
       ├─────────────────────────┐
       ▼                         ▼
┌──────────────┐        ┌────────────────┐
│     test     │        │    security    │   ~2 min  pip-audit · detect-secrets
└──────┬───────┘        └───────┬────────┘
       │                        │
       └────────────┬───────────┘
                    │ (both must pass before building)
                    ▼
           ┌──────────────┐
           │    build     │   ~3 min  docker build (no push on CI)
           └──────────────┘

────────── main branch only ───────────────────────

Push to main (after CI passes)
        │
        ▼
┌─────────────────────┐
│     build-push      │   ~5 min  WIF auth → Artifact Registry push
│                     │          (SHA tag + latest tag + SBOM)
└──────┬──────────────┘
       │ outputs: image_tag, digest, git_sha
       ▼
┌─────────────────────┐
│   deploy staging    │   ~5 min  3-placeholder sed substitution
│   + smoke tests     │          gcloud run services replace
└─────────────────────┘          scripts/smoke_test.py
```

---

## CI workflow (`.github/workflows/ci.yml`)

Triggers on every push to any branch and on pull requests targeting main.

### Job: `quality`

| Step | Tool | Purpose |
|------|------|---------|
| Formatting check | `black --check` | Consistent code style |
| Linting | `ruff check` | Import order, naming, common errors |
| Type checking | `mypy` | Catch type errors in the serving layer |

`mypy` runs in non-strict mode with `--ignore-missing-imports` to avoid failures from untyped third-party packages (numpy, scikit-learn).

### Job: `test`

Depends on `quality`. Runs all tests in two invocations:

**Tier 1 & 2** — Unit and integration tests:
```
python -m pytest tests/ --ignore=tests/operational \
    --cov=alertiq --cov-fail-under=70
```

Tests use synthetic in-memory fixtures (`tests/serving/conftest.py` trains a `TriageScorer` on numpy arrays). No `alerts.csv` or pre-trained artifact is required in CI.

**Tier 3** — Operational failure-mode tests:
```
python -m pytest tests/operational/
```

These tests exercise the system at its failure boundaries: audit write failures, degraded mode (no model), oversized payloads, malformed JSON, and deployment traceability field population.

Coverage report is uploaded as a GitHub Actions artifact (`coverage-report-<sha>`).

### Job: `security`

Depends on `quality`. Runs in parallel with `test`.

| Step | Tool | Behaviour |
|------|------|-----------|
| Dependency CVE scan | `pip-audit` | Soft-fail on unfixable transitive CVEs (produces `security-report.md`) |
| Secret scanning | `detect-secrets` | Hard-fail if high-entropy strings are detected outside `.venv` and `.git` |

The security report is uploaded as a GitHub Actions artifact (`security-report-<sha>`, retained 30 days).

> **Note on soft-fail**: `pip-audit` uses `|| true` to avoid hard-failing on CVEs in transitive dependencies that cannot be fixed by pinning. Review `security-report.md` in the Actions artifact and address any fixable CVEs before merging.

### Job: `build`

Depends on **both** `test` and `security`. Only proceeds if both pass — a broken or vulnerable image is never built.

Builds the Docker image using layer caching from the GitHub Actions cache. Does **not** push the image (push is handled by the CD workflow on `main` only).

---

## CD workflow (`.github/workflows/cd.yml`)

Triggers when the CI workflow completes successfully on the `main` branch.

### Authentication: Workload Identity Federation

The CD workflow authenticates to Google Cloud using Workload Identity Federation (WIF). No long-lived service account JSON key is stored in GitHub secrets. WIF exchanges GitHub's OIDC JWT for a short-lived GCP access token scoped to the CD service account.

Trust chain:
```
GitHub OIDC token (per-workflow-run)
        │
        ▼ STS token exchange
Short-lived GCP access token
        │
        ▼ impersonation
alertiq-cd service account
        │
        ├─▶ Artifact Registry (write)
        └─▶ Cloud Run (deploy)
```

**Required GitHub secrets:**

| Secret | Description |
|--------|-------------|
| `GCP_PROJECT_ID` | Google Cloud project ID |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |
| `GCP_SERVICE_ACCOUNT` | Service account email for impersonation |

See `docs/DEPLOYMENT.md` and `infra/terraform/` for the one-time GCP setup.

### Container registry: Google Artifact Registry

Images are pushed to:
```
europe-west1-docker.pkg.dev/<project>/alertiq/api:<git-sha>  (immutable)
europe-west1-docker.pkg.dev/<project>/alertiq/api:latest     (mutable, for cache)
```

Artifact Registry is in the same GCP project and region as Cloud Run, which:
- Eliminates cross-registry authentication
- Allows Cloud Run to pull images using the same WIF service account
- Avoids cross-region egress costs

SHA tags are immutable — a re-push to the same tag is rejected. Only SHA tags are used for deployment and rollback. `latest` is used only for build-cache warming.

### Deployment traceability

The `build-push` job captures three values and passes them to the `deploy` job as outputs:

| Output | Value |
|--------|-------|
| `image_tag` | Full Artifact Registry URL with SHA tag |
| `digest` | `sha256:...` image content digest |
| `git_sha` | 40-character Git commit SHA |

All three are substituted into `deploy/cloudrun-staging.yaml` before deploying:

```bash
sed \
  -e "s|IMAGE_TAG_PLACEHOLDER|${IMAGE_TAG}|g" \
  -e "s|GIT_SHA_PLACEHOLDER|${GIT_SHA}|g" \
  -e "s|DIGEST_PLACEHOLDER|${DIGEST}|g" \
  deploy/cloudrun-staging.yaml > /tmp/deploy.yaml
gcloud run services replace /tmp/deploy.yaml --region="${AR_REGION}"
```

All three values are exposed via `GET /health` in the deployed service, making it possible to trace any revision back to its exact source commit and byte-for-byte container image.

### Job: `build-push`

Builds the Docker image, pushes to Artifact Registry, and captures the image digest. Produces a Software Bill of Materials (SBOM) and provenance attestation for supply-chain transparency.

### Job: `deploy`

Deploys to Cloud Run staging using declarative IaC with three-placeholder substitution (above). Waits up to 90 seconds for the service to report ready, then runs smoke tests via `scripts/smoke_test.py`.

**Production promotion** is a deliberate manual step. See `docs/DEPLOYMENT.md`.

---

## Concurrency control

The CI workflow uses a `concurrency` group per branch that cancels in-progress runs when a new push arrives:

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

The CD workflow uses a serialising concurrency group (no cancel) to prevent two simultaneous deployments:

```yaml
concurrency:
  group: cd-deploy
  cancel-in-progress: false
```

---

## Local equivalents

Run any CI step locally before pushing:

```bash
# Formatting
black --check src/ tests/ scripts/

# Linting
ruff check src/ tests/ scripts/

# Type checking
mypy src/alertiq/serving/ --ignore-missing-imports --no-strict-optional

# Tests
ALERTIQ_AUDIT_LOG_PATH="" python -m pytest tests/ --ignore=tests/operational -q
ALERTIQ_AUDIT_LOG_PATH="" python -m pytest tests/operational/ -q

# Security
pip-audit --requirement <(pip freeze) --skip-editable --format=markdown
detect-secrets scan --no-verify . > secrets-scan.json

# Docker build (local, no push)
docker build -t alertiq-api:local .

# Authenticate to Artifact Registry (for manual push)
gcloud auth configure-docker europe-west1-docker.pkg.dev
```

---

## Adding a new CI check

1. Add the step to the appropriate job in `.github/workflows/ci.yml`.
2. If the check should block the Docker build, add it to `needs: [test, security]`.
3. Document the check here.

---

## Rollback

Rollback does not require a CI/CD change. See `docs/OPERATIONS_RUNBOOK.md` for the rollback procedure.
