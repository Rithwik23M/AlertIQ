# ============================================================================ #
# AlertIQ — Terraform Version Constraints
# ============================================================================ #

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Recommended: use a remote backend (GCS) for shared state.
  # Uncomment and configure once the bucket exists:
  #
  # backend "gcs" {
  #   bucket = "<your-tfstate-bucket>"
  #   prefix = "alertiq/terraform/state"
  # }
  #
  # To create the bucket:
  #   gsutil mb -l europe-west1 gs://<your-project-id>-tfstate
  #   gsutil versioning set on gs://<your-project-id>-tfstate
  #
  # For a solo portfolio project, local state (the default) is acceptable.
  # Commit .terraform.lock.hcl but NOT terraform.tfstate or terraform.tfstate.backup.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
