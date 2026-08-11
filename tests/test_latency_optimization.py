import pandas as pd
import pytest

from src.latency_optimization import (
    MODEL_DEFAULT,
    MODEL_SMALL,
    _cost_per_call,
    _fmt_change_pct,
    compute_before_after,
    sample_simple_rows,
)


def test_fmt_change_pct_improvement_and_regression():
    assert _fmt_change_pct(0.11) == "-11%"
    assert _fmt_change_pct(0.0) == "-0%"
    assert _fmt_change_pct(-0.03) == "+3%"  # a real regression must show as an increase, not a double negative


def test_cost_per_call_uses_correct_price_per_model():
    # gemini-2.5-flash: $0.30/1M in, $2.50/1M out
    cost = _cost_per_call(MODEL_DEFAULT, input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(0.30 + 2.50)
    # gemini-3.1-flash-lite: $0.25/1M in, $1.50/1M out
    cost_small = _cost_per_call(MODEL_SMALL, input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_small == pytest.approx(0.25 + 1.50)
    assert cost_small < cost


def test_sample_simple_rows_only_returns_high_confidence_rows():
    df = pd.DataFrame({
        "regex_confidence": [0.85, 0.85, 0.40, 0.40, 0.85],
        "beneficiary_name": ["a", "b", "c", "d", "e"],
    })
    sample = sample_simple_rows(df, n=10)  # more than available -- should cap, not error
    assert len(sample) == 3
    assert (sample["regex_confidence"] == 0.85).all()


def test_compute_before_after_agreement_and_totals():
    full_df = pd.DataFrame({"regex_confidence": [0.85] * 6 + [0.40] * 4})  # 10 rows: 6 simple, 4 hard
    before = {
        "n_calls": 100, "latency_ms_median": 1000.0, "latency_ms_p95": 2000.0,
        "input_tokens_mean": 400.0, "output_tokens_mean": 70.0,
    }
    sample_result_df = pd.DataFrame({
        "small_facility_type": ["bilateral", "bilateral", "syndicate"],
        "original_big_facility_type": ["bilateral", "syndicate", "syndicate"],  # 2/3 agree
        "small_latency_ms": [500.0, 600.0, 550.0],
        "small_input_tokens": [400.0, 410.0, 405.0],
        "small_output_tokens": [65.0, 70.0, 68.0],
        "small_cached": [False, False, False],
    })

    stats = compute_before_after(full_df, sample_result_df, before)

    assert stats["n_total"] == 10
    assert stats["n_simple"] == 6
    assert stats["n_hard"] == 4
    assert stats["agreement_rate"] == pytest.approx(2 / 3)
    # routed cost must be strictly less than all-MODEL_DEFAULT cost, since MODEL_SMALL is cheaper per call
    assert stats["after_total_cost_usd"] < stats["before_total_cost_usd"]
    assert stats["cost_saved_pct"] > 0


def test_compute_before_after_falls_back_when_sample_is_all_cached():
    # every fresh-call metric must still resolve (no ZeroDivisionError / empty-slice error)
    # when the whole sample happened to be cache hits (e.g. a rerun).
    full_df = pd.DataFrame({"regex_confidence": [0.85, 0.40]})
    before = {
        "n_calls": 10, "latency_ms_median": 900.0, "latency_ms_p95": 1200.0,
        "input_tokens_mean": 400.0, "output_tokens_mean": 70.0,
    }
    sample_result_df = pd.DataFrame({
        "small_facility_type": ["bilateral"],
        "original_big_facility_type": ["bilateral"],
        "small_latency_ms": [0.0],
        "small_input_tokens": [400.0],
        "small_output_tokens": [70.0],
        "small_cached": [True],
    })
    stats = compute_before_after(full_df, sample_result_df, before)
    assert stats["sample_fresh_calls"] == 1  # fell back to using the cached row rather than dividing by zero
