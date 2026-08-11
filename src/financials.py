"""
Phase 3 — External Financial Baseline  [Gen AI #2]
===========================================================================
For the 20 real JSE-listed entities in src.common.EXPECTED_ENTITIES, extracts a
structured financial baseline (revenue, cost of sales, inventory, trade
receivables/payables, total debt, foreign revenue %) to a strict schema, with a
source citation and a confidence flag on every field.

Scope note vs. the original brief: hackathon.txt's data table implies financial-
statement PDFs would be supplied alongside the 3 CSVs. None were. This phase
therefore sources real public filings data instead (JSE-listed companies'
own results releases plus stockanalysis.com, a filings-derived aggregator used
for cross-company consistency) -- see METHODOLOGY.md §0 "Discrepancy 2" and
PLAN.md's Phase 3 section for the full rationale. hackathon.txt's own "Data" and
"Hints and Tips" sections explicitly invite exactly this.

Pipeline shape mirrors Phase 2 (src/forensics.py) deliberately:
  1. Raw source text, fetched once and committed as evidence, at
     data/external/raw/<entity_id>_*.md (income statement + balance sheet,
     as returned by each fetch, with source URLs preserved) and
     data/external/raw/geographic_foreign_revenue_notes.md (foreign revenue /
     geographic segment research, entity-keyed sections).
  2. An LLM (Gemini) reads that raw text per entity and extracts to a strict
     pydantic schema -- this is the actual "Gen AI component 2" the brief
     scores: normalising inconsistent units/currencies/fiscal-year windows,
     deriving cost_of_sales when only gross_profit is disclosed, picking the
     latest COMPLETE fiscal year across sources with different period-ends,
     and carrying a source note + confidence flag on every field. NEVER
     invents a number -- a field with no support in the raw text is null.
  3. Cross-checked against a hand-labelled ground truth
     (tests/financials_ground_truth.csv, independently re-verified against
     primary sources) -- the field-level accuracy report is the Phase 3
     equivalent of Phase 2's regex-vs-LLM disagreement rate.

Output: data/processed/financial_baseline.parquet

Run standalone:
    python -m src.financials                # full run (all 20 entities)
    python -m src.financials --entity E01    # single entity (debugging)
    python -m src.financials --no-llm        # skip the LLM call (no API key needed;
                                              # produces an empty/null baseline, all
                                              # fields propagate null -- this phase has
                                              # no non-LLM baseline, unlike Phase 2)
"""
from __future__ import annotations

import argparse
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field

from src.common import (
    EXPECTED_ENTITIES,
    EXTERNAL_RAW_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    TESTS_DIR,
    configure_logging,
    ensure_dirs,
)
from src.llm import MissingAPIKeyError, LLMResult, generate_structured, get_client

logger = logging.getLogger(__name__)

OUTPUT_PARQUET = PROCESSED_DIR / "financial_baseline.parquet"
OUTPUT_REPORT_MD = REPORTS_DIR / "financials_report.md"
GROUND_TRUTH_CSV = TESTS_DIR / "financials_ground_truth.csv"
NAMESPACE = "financials_baseline_extraction"

FIELDS = [
    "total_revenue",
    "cost_of_sales",
    "inventory",
    "trade_receivables",
    "trade_payables",
    "total_debt",
    "foreign_revenue_pct",
]


# --------------------------------------------------------------------------
# 1. Load raw source text per entity
# --------------------------------------------------------------------------
_GEO_SECTION_PATTERN = re.compile(r"^## (E\d{2}) .*?(?=^## E\d{2} |\Z)", re.MULTILINE | re.DOTALL)


def load_geo_notes() -> dict[str, str]:
    path = EXTERNAL_RAW_DIR / "geographic_foreign_revenue_notes.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return {m.group(1): m.group(0).strip() for m in _GEO_SECTION_PATTERN.finditer(text)}


def load_raw_text_for_entity(entity_id: str, geo_notes: dict[str, str]) -> Optional[str]:
    files = sorted(EXTERNAL_RAW_DIR.glob(f"{entity_id}_*.md"))
    if not files:
        return None
    parts = [f.read_text(encoding="utf-8") for f in files]
    if entity_id in geo_notes:
        parts.append("## Foreign revenue / geographic segment research\n\n" + geo_notes[entity_id])
    return "\n\n---\n\n".join(parts)


# --------------------------------------------------------------------------
# 2. LLM extraction schema
# --------------------------------------------------------------------------
class ConfidenceLevel(str, Enum):
    high = "high"  # directly-disclosed line item from a primary source or a reliable filings-derived aggregator
    medium = "medium"  # derived by calculation (e.g. revenue - gross_profit), or an operating-region proxy rather than a strict definition
    low = "low"  # directional/qualitative only, secondary source, or real definitional ambiguity in the raw text


class FinancialBaselineExtraction(BaseModel):
    fiscal_year_end: Optional[str] = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) of the most recently COMPLETED fiscal year end covered by "
        "the figures you extract. Prefer the latest full year over a TTM/interim figure if both are "
        "present in the source text, since TTM windows are not how the company itself reports "
        "'the annual figures'. Null if genuinely undeterminable.",
    )
    reported_currency: Optional[str] = Field(
        default=None, description="ISO currency code of the figures as extracted (e.g. ZAR, USD, GBP, EUR)."
    )

    total_revenue: Optional[float] = Field(
        default=None, description="Total revenue for the fiscal_year_end period, in reported_currency millions."
    )
    total_revenue_confidence: Optional[ConfidenceLevel] = None

    cost_of_sales: Optional[float] = Field(
        default=None,
        description="Cost of sales/cost of revenue for the same period, in reported_currency millions. If the "
        "source text does not disclose this as its own line item but DOES show gross_profit, derive it as "
        "(total_revenue - gross_profit) and set cost_of_sales_is_derived=true with medium confidence -- never "
        "leave it null just because it wasn't a labelled line item if it's computable from what IS given.",
    )
    cost_of_sales_confidence: Optional[ConfidenceLevel] = None
    cost_of_sales_is_derived: bool = Field(
        default=False, description="True if cost_of_sales was computed as revenue - gross_profit rather than read directly."
    )

    inventory: Optional[float] = Field(default=None, description="Inventory balance, in reported_currency millions.")
    inventory_confidence: Optional[ConfidenceLevel] = None

    trade_receivables: Optional[float] = Field(
        default=None,
        description="Trade/accounts receivable balance, in reported_currency millions. Do not use a generic "
        "'Other Receivables' line as a substitute -- if only that is disclosed (common for insurers), leave "
        "this null and add 'trade_receivables' to not_applicable_fields instead if the entity is a business "
        "type (insurer, REIT) where the concept doesn't apply the same way.",
    )
    trade_receivables_confidence: Optional[ConfidenceLevel] = None

    trade_payables: Optional[float] = Field(default=None, description="Trade/accounts payable balance, in reported_currency millions.")
    trade_payables_confidence: Optional[ConfidenceLevel] = None

    total_debt: Optional[float] = Field(
        default=None,
        description="Total debt (short-term + current portion of long-term + long-term), in reported_currency "
        "millions, as shown in the balance sheet table. If the source text ALSO mentions a different "
        "company-stated 'net debt' or 'adjusted net debt' figure, prefer the balance-sheet total_debt for this "
        "field and mention the alternate figure in source_note instead of substituting it in.",
    )
    total_debt_confidence: Optional[ConfidenceLevel] = None

    foreign_revenue_pct: Optional[float] = Field(
        default=None,
        description="Percentage (0-100) of revenue from OUTSIDE South Africa, if a specific figure or a cleanly "
        "derivable one (e.g. from two disclosed absolute totals) is present in the source text. Null if the "
        "text only has qualitative language ('highly diversified', 'export-intensive') with no number attached "
        "-- do not estimate a percentage from adjectives.",
    )
    foreign_revenue_pct_confidence: Optional[ConfidenceLevel] = None

    not_applicable_fields: list[str] = Field(
        default_factory=list,
        description="Names of fields among [cost_of_sales, inventory, trade_receivables, trade_payables] that "
        "are not a meaningful concept for this entity's business model (e.g. inventory/cost_of_sales for an "
        "insurer or REIT) -- distinct from 'not found in the source text'. Use the exact field names.",
    )
    source_note: str = Field(
        description="One or two sentences: which source(s) in the raw text you drew from, the fiscal year you "
        "picked and why, and any definitional caveats worth a banker knowing (e.g. two conflicting debt "
        "figures, a structural one-off like a merger or divestment distorting a comparison)."
    )


SYSTEM_INSTRUCTION = """You are a credit/financial analyst at Syn Bank, a corporate and investment bank, \
building an external financial baseline for a JSE-listed corporate client from research notes your team has \
already gathered (fetched from public filings, filings-derived data aggregators, and results announcements). \
You are NOT browsing the web yourself -- you only see the raw text provided to you.

Your job: extract a strict set of financial figures for the most recently COMPLETED fiscal year, each with a \
confidence flag, from text that may span multiple sources with different fiscal-year windows, currencies, and \
definitions (e.g. two different "debt" figures, or a metric derived from a calculation shown in the notes \
rather than a labelled line item).

Today's date is 2026-08-11. Financial data tables in the source text may show fiscal years you find \
unfamiliar (e.g. FY2025 or FY2026) if your own training data was less current -- that is expected and correct, \
not a data error. Do not let a year "feeling" more recent or familiar to you override what the text actually \
shows.

Rules -- these matter more than completeness:
- NEVER invent or estimate a number that isn't supported by the text. If a figure genuinely isn't present or \
derivable, leave it null. A null is far more useful downstream than a plausible-looking guess -- it lets \
uncertainty propagate honestly instead of being silently hidden.
- Fiscal year selection algorithm, apply this explicitly: scan every period-ending date shown anywhere in the \
source text for this entity; among those on or before today's date (2026-08-11), pick the SINGLE LATEST one; \
extract every field from that column only. Do not default to an earlier year because it looks more "normal", \
more complete, or because another part of the text discusses it more -- an explanatory note about why the \
latest year looks unusual (a merger, a divestment, a one-off) is a reason to keep using that latest year and \
mention the caveat in source_note, never a reason to fall back to an earlier one.
- Prefer the latest full fiscal year over a TTM (trailing-twelve-month) figure when the text shows both -- TTM \
is not itself a fiscal year, but if the TTM period-end is more recent than any labelled fiscal year and the \
labelled latest fiscal year's data looks incomplete, say so in source_note rather than silently picking either.
- When multiple candidate figures conflict (e.g. balance-sheet "Total Debt" vs. a company-stated "adjusted net \
debt"), pick the more standard/comparable one for the named field and note the alternate in source_note -- do \
not average or silently pick whichever is larger/smaller.
- Distinguish "not applicable" (this concept doesn't exist for this business model, e.g. inventory for an \
insurer) from "not found" (concept applies but no figure was in the text) -- use not_applicable_fields for the \
former, leave the field null with no special flag for the latter.
- confidence: high = directly disclosed and unambiguous; medium = derived by calculation or an accepted proxy \
(e.g. operating-region mix standing in for revenue-destination mix); low = directional/qualitative source, \
real definitional ambiguity, or a single-quarter figure standing in for an annual one."""


def _build_prompt(entity_id: str, raw_text: str) -> str:
    meta = EXPECTED_ENTITIES[entity_id]
    return (
        f"entity_id: {entity_id}\nentity_name: {meta['name']}\nsector: {meta['sector']}\n\n"
        f"--- Research notes (fetched from public sources) ---\n\n{raw_text}"
    )


def _extract_one(entity_id: str, raw_text: str) -> tuple[str, LLMResult]:
    prompt = _build_prompt(entity_id, raw_text)
    result = generate_structured(
        namespace=NAMESPACE,
        system_instruction=SYSTEM_INSTRUCTION,
        prompt=prompt,
        response_schema=FinancialBaselineExtraction,
        extra_cache_key=entity_id,
    )
    return entity_id, result


def run_llm_extraction(entity_ids: list[str], max_workers: int = 8) -> pd.DataFrame:
    geo_notes = load_geo_notes()
    raw_by_entity = {eid: load_raw_text_for_entity(eid, geo_notes) for eid in entity_ids}
    missing = [eid for eid, txt in raw_by_entity.items() if txt is None]
    if missing:
        logger.warning("No raw source text found for %d entities: %s", len(missing), missing)

    rows: list[dict] = []
    results_by_entity: dict[str, LLMResult] = {}
    to_run = {eid: txt for eid, txt in raw_by_entity.items() if txt is not None}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_extract_one, eid, txt): eid for eid, txt in to_run.items()}
        for fut in as_completed(futures):
            eid = futures[fut]
            try:
                _, result = fut.result()
                results_by_entity[eid] = result
            except Exception:
                logger.exception("Extraction failed for entity_id=%s", eid)

    for entity_id in entity_ids:
        meta = EXPECTED_ENTITIES[entity_id]
        row = {
            "entity_id": entity_id,
            "entity_name": meta["name"],
            "sector": meta["sector"],
            "has_raw_source": raw_by_entity.get(entity_id) is not None,
        }
        result = results_by_entity.get(entity_id)
        if result is not None and result.parsed is not None:
            parsed: FinancialBaselineExtraction = result.parsed
            row.update(parsed.model_dump())
            row["llm_cached"] = result.cached
            row["llm_latency_ms"] = result.latency_ms
        else:
            row["extraction_failed"] = True
        rows.append(row)

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 3. Ground-truth accuracy check
# --------------------------------------------------------------------------
def load_ground_truth() -> Optional[pd.DataFrame]:
    if not GROUND_TRUTH_CSV.exists():
        return None
    return pd.read_csv(GROUND_TRUTH_CSV)


def score_against_ground_truth(df: pd.DataFrame, ground_truth: pd.DataFrame, tolerance_pct: float = 2.0) -> pd.DataFrame:
    """Field-level accuracy: numeric fields match within tolerance_pct%, categorical/text fields match exactly.

    A ground-truth row with an EMPTY ground_truth_value means "this field is expected to be null"
    (e.g. cost_of_sales for an insurer) -- distinct from a missing/unlabelled row. Scoring an
    extracted null against an expected-null as a mismatch would penalise the pipeline for correctly
    declining to invent a figure, which is exactly the behaviour this project rewards.
    """
    rows = []
    indexed = df.set_index("entity_id")
    for _, gt in ground_truth.iterrows():
        entity_id, field = gt["entity_id"], gt["field"]
        expected = gt["ground_truth_value"]
        expected_is_null = pd.isna(expected)
        if entity_id not in indexed.index or field not in indexed.columns:
            rows.append({"entity_id": entity_id, "field": field, "match": False, "reason": "field_or_entity_missing"})
            continue
        actual = indexed.loc[entity_id, field]
        actual_is_null = pd.isna(actual)

        if expected_is_null:
            match = actual_is_null
            reason = "correct_null" if match else "expected_null_but_extracted_a_value"
            rows.append({"entity_id": entity_id, "field": field, "match": match, "reason": reason, "expected": None, "actual": None if actual_is_null else actual})
            continue
        if actual_is_null:
            rows.append({"entity_id": entity_id, "field": field, "match": False, "reason": "extracted_null", "expected": expected, "actual": None})
            continue
        try:
            expected_f, actual_f = float(expected), float(actual)
            pct_diff = abs(actual_f - expected_f) / abs(expected_f) * 100 if expected_f else abs(actual_f)
            match = pct_diff <= tolerance_pct
            rows.append({"entity_id": entity_id, "field": field, "match": match, "reason": f"{pct_diff:.2f}% diff", "expected": expected_f, "actual": actual_f})
        except (TypeError, ValueError):
            match = str(actual).strip().lower() == str(expected).strip().lower()
            rows.append({"entity_id": entity_id, "field": field, "match": match, "reason": "exact_str", "expected": expected, "actual": actual})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 4. Reporting
# --------------------------------------------------------------------------
def render_markdown(df: pd.DataFrame, scoring: Optional[pd.DataFrame], llm_ran: bool) -> str:
    lines = ["# Phase 3 — External Financial Baseline Report", ""]
    lines.append(
        f"Entities processed: **{len(df)}** / {len(EXPECTED_ENTITIES)}. "
        "No financial-statement PDFs were supplied with the hackathon data (see METHODOLOGY.md §0) -- "
        "every figure below is sourced from public filings / filings-derived aggregators, fetched once and "
        "committed at `data/external/raw/`, then extracted to this schema by Gemini "
        "(`src/financials.py`, namespace `financials_baseline_extraction`). Full source list: "
        "`reports/external_sources.md`."
    )
    lines.append("")

    if not llm_ran:
        lines.append("> **LLM extraction not run this pass** (no GEMINI_API_KEY configured). No baseline produced.")
        return "\n".join(lines)

    lines.append("## Coverage — non-null rate per field\n")
    cov = pd.DataFrame(
        {"field": FIELDS, "non_null_n": [df[f].notna().sum() if f in df.columns else 0 for f in FIELDS]}
    )
    cov["non_null_pct"] = (cov["non_null_n"] / len(df) * 100).round(0).astype(int).astype(str) + "%"
    lines.append(cov.to_markdown(index=False))

    if "not_applicable_fields" in df.columns:
        na_counts: dict[str, int] = {}
        for lst in df["not_applicable_fields"].dropna():
            for f in lst:
                na_counts[f] = na_counts.get(f, 0) + 1
        if na_counts:
            lines.append("\n**Flagged not-applicable** (business model doesn't have this line item, e.g. insurers/REITs):\n")
            lines.append(pd.DataFrame([{"field": k, "n_entities": v} for k, v in na_counts.items()]).to_markdown(index=False))

    if "total_revenue_confidence" in df.columns:
        lines.append("\n## Confidence distribution by field\n")
        conf_rows = []
        for f in FIELDS:
            cf = f"{f}_confidence"
            if cf in df.columns:
                vc = df[cf].value_counts()
                conf_rows.append({"field": f, "high": int(vc.get("high", 0)), "medium": int(vc.get("medium", 0)), "low": int(vc.get("low", 0)), "null": int(df[f].isna().sum())})
        lines.append(pd.DataFrame(conf_rows).to_markdown(index=False))

    if scoring is not None and len(scoring):
        n_match = int(scoring["match"].sum())
        n_total = len(scoring)
        lines.append(f"\n## Ground-truth accuracy\n\n- Hand-labelled sample: **{n_total} (entity, field) pairs** "
                      f"(`tests/financials_ground_truth.csv`), independently re-verified against primary sources.\n"
                      f"- **Field-level accuracy: {n_match}/{n_total} ({n_match/n_total:.1%})** within "
                      f"±2% tolerance for numeric fields, exact match for categorical.")
        lines.append("\n" + scoring.to_markdown(index=False))

    lines.append("\n## Full baseline table\n")
    display_cols = ["entity_id", "entity_name", "sector", "fiscal_year_end", "reported_currency"] + FIELDS
    display_cols = [c for c in display_cols if c in df.columns]
    lines.append(df[display_cols].to_markdown(index=False))

    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> pd.DataFrame:
    parser = argparse.ArgumentParser(description="Phase 3: external financial baseline extraction.")
    parser.add_argument("--entity", type=str, default=None, help="Process a single entity_id (debugging).")
    parser.add_argument("--no-llm", action="store_true", help="Skip the LLM call (no baseline produced; this phase has no non-LLM fallback).")
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()

    configure_logging()
    ensure_dirs()

    entity_ids = [args.entity] if args.entity else sorted(EXPECTED_ENTITIES.keys())

    llm_ran = False
    if not args.no_llm:
        try:
            get_client()
            llm_ran = True
        except MissingAPIKeyError as e:
            logger.warning("%s\nNo baseline can be produced without an LLM this phase.", e)

    if not llm_ran:
        df = pd.DataFrame(
            [{"entity_id": eid, **EXPECTED_ENTITIES[eid]} for eid in entity_ids]
        )
        report = render_markdown(df, None, llm_ran=False)
        OUTPUT_REPORT_MD.write_text(report, encoding="utf-8")
        logger.info("Wrote %s (no-llm mode)", OUTPUT_REPORT_MD)
        return df

    df = run_llm_extraction(entity_ids, max_workers=args.max_workers)
    logger.info("Extraction complete: %d / %d entities have a fiscal_year_end.", df["fiscal_year_end"].notna().sum() if "fiscal_year_end" in df else 0, len(df))

    df.to_parquet(OUTPUT_PARQUET, index=False)
    logger.info("Wrote %s (%d rows)", OUTPUT_PARQUET, len(df))

    ground_truth = load_ground_truth()
    scoring = score_against_ground_truth(df, ground_truth) if ground_truth is not None else None
    if scoring is not None:
        logger.info("Ground-truth accuracy: %d/%d (%.1f%%)", scoring["match"].sum(), len(scoring), scoring["match"].mean() * 100)

    report = render_markdown(df, scoring, llm_ran=True)
    OUTPUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUTPUT_REPORT_MD)

    return df


if __name__ == "__main__":
    main()
