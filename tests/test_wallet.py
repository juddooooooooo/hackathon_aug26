import pandas as pd
import pytest

from src.wallet import _v, add_share_and_breach_columns, blended_tam_and_captured, to_zar

ASSUMPTIONS = {
    "fx_to_zar": {
        "USD": {"value": 16.0, "source": "test"},
        "ZAR": {"value": 1.0, "source": "test"},
    }
}


def test_v_handles_bare_number():
    assert _v(42) == 42.0


def test_v_handles_dict_with_value_key():
    assert _v({"value": 42, "rationale": "because"}) == 42.0


def test_to_zar_converts_using_named_rate():
    assert to_zar(100.0, "USD", ASSUMPTIONS) == pytest.approx(1600.0)


def test_to_zar_identity_for_zar():
    assert to_zar(100.0, "ZAR", ASSUMPTIONS) == pytest.approx(100.0)


def test_to_zar_returns_none_for_null_value():
    assert to_zar(None, "USD", ASSUMPTIONS) is None
    assert to_zar(float("nan"), "USD", ASSUMPTIONS) is None


def test_to_zar_returns_none_for_unknown_currency():
    # Regression: must not raise -- an entity with a currency we have no
    # rate for should null-propagate, not crash the whole pipeline.
    assert to_zar(100.0, "XYZ", ASSUMPTIONS) is None


def test_to_zar_returns_none_for_null_currency():
    assert to_zar(100.0, None, ASSUMPTIONS) is None


def _df(rows):
    return pd.DataFrame(rows)


def test_share_of_wallet_null_when_tam_missing():
    df = _df([{"tam_zar": None, "captured_zar": 100.0}])
    out = add_share_and_breach_columns(df)
    assert pd.isna(out.iloc[0]["share_of_wallet"])
    assert out.iloc[0]["tam_assumption_breach"] == False


def test_share_of_wallet_null_when_captured_missing():
    # e.g. rate_hedging / debt_arrangement -- captured is structurally
    # unobservable, must NOT be treated as a 0% share.
    df = _df([{"tam_zar": 100.0, "captured_zar": None}])
    out = add_share_and_breach_columns(df)
    assert pd.isna(out.iloc[0]["share_of_wallet"])


def test_share_of_wallet_normal_case():
    df = _df([{"tam_zar": 200.0, "captured_zar": 50.0}])
    out = add_share_and_breach_columns(df)
    assert out.iloc[0]["share_of_wallet"] == pytest.approx(0.25)
    assert out.iloc[0]["tam_assumption_breach"] == False


def test_captured_exceeding_tam_is_flagged_not_clipped():
    # Regression case: Pepkor's deposit_nii (see reports/wallet_report.md
    # "TAM assumption breaches"). Must NOT be silently clipped to 100% --
    # that would hide a real signal that the TAM assumption is too
    # conservative for that entity.
    df = _df([{"tam_zar": 80.0, "captured_zar": 95.0}])
    out = add_share_and_breach_columns(df)
    assert out.iloc[0]["share_of_wallet"] == pytest.approx(95.0 / 80.0)
    assert out.iloc[0]["share_of_wallet"] > 1.0
    assert out.iloc[0]["tam_assumption_breach"] == True


def test_zero_tam_does_not_raise_division_error():
    df = _df([{"tam_zar": 0.0, "captured_zar": 10.0}])
    out = add_share_and_breach_columns(df)
    assert pd.isna(out.iloc[0]["share_of_wallet"])


def test_blended_tam_and_captured_excludes_unmatched_rows():
    # Regression case: independently dropna()-ing tam_zar and captured_zar
    # and summing each column separately double-dips -- fx_hedging's
    # captured leg is observable even when its TAM is null (missing
    # foreign_revenue_pct), so an independent-sum blend counts that
    # captured revenue in the numerator with no matching TAM in the
    # denominator, inflating the blended share (was 4.6%, corrected to
    # 5.3% -- see METHODOLOGY.md Phase 4 section).
    df = _df(
        [
            {"tam_zar": 100.0, "captured_zar": 10.0},  # both observable -- counted
            {"tam_zar": None, "captured_zar": 50.0},  # captured-only leak -- must be excluded
            {"tam_zar": 200.0, "captured_zar": None},  # tam-only (e.g. debt_arrangement) -- must be excluded
        ]
    )
    tam, captured = blended_tam_and_captured(df)
    assert tam == pytest.approx(100.0)
    assert captured == pytest.approx(10.0)
