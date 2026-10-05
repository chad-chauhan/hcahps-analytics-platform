# Ingestion — raw layer runbook

## What this step does (plain language)

Downloads the two public CMS datasets and puts them into the **raw layer** — the
bottom of our data platform. "Raw" means: exactly as CMS published them, no
cleaning, no renaming. If anyone ever questions a number downstream, we can trace
it back to these untouched files.

## The two datasets

| Table we create | CMS dataset | CMS ID | Approx. rows |
|---|---|---|---|
| `raw_hcahps` | Patient survey (HCAHPS) - Hospital | `dgck-syfz` | ~325,000 |
| `raw_hospital_outcomes` | Complications and Deaths - Hospital | `ynj2-r877` | ~95,000 |

Source: <https://data.cms.gov/provider-data/> (U.S. Government Open Data, public domain).

## How to run

```bash
# From the repo root, with the virtualenv active:
pip install -r ingestion/requirements.txt

# Load into local DuckDB (no account, no credentials needed):
make ingest
# which is shorthand for:
python ingestion/download_cms.py --target duckdb

# Re-run without re-downloading (uses CSVs already in ingestion/raw/):
python ingestion/download_cms.py --target duckdb --skip-download

# Load into BigQuery instead (needs GCP project + service-account key):
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
make ingest-bigquery BQ_PROJECT=your-gcp-project-id
```

## How to verify it worked

The script prints a verification report at the end: row counts and column names per
table. You can also inspect the DuckDB file directly:

```bash
python -c "
import duckdb
con = duckdb.connect('warehouse/hcahps.duckdb')
print(con.execute('SHOW TABLES').fetchall())
print(con.execute('SELECT COUNT(*) FROM raw.raw_hcahps').fetchall())
"
```

## Design notes

- **Idempotent:** re-running produces the same result — tables are replaced, not appended.
- **DuckDB first:** the default target needs zero credentials, so anyone can run it.
- **BigQuery path is credential-gated:** without `GOOGLE_APPLICATION_CREDENTIALS`
  it prints a clear skip message instead of failing.
- Raw CSVs are git-ignored (they're large); the script re-downloads them on demand.
