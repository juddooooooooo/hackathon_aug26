import numpy as np
import pandas as pd
import pytest

from src.uncertainty import (
    _blended_share,
    _linregress_on_series,
    credible_interval,
    get_leaf,
    get_wallet_leaf_paths,
    leaf_label,
    perturb_assumptions,
)

SAMPLE_ASSUMPTIONS = {
    "fx_to_zar": {
        "USD": {"value": 16.0, "source": "test"},  # no low/high -- must be excluded
    },
    "transactional_banking": {
        "deposit_nii_margin_bps": {"value": 200, "low": 150, "high": 300, "rationale": "x"},
        "fee_per_payment_zar": {
            "EFT": {"value": 15, "low": 8, "high": 25, "rationale": "x"},
            "SWIFT": {"value": 250, "low": 150, "high": 350, "rationale": "x"},
        },
    },
    "global_markets": {
        "fx_margin_bps": {"value": 20, "low": 10, "high": 30, "rationale": "x"},
    },
    "investment_banking": {
        "arrangement_fee_bps": {"value": 100, "low": 50, "high": 150, "rationale": "x"},
    },
    "revealed_presence": {
        # a separate section, not read by build_wallet_model -- must be excluded
        "sow_floor_pct": {"value": 5, "low": 2, "high": 10, "rationale": "x"},
    },
}


def test_get_wallet_leaf_paths_finds_every_leaf():
    paths = get_wallet_leaf_paths(SAMPLE_ASSUMPTIONS)
    labels = {leaf_label(p) for p, _ in paths}
    assert labels == {
        "transactional_banking.deposit_nii_margin_bps",
        "transactional_banking.fee_per_payment_zar.EFT",
        "transactional_banking.fee_per_payment_zar.SWIFT",
        "global_markets.fx_margin_bps",
        "investment_banking.arrangement_fee_bps",
    }


def test_get_wallet_leaf_paths_excludes_fx_to_zar():
    paths = get_wallet_leaf_paths(SAMPLE_ASSUMPTIONS)
    labels = {leaf_label(p) for p, _ in paths}
    assert not any(label.startswith("fx_to_zar") for label in labels)


def test_get_wallet_leaf_paths_excludes_revealed_presence():
    # revealed_presence feeds the presence estimator, not build_wallet_model
    # -- perturbing it in the wallet Monte Carlo would be pointless (no
    # effect) and would corrupt the presence-estimator's own calibration if
    # the same dict were reused without care.
    paths = get_wallet_leaf_paths(SAMPLE_ASSUMPTIONS)
    labels = {leaf_label(p) for p, _ in paths}
    assert not any(label.startswith("revealed_presence") for label in labels)


def test_get_leaf_resolves_nested_path():
    leaf = get_leaf(SAMPLE_ASSUMPTIONS, ("transactional_banking", "fee_per_payment_zar", "SWIFT"))
    assert leaf["value"] == 250


def test_perturb_assumptions_stays_within_bounds():
    rng = np.random.default_rng(0)
    perturbed = perturb_assumptions(SAMPLE_ASSUMPTIONS, rng)
    for path, _ in get_wallet_leaf_paths(SAMPLE_ASSUMPTIONS):
        orig_leaf = get_leaf(SAMPLE_ASSUMPTIONS, path)
        new_leaf = get_leaf(perturbed, path)
        assert orig_leaf["low"] <= new_leaf["value"] <= orig_leaf["high"]


def test_perturb_assumptions_does_not_mutate_original():
    rng = np.random.default_rng(0)
    original_value = SAMPLE_ASSUMPTIONS["transactional_banking"]["deposit_nii_margin_bps"]["value"]
    perturb_assumptions(SAMPLE_ASSUMPTIONS, rng)
    assert SAMPLE_ASSUMPTIONS["transactional_banking"]["deposit_nii_margin_bps"]["value"] == original_value


def test_perturb_assumptions_leaves_fx_rates_untouched():
    rng = np.random.default_rng(0)
    perturbed = perturb_assumptions(SAMPLE_ASSUMPTIONS, rng)
    assert perturbed["fx_to_zar"]["USD"]["value"] == 16.0


def test_credible_interval_basic():
    df = pd.DataFrame({"portfolio_share": [0.01, 0.02, 0.03, 0.04, 0.05] * 20})
    ci = credible_interval(df, "portfolio_share")
    assert ci["n"] == 100
    assert ci["p5"] <= ci["p50"] <= ci["p95"]


def test_credible_interval_empty_series_does_not_raise():
    df = pd.DataFrame({"portfolio_share": [None, None]})
    ci = credible_interval(df, "portfolio_share")
    assert ci["n"] == 0
    assert ci["p5"] is None


def test_blended_share_none_when_tam_zero():
    df = pd.DataFrame({"tam_zar": [0.0], "captured_zar": [10.0]})
    share, tam, captured = _blended_share(df)
    assert share is None


def test_linregress_flat_series_low_r_squared():
    g = pd.DataFrame({"quarter": pd.date_range("2023-01-01", periods=12, freq="QS"), "volume_zar": [100.0] * 12})
    result = _linregress_on_series(g, "volume_zar")
    assert result["slope_zar_per_quarter"] == pytest.approx(0.0, abs=1e-9)
    assert result["significant_p05"] is False


def test_linregress_clear_upward_trend_is_significant():
    g = pd.DataFrame(
        {"quarter": pd.date_range("2023-01-01", periods=12, freq="QS"), "volume_zar": [100.0 + 50 * i for i in range(12)]}
    )
    result = _linregress_on_series(g, "volume_zar")
    assert result["slope_zar_per_quarter"] == pytest.approx(50.0, rel=0.01)
    assert result["significant_p05"] is True
    assert result["r_squared"] > 0.99


def test_linregress_too_few_points_returns_null_not_error():
    g = pd.DataFrame({"quarter": pd.date_range("2023-01-01", periods=2, freq="QS"), "volume_zar": [100.0, 200.0]})
    result = _linregress_on_series(g, "volume_zar")
    assert result["slope_zar_per_quarter"] is None
    assert result["significant_p05"] is False
