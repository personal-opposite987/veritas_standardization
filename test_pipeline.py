

import sys
import os
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(PROJECT_ROOT, "ingestion_module", "GCS_BUCKET"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "standardization_module"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "validation_module"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "DB_LOADER_module"))

from dedup import run_ingestion
from standardize import standardise_all
from validate import validate_all
from loader import load_all

SAMPLE_DATA_FOLDER = os.path.join(PROJECT_ROOT, "ingestion_module", "GCS_BUCKET")
DB_PATH = os.path.join(PROJECT_ROOT, "DB_LOADER_module", "veritas.db")

# sqlite3.connect() does NOT create missing parent directories -- only
# the file itself. Ensure the folder exists before connecting, or the
# connect call fails with "unable to open database file".
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def main():
    print("=" * 60)
    print("STAGE 1: INGESTION")
    print("=" * 60)
    unique, dupes = run_ingestion(SAMPLE_DATA_FOLDER)
    print(f"Unique records: {len(unique)}")
    print(f"Duplicates filtered: {len(dupes)}")

    print()
    print("=" * 60)
    print("STAGE 2: STANDARDISATION")
    print("=" * 60)
    standardised = standardise_all(unique)
    print(f"Encounters: {len(standardised['encounters'])}")
    print(f"Lab results: {len(standardised['lab_results'])}")
    print(f"Medications: {len(standardised['medications'])}")

    print()
    print("=" * 60)
    print("STAGE 3: VALIDATION")
    print("=" * 60)
    validated = validate_all(standardised)

    status_counts = Counter(r["validation_status"] for r in validated["lab_results"])
    print("Lab result validation_status distribution:")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}")

    print()
    print("=" * 60)
    print("STAGE 4: DB LOADER")
    print("=" * 60)
    summary = load_all(validated, db_path=DB_PATH, duplicate_log=dupes)
    print(f"Encounters inserted: {summary['encounters_inserted']}")
    print(f"Encounters skipped (duplicate): {summary['encounters_skipped_duplicate']}")
    print(f"Lab results loaded: {summary['lab_results_loaded']}")
    print(f"Medications loaded: {summary['medications_loaded']}")
    print(f"DB file: {DB_PATH}")

    print()
    print("=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    return summary


if __name__ == "__main__":
    main()