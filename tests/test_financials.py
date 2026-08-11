import pandas as pd

from src.financials import load_geo_notes, score_against_ground_truth


def _df(rows):
    return pd.DataFrame(rows)


def test_expected_null_matches_extracted_null():
    # e.g. cost_of_sales for an insurer -- both "expected" and "extracted" are null -> match.
    df = _df([{"entity_id": "E08", "cost_of_sales": None}])
    gt = _df([{"entity_id": "E08", "field": "cost_of_sales", "ground_truth_value": None}])
    scored = score_against_ground_truth(df, gt)
    assert scored.iloc[0]["match"] == True
    assert scored.iloc[0]["reason"] == "correct_null"


def test_expected_null_but_value_extracted_is_a_mismatch():
    # The pipeline invented/found a figure for a field that shouldn't have one.
    df = _df([{"entity_id": "E08", "cost_of_sales": 123.0}])
    gt = _df([{"entity_id": "E08", "field": "cost_of_sales", "ground_truth_value": None}])
    scored = score_against_ground_truth(df, gt)
    assert scored.iloc[0]["match"] == False
    assert scored.iloc[0]["reason"] == "expected_null_but_extracted_a_value"


def test_expected_value_but_extraction_null_is_a_miss_not_silently_a_match():
    df = _df([{"entity_id": "E01", "total_revenue": None}])
    gt = _df([{"entity_id": "E01", "field": "total_revenue", "ground_truth_value": 51262}])
    scored = score_against_ground_truth(df, gt)
    assert scored.iloc[0]["match"] == False
    assert scored.iloc[0]["reason"] == "extracted_null"


def test_numeric_within_tolerance_matches():
    df = _df([{"entity_id": "E01", "total_revenue": 51260.0}])
    gt = _df([{"entity_id": "E01", "field": "total_revenue", "ground_truth_value": 51262}])
    scored = score_against_ground_truth(df, gt, tolerance_pct=2.0)
    assert scored.iloc[0]["match"] == True


def test_numeric_outside_tolerance_does_not_match():
    df = _df([{"entity_id": "E01", "total_revenue": 40000.0}])
    gt = _df([{"entity_id": "E01", "field": "total_revenue", "ground_truth_value": 51262}])
    scored = score_against_ground_truth(df, gt, tolerance_pct=2.0)
    assert scored.iloc[0]["match"] == False


def test_string_field_exact_match_case_insensitive():
    df = _df([{"entity_id": "E19", "fiscal_year_end": "2025-06-30"}])
    gt = _df([{"entity_id": "E19", "field": "fiscal_year_end", "ground_truth_value": "2025-06-30"}])
    scored = score_against_ground_truth(df, gt)
    assert scored.iloc[0]["match"] == True


def test_string_field_mismatch_is_reported_not_swallowed():
    # Regression case: Aspen Pharmacare period-selection miss (see tests/financials_ground_truth.csv).
    df = _df([{"entity_id": "E19", "fiscal_year_end": "2024-06-30"}])
    gt = _df([{"entity_id": "E19", "field": "fiscal_year_end", "ground_truth_value": "2025-06-30"}])
    scored = score_against_ground_truth(df, gt)
    assert scored.iloc[0]["match"] == False


def test_missing_entity_or_field_is_reported_not_raised():
    df = _df([{"entity_id": "E01", "total_revenue": 51262.0}])
    gt = _df([{"entity_id": "E99", "field": "total_revenue", "ground_truth_value": 1.0}])
    scored = score_against_ground_truth(df, gt)
    assert scored.iloc[0]["match"] == False
    assert scored.iloc[0]["reason"] == "field_or_entity_missing"


def test_load_geo_notes_splits_sections_by_entity_heading(tmp_path, monkeypatch):
    import src.financials as financials_mod

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "geographic_foreign_revenue_notes.md").write_text(
        "# header\n\n## E01 BHP Group\nBHP notes here.\n\n## E02 Glencore\nGlencore notes here.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(financials_mod, "EXTERNAL_RAW_DIR", raw_dir)
    notes = load_geo_notes()
    assert set(notes.keys()) == {"E01", "E02"}
    assert "BHP notes here" in notes["E01"]
    assert "Glencore notes here" in notes["E02"]
    assert "BHP notes" not in notes["E02"]
