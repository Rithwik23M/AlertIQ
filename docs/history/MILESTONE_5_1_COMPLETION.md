# AlertIQ  -  Milestone 5.1 Completion Report

**Milestone:** Cloud Hardening (post-Milestone 5 adversarial review)
**Status:** ✅ Complete
**All tests:** 597 unit/integration + 30 operational = **627 passing, 0 failing**

---

## What was changed

Milestone 5.1 addressed eight findings from the adversarial review of the Milestone 5 deployment configuration. No product functionality was added. The changes harden the infrastructure, improve deployment traceability, and produce accurate documentation.

---

## Findings and resolutions

### Finding 1  -  Incorrect billing model in production

**Problem:** `cloudrun-production.yaml` used `minScale: "1"` and `cpu-throttling: "false"` (instance-based billing, ~$5–10/month idle). The cost estimate claimed ~$3–5/month but the billing model was wrong for a portfolio project receiving occasional traffic.

**Resolution:** Changed production to match staging: `minScale: "0"`, `cpu-throttling: "true"`, `cpu: "1"`, `memory: 512Mi`. Both environments now use request-based billing. Expected cost: **$0** within the 2 M free request tier.

Added a billing trade-off table in the production YAML header and in `OPERATIONS_RUNBOOK.md §Latency issues` documenting the cold-start penalty (~3–10 s) and the conditions under which `minScale: 1` should be reconsidered.

---

### Finding 2  -  Wrong deployment region

**Problem:** `cloudrun-production.yaml` used `us-central1` while the Milestone 5 design specified `europe-west1` (sub-20 ms to Dublin, EU data location). `cd.yml` had a `GCP_REGION` secret that could be set to either region, creating a mismatch risk.

**Resolution:**
- `cloudrun-production.yaml`: all region references changed to `europe-west1`.
- `cd.yml`: `GCP_REGION` secret removed; region hardcoded as `AR_REGION: europe-west1` in workflow env. Region is now a code constant, not a secret that can be misconfigured.
- Added EU compliance disclaimer to both deployment YAMLs: region alone does NOT establish GDPR compliance or banking/AML regulatory compliance.
- Updated all docs.

---

### Finding 3  -  Container registry: GHCR → Google Artifact Registry

**Problem:** Images were pushed to `ghcr.io` (GitHub Container Registry), which is a separate authentication domain from GCP. This required a `packages: write` GitHub permission and created a two-registry trust chain.

**Resolution:** Replaced GHCR with Google Artifact Registry at `europe-west1-docker.pkg.dev/<project>/alertiq/api`. Changes:
- `cd.yml`: removed `packages: write` permission and GHCR login step. Docker now authenticates to Artifact Registry using the WIF access token (same credential as Cloud Run deployment).
- Image URL format: `europe-west1-docker.pkg.dev/<project>/alertiq/api:<sha>` (SHA tag, immutable) and `:latest` (mutable, cache only).
- SHA tags are immutable in Artifact Registry  -  a re-push to the same tag is rejected, making accidental overwrite of known-good images impossible.
- Updated CI_CD.md and DEPLOYMENT.md.

---

### Finding 4  -  Terraform infrastructure

**Problem:** No declarative infrastructure-as-code existed for the GCP resources. One-time setup required running manual `gcloud` commands from DEPLOYMENT.md, which is error-prone and not reproducible.

**Resolution:** Created `infra/terraform/` with four files:

| File | Contents |
|------|---------|
| `versions.tf` | Terraform and Google provider version pins |
| `variables.tf` | Input variables: project_id, region, github_owner, github_repo |
| `main.tf` | All GCP resources: APIs, Artifact Registry, CD service account, IAM, WIF pool + provider |
| `outputs.tf` | WIF provider name, SA email, Artifact Registry URL (ready to paste into GitHub secrets) |

**Terraform scope:** Provisions infrastructure only. Cloud Run service management stays in the CD workflow (`gcloud run services replace`) to avoid Terraform state conflicts with a CI/CD-driven deployment.

**Interview defensibility:** The Terraform configuration is small enough to explain completely: five GCP APIs enabled, one Artifact Registry repository, one service account with two IAM roles, one WIF pool and provider, one IAM binding scoped to the specific GitHub repository.

---

### Finding 5  -  Audit durability classification

**Problem:** Audit durability was undocumented. The fail-open behaviour was implemented and tested, but an engineer deploying to a regulated environment would not know what durability guarantees existed or what upgrades were needed.

**Resolution:** Added an `Audit Durability Classification` section to both `DEPLOYMENT.md` and `OPERATIONS_RUNBOOK.md` documenting:

- Current behaviour: stdout → Cloud Logging (non-durable at the Cloud Run layer)
- What happens on instance termination (buffered records may be lost)
- What a regulated FI would require (Spanner, BigQuery, GCS WORM)
- Fail-open vs. fail-closed trade-offs
- The upgrade path (replacing `_emit()` in `AuditLogger`)

No database was added  -  the portfolio deployment is correctly documented as best-effort, fail-open audit logging.

---

### Finding 6  -  Deployment traceability

**Problem:** The staging YAML had `IMAGE_TAG_PLACEHOLDER` (one placeholder). The production YAML had no placeholders. Neither YAML exposed the deploying commit SHA or image content digest in the running service. The `/health` endpoint did not surface any traceability fields.

**Resolution:**
- Both service YAMLs: added `ALERTIQ_GIT_SHA` and `ALERTIQ_IMAGE_DIGEST` env vars with corresponding `GIT_SHA_PLACEHOLDER` and `DIGEST_PLACEHOLDER` values.
- `cd.yml`: captures `digest` from `docker/build-push-action` and `git_sha` from `github.event.workflow_run.head_sha`; substitutes all three placeholders with a three-line `sed` command.
- `schema.py` (`HealthResponse`): added `git_sha: str | None = None` and `image_digest: str | None = None`.
- `app.py` (`health()`): reads `ALERTIQ_GIT_SHA` and `ALERTIQ_IMAGE_DIGEST` from the environment; populates both fields in `HealthResponse` for all service states (ok, degraded).
- 4 new operational tests verify the traceability fields: absent without env vars, populated when set, present in degraded mode.

Every deployed Cloud Run revision can now answer: which Git commit, which container bytes, which model version, which Cloud Run revision, and what timestamp.

---

### Finding 7  -  Cost safeguards documentation

**Problem:** The documentation implied that `maxScale` was a hard billing cap and that ~$3–5/month was correct for production.

**Resolution:**
- Corrected cost estimates in DEPLOYMENT.md and MILESTONE_5_COMPLETION.md.
- Added explicit documentation that `maxScale` is a soft limit (caps autoscaling, not billing).
- Documented the recommended Billing Alert procedure (Cloud Console → Billing → Budgets & alerts).
- Explicitly stated that billing alerts notify but do NOT hard-stop spending  -  a Cloud Function would be required for a hard cap.

---

### Finding 8  -  Validate

Full test suite run after all changes.

```
Tier 1 + Tier 2 (unit and integration):  597 passed, 0 failed
Tier 3 (operational failure-mode):        30 passed, 0 failed  (+4 traceability tests)
─────────────────────────────────────────────────────────────────────────
Total:                                   627 passed, 0 failed
```

---

## Files changed

| File | Change |
|------|--------|
| `deploy/cloudrun-staging.yaml` | Added GIT_SHA_PLACEHOLDER, DIGEST_PLACEHOLDER, EU region comments, compliance disclaimer |
| `deploy/cloudrun-production.yaml` | Changed to europe-west1, min=0, cpu-throttling=true, 1 CPU/512Mi, added traceability placeholders |
| `.github/workflows/cd.yml` | Replaced GHCR with Artifact Registry; added digest capture; three-placeholder sed substitution |
| `src/alertiq/serving/schema.py` | Added `git_sha`, `image_digest` to `HealthResponse` |
| `src/alertiq/serving/app.py` | Health endpoint reads and exposes GIT_SHA/IMAGE_DIGEST env vars |
| `tests/operational/test_failure_modes.py` | Added `TestDeploymentTraceability` (4 tests) |
| `infra/terraform/versions.tf` | New  -  Terraform version constraints |
| `infra/terraform/variables.tf` | New  -  input variables |
| `infra/terraform/main.tf` | New  -  GCP resource definitions |
| `infra/terraform/outputs.tf` | New  -  WIF provider name, SA email, registry URL |
| `infra/terraform/.gitignore` | New  -  excludes state files and plan outputs |
| `docs/DEPLOYMENT.md` | Major rewrite: Artifact Registry, europe-west1, Terraform, audit durability, cost safeguards |
| `docs/CI_CD.md` | Updated: Artifact Registry, WIF auth chain, three-placeholder substitution |
| `docs/OPERATIONS_RUNBOOK.md` | Added traceability runbook entry, audit durability classification, europe-west1 region |
| `docs/MILESTONE_5_COMPLETION.md` | Updated cost estimate to europe-west1 / request-based billing |

---

## What was intentionally not changed

Per Milestone 5.1 constraints:

- ML system and API scoring logic are unchanged.
- No product functionality added.
- No Kubernetes introduced.
- No MLflow or heavyweight model registry introduced.
- No database added to the audit transport (documented as a future upgrade path, not a checkbox).
- Output labels continue to not imply autonomous compliance determination.
- Milestone 6 has not been started.
