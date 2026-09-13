# ============================================================================ #
# AlertIQ — GCP Infrastructure
# ============================================================================ #
#
# What this file provisions (IaC scope):
#
#   1. Required GCP APIs
#   2. Google Artifact Registry repository
#   3. CD service account + IAM roles
#   4. Workload Identity Federation pool and GitHub provider
#   5. IAM binding: allow GitHub Actions to impersonate the CD service account
#
# What is deliberately EXCLUDED from Terraform:
#
#   • Cloud Run services — managed by `gcloud run services replace` in cd.yml.
#     Mixing Terraform state with a CI/CD-driven gcloud deployment creates
#     conflicts.  The deployment YAMLs in deploy/ are the source of truth for
#     the running service configuration.
#
#   • Secrets — created manually in Google Secret Manager once, then referenced
#     in cloud run YAMLs via secretKeyRef.
#
#   • DNS / HTTPS certificate — Cloud Run provides a managed TLS endpoint;
#     custom domain mapping is a one-off gcloud step documented in DEPLOYMENT.md.
#
# ── Deployment commands ─────────────────────────────────────────────────── #
#
#   cd infra/terraform
#   terraform init
#   terraform plan -var="project_id=<YOUR_PROJECT>" \
#                  -var="github_owner=<YOUR_GITHUB_ORG_OR_USER>"
#   terraform apply -var="project_id=<YOUR_PROJECT>" \
#                   -var="github_owner=<YOUR_GITHUB_ORG_OR_USER>"
#
# After apply, copy the outputs into GitHub repository secrets:
#
#   GCP_PROJECT_ID                  ← var.project_id
#   GCP_WORKLOAD_IDENTITY_PROVIDER  ← output.wif_provider_name
#   GCP_SERVICE_ACCOUNT             ← output.cd_service_account_email
#
# ============================================================================ #

# ── 1. Required GCP APIs ─────────────────────────────────────────────────── #

locals {
  required_apis = [
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false  # Do not disable APIs when running `terraform destroy`
                              # — other workloads in the project may depend on them.
}

# ── 2. Artifact Registry repository ─────────────────────────────────────── #

resource "google_artifact_registry_repository" "alertiq" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repository
  format        = "DOCKER"
  description   = "AlertIQ API container images"

  depends_on = [google_project_service.required]
}

# ── 3. CD service account ────────────────────────────────────────────────── #

resource "google_service_account" "cd" {
  project      = var.project_id
  account_id   = var.cd_service_account_name
  display_name = "AlertIQ CD service account"
  description  = "Used by GitHub Actions (via WIF) to push images and deploy to Cloud Run."
}

# Role: push images to Artifact Registry.
resource "google_project_iam_member" "cd_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.cd.email}"
}

# Role: deploy to Cloud Run.
resource "google_project_iam_member" "cd_cloud_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.cd.email}"
}

# Role: allow Cloud Run to pull images from Artifact Registry on behalf of the
# default Compute service account (needed when Cloud Run creates new instances).
# Note: this binding targets the project-level Compute SA, not the CD SA.
resource "google_project_iam_member" "compute_artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${data.google_compute_default_service_account.default.email}"
}

data "google_compute_default_service_account" "default" {
  project = var.project_id

  depends_on = [google_project_service.required]
}

# ── 4. Workload Identity Federation ─────────────────────────────────────── #
#
# WIF lets GitHub Actions obtain a short-lived GCP access token by presenting
# the OIDC JWT that GitHub generates for each workflow run.  No long-lived
# service account key is stored anywhere.
#
# Trust chain:
#   GitHub OIDC token  →  STS token exchange  →  CD service account token
#

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = var.wif_pool_id
  display_name              = "GitHub Actions pool"
  description               = "Allows GitHub Actions to authenticate to GCP without a service account key."

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  display_name                       = "GitHub OIDC provider"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  # Attribute mappings: project GitHub's JWT claims onto Google attributes.
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Attribute condition: only allow tokens from this specific repository.
  # This prevents any other GitHub repo from impersonating this service account.
  attribute_condition = "assertion.repository == '${var.github_owner}/${var.github_repo}'"
}

# ── 5. Allow GitHub Actions to impersonate the CD service account ─────── #

resource "google_service_account_iam_member" "github_wif_impersonation" {
  service_account_id = google_service_account.cd.name
  role               = "roles/iam.workloadIdentityUser"

  # The principal set grants impersonation to all tokens from the repository.
  member = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}
