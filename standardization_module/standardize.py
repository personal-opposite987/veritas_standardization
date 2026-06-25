

from __future__ import annotations

import re
from typing import Any


# lab_report -> lab_results rows

def standardise_lab_report(record: dict[str, Any]) -> dict[str, Any]:
    """record is one entry from Ingestion's unique_records list, where
    record['classifier'] == 'lab_report'.

    Returns a dict with two keys:
      - 'encounter': a lightweight encounters row for this lab_report block
      - 'lab_results': list of dicts, one per test in report_details

    WHY lab_report GETS ITS OWN encounters ROW (not linked to a sibling
    discharge_summary in the same file): nothing in the source data ties
    a lab_report block to a discharge_summary block in the same file as
    the same clinical encounter -- there's no shared patient/visit ID
    (basic_info.uhid is itself redacted in the samples). Assuming
    same-file co-location implies same-encounter would be an unverified,
    risky assumption to bake into a healthcare data pipeline. Each
    lab_report block is therefore treated as its own independent
    encounter, scoped only to the data it actually contains.
    """
    data = record["data"]
    encounter_id = record["content_hash"]
    source_file = record["source_file"]
    basic_info = data.get("basic_info", {})

    encounter = {
        "encounter_id": encounter_id,
        "source_file": source_file,
        "classifier": "lab_report",
        "age_raw": basic_info.get("age"),
        "age_years": parse_age(basic_info.get("age")),
        "gender_raw": basic_info.get("gender"),
        "gender_canonical": parse_gender(basic_info.get("gender")),
        "admission_date_raw": None,   # lab_report has no admission/discharge concept
        "discharge_date_raw": None,
        "diagnosis": None,
        "brief_history": None,
        "doctor_name": None,
        "hospital_name": basic_info.get("lab_or_hospital_name"),
        "ward": None,
        "recommendations": None,
    }

    rows = []
    for test in data.get("report_details", []):
        rows.append({
            "encounter_id": encounter_id,
            "source_file": source_file,
            "test_name_raw": test.get("test_name"),
            "result_raw": test.get("result"),
            "range_raw": test.get("range"),
            "unit_raw": test.get("unit"),
            "analytics": test.get("test_analytics"),
            "source_page_no": test.get("page_no"),
        })

    return {"encounter": encounter, "lab_results": rows}


# discharge_summary -> one encounters row + N medications rows

# FR-2.5: parse free-text age strings into a numeric year value.
# Handles forms actually plausible for this domain: "45", "45 Years",
# "45Y", "3 Months", "10 Days", "45 yrs 3 months". Returns None (rather
# than raising) for anything unparseable, e.g. the redacted placeholder
# "[AGE REDACTED]" itself, or genuinely malformed input -- a failed parse
# is a data quality signal for Validation (FR-3), not a pipeline crash.
_AGE_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>year|yr|y|month|mo|m|day|d)s?\b",
    re.IGNORECASE,
)

_AGE_UNIT_TO_YEARS = {
    "year": 1, "yr": 1, "y": 1,
    "month": 1 / 12, "mo": 1 / 12, "m": 1 / 12,
    "day": 1 / 365, "d": 1 / 365,
}


def parse_age(age_raw: str | None) -> float | None:
    """Returns age normalised to years (float), or None if unparseable."""
    if not age_raw or not isinstance(age_raw, str):
        return None

    matches = _AGE_PATTERN.findall(age_raw)
    if not matches:
        return None

    total_years = 0.0
    for value_str, unit_str in matches:
        unit_key = unit_str.lower()
        factor = _AGE_UNIT_TO_YEARS.get(unit_key)
        if factor is None:
            return None
        total_years += float(value_str) * factor

    return round(total_years, 3)


# FR-2.5: canonicalise free-text gender values into a fixed vocabulary.
_GENDER_MAP = {
    "m": "male", "male": "male",
    "f": "female", "female": "female",
}


def parse_gender(gender_raw: str | None) -> str | None:
    if not gender_raw or not isinstance(gender_raw, str):
        return None
    key = gender_raw.strip().lower()
    return _GENDER_MAP.get(key)  # None if unrecognised -- surfaced by Validation, not guessed


# FR-2.6: small static medicine-name -> generic-name dictionary, seeded
# from names actually present in the sample discharge summaries. This is
# explicitly NOT meant to be exhaustive -- production would integrate
# something like RxNorm or a licensed drug ontology. Documented as a
# Scope Exclusion in docs/assumptions.md.
_MEDICINE_GENERIC_MAP = {
    "tab. miso": "misoprostol",
    "inj. synto": "oxytocin",
    "inj. pan": "pantoprazole",
    "cap. pan d": "pantoprazole + domperidone",
    "cap. pan 40": "pantoprazole",
    "inj. pcm": "paracetamol",
    "tab dolo 650": "paracetamol",
    "inj. dynapar": "diclofenac",
    "tab. diclomol": "diclofenac + paracetamol",
    "inj. emeset": "ondansetron",
    "inj. fortwin": "pentazocine",
    "inj. phenargan": "promethazine",
    "inj. supacef": "cefuroxime",
    "tab ceftum 500 mg": "cefuroxime",
    "cap. vizylac": "probiotic (lactobacillus)",
    "powder naturolax": "ispaghula husk (laxative)",
    "syp duphalac": "lactulose",
    "tab medicip": "ciprofloxacin",
    "inj. monocef": "ceftriaxone",
    "inj pantop": "pantoprazole",
    "inj neuro bion forte": "vitamin b complex",
}


def map_medicine_to_generic(medicine_raw: str | None) -> str | None:
    if not medicine_raw or not isinstance(medicine_raw, str):
        return None
    key = medicine_raw.strip().lower()
    # Strip trailing dosage tokens like "500 MG" before lookup, then retry
    # exact match first since the dict already includes some dosage forms.
    if key in _MEDICINE_GENERIC_MAP:
        return _MEDICINE_GENERIC_MAP[key]
    stripped = re.sub(r"\s*\d+\s*mg\b.*$", "", key).strip()
    return _MEDICINE_GENERIC_MAP.get(stripped)  # None if not in our small dictionary


def standardise_discharge_summary(record: dict[str, Any]) -> dict[str, Any]:
    """record is one entry from Ingestion's unique_records list, where
    record['classifier'] == 'discharge_summary'.

    Returns a dict with two keys:
      - 'encounter': the single encounters row
      - 'medications': list of medications rows (FK -> encounter_id)
    """
    data = record["data"]
    encounter_id = record["content_hash"]
    source_file = record["source_file"]

    encounter = {
        "encounter_id": encounter_id,
        "source_file": source_file,
        "classifier": "discharge_summary",
        "age_raw": data.get("age"),
        "age_years": parse_age(data.get("age")),
        "gender_raw": data.get("gender"),
        "gender_canonical": parse_gender(data.get("gender")),
        "admission_date_raw": data.get("admissionDate"),
        "discharge_date_raw": data.get("dischargeDate"),
        "diagnosis": data.get("diagnosis"),
        "brief_history": data.get("briefHistory"),
        "doctor_name": data.get("doctorName"),
        "hospital_name": data.get("hospitalName"),
        "ward": data.get("ward"),
        "recommendations": data.get("recommendations"),
    }

    medications_raw = []
    for med in data.get("dischargeMedications", []):
        medicine_raw = med.get("medicine")
        dose = med.get("dose") or None       # "" -> None
        frequency = med.get("frequency") or None  # "" -> None

        # "N/A" appears verbatim in the sample data as a real medicine
        # entry -- treat it as "no medicine recorded", not a drug name.
        if medicine_raw and medicine_raw.strip().upper() == "N/A":
            continue

        medications_raw.append({
            "encounter_id": encounter_id,
            "medicine_raw": medicine_raw,
            "medicine_generic": map_medicine_to_generic(medicine_raw),
            "dose": dose,
            "frequency": frequency,
        })

    medications = _dedupe_medications(medications_raw)

    return {"encounter": encounter, "medications": medications}


def _dedupe_medications(medications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Source data sometimes lists the same medicine twice within one
    encounter's dischargeMedications array -- once with blank dose/frequency
    (often an initial order-entry stub) and once with the real values
    filled in (verified directly in Sample_JSON_file1.json: "Tab. miso"
    appears with ("", "") and again with ("1 TAB", "12 HOURLY")).

    Rule: group by medicine name (case-insensitive). Within a group, if
    ANY row has a non-empty dose or frequency, keep only the row(s) that
    have a non-empty dose/frequency, dropping the blank stub(s). If ALL
    rows in a group are blank, keep one (information may genuinely be
    unavailable -- not our call to discard it).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []

    for med in medications:
        key = (med["medicine_raw"] or "").strip().lower()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(med)

    deduped = []
    for key in order:
        group = groups[key]
        non_blank = [m for m in group if m["dose"] or m["frequency"]]
        if non_blank:
            deduped.extend(non_blank)
        else:
            deduped.append(group[0])

    return deduped


# Dispatcher

def standardise_record(record: dict[str, Any]) -> dict[str, Any]:
    """Routes a single unique_record to the correct extractor based on
    classifier. Returns a uniform shape so callers don't need to know
    which classifier produced it:
        {"encounters": [...], "lab_results": [...], "medications": [...]}
    """
    classifier = record.get("classifier")

    if classifier == "lab_report":
        result = standardise_lab_report(record)
        return {
            "encounters": [result["encounter"]],
            "lab_results": result["lab_results"],
            "medications": [],
        }

    if classifier == "discharge_summary":
        result = standardise_discharge_summary(record)
        return {
            "encounters": [result["encounter"]],
            "lab_results": [],
            "medications": result["medications"],
        }

    # Unknown classifier: don't silently drop it -- surface it so
    # Validation/error-log can flag it instead of data vanishing quietly.
    return {
        "encounters": [],
        "lab_results": [],
        "medications": [],
        "unhandled_classifier": classifier,
        "source_file": record.get("source_file"),
    }


def standardise_all(unique_records: list[dict[str, Any]]) -> dict[str, list]:
    """Runs standardise_record over every unique_record and flattens the
    results into three lists, ready for the DB Loader.
    """
    encounters, lab_results, medications, unhandled = [], [], [], []

    for record in unique_records:
        result = standardise_record(record)
        encounters.extend(result["encounters"])
        lab_results.extend(result["lab_results"])
        medications.extend(result["medications"])
        if "unhandled_classifier" in result:
            unhandled.append(result)

    return {
        "encounters": encounters,
        "lab_results": lab_results,
        "medications": medications,
        "unhandled": unhandled,
    }