# One-command shortcuts. Run from the repo root.

.PHONY: ingest ingest-bigquery

# Default: download CMS data + load into local DuckDB (no credentials needed).
ingest:
	python ingestion/download_cms.py --target duckdb

# Cloud: also load into BigQuery. Needs BQ_PROJECT and GOOGLE_APPLICATION_CREDENTIALS.
# Example: make ingest-bigquery BQ_PROJECT=my-gcp-project
ingest-bigquery:
	python ingestion/download_cms.py --target both --bq-project $(BQ_PROJECT)
