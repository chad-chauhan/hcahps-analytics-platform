variable "project_id" {
  description = "GCP project ID (e.g. hcahps-analytics). You create this once in the Cloud Console."
  type        = string
}

variable "billing_account_id" {
  description = "Billing account ID in the form billingAccounts/010C48-E97F9D-6D434E (find it on the Cloud Console Billing page)."
  type        = string
}

variable "region" {
  description = "BigQuery dataset location."
  type        = string
  default     = "US"
}

variable "alert_email" {
  description = "Email address that receives the $1 budget alerts."
  type        = string
  default     = "chadch615@gmail.com"
}
