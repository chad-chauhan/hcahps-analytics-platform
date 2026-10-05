# infra/ — platform layer runbook

## What this folder is (plain language)

Terraform code that creates the *platform* our pipeline runs on: the two BigQuery
datasets, the pipeline's service account with least-privilege access, and the $1
budget alert that guards our $0 cost cap. Everything here is version-controlled,
so the platform can be rebuilt exactly, reviewed in pull requests, and torn down
cleanly.

**Boundary reminder:** Terraform owns *datasets*. dbt owns *tables* (M3). The GCP
project itself and the billing-account link are created once by you in the console
— Terraform can't do those without your login.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.5
- [gcloud CLI](https://cloud.google.com/sdk/docs/install)
- The GCP project created and billing linked (console steps below)

## Runbook

### Step 1 — Create the project + link billing (console, one time, ~5 min)

1. https://console.cloud.google.com → select/create project → **New project** →
   Project ID like `hcahps-analytics` → Create.
2. **Billing** (left menu) → **Link a billing account** → select yours.
   (This is the only step that touches money — and the budget alert in Step 3
   guards it.)
3. Note your **project ID** and **billing account ID**
   (`billingAccounts/XXXXXX-XXXXXX-XXXXXX`, shown on the Billing page).

### Step 2 — Configure (local, ~2 min)

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set project_id and billing_account_id.
```

### Step 3 — Authenticate + apply (local, ~5 min)

```bash
# Log in with the Google account that owns the project:
gcloud auth application-default login
gcloud auth application-default set-quota-project <your-project-id>

terraform init     # downloads the Google provider (no credentials needed)
terraform plan     # DRY RUN — shows exactly what will be created. Review it.
terraform apply    # type "yes" — creates datasets, service account, IAM, budget
```

The Terraform provider also explicitly uses `project_id` as its quota project.
The authenticated account must have `serviceusage.services.use` on that project
(for example, through `roles/serviceusage.serviceUsageConsumer`), and
`billingbudgets.googleapis.com` must be enabled there.

Expected result (~10 resources):

- `google_project_service.bigquery` + `billing_budgets` (APIs enabled)
- `google_bigquery_dataset.raw` and `.analytics`
- `google_service_account.pipeline` (`hcahps-pipeline@<project>.iam.gserviceaccount.com`)
- IAM: `bigquery.jobUser` on the project, `bigquery.dataEditor` on both datasets
- `google_billing_budget.zero_spend_guardrail` ($1, alerts at 50/90/100%)
- `google_monitoring_notification_channel.email` (alerts to chadch615@gmail.com)

### Step 4 — Create the JSON key (console, ~2 min, manual on purpose)

The private key is created by you so it never lands in Terraform state:

1. https://console.cloud.google.com/iam-admin/serviceaccounts → select your project
2. Click `hcahps-pipeline` → **Keys** → **Add key** → **Create new key** → **JSON**
3. Your browser downloads the file. **Store it outside the repo**, e.g.
   `~/.config/gcloud/hcahps-pipeline-key.json`. Never commit it, never paste it
   in chat.
4. Use it:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/hcahps-pipeline-key.json
   make ingest-bigquery BQ_PROJECT=<your-project-id>
   ```

### Tear down (if ever needed)

```bash
terraform destroy   # removes everything Terraform created, nothing else
```

## Verify it worked

```bash
# Datasets exist:
bq ls --project_id=<your-project-id>
# Budget exists: Cloud Console → Billing → Budgets & alerts → "HCAHPS $1 guardrail"
```
