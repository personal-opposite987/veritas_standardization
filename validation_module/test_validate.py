

from validate import (
    validate_lab_result,
    validate_encounter,
    _extract_numeric,
    _parse_range,
)


# Numeric / range parsing helpers

def test_extract_numeric_handles_units_and_commas():
    assert _extract_numeric("9700") == 9700.0
    assert _extract_numeric("13.7 g/dl") == 13.7
    assert _extract_numeric("4,290 cells/cu.mm") == 4290.0
    assert _extract_numeric("POSITIVE") is None
    assert _extract_numeric("") is None
    assert _extract_numeric(None) is None


def test_parse_range_handles_span_and_bounds():
    assert _parse_range("4000-10000") == (4000.0, 10000.0)
    assert _parse_range("31.5-34.5") == (31.5, 34.5)
    assert _parse_range("<50") == (None, 50.0)
    assert _parse_range(">1.15") == (1.15, None)
    assert _parse_range("Less than 1:80") is None
    assert _parse_range("") is None
    assert _parse_range(None) is None


# Lab result validation — against real extracted rows

def test_in_range_real_case():
    # Sample_JSON_file1.json lab_report-equivalent shape: Hemoglobin 9700 in 4000-10000
    row = {"test_name_raw": "aemoglobin", "result_raw": "9700",
           "range_raw": "4000-10000", "unit_raw": "cell/cu.mm", "analytics": "normal"}
    out = validate_lab_result(row)
    assert out["validation_status"] == "Normal"  # trusted from source analytics
    assert out["flag_reason"] is None


def test_out_of_range_with_comparison_bound():
    # Real case found in Sample_JSON_file2.json: ALT result=91 against range "<50"
    row = {"test_name_raw": "ALANINE AMINOTRANSFERASE", "result_raw": "91",
           "range_raw": "<50", "unit_raw": "U/L", "analytics": "Visible with P-5-P"}
    out = validate_lab_result(row)
    assert out["validation_status"] == "Out of Range"
    assert "91" in out["flag_reason"]


def test_comma_and_unit_stripped_result_still_unparseable_without_range():
    # Real case: result has comma+unit (parseable), but range_raw is empty
    row = {"test_name_raw": "CORRECTED TLC", "result_raw": "4,290 Cells/cu.mm",
           "range_raw": "", "unit_raw": "", "analytics": "low/normal/high"}
    out = validate_lab_result(row)
    # result IS numeric (4290.0) but range can't be parsed -> Unparseable, not a guess
    assert out["validation_status"] == "Unparseable"


def test_qualitative_result_is_unparseable_not_forced_numeric():
    row = {"test_name_raw": "WIDAL TEST", "result_raw": "POSITIVE",
           "range_raw": "Less than 1:80", "unit_raw": "", "analytics": ""}
    out = validate_lab_result(row)
    assert out["validation_status"] == "Unparseable"


def test_methodology_name_in_analytics_does_not_get_trusted():
    # 'Calculated' is a methodology name, not a clinical classification --
    # must fall through to numeric parsing, not be returned verbatim.
    row = {"test_name_raw": "DE RITIS RATIO", "result_raw": "1.6",
           "range_raw": "<1.15", "unit_raw": "", "analytics": "Calculated"}
    out = validate_lab_result(row)
    assert out["validation_status"] in ("Out of Range", "In Range")
    assert out["validation_status"] != "Calculated"


# Date validation — SYNTHETIC cases (no bad dates exist in real samples)

def test_date_valid_real_format_ddmmyyyy():
    encounter = {"admission_date_raw": "09-10-2025", "discharge_date_raw": "11-10-2025"}
    out = validate_encounter(encounter)
    assert out["date_validation_status"] == "Valid"


def test_date_valid_real_format_ddmonyyyy():
    # Sample_JSON_file2.json uses this alternate format: "07-Oct-2025"
    encounter = {"admission_date_raw": "05-10-2025", "discharge_date_raw": "07-Oct-2025"}
    out = validate_encounter(encounter)
    assert out["date_validation_status"] == "Valid"


def test_date_invalid_admission_after_discharge_SYNTHETIC():
    """SYNTHETIC: no real sample has admission > discharge. Fabricated to
    prove the Invalid path is reachable and correctly triggered."""
    encounter = {"admission_date_raw": "15-10-2025", "discharge_date_raw": "10-10-2025"}
    out = validate_encounter(encounter)
    assert out["date_validation_status"] == "Invalid"
    assert "after" in out["date_flag_reason"]


def test_date_unparseable_garbage_string_SYNTHETIC():
    """SYNTHETIC: no real sample has a malformed date string. Fabricated
    to prove malformed input doesn't crash and is correctly flagged."""
    encounter = {"admission_date_raw": "not-a-date", "discharge_date_raw": "11-10-2025"}
    out = validate_encounter(encounter)
    assert out["date_validation_status"] == "Unparseable"
    assert "admissionDate" in out["date_flag_reason"]


def test_date_unparseable_missing_discharge_SYNTHETIC():
    """SYNTHETIC: covers the case where dischargeDate is null (plausible
    for an in-progress/not-yet-discharged encounter, not present in our
    5 samples but realistic for a live system)."""
    encounter = {"admission_date_raw": "09-10-2025", "discharge_date_raw": None}
    out = validate_encounter(encounter)
    assert out["date_validation_status"] == "Unparseable"
    assert "dischargeDate" in out["date_flag_reason"]


if __name__ == "__main__":
    import inspect

    test_functions = [
        obj for name, obj in list(globals().items())
        if name.startswith("test_") and inspect.isfunction(obj)
    ]

    passed, failed = 0, 0
    for fn in test_functions:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")