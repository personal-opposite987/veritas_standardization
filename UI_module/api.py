

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = Path(__file__).resolve().parent.parent / "DB_LOADER_module" / "veritas.db"
# NOTE: adjust DB_PATH above if your veritas.db lives elsewhere, e.g.
# DB_PATH = Path(__file__).resolve().parent.parent / "DB_LOADER_module" / "veritas.db"

app = FastAPI(title="Veritas Claims Operational API")

# CORS: the React/Vite dev server runs on a different port (5173) than
# this API (8000), so the browser blocks requests unless we explicitly
# allow it. Wide open for local development only -- would be locked down
# to specific origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Database not found at {DB_PATH}. Run test_pipeline.py first to populate it.",
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name, not just index
    return conn


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# FR-5.1: basic dashboard statistics
# --------------------------------------------------------------------------- #

@app.get("/api/stats/summary")
def stats_summary():
    conn = get_db()
    try:
        encounters_total = conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0]
        lab_results_total = conn.execute("SELECT COUNT(*) FROM lab_results").fetchone()[0]
        medications_total = conn.execute("SELECT COUNT(*) FROM medications").fetchone()[0]
        duplicates_total = conn.execute(
            "SELECT COUNT(*) FROM error_log WHERE error_type = 'duplicate'"
        ).fetchone()[0]
        other_errors_total = conn.execute(
            "SELECT COUNT(*) FROM error_log WHERE error_type != 'duplicate'"
        ).fetchone()[0]

        return {
            "encounters_total": encounters_total,
            "lab_results_total": lab_results_total,
            "medications_total": medications_total,
            "duplicates_total": duplicates_total,
            "other_errors_total": other_errors_total,
        }
    finally:
        conn.close()


@app.get("/api/stats/validation-breakdown")
def validation_breakdown():
    """FR-5.1 / FR-5.3: how many lab results fall into each
    validation_status bucket (Normal, Out of Range, Unparseable, etc.)
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT validation_status, COUNT(*) as count
            FROM lab_results
            GROUP BY validation_status
            ORDER BY count DESC
            """
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.get("/api/stats/by-clinic")
def stats_by_clinic():
    """FR-5.4: breakdown grouped by source_file, used as a clinic-id
    proxy since the sample data has no folder-based clinic structure
    (see ingestion's _infer_clinic_id / dedup.py docstring for why).
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT source_file,
                   COUNT(*) as encounter_count,
                   SUM(CASE WHEN classifier = 'discharge_summary' THEN 1 ELSE 0 END) as discharge_summaries,
                   SUM(CASE WHEN classifier = 'lab_report' THEN 1 ELSE 0 END) as lab_reports
            FROM encounters
            GROUP BY source_file
            ORDER BY source_file
            """
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# FR-5.2: searchable / filterable encounter list
# --------------------------------------------------------------------------- #

@app.get("/api/encounters")
def list_encounters(
    search: str | None = Query(None, description="Free-text search over diagnosis and source_file"),
    classifier: str | None = Query(None, description="Filter by 'discharge_summary' or 'lab_report'"),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
):
    conn = get_db()
    try:
        clauses = []
        params: list[Any] = []

        if search:
            clauses.append("(diagnosis LIKE ? OR source_file LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if classifier:
            clauses.append("classifier = ?")
            params.append(classifier)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        rows = conn.execute(
            f"""
            SELECT encounter_id, source_file, classifier, diagnosis,
                   admission_date_raw, discharge_date_raw, date_validation_status
            FROM encounters
            {where_clause}
            ORDER BY source_file
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM encounters {where_clause}", params
        ).fetchone()[0]

        return {"total": total, "results": rows_to_dicts(rows)}
    finally:
        conn.close()


@app.get("/api/encounters/{encounter_id}")
def get_encounter_detail(encounter_id: str):
    """Drill-down view: one encounter plus its lab_results and medications."""
    conn = get_db()
    try:
        encounter = conn.execute(
            "SELECT * FROM encounters WHERE encounter_id = ?", (encounter_id,)
        ).fetchone()

        if encounter is None:
            raise HTTPException(status_code=404, detail=f"Encounter {encounter_id} not found")

        lab_results = conn.execute(
            "SELECT * FROM lab_results WHERE encounter_id = ?", (encounter_id,)
        ).fetchall()

        medications = conn.execute(
            "SELECT * FROM medications WHERE encounter_id = ?", (encounter_id,)
        ).fetchall()

        return {
            "encounter": dict(encounter),
            "lab_results": rows_to_dicts(lab_results),
            "medications": rows_to_dicts(medications),
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# FR-5.3: error / duplicate visibility
# --------------------------------------------------------------------------- #

@app.get("/api/errors")
def list_errors(
    error_type: str | None = Query(None, description="Filter by 'duplicate' or 'unhandled_classifier'"),
    limit: int = Query(100, le=1000),
):
    conn = get_db()
    try:
        if error_type:
            rows = conn.execute(
                """
                SELECT error_id, error_type, source_file, error_reason, logged_at
                FROM error_log
                WHERE error_type = ?
                ORDER BY logged_at DESC
                LIMIT ?
                """,
                (error_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT error_id, error_type, source_file, error_reason, logged_at
                FROM error_log
                ORDER BY logged_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.get("/api/health")
def health_check():
    """Quick check the API is up and can see the DB file at all."""
    return {"status": "ok", "db_path": str(DB_PATH), "db_exists": DB_PATH.exists()}