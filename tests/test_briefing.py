import pandas as pd

from src.briefing import build_entity_context


def test_build_entity_context_aggregates_competitor_events_by_tier():
    entity_df = pd.DataFrame(
        [
            {
                "entity_id": "E01",
                "entity_name": "Test Co",
                "sector": "mining",
                "is_global_major": False,
                "total_expected_value_zar": 100.0,
                "total_wallet_gap_zar": 200.0,
                "total_unknown_capture_tam_zar": 50.0,
                "top_pillar": "Transactional Banking",
                "win_probability": 0.5,
                "relationship_strength_score": 0.3,
                "any_sequencing_flag": False,
            }
        ]
    )
    competitor_events = pd.DataFrame(
        [
            {"entity_id": "E01", "signal_tier": "primary", "value_zar": 1000.0},
            {"entity_id": "E01", "signal_tier": "primary", "value_zar": 500.0},
            {"entity_id": "E01", "signal_tier": "secondary", "value_zar": 200.0},
        ]
    )
    fin = pd.DataFrame([{"entity_id": "E01", "total_revenue": 5000.0, "foreign_revenue_pct": 40.0}]).set_index("entity_id")
    wallet_df = pd.DataFrame([{"entity_id": "E01", "tam_assumption_breach": False}])

    ctx = build_entity_context(entity_df, competitor_events, fin, wallet_df)
    assert ctx["E01"]["competitor_credit_primary_zar"] == 1500.0
    assert ctx["E01"]["competitor_credit_secondary_zar"] == 200.0
    assert ctx["E01"]["total_revenue_zar_m"] == 5000.0
    assert ctx["E01"]["foreign_revenue_pct"] == 40.0


def test_build_entity_context_handles_no_competitor_events():
    entity_df = pd.DataFrame(
        [
            {
                "entity_id": "E02",
                "entity_name": "Test Co 2",
                "sector": "consumer",
                "is_global_major": False,
                "total_expected_value_zar": 10.0,
                "total_wallet_gap_zar": 20.0,
                "total_unknown_capture_tam_zar": 5.0,
                "top_pillar": "Transactional Banking",
                "win_probability": 0.5,
                "relationship_strength_score": 0.3,
                "any_sequencing_flag": False,
            }
        ]
    )
    competitor_events = pd.DataFrame(columns=["entity_id", "signal_tier", "value_zar"])
    fin = pd.DataFrame(columns=["entity_id", "total_revenue", "foreign_revenue_pct"]).set_index("entity_id")
    wallet_df = pd.DataFrame([{"entity_id": "E02", "tam_assumption_breach": False}])

    ctx = build_entity_context(entity_df, competitor_events, fin, wallet_df)
    assert ctx["E02"]["competitor_credit_primary_zar"] == 0.0
    assert ctx["E02"]["competitor_credit_secondary_zar"] == 0.0
    assert ctx["E02"]["total_revenue_zar_m"] is None


def test_build_entity_context_flags_tam_assumption_breach_per_entity():
    entity_df = pd.DataFrame(
        [
            {
                "entity_id": "E11",
                "entity_name": "Breach Co",
                "sector": "consumer",
                "is_global_major": False,
                "total_expected_value_zar": 10.0,
                "total_wallet_gap_zar": 20.0,
                "total_unknown_capture_tam_zar": 5.0,
                "top_pillar": "Transactional Banking",
                "win_probability": 0.5,
                "relationship_strength_score": 0.3,
                "any_sequencing_flag": False,
            }
        ]
    )
    competitor_events = pd.DataFrame(columns=["entity_id", "signal_tier", "value_zar"])
    fin = pd.DataFrame(columns=["entity_id", "total_revenue", "foreign_revenue_pct"]).set_index("entity_id")
    # multiple rows, only one breached -- .any() must catch it
    wallet_df = pd.DataFrame(
        [
            {"entity_id": "E11", "tam_assumption_breach": False},
            {"entity_id": "E11", "tam_assumption_breach": True},
        ]
    )

    ctx = build_entity_context(entity_df, competitor_events, fin, wallet_df)
    assert ctx["E11"]["tam_assumption_breach"] is True
