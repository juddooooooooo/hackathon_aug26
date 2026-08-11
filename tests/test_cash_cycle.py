import duckdb
import pandas as pd
import pytest

from src.cash_cycle import (
    ENGAGEMENT_LEAD_MONTHS,
    SEASONALITY_FLAT_THRESHOLD,
    compute_day_of_month_uniformity,
    compute_seasonality,
)


def _make_con(rows: list[dict]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    con.register("transactional_banking", df)
    return con


def test_compute_seasonality_flags_a_genuinely_seasonal_entity():
    # E01: all volume concentrated in December -> high CV, peak_month=12,
    # is_seasonal True. E02: volume spread evenly across all 12 months ->
    # near-zero CV, is_seasonal False. Both need >=2 leg-type rows per
    # month/entity to look like the real schema.
    rows = []
    for month in range(1, 13):
        vol = 1_000_000 if month == 12 else 10_000  # E01: December spike
        rows.append({"entity_id": "E01", "entity_name": "Seasonal Co", "sector": "consumer",
                      "date": f"2024-{month:02d}-15", "leg_type": "collections", "amount_zar": vol})
        rows.append({"entity_id": "E02", "entity_name": "Flat Co", "sector": "mining",
                      "date": f"2024-{month:02d}-15", "leg_type": "collections", "amount_zar": 100_000})
    con = _make_con(rows)

    df = compute_seasonality(con)

    e01 = df.set_index("entity_id").loc["E01"]
    e02 = df.set_index("entity_id").loc["E02"]
    assert e01["peak_month"] == 12
    assert e01["is_seasonal"] is True or bool(e01["is_seasonal"]) is True
    assert e01["seasonality_cv"] > SEASONALITY_FLAT_THRESHOLD
    assert bool(e02["is_seasonal"]) is False
    assert e02["seasonality_cv"] < e01["seasonality_cv"]


def test_suggested_engagement_month_wraps_around_year_boundary():
    # Peak in January -> engagement month must wrap backwards into the
    # previous year's Nov/Dec, not go negative or to month 0.
    rows = []
    for month in range(1, 13):
        vol = 1_000_000 if month == 1 else 10_000
        rows.append({"entity_id": "E03", "entity_name": "Jan Peak Co", "sector": "retail",
                      "date": f"2024-{month:02d}-10", "leg_type": "supplier_payments", "amount_zar": vol})
    con = _make_con(rows)

    df = compute_seasonality(con)
    row = df.iloc[0]
    assert row["peak_month"] == 1
    expected = (1 - ENGAGEMENT_LEAD_MONTHS - 1) % 12 + 1
    assert row["suggested_engagement_month"] == expected
    assert 1 <= row["suggested_engagement_month"] <= 12


def test_compute_day_of_month_uniformity_returns_both_leg_types():
    rows = [
        {"entity_id": "E01", "entity_name": "X", "sector": "mining", "date": "2024-01-05",
         "leg_type": "collections", "amount_zar": 100.0},
        {"entity_id": "E01", "entity_name": "X", "sector": "mining", "date": "2024-01-20",
         "leg_type": "supplier_payments", "amount_zar": 200.0},
    ]
    con = _make_con(rows)
    result = compute_day_of_month_uniformity(con)
    assert set(result.keys()) == {"collections", "supplier_payments"}
    assert all(isinstance(v, float) for v in result.values())
