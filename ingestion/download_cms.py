#!/usr/bin/env python3
"""
Download public CMS hospital datasets and load them into the RAW layer.

What it does (in order):
  1. Downloads two CSV files from data.cms.gov — untouched, saved under ingestion/raw/.
  2. Loads each CSV into the raw layer:
       - DuckDB (default): a local file at warehouse/hcahps.duckdb — no account needed.
       - BigQuery (with --target bigquery): a `raw` dataset in your GCP project.
  3. Prints a verification report: row counts and columns per table.

Examples:
  python ingestion/download_cms.py --target duckdb
  python ingestion/download_cms.py --target bigquery --bq-project my-gcp-project
  python ingestion/download_cms.py --target both --bq-project my-gcp-project

BigQuery needs GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account JSON
key. Without it, the BigQuery step is skipped with a clear message — nothing fails.
"""

import argparse
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent          # ingestion/
REPO_ROOT = BASE_DIR.parent                          # repo root
RAW_DIR = BASE_DIR / "raw"                           # untouched source files
WAREHOUSE_DIR = REPO_ROOT / "warehouse"              # local DuckDB file lives here
DUCKDB_PATH = WAREHOUSE_DIR / "hcahps.duckdb"

# CMS Provider Data Catalog — stable datastore API. Dataset pages:
#   HCAHPS:    https://data.cms.gov/provider-data/dataset/dgck-syfz
#   Outcomes:  https://data.cms.gov/provider-data/dataset/ynj2-r877
DATASETS = {
    "raw_hcahps": {
        "cms_id": "dgck-syfz",
        "title": "Patient survey (HCAHPS) - Hospital",
        "csv_name": "hcahps_hospital.csv",
    },
    "raw_hospital_outcomes": {
        "cms_id": "ynj2-r877",
        "title": "Complications and Deaths - Hospital",
        "csv_name": "hospital_outcomes.csv",
    },
}

API_URL = "https://data.cms.gov/provider-data/api/1/datastore/query/{cms_id}/0/download?format=csv"


def download_csv(cms_id: str, dest: Path, retries: int = 3) -> Path:
    """Download a CMS dataset CSV with retries. Returns the saved file path."""
    url = API_URL.format(cms_id=cms_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            print(f"  downloading (attempt {attempt}/{retries}): {url}")
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):  # 1 MB chunks
                        f.write(chunk)
            size_mb = dest.stat().st_size / (1 << 20)
            print(f"  saved {dest.name} ({size_mb:.1f} MB)")
            return dest
        except Exception as e:  # network hiccup — retry
            last_error = e
            print(f"  attempt {attempt} failed: {e}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"download failed after {retries} attempts: {last_error}")


def load_duckdb(csv_path: Path, table: str) -> dict:
    """Load a CSV into the local DuckDB raw layer. Returns {rows, columns}."""
    import duckdb

    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        # Replace the table so re-runs are idempotent (same result every time).
        con.execute(
            f"CREATE OR REPLACE TABLE raw.{table} AS "
            f"SELECT * FROM read_csv_auto('{csv_path}', header=true, sample_size=-1)"
        )
        rows = con.execute(f"SELECT COUNT(*) FROM raw.{table}").fetchone()[0]
        cols = [d[0] for d in con.execute(f"SELECT * FROM raw.{table} LIMIT 0").description]
        return {"rows": rows, "columns": cols}
    finally:
        con.close()


def load_bigquery(csv_path: Path, table: str, project: str) -> dict:
    """Load a CSV into BigQuery dataset `raw`. Returns {rows}."""
    import os

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("  SKIP: GOOGLE_APPLICATION_CREDENTIALS is not set — BigQuery load skipped.")
        print("        (DuckDB load above still succeeded. See ingestion/README.md.)")
        return {"rows": None, "skipped": True}

    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    dataset_id = f"{project}.raw"
    # Create the dataset if it doesn't exist yet.
    client.create_dataset(dataset_id, exists_ok=True)

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        autodetect=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,  # idempotent re-runs
    )
    with open(csv_path, "rb") as f:
        job = client.load_table_from_file(f, f"{dataset_id}.{table}", job_config=job_config)
    job.result()  # wait for completion
    rows = client.get_table(f"{dataset_id}.{table}").num_rows
    return {"rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest CMS hospital data into the raw layer.")
    parser.add_argument("--target", choices=["duckdb", "bigquery", "both"], default="duckdb",
                        help="Where to load the raw tables (default: duckdb).")
    parser.add_argument("--bq-project", default=None,
                        help="GCP project id (required for bigquery target).")
    parser.add_argument("--skip-download", action="store_true",
                        help="Reuse CSVs already in ingestion/raw/ instead of re-downloading.")
    args = parser.parse_args()

    if args.target in ("bigquery", "both") and not args.bq_project:
        print("ERROR: --bq-project is required when target includes bigquery.", file=sys.stderr)
        return 2

    report = {}
    for table, spec in DATASETS.items():
        print(f"\n=== {spec['title']} -> {table} ===")
        csv_path = RAW_DIR / spec["csv_name"]
        if args.skip_download and csv_path.exists():
            print(f"  reusing existing {csv_path.name}")
        else:
            download_csv(spec["cms_id"], csv_path)

        if args.target in ("duckdb", "both"):
            print("  loading into DuckDB (warehouse/hcahps.duckdb)...")
            stats = load_duckdb(csv_path, table)
            print(f"  raw.{table}: {stats['rows']:,} rows x {len(stats['columns'])} columns")
            report[table] = stats

        if args.target in ("bigquery", "both"):
            print(f"  loading into BigQuery ({args.bq_project}.raw.{table})...")
            stats = load_bigquery(csv_path, table, args.bq_project)
            if not stats.get("skipped"):
                print(f"  {args.bq_project}.raw.{table}: {stats['rows']:,} rows")

    # ---- verification report ----
    print("\n================ VERIFICATION ================")
    print(f"DuckDB file : {DUCKDB_PATH} ({'exists' if DUCKDB_PATH.exists() else 'not built'})")
    for table, stats in report.items():
        print(f"  raw.{table}: {stats['rows']:,} rows")
        print(f"    columns: {', '.join(stats['columns'][:8])} ... ({len(stats['columns'])} total)")
    print("Raw CSVs kept untouched in ingestion/raw/ for full traceability.")
    print("================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
