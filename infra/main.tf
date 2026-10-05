# ─────────────────────────────────────────────────────────────
# HCAHPS platform layer — managed with Terraform.
#
# What this owns (and nothing else):
#   • BigQuery API enablement
#   • Datasets: `raw` and `analytics`
#   • Pipeline service account + least-privilege IAM
#   • The $1 budget alert (our $0 cost-cap guardrail, as code)
#
# What this does NOT own:
#   • TABLES — dbt creates those from models (M3). Terraform touching
#     tables would fight dbt, so the boundary is: Terraform = datasets,
#     dbt = everything inside them.
#   • The GCP project itself and the billing-account link — those need
#     your interactive login, so you create them once in the console.
#   • The service-account JSON KEY — created manually in the console on
#     purpose, so the private key never lands in Terraform state.
# ─────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---- APIs ----------------------------------------------------
resource "google_project_service" "bigquery" {
  service            = "bigquery.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "billing_budgets" {
  service            = "billingbudgets.googleapis.com"
  disable_on_destroy = false
}

# ---- Datasets ------------------------------------------------
# dbt will create tables inside these; Terraform only owns the containers.
resource "google_bigquery_dataset" "raw" {
  dataset_id  = "raw"
  description = "Raw layer: untouched CMS source files. Containers managed by Terraform; tables loaded by ingestion."
  location    = var.region
  depends_on  = [google_project_service.bigquery]
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id  = "analytics"
  description = "Analytics layer: dbt-built marts. Containers managed by Terraform; tables created by dbt."
  location    = var.region
  depends_on  = [google_project_service.bigquery]
}

# ---- Pipeline service account --------------------------------
resource "google_service_account" "pipeline" {
  account_id   = "hcahps-pipeline"
  display_name = "HCAHPS pipeline service account"
  description  = "Used by ingestion and dbt to write BigQuery datasets. JSON key is created manually — never in state."
}

# Lets the service account RUN query jobs in the project (required for any BQ work).
resource "google_project_iam_member" "pipeline_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

# Lets it read/write DATA, scoped to just our two datasets (least privilege —
# no project-wide dataEditor, so a compromised key can't touch other datasets).
resource "google_bigquery_dataset_iam_member" "pipeline_raw_editor" {
  dataset_id = google_bigquery_dataset.raw.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_bigquery_dataset_iam_member" "pipeline_analytics_editor" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.pipeline.email}"
}

# ---- $1 budget alert (the $0 guardrail, as code) --------------
resource "google_monitoring_notification_channel" "email" {
  display_name = "HCAHPS budget alerts"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

resource "google_billing_budget" "zero_spend_guardrail" {
  billing_account = var.billing_account_id
  display_name    = "HCAHPS $1 guardrail"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "1"
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.email.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.billing_budgets]
}
