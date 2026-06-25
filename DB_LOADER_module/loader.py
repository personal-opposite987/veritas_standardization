

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "veritas.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS encounters (
    encounter_id        TEXT PRIMARY KEY,   -- = content_hash
    source_file          TEXT,
    classifier            TEXT,
    age_raw               TEXT,
    age_years             REAL,
    gender_raw            TEXT,
    gender_canonical      TEXT,
    admission_date_raw    TEXT,
    discharge_date_raw    TEXT,
    diagnosis             TEXT,
    brief_history         TEXT,
    doctor_name           TEXT,
    hospital_name         TEXT,
    ward                  TEXT,
    recommendations       TEXT,
    date_validation_status TEXT,
    date_flag_reason      TEXT,
    loaded_at             TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lab_results (
    result_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id          TEXT NOT NULL,
    source_file           TEXT,
    test_name_raw         TEXT,
    result_raw            TEXT,
    range_raw             TEXT,
    unit_raw              TEXT,
    analytics             TEXT,
    source_page_no        INTEGER,
    validation_status     TEXT,
    flag_reason           TEXT,
    FOREIGN KEY (encounter_id) REFERENCES encounters(encounter_id)
);

CREATE TABLE IF NOT EXISTS medications (
    medication_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id          TEXT NOT NULL,
    medicine_raw          TEXT,
    medicine_generic       TEXT,
    dose                  TEXT,
    frequency             TEXT,
    FOREIGN KEY (encounter_id) REFERENCES encounters(encounter_id)
);

CREATE TABLE IF NOT EXISTS error_log (
    error_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    error_type            TEXT,                -- 'duplicate' | 'unhandled_classifier' | other
    source_file           TEXT,
    error_reason          TEXT,
    raw_content           TEXT,
    logged_at             TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lab_results_encounter ON lab_results(encounter_id);
CREATE INDEX IF NOT EXISTS idx_medications_encounter ON medications(encounter_id);
"""


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _encounter_exists(conn: sqlite3.Connection, encounter_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM encounters WHERE encounter_id = ?", (encounter_id,)
    ).fetchone()
    return row is not None


def load_encounter_unit(
    conn: sqlite3.Connection,
    encounter: dict[str, Any],
    lab_results: list[dict[str, Any]],
    medications: list[dict[str, Any]],
) -> bool:
    """Loads one encounter and its child rows as a single atomic unit.

    Returns True if inserted, False if skipped as a duplicate.
    Raises if the insert fails for a reason OTHER than the expected
    UNIQUE constraint violation (e.g. a real schema mismatch) -- those
    should not be silently swallowed.
    """
    encounter_id = encounter["encounter_id"]

    if _encounter_exists(conn, encounter_id):
        return False  # duplicate -- skip the whole unit, see module docstring

    conn.execute(
        """
        INSERT INTO encounters (
            encounter_id, source_file, classifier, age_raw, age_years,
            gender_raw, gender_canonical, admission_date_raw, discharge_date_raw,
            diagnosis, brief_history, doctor_name, hospital_name, ward,
            recommendations, date_validation_status, date_flag_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            encounter_id, encounter.get("source_file"), encounter.get("classifier"),
            encounter.get("age_raw"), encounter.get("age_years"),
            encounter.get("gender_raw"), encounter.get("gender_canonical"),
            encounter.get("admission_date_raw"), encounter.get("discharge_date_raw"),
            encounter.get("diagnosis"), encounter.get("brief_history"),
            encounter.get("doctor_name"), encounter.get("hospital_name"),
            encounter.get("ward"), encounter.get("recommendations"),
            encounter.get("date_validation_status"), encounter.get("date_flag_reason"),
        ),
    )

    for r in lab_results:
        conn.execute(
            """
            INSERT INTO lab_results (
                encounter_id, source_file, test_name_raw, result_raw, range_raw,
                unit_raw, analytics, source_page_no, validation_status, flag_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                encounter_id, r.get("source_file"), r.get("test_name_raw"),
                r.get("result_raw"), r.get("range_raw"), r.get("unit_raw"),
                r.get("analytics"), r.get("source_page_no"),
                r.get("validation_status"), r.get("flag_reason"),
            ),
        )

    for m in medications:
        conn.execute(
            """
            INSERT INTO medications (encounter_id, medicine_raw, medicine_generic, dose, frequency)
            VALUES (?, ?, ?, ?, ?)
            """,
            (encounter_id, m.get("medicine_raw"), m.get("medicine_generic"), m.get("dose"), m.get("frequency")),
        )

    return True


def log_error(
    conn: sqlite3.Connection,
    source_file: str,
    error_reason: str,
    raw_content: str | None = None,
    error_type: str = "unhandled_classifier",
) -> None:
    conn.execute(
        "INSERT INTO error_log (error_type, source_file, error_reason, raw_content) VALUES (?, ?, ?, ?)",
        (error_type, source_file, error_reason, raw_content),
    )


def log_duplicates(conn: sqlite3.Connection, duplicate_log: list[dict[str, Any]]) -> int:
    """Writes Ingestion's duplicate_log into error_log so the UI (FR-5.3)
    has one queryable place for both errors and skipped duplicates,
    instead of duplicates only existing in a local JSON file the UI
    can't see. Idempotent on re-run: if the same content_hash + source
    file pairing was already logged, we skip re-inserting it, mirroring
    the same idempotency principle used for encounters.
    """
    logged = 0
    for dup in duplicate_log:
        already_logged = conn.execute(
            """
            SELECT 1 FROM error_log
            WHERE error_type = 'duplicate' AND source_file = ? AND error_reason LIKE ?
            """,
            (dup.get("source_file"), f"%{dup.get('content_hash', '')[:16]}%"),
        ).fetchone()
        if already_logged:
            continue

        log_error(
            conn,
            source_file=dup.get("source_file"),
            error_reason=(
                f"Duplicate of {dup.get('duplicate_of')} "
                f"(classifier={dup.get('classifier')}, content_hash={dup.get('content_hash')})"
            ),
            error_type="duplicate",
        )
        logged += 1
    return logged


def load_all(
    validated: dict[str, list],
    db_path: str | Path = DEFAULT_DB_PATH,
    duplicate_log: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Takes the output of validate_all() and loads it into SQLite.

    Groups lab_results and medications by encounter_id so each encounter
    is loaded as one atomic unit (see load_encounter_unit). Returns
    summary counts for the caller / UI to display.

    duplicate_log: optional, the second return value of Ingestion's
    run_ingestion(). If provided, each duplicate is recorded in error_log
    (error_type='duplicate') so the Operational UI (FR-5.3) can surface
    "N duplicates were found and skipped" instead of that information
    only existing in a transient local JSON file.
    """
    conn = get_connection(db_path)
    init_schema(conn)

    lab_by_encounter: dict[str, list] = {}
    for r in validated["lab_results"]:
        lab_by_encounter.setdefault(r["encounter_id"], []).append(r)

    meds_by_encounter: dict[str, list] = {}
    for m in validated["medications"]:
        meds_by_encounter.setdefault(m["encounter_id"], []).append(m)

    inserted, skipped_duplicates = 0, 0

    for encounter in validated["encounters"]:
        encounter_id = encounter["encounter_id"]
        was_inserted = load_encounter_unit(
            conn,
            encounter,
            lab_by_encounter.get(encounter_id, []),
            meds_by_encounter.get(encounter_id, []),
        )
        if was_inserted:
            inserted += 1
        else:
            skipped_duplicates += 1

    for unhandled in validated.get("unhandled", []):
        log_error(
            conn,
            source_file=unhandled.get("source_file"),
            error_reason=f"Unhandled classifier: {unhandled.get('unhandled_classifier')}",
            error_type="unhandled_classifier",
        )

    duplicates_logged = 0
    if duplicate_log:
        duplicates_logged = log_duplicates(conn, duplicate_log)

    conn.commit()
    conn.close()

    return {
        "encounters_inserted": inserted,
        "encounters_skipped_duplicate": skipped_duplicates,
        "lab_results_loaded": sum(len(v) for k, v in lab_by_encounter.items()),
        "medications_loaded": sum(len(v) for k, v in meds_by_encounter.items()),
        "duplicates_logged_this_run": duplicates_logged,
    }


def reset_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    if path.exists():
        path.unlink()
        print(f"Deleted {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Veritas Claims DB Loader")
    parser.add_argument("--reset", action="store_true", help="Delete the existing DB file before running")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path to SQLite DB file")
    args = parser.parse_args()

    if args.reset:
        reset_db(args.db_path)

    conn = get_connection(args.db_path)
    init_schema(conn)
    conn.close()
    print(f"Schema initialised at {args.db_path}")