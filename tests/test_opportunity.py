import pandas as pd
import pytest

from src.opportunity import (
    build_pillar_ranking,
    compute_wallet_gaps,
    compute_win_probability,
)

ASSUMPTIONS = {
    "opportunity_ranking": {
        "net_margin_realization": {"value": 0.65, "low": 0.55, "high": 0.75, "rationale": "x"},
        "win_probability_weights": {
            "breadth": {"value": 0.30, "rationale": "x"},
            "relationship_strength": {"value": 0.30, "rationale": "x"},
            "momentum": {"value": 0.20, "rationale": "x"},
            "country_adjacency": {"value": 0.20, "rationale": "x"},
        },
        "sequencing_risk_threshold": {"value": 0.10, "rationale": "x"},
        "sequencing_penalty_multiplier": {"value": 0.5, "rationale": "x"},
    }
}


def _wallet_df(rows):
    return pd.DataFrame(rows)


def test_wallet_gap_computed_when_both_observable():
    df = _wallet_df([{"tam_zar": 100.0, "captured_zar": 30.0}])
    out = compute_wallet_gaps(df)
    assert out.iloc[0]["wallet_gap_zar"] == pytest.approx(70.0)
    assert pd.isna(out.iloc[0]["unknown_capture_tam_zar"])


def test_wallet_gap_floored_at_zero_not_negative():
    # e.g. Pepkor's deposit_nii TAM-assumption breach: captured > tam.
    df = _wallet_df([{"tam_zar": 80.0, "captured_zar": 95.0}])
    out = compute_wallet_gaps(df)
    assert out.iloc[0]["wallet_gap_zar"] == 0.0


def test_unknown_capture_tam_reported_when_captured_null():
    # e.g. debt_arrangement -- structurally unobservable captured side.
    df = _wallet_df([{"tam_zar": 500.0, "captured_zar": None}])
    out = compute_wallet_gaps(df)
    assert pd.isna(out.iloc[0]["wallet_gap_zar"])
    assert out.iloc[0]["unknown_capture_tam_zar"] == pytest.approx(500.0)


def test_wallet_gap_null_when_tam_null():
    df = _wallet_df([{"tam_zar": None, "captured_zar": 10.0}])
    out = compute_wallet_gaps(df)
    assert pd.isna(out.iloc[0]["wallet_gap_zar"])
    assert pd.isna(out.iloc[0]["unknown_capture_tam_zar"])


def test_win_probability_weighted_combination():
    signals = pd.DataFrame(
        [{"entity_id": "E01", "breadth_score": 1.0, "relationship_strength_score": 0.5, "momentum_score": 0.5, "country_adjacency_score": 0.5}]
    )
    out = compute_win_probability(signals, ASSUMPTIONS)
    expected = 1.0 * 0.30 + 0.5 * 0.30 + 0.5 * 0.20 + 0.5 * 0.20
    assert out.iloc[0]["win_probability"] == pytest.approx(expected)


def test_win_probability_clipped_to_bounds():
    signals = pd.DataFrame(
        [
            {"entity_id": "E01", "breadth_score": 0.0, "relationship_strength_score": 0.0, "momentum_score": 0.0, "country_adjacency_score": 0.0},
            {"entity_id": "E02", "breadth_score": 1.0, "relationship_strength_score": 1.0, "momentum_score": 1.0, "country_adjacency_score": 1.0},
        ]
    )
    out = compute_win_probability(signals, ASSUMPTIONS)
    assert out.iloc[0]["win_probability"] == pytest.approx(0.05)
    assert out.iloc[1]["win_probability"] == pytest.approx(0.95)


def _pillar_gap_df(entity_id, pillar, tam, captured, relationship_strength):
    gap_df = compute_wallet_gaps(pd.DataFrame([{"entity_id": entity_id, "pillar": pillar, "tam_zar": tam, "captured_zar": captured}]))
    signals = pd.DataFrame(
        [
            {
                "entity_id": entity_id,
                "entity_name": "Test Co",
                "sector": "consumer",
                "is_global_major": False,
                "relationship_strength_score": relationship_strength,
                "breadth_score": 1.0,
                "country_adjacency_score": 0.5,
                "momentum_score": 0.5,
            }
        ]
    )
    signals = compute_win_probability(signals, ASSUMPTIONS)
    return gap_df, signals


def test_sequencing_flag_fires_below_threshold_for_cross_sell_pillar():
    gap_df, signals = _pillar_gap_df("E01", "Global Markets", 100.0, 10.0, relationship_strength=0.05)
    out = build_pillar_ranking(gap_df, signals, ASSUMPTIONS)
    assert bool(out.iloc[0]["sequencing_flag"]) is True
    # win_probability must be penalised (halved), not merely flagged for show
    assert out.iloc[0]["win_probability_adjusted"] == pytest.approx(out.iloc[0]["win_probability"] * 0.5)


def test_sequencing_flag_does_not_fire_above_threshold():
    gap_df, signals = _pillar_gap_df("E01", "Global Markets", 100.0, 10.0, relationship_strength=0.50)
    out = build_pillar_ranking(gap_df, signals, ASSUMPTIONS)
    assert bool(out.iloc[0]["sequencing_flag"]) is False
    assert out.iloc[0]["win_probability_adjusted"] == pytest.approx(out.iloc[0]["win_probability"])


def test_sequencing_flag_never_fires_for_transactional_banking():
    # TB is the foundational pillar itself -- there's no "prior pillar" to sequence from.
    gap_df, signals = _pillar_gap_df("E01", "Transactional Banking", 100.0, 10.0, relationship_strength=0.01)
    out = build_pillar_ranking(gap_df, signals, ASSUMPTIONS)
    assert bool(out.iloc[0]["sequencing_flag"]) is False


def test_expected_value_formula():
    gap_df, signals = _pillar_gap_df("E01", "Transactional Banking", 100.0, 10.0, relationship_strength=0.50)
    out = build_pillar_ranking(gap_df, signals, ASSUMPTIONS)
    row = out.iloc[0]
    assert row["expected_value_zar"] == pytest.approx(row["wallet_gap_zar"] * row["win_probability_adjusted"] * 0.65)
