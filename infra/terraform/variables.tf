# ============================================================================ #
# AlertIQ — Terraform Input Variables
# ============================================================================ #

variable "project_id" {
  description = "GCP project ID where all AlertIQ resources are created."
  type        = string
}

variable "region" {
  description = "GCP region for Artifact Registry and Cloud Run (must match deployment YAMLs)."
  type        = string
  default     = "europe-west1"
}

variable "github_owner" {
  description = "GitHub organisation or username that owns the alertiq repository (used in WIF attribute condition)."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without owner prefix, e.g. 'alertiq')."
  type        = string
  default     = "alertiq"
}

variable "artifact_registry_repository" {
  description = "Artifact Registry repository name (must match the AR_REPOSITORY env var in cd.yml)."
  type        = string
  default     = "alertiq"
}

variable "cd_service_account_name" {
  description = "Short name for the CD service account (the part before @<project>.iam.gserviceaccount.com)."
  type        = string
  default     = "alertiq-cd"
}

variable "wif_pool_id" {
  description = "Workload Identity Pool ID (alphanumeric and hyphens, max 32 chars)."
  type        = string
  default     = "alertiq-pool"
}

variable "wif_provider_id" {
  description = "Workload Identity Provider ID within the pool."
  type        = string
  default     = "alertiq-github-provider"
}
