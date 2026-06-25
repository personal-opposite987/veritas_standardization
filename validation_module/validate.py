
from __future__ import annotations

import re
from datetime import datetime
from typing import Any


# FR-3.1 / FR-3.3: lab result validation + categorisation

# Genuine clinical classifications we trust directly from the source.
# Deliberately NOT including methodology/instrument names or placeholders
# like 'low/normal/high' -- see module docstring for why.
ALLOWED_ANALYTICS = {
    "normal": "Normal",
    "low": "Low",
    "high": "High",
    "positive": "Positive",
    "negative": "Negative",
    "present": "Present",
    "absent": "Absent",
}

# Strips a leading/trailing unit or descriptive suffix from a result
# string, keeping the numeric portion. Handles thousand-separator commas
# (e.g. "4,290 cells/cu.mm") by stripping commas before matching.
_NUMERIC_RESULT_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")

# "low-high" span, e.g. "4000-10000", "31.5-34.5"
_RANGE_SPAN_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$")

# Comparison-operator bound, e.g. "<50", "< 50", ">1.15"
_RANGE_BOUND_PATTERN = re.compile(r"^\s*(?P<op><|>|<=|>=)\s*(-?\d+(?:\.\d+)?)\s*$")


def _extract_numeric(value_raw: str | None) -> float | None:
    """Pulls a leading numeric value out of a result string, tolerating
    embedded units and thousand-separator commas. Returns None if no
    number can be found at all (e.g. "POSITIVE", "OTE", "")."""
    if not value_raw or not isinstance(value_raw, str):
        return None
    cleaned = value_raw.replace(",", "").strip()
    match = _NUMERIC_RESULT_PATTERN.match(cleaned)
    if not match:
        return None
    return float(match.group(1))


def _parse_range(range_raw: str | None) -> tuple[float | None, float | None] | None:
    """Returns (low, high) where either bound may be None for an
    open-ended comparison range (e.g. "<50" -> (None, 50.0)).
    Returns None entirely if range_raw doesn't match any known pattern
    (e.g. "Less than 1:80", "= 1 COI - Equivocal")."""
    if not range_raw or not isinstance(range_raw, str):
        return None

    cleaned = range_raw.replace(",", "").strip()

    span_match = _RANGE_SPAN_PATTERN.match(cleaned)
    if span_match:
        low, high = float(span_match.group(1)), float(span_match.group(2))
        return (low, high) if low <= high else (high, low)

    bound_match = _RANGE_BOUND_PATTERN.match(cleaned)
    if bound_match:
        op, value = bound_match.group("op"), float(bound_match.group(2))
        if op in ("<", "<="):
            return (None, value)
        return (value, None)  # > or >=

    return None


def validate_lab_result(row: dict[str, Any]) -> dict[str, Any]:
    """Takes one lab_results row (from Standardisation) and returns it
    with two fields added: 'validation_status' and 'flag_reason'.

    validation_status is one of:
      Normal | Low | High | Positive | Negative | Present | Absent
          -> trusted directly from source test_analytics
      In Range | Out of Range
          -> derived from our own numeric/range parsing
      Unparseable
          -> neither source nor our parsing could determine a status
    """
    analytics_key = (row.get("analytics") or "").strip().lower()

    if analytics_key in ALLOWED_ANALYTICS:
        return {
            **row,
            "validation_status": ALLOWED_ANALYTICS[analytics_key],
            "flag_reason": None,
        }

    result_value = _extract_numeric(row.get("result_raw"))
    range_bounds = _parse_range(row.get("range_raw"))

    if result_value is None:
        return {
            **row,
            "validation_status": "Unparseable",
            "flag_reason": "FR-3.4: result_raw is not numeric and source analytics gave no usable classification",
        }

    if range_bounds is None:
        return {
            **row,
            "validation_status": "Unparseable",
            "flag_reason": "FR-3.4: result_raw is numeric but range_raw could not be parsed",
        }

    low, high = range_bounds
    in_range = (low is None or result_value >= low) and (high is None or result_value <= high)

    return {
        **row,
        "validation_status": "In Range" if in_range else "Out of Range",
        "flag_reason": None if in_range else f"FR-3.1: result {result_value} outside range ({low}, {high})",
    }


def validate_lab_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [validate_lab_result(r) for r in rows]


# FR-3.2: date validation for encounters

# Sample data uses DD-MM-YYYY ("09-10-2025") and "DD-Mon-YYYY" ("07-Oct-2025")
# in different files -- both formats observed directly in the provided
# samples (Sample_JSON_file1.json vs Sample_JSON_file2.json), so both are
# handled rather than assuming one fixed format across all clinics.
_DATE_FORMATS = ("%d-%m-%Y", "%d-%b-%Y")


def _parse_date(date_raw: str | None) -> datetime | None:
    if not date_raw or not isinstance(date_raw, str):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_raw.strip(), fmt)
        except ValueError:
            continue
    return None


def validate_encounter(encounter: dict[str, Any]) -> dict[str, Any]:
    """Adds 'date_validation_status' and 'date_flag_reason' to an
    encounter row. Checks: both dates parseable, and admission <= discharge.
    """
    admission_dt = _parse_date(encounter.get("admission_date_raw"))
    discharge_dt = _parse_date(encounter.get("discharge_date_raw"))

    if admission_dt is None or discharge_dt is None:
        unparseable_field = "admissionDate" if admission_dt is None else "dischargeDate"
        return {
            **encounter,
            "date_validation_status": "Unparseable",
            "date_flag_reason": f"FR-3.2: could not parse {unparseable_field}",
        }

    if admission_dt > discharge_dt:
        return {
            **encounter,
            "date_validation_status": "Invalid",
            "date_flag_reason": "FR-3.2: admissionDate is after dischargeDate",
        }

    return {
        **encounter,
        "date_validation_status": "Valid",
        "date_flag_reason": None,
    }


def validate_encounters(encounters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [validate_encounter(e) for e in encounters]


# Batch entry point

def validate_all(standardised: dict[str, list]) -> dict[str, list]:
    """Takes the output of standardise_all() and returns it with
    lab_results and encounters annotated with validation fields.
    medications and unhandled pass through untouched -- FR-3 doesn't
    define validation rules for medications in this assignment.
    """
    return {
        "encounters": validate_encounters(standardised["encounters"]),
        "lab_results": validate_lab_results(standardised["lab_results"]),
        "medications": standardised["medications"],
        "unhandled": standardised["unhandled"],
    }