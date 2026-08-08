"""Unit tests for the deterministic regex baseline in src.forensics.

These cover the four real memo templates found in the data (see
reports/profiling_report.md) plus the near-miss beneficiary names that make
the lender-name heuristic non-trivial (see METHODOLOGY.md "Regex baseline
design"). No API key or network access required -- this only tests the
regex baseline, not the LLM extraction.
"""
import pandas as pd

from src.forensics import (
    _null_safe_eq,
    regex_confidence,
    regex_external_reference,
    regex_facility_type,
    regex_lender_name,
)

# --------------------------------------------------------------------------
# facility_type
# --------------------------------------------------------------------------
def test_facility_type_syndicate():
    assert regex_facility_type("Syndicate participation settlement - ref 897009") == "syndicate"


def test_facility_type_bridging():
    assert regex_facility_type("Bridging facility settlement - ref 302397") == "bridging"


def test_facility_type_other_for_generic_drawdown():
    # No syndicate/bridging/bilateral keyword -> falls through to 'other'.
    # This is exactly the ambiguous case the LLM is expected to add
    # judgement on top of (see forensics_report.md facility_type confusion).
    assert regex_facility_type("Loan drawdown proceeds - ext. ref 615121") == "other"


def test_facility_type_other_for_settlement_re_facility():
    assert regex_facility_type("Settlement re: facility drawdown - ref 823377") == "other"


def test_facility_type_bilateral_keyword_recognised():
    # Never actually appears in the observed data, but the pattern must
    # still fire if the vocabulary ever changes upstream.
    assert regex_facility_type("Bilateral loan agreement settlement - ref 1") == "bilateral"


def test_facility_type_case_insensitive():
    assert regex_facility_type("SYNDICATE PARTICIPATION SETTLEMENT - REF 1") == "syndicate"


# --------------------------------------------------------------------------
# external_reference
# --------------------------------------------------------------------------
def test_external_reference_plain_ref():
    assert regex_external_reference("Syndicate participation settlement - ref 897009") == "897009"


def test_external_reference_ext_ref_prefix():
    assert regex_external_reference("Loan drawdown proceeds - ext. ref 615121") == "615121"


def test_external_reference_none_when_absent():
    assert regex_external_reference("No reference number in here at all") is None


# --------------------------------------------------------------------------
# lender_name — must reconstruct the known-5 without looking them up
# --------------------------------------------------------------------------
def test_lender_name_matches_known_banks():
    for name in [
        "Halcyon Trade Bank",
        "Meridian Bank Ltd",
        "Northgate Financial Bank",
        "Solstice Capital Bank",
        "Crestwood Merchant Bank",
    ]:
        assert regex_lender_name(name) == name


def test_lender_name_null_for_ordinary_supplier():
    assert regex_lender_name("Golden Valley Retail Supplies") is None
    assert regex_lender_name("Cape Wholesale Distributors") is None


def test_lender_name_null_for_trading_house_near_miss():
    # Shares a root word with a known bank ("Meridian") but is not a bank --
    # a real near-miss present in trade_finance.csv. The heuristic must not
    # be fooled by the shared root.
    assert regex_lender_name("Meridian International Trading House") is None
    assert regex_lender_name("Crestview Resources Trading") is None


def test_lender_name_matches_correspondent_banking_labels_too():
    # Known limitation, documented in METHODOLOGY.md: the "Bank" substring
    # heuristic also fires on generic correspondent-banking plumbing labels.
    # This is fine in practice because these labels never co-occur with a
    # non-null memo row in the dataset (verified in profiling) -- this test
    # just pins down the actual (imprecise) behaviour so a future change in
    # the data would be caught rather than silently ignored.
    assert regex_lender_name("Bank Correspondent Transfer") == "Bank Correspondent Transfer"
    assert regex_lender_name("FX Settlement - Correspondent Bank") == "FX Settlement - Correspondent Bank"


# --------------------------------------------------------------------------
# confidence (rule-based proxy, not a calibrated probability)
# --------------------------------------------------------------------------
def test_confidence_high_for_explicit_keyword():
    assert regex_confidence("Syndicate participation settlement - ref 1") == 0.85


def test_confidence_low_for_generic_other_bucket():
    assert regex_confidence("Loan drawdown proceeds - ext. ref 1") == 0.40


# --------------------------------------------------------------------------
# _null_safe_eq — regression test for the "None == None is False on a
# pandas Series" footgun (see METHODOLOGY.md Phase 2 §"disagreement-rate
# methodology"). Plain `a == b` on two all-None object Series returns all
# False, which silently inflated the disagreement rate to 66.7% on rows
# where both regex and the LLM correctly found no lender.
# --------------------------------------------------------------------------
def test_null_safe_eq_treats_both_none_as_agreement():
    a = pd.Series([None, "X", None, "Y"])
    b = pd.Series([None, "X", None, "Z"])
    assert _null_safe_eq(a, b).tolist() == [True, True, True, False]


def test_null_safe_eq_one_sided_none_is_disagreement():
    a = pd.Series([None, "X"])
    b = pd.Series(["X", None])
    assert _null_safe_eq(a, b).tolist() == [False, False]


def test_plain_series_eq_is_the_footgun_this_guards_against():
    # Documents *why* _null_safe_eq exists: plain `==` on all-None Series
    # returns False, not True, unlike scalar Python `None == None`.
    a = pd.Series([None, None])
    b = pd.Series([None, None])
    assert (a == b).tolist() == [False, False]
    assert _null_safe_eq(a, b).tolist() == [True, True]
