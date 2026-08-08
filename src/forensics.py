"""
Phase 2 — Forensic Extraction of the Competitor-Credit Signal  [Gen AI #1]
===========================================================================
Isolates every non-null `memo` row across all three source files and turns
the free text into structured fields:

    lender_name       -- who the money is really flowing to/from, if the
                          counterparty reads as a financial institution
    facility_type     -- syndicate | bridging | bilateral | other
    external_reference-- the deal/facility reference NUMBER embedded in the
                          memo text itself (distinct from Syn Bank's own
                          structured `reference` column -- see below)
    confidence_score   -- the model's own confidence, 0-1

Scope note vs. the original brief: the brief describes this signal living in
cross_border_payments.csv and trade_finance.csv (~542 rows). Phase 1's
profiling (reports/profiling_report.md) found transactional_banking.csv
carries its own `memo` column with the *same* fingerprint at larger rand
value (3,657 rows, R597m vs. the original R403m). This module processes all
three files' memo rows on the same principle the brief already applies to
trade_finance.csv: beneficiary_name determines confidence tier, not which
file the row came from.

Two-tier confidence, by construction (not by model judgement):
    primary   -- beneficiary_name is one of the 5 recurring counterparties
                 that ONLY ever appear on templated loan/facility memo rows
                 (see src.common.KNOWN_COMPETITOR_BENEFICIARIES). High
                 confidence this is genuine competitor-credit settlement.
    secondary -- same template language, but beneficiary_name is an
                 ordinary trade counterparty. Lower confidence: could be
                 proceeds on-forwarding, could be a labelling artefact. Not
                 double-counted with `primary` in the headline number --
                 see METHODOLOGY.md.

Why the LLM sees memo + beneficiary_name jointly, not memo alone: every memo
in this dataset is one of exactly 4 short templates ("Syndicate
participation settlement - ref NNNNNN", etc.) -- none of them name a lender
inline. lender_name is only recoverable by judging whether beneficiary_name
denotes a financial institution, which is a genuine (if narrow) NLP
judgement call, not a lookup. See generate_structured()'s docstring in
src/llm.py for how this shapes the cache key.

Cross-checked against a deterministic regex baseline; the LLM-vs-regex
disagreement rate is the measurable Gen AI accuracy claim required by the
brief's 20% criterion.

Output: data/processed/competitor_credit_events.parquet

Run standalone:
    python -m src.forensics                 # full run (all memo rows)
    python -m src.forensics --sample 40      # quick smoke test on a sample
    python -m src.forensics --no-llm         # regex baseline only (no API key needed)
"""
from __future__ import annotations

import argparse
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Optional

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

from src.common import (
    DUCKDB_PATH,
    KNOWN_COMPETITOR_BENEFICIARIES,
    PROCESSED_DIR,
    REPORTS_DIR,
    configure_logging,
    ensure_dirs,
)
from src.llm import MissingAPIKeyError, MODEL_DEFAULT, LLMResult, generate_structured, get_client

logger = logging.getLogger(__name__)

OUTPUT_PARQUET = PROCESSED_DIR / "competitor_credit_events.parquet"
OUTPUT_REPORT_MD = REPORTS_DIR / "forensics_report.md"
NAMESPACE = "forensics_memo_extraction"


# --------------------------------------------------------------------------
# 1. Load every non-null-memo row across all three files, unified schema
# --------------------------------------------------------------------------
def load_memo_rows(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    tb = con.sql(
        """
        SELECT
            'transactional_banking' AS source_file,
            transaction_id AS row_id,
            entity_id, entity_name, sector, date,
            amount_zar AS value_zar,
            beneficiary_name, reference AS structured_reference, memo,
            leg_type AS record_subtype, direction
        FROM transactional_banking WHERE memo IS NOT NULL
        """
    ).fetchdf()

    xbp = con.sql(
        """
        SELECT
            'cross_border_payments' AS source_file,
            transaction_id AS row_id,
            entity_id, entity_name, sector, date,
            value_zar,
            beneficiary_name, reference AS structured_reference, memo,
            corridor_type AS record_subtype, direction
        FROM cross_border_payments WHERE memo IS NOT NULL
        """
    ).fetchdf()

    tf = con.sql(
        """
        SELECT
            'trade_finance' AS source_file,
            instrument_id AS row_id,
            entity_id, entity_name, sector, date,
            value_zar,
            beneficiary_name, reference AS structured_reference, memo,
            instrument_type AS record_subtype, direction
        FROM trade_finance WHERE memo IS NOT NULL
        """
    ).fetchdf()

    df = pd.concat([tb, xbp, tf], ignore_index=True)
    df["signal_tier"] = df["beneficiary_name"].apply(
        lambda b: "primary" if b in KNOWN_COMPETITOR_BENEFICIARIES else "secondary"
    )
    logger.info(
        "Loaded %d memo rows total (%d primary / %d secondary) across %d source files.",
        len(df),
        (df.signal_tier == "primary").sum(),
        (df.signal_tier == "secondary").sum(),
        df.source_file.nunique(),
    )
    return df


# --------------------------------------------------------------------------
# 2. Deterministic regex baseline
# --------------------------------------------------------------------------
_FACILITY_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsyndicat", re.I), "syndicate"),
    (re.compile(r"\bbridg", re.I), "bridging"),
    (re.compile(r"\bbilateral", re.I), "bilateral"),
]
_EXTERNAL_REF_PATTERN = re.compile(r"ref\.?\s*(\d+)", re.I)
_BANK_NAME_PATTERN = re.compile(r"\bbank\b", re.I)
_CONFIDENCE_KEYWORDS = re.compile(r"syndicat|bridg|bilateral", re.I)


def regex_facility_type(memo: str) -> str:
    for pattern, label in _FACILITY_TYPE_PATTERNS:
        if pattern.search(memo):
            return label
    return "other"


def regex_external_reference(memo: str) -> Optional[str]:
    m = _EXTERNAL_REF_PATTERN.search(memo)
    return m.group(1) if m else None


def regex_lender_name(beneficiary_name: str) -> Optional[str]:
    # Deliberately a generic "looks like a bank name" heuristic (word-boundary
    # match on "Bank"), NOT a lookup against KNOWN_COMPETITOR_BENEFICIARIES --
    # that would make the baseline circular (it already knows the answer).
    # Verified clean on this dataset: of all beneficiary_name values containing
    # "bank" (any file, any row), only the 5 known names appear on memo-bearing
    # rows; two generic correspondent-banking labels ("Bank Correspondent
    # Transfer", "FX Settlement - Correspondent Bank") exist elsewhere in
    # cross_border_payments but never co-occur with a non-null memo. See
    # METHODOLOGY.md.
    return beneficiary_name if _BANK_NAME_PATTERN.search(beneficiary_name) else None


def regex_confidence(memo: str) -> float:
    # Rule-based proxy, not a calibrated probability: an explicit keyword
    # (syndicate/bridging/bilateral) gets high confidence; falling through to
    # the uninformative 'other' bucket gets low confidence. Exists purely so
    # the LLM's confidence_score has a deterministic baseline to sit next to.
    return 0.85 if _CONFIDENCE_KEYWORDS.search(memo) else 0.40


def apply_regex_baseline(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["regex_facility_type"] = df["memo"].apply(regex_facility_type)
    df["regex_external_reference"] = df["memo"].apply(regex_external_reference)
    df["regex_lender_name"] = df["beneficiary_name"].apply(regex_lender_name)
    df["regex_confidence"] = df["memo"].apply(regex_confidence)
    return df


# --------------------------------------------------------------------------
# 3. LLM extraction
# --------------------------------------------------------------------------
class FacilityType(str, Enum):
    syndicate = "syndicate"
    bridging = "bridging"
    bilateral = "bilateral"
    other = "other"


class MemoExtraction(BaseModel):
    lender_name: Optional[str] = Field(
        default=None,
        description=(
            "The counterparty this memo implies is the actual lender/facility bank, "
            "ONLY if beneficiary_name plausibly denotes a bank or lending institution "
            "(e.g. ends in 'Bank', 'Merchant Bank'). Null if beneficiary_name reads as "
            "an ordinary trading company, supplier, or government body -- do not invent "
            "a lender that isn't textually supported by beneficiary_name."
        ),
    )
    facility_type: FacilityType = Field(
        description=(
            "syndicate = memo explicitly signals multiple lenders participating together; "
            "bridging = memo explicitly signals a short-term/interim facility; "
            "bilateral = single-lender drawdown/repayment language with no syndication or "
            "bridging cue; other = cannot be determined from the text."
        )
    )
    external_reference: Optional[str] = Field(
        default=None,
        description=(
            "The reference NUMBER written inside the memo text itself (e.g. 'ref 897009' -> "
            "'897009'). This is the counterparty/competitor's own deal reference, NOT the "
            "structured_reference field shown to you for context -- they are deliberately "
            "different numbers. Null if no number appears in the memo."
        ),
    )
    confidence_score: float = Field(ge=0.0, le=1.0, description="Your confidence in facility_type and lender_name jointly, 0-1.")
    reasoning: str = Field(description="One short sentence: why you made this call.")


SYSTEM_INSTRUCTION = """You are a forensic transactions analyst at Syn Bank, a corporate and \
investment bank. You are shown one settlement record where Syn Bank processed a payment on \
behalf of a corporate client, and the free-text memo field is unusually populated (memo is null \
on 99.5%+ of records, so a filled memo is itself notable).

Your job: determine whether this record is evidence that a DIFFERENT bank or lender originated a \
credit facility (loan, bridging facility, or syndicated facility) that Syn Bank is merely settling \
the cash movements for -- i.e. Syn Bank holds the payment flow but a competitor holds the credit \
relationship. Extract structured fields from the memo text, using beneficiary_name and \
structured_reference only as supporting context (never invent facts the memo text doesn't support).

Field rules:
- lender_name: fill in ONLY if beneficiary_name itself plausibly denotes a bank/lending \
institution. If beneficiary_name reads as an ordinary trading company, supplier, government \
body, or anything else that is not a financial institution, return null even if the memo text \
uses loan/facility language.
- facility_type: syndicate | bridging | bilateral | other, per the field description.
- external_reference: the number following "ref" inside the memo text ONLY. Do not return \
structured_reference's value here even if no number is found in the memo -- return null instead.
- confidence_score: calibrate this down when the memo text is generic (e.g. plain "facility \
drawdown" with no syndicate/bridging cue) and up when explicit keywords are present.
- reasoning: one short sentence a bank coverage analyst could read in a hurry."""


def _build_prompt(row: pd.Series) -> str:
    context_lines = [
        f"record_type: {row['source_file']} ({row['record_subtype']}, {row['direction']})",
        f"beneficiary_name: {row['beneficiary_name']}",
        f"structured_reference: {row['structured_reference']}",
        f"value_zar: {row['value_zar']:.2f}",
        f"memo: {row['memo']}",
    ]
    return "\n".join(context_lines)


def _extract_one(row: pd.Series) -> tuple[Any, LLMResult]:
    prompt = _build_prompt(row)
    # extra_cache_key folds in beneficiary_name (and everything else in the
    # prompt) automatically since prompt itself is part of the hash -- kept
    # here as a second positional argument for readability/defence-in-depth.
    result = generate_structured(
        namespace=NAMESPACE,
        system_instruction=SYSTEM_INSTRUCTION,
        prompt=prompt,
        response_schema=MemoExtraction,
        extra_cache_key=str(row["beneficiary_name"]),
    )
    return row["row_id"], result


def run_llm_extraction(df: pd.DataFrame, max_workers: int = 12) -> pd.DataFrame:
    df = df.copy()
    for col in ["llm_lender_name", "llm_facility_type", "llm_external_reference", "llm_reasoning"]:
        df[col] = None
    df["llm_confidence_score"] = float("nan")
    df["llm_cached"] = False
    df["llm_latency_ms"] = float("nan")
    df["llm_model"] = MODEL_DEFAULT

    results_by_row_id: dict[str, LLMResult] = {}
    n = len(df)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_extract_one, row): row["row_id"] for _, row in df.iterrows()}
        for fut in as_completed(futures):
            row_id = futures[fut]
            try:
                _, result = fut.result()
                results_by_row_id[row_id] = result
            except Exception:
                logger.exception("LLM extraction failed for row_id=%s", row_id)
            done += 1
            if done % 250 == 0 or done == n:
                logger.info("LLM extraction: %d / %d rows done", done, n)

    for idx, row in df.iterrows():
        result = results_by_row_id.get(row["row_id"])
        if result is None or result.parsed is None:
            continue
        parsed: MemoExtraction = result.parsed
        df.at[idx, "llm_lender_name"] = parsed.lender_name
        df.at[idx, "llm_facility_type"] = parsed.facility_type.value
        df.at[idx, "llm_external_reference"] = parsed.external_reference
        df.at[idx, "llm_confidence_score"] = parsed.confidence_score
        df.at[idx, "llm_reasoning"] = parsed.reasoning
        df.at[idx, "llm_cached"] = result.cached
        df.at[idx, "llm_latency_ms"] = result.latency_ms
        df.at[idx, "llm_model"] = result.model

    return df


# --------------------------------------------------------------------------
# 4. Agreement / disagreement-rate computation
# --------------------------------------------------------------------------
def _norm_str(x: Any) -> Optional[str]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip()
    return s if s else None


def _null_safe_eq(a: pd.Series, b: pd.Series) -> pd.Series:
    # Plain `a == b` on object-dtype Series treats None/NaN like SQL NULL:
    # None == None evaluates to False, not True. That's wrong for our
    # purposes -- "both extractors correctly found no lender" IS agreement.
    return (a == b) | (a.isna() & b.isna())


def compute_agreement(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    has_llm = df["llm_facility_type"].notna()

    regex_lender = df["regex_lender_name"].apply(_norm_str)
    llm_lender = df["llm_lender_name"].apply(_norm_str)
    regex_ref = df["regex_external_reference"].apply(_norm_str)
    llm_ref = df["llm_external_reference"].apply(_norm_str)

    agree_facility_type = df["regex_facility_type"] == df["llm_facility_type"]
    agree_lender_name = _null_safe_eq(regex_lender, llm_lender)
    agree_external_reference = _null_safe_eq(regex_ref, llm_ref)
    agree_all = agree_facility_type & agree_lender_name & agree_external_reference & has_llm

    # Nullable "boolean" dtype (not numpy bool) so rows with no LLM result
    # can hold pd.NA instead of silently reading as False.
    df["agree_facility_type"] = agree_facility_type.astype("boolean")
    df["agree_lender_name"] = agree_lender_name.astype("boolean")
    df["agree_external_reference"] = agree_external_reference.astype("boolean")
    df["agree_all"] = agree_all.astype("boolean")
    df.loc[~has_llm, ["agree_facility_type", "agree_lender_name", "agree_external_reference", "agree_all"]] = pd.NA
    return df


_TRAILING_REF_PATTERN = re.compile(r"\s*-?\s*(ext\.\s*)?ref\s*\d+\s*$")


def confidence_calibration_table(df: pd.DataFrame) -> pd.DataFrame:
    """For rows where the regex baseline landed in the ambiguous 'other'
    bucket (no syndicate/bridging/bilateral keyword), show how the LLM's
    confidence_score tracks the amount of corroborating evidence available:
    explicit "loan" language in the memo, and/or a beneficiary_name that
    reads as a bank. This is the calibration story behind the headline
    disagreement rate -- see METHODOLOGY.md.
    """
    sub = df[(df["regex_facility_type"] == "other") & df["llm_facility_type"].notna()].copy()
    sub["memo_template"] = sub["memo"].str.replace(_TRAILING_REF_PATTERN, "", regex=True)
    sub["beneficiary_reads_as_bank"] = sub["regex_lender_name"].notna()
    out = (
        sub.groupby(["memo_template", "beneficiary_reads_as_bank", "llm_facility_type"])
        .agg(n=("row_id", "count"), mean_confidence=("llm_confidence_score", "mean"))
        .reset_index()
        .sort_values(["memo_template", "beneficiary_reads_as_bank", "llm_facility_type"])
    )
    return out


def disagreement_summary(df: pd.DataFrame) -> dict[str, Any]:
    scored = df[df["llm_facility_type"].notna()]
    n = len(scored)
    if n == 0:
        return {"n_scored": 0}

    def rate(col: str) -> float:
        return float(1 - scored[col].mean())

    by_field = {
        "facility_type_disagreement_rate": rate("agree_facility_type"),
        "lender_name_disagreement_rate": rate("agree_lender_name"),
        "external_reference_disagreement_rate": rate("agree_external_reference"),
        "overall_disagreement_rate": rate("agree_all"),
    }
    by_tier = (
        scored.groupby("signal_tier")["agree_all"]
        .apply(lambda s: float(1 - s.mean()))
        .to_dict()
    )
    by_facility_type_confusion = (
        scored.groupby(["regex_facility_type", "llm_facility_type"]).size().rename("n").reset_index().to_dict(orient="records")
    )
    return {
        "n_scored": n,
        **by_field,
        "overall_disagreement_rate_by_tier": by_tier,
        "facility_type_confusion": by_facility_type_confusion,
        "llm_confidence_mean": float(scored["llm_confidence_score"].mean()),
        "llm_confidence_median": float(scored["llm_confidence_score"].median()),
        "regex_confidence_mean": float(scored["regex_confidence"].mean()),
        "n_cache_hits": int(scored["llm_cached"].sum()),
        "mean_latency_ms_uncached": float(scored.loc[~scored["llm_cached"], "llm_latency_ms"].mean()) if (~scored["llm_cached"]).any() else None,
    }


# --------------------------------------------------------------------------
# 5. Reporting
# --------------------------------------------------------------------------
def render_markdown(df: pd.DataFrame, agreement: dict[str, Any], llm_ran: bool, calibration: pd.DataFrame | None = None) -> str:
    lines = ["# Phase 2 — Forensic Extraction Report", ""]
    lines.append(
        f"Total memo-bearing rows processed: **{len(df):,}** "
        f"(primary tier: {(df.signal_tier == 'primary').sum():,}, "
        f"secondary tier: {(df.signal_tier == 'secondary').sum():,})"
    )
    lines.append("")
    by_source = df.groupby("source_file").agg(n=("row_id", "count"), value_zar=("value_zar", "sum")).reset_index()
    by_source["value_zar"] = by_source["value_zar"].map(lambda x: f"R{x:,.0f}")
    lines.append(by_source.to_markdown(index=False))

    lines.append("\n**By confidence tier**\n")
    by_tier = df.groupby("signal_tier").agg(n=("row_id", "count"), value_zar=("value_zar", "sum")).reset_index()
    by_tier["value_zar"] = by_tier["value_zar"].map(lambda x: f"R{x:,.0f}")
    lines.append(by_tier.to_markdown(index=False))

    lines.append("\n## Regex baseline — facility_type distribution\n")
    lines.append(df["regex_facility_type"].value_counts().rename_axis("facility_type").reset_index(name="n").to_markdown(index=False))

    if not llm_ran:
        lines.append(
            "\n> **LLM extraction not run this pass** (no GEMINI_API_KEY configured). "
            "Regex baseline only, below. Set the key and rerun `python -m src.forensics` "
            "to populate llm_* columns and the disagreement-rate metric."
        )
        return "\n".join(lines)

    lines.append(f"\n## LLM ({df['llm_model'].dropna().iloc[0] if df['llm_model'].notna().any() else 'n/a'}) vs. regex baseline\n")
    lines.append(f"- Rows scored by both: {agreement['n_scored']:,}")
    lines.append(f"- **Overall disagreement rate: {agreement['overall_disagreement_rate']:.1%}**")
    lines.append(f"  - facility_type: {agreement['facility_type_disagreement_rate']:.1%}")
    lines.append(f"  - lender_name: {agreement['lender_name_disagreement_rate']:.1%}")
    lines.append(f"  - external_reference: {agreement['external_reference_disagreement_rate']:.1%}")
    lines.append(f"- LLM confidence_score: mean {agreement['llm_confidence_mean']:.2f}, median {agreement['llm_confidence_median']:.2f}")
    lines.append(f"- Cache hits this run: {agreement['n_cache_hits']:,} / {agreement['n_scored']:,}")
    if agreement.get("mean_latency_ms_uncached"):
        lines.append(f"- Mean latency (uncached calls): {agreement['mean_latency_ms_uncached']:.0f} ms")

    lines.append("\n**Disagreement rate by confidence tier**\n")
    tier_df = pd.DataFrame(
        [{"signal_tier": k, "disagreement_rate": v} for k, v in agreement["overall_disagreement_rate_by_tier"].items()]
    )
    lines.append(tier_df.to_markdown(index=False))

    lines.append("\n**facility_type confusion (regex baseline vs. LLM)**\n")
    conf_df = pd.DataFrame(agreement["facility_type_confusion"]).rename(
        columns={"regex_facility_type": "regex", "llm_facility_type": "llm"}
    )
    lines.append(conf_df.to_markdown(index=False))

    if calibration is not None and len(calibration):
        lines.append(
            "\n**Confidence calibration on the ambiguous regex='other' bucket** "
            "(explicit 'loan' language and/or a bank-shaped beneficiary name = more "
            "corroborating evidence = higher stated confidence; note the mean_confidence "
            "column is monotonic in the amount of evidence, both within and across "
            "templates)\n"
        )
        cal = calibration.rename(
            columns={"beneficiary_reads_as_bank": "beneficiary_is_bank", "llm_facility_type": "llm_call"}
        ).copy()
        cal["mean_confidence"] = cal["mean_confidence"].round(3)
        lines.append(cal.to_markdown(index=False))

    disagreements = df[(df["agree_all"] == False).fillna(False)]  # noqa: E712 (pandas nullable bool)
    if len(disagreements):
        lines.append(f"\n**Sample disagreements** ({min(10, len(disagreements))} of {len(disagreements)})\n")
        sample_cols = [
            "source_file", "entity_name", "beneficiary_name", "memo",
            "regex_facility_type", "llm_facility_type", "regex_lender_name", "llm_lender_name", "llm_reasoning",
        ]
        lines.append(disagreements[sample_cols].head(10).to_markdown(index=False))

    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> pd.DataFrame:
    parser = argparse.ArgumentParser(description="Phase 2: forensic extraction of the competitor-credit memo signal.")
    parser.add_argument("--sample", type=int, default=None, help="Process a random sample of N rows instead of all rows (smoke test).")
    parser.add_argument("--no-llm", action="store_true", help="Skip the LLM call, regex baseline only.")
    parser.add_argument("--max-workers", type=int, default=12, help="Concurrent LLM requests.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    configure_logging()
    ensure_dirs()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    df = load_memo_rows(con)
    con.close()

    if args.sample:
        df = df.sample(n=min(args.sample, len(df)), random_state=args.seed).reset_index(drop=True)
        logger.info("Sampled down to %d rows (--sample %d).", len(df), args.sample)

    df = apply_regex_baseline(df)

    llm_ran = False
    if not args.no_llm:
        try:
            get_client()
            llm_ran = True
        except MissingAPIKeyError as e:
            logger.warning("%s\nProceeding with regex baseline only.", e)

    calibration = None
    if llm_ran:
        df = run_llm_extraction(df, max_workers=args.max_workers)
        df = compute_agreement(df)
        agreement = disagreement_summary(df)
        calibration = confidence_calibration_table(df)
        if agreement.get("n_scored"):
            logger.info("Overall LLM-vs-regex disagreement rate: %.1f%%", agreement["overall_disagreement_rate"] * 100)
        else:
            logger.info("No rows scored.")
    else:
        agreement = {}

    df.to_parquet(OUTPUT_PARQUET, index=False)
    logger.info("Wrote %s (%d rows)", OUTPUT_PARQUET, len(df))

    report = render_markdown(df, agreement, llm_ran, calibration)
    OUTPUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUTPUT_REPORT_MD)

    return df


if __name__ == "__main__":
    main()
