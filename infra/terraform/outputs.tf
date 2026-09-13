# ============================================================================ #
# AlertIQ — Terraform Outputs
# ============================================================================ #
#
# Copy these values into GitHub repository secrets after `terraform apply`.
#
# ============================================================================ #

output "wif_provider_name" {
  description = "Full resource name of the Workload Identity Provider. Set as GCP_WORKLOAD_IDENTITY_PROVIDER in GitHub secrets."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "cd_service_account_email" {
  description = "Email of the CD service account. Set as GCP_SERVICE_ACCOUNT in GitHub secrets."
  value       = google_service_account.cd.email
}

output "artifact_registry_url" {
  description = "Base URL for Artifact Registry images (region-docker.pkg.dev/project/repo)."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repository}"
}

output "artifact_registry_image" {
  description = "Full image path for the AlertIQ API (append :<tag> or @<digest> for deployment)."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repository}/api"
}

output "github_actions_setup_summary" {
  description = "Summary of GitHub secrets to configure after applying this Terraform configuration."
  value = <<-EOT
    ─────────────────────────────────────────────────────────────────
    GitHub repository secrets to configure:

    GCP_PROJECT_ID:
      ${var.project_id}

    GCP_WORKLOAD_IDENTITY_PROVIDER:
      ${google_iam_workload_identity_pool_provider.github.name}

    GCP_SERVICE_ACCOUNT:
      ${google_service_account.cd.email}

    Docker image base URL (for reference):
      ${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repository}/api
    ─────────────────────────────────────────────────────────────────
  EOT
}
