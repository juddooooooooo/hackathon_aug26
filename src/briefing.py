"""
Phase 8 support — AI-Generated Client Briefing Notes (`src/briefing.py`)
===========================================================================
hackathon.txt's dashboard deliverable requires "AI-generated briefing notes
for AT LEAST 3 clients... generated from model output, not free-generated
— state this on the page." This module is that Gen AI component: for every
entity, it feeds Gemini ONLY already-computed figures (Phase 2-6 outputs —
opportunity ranking, wallet gaps, right-to-win signals, competitor-credit
exposure, financials) and asks for a short banker-facing summary grounded
strictly in those figures. Never asked to reason from raw data, never given
room to invent a number -- every rand figure in a briefing note traces back
to a parquet file already produced by an earlier phase.

Uses src.llm.generate_structured like every other Gen AI component in this
pipeline (Phase 2, Phase 3) -- prompt logging, caching, usage ledger, all
for free.

Output: data/processed/briefing_notes.parquet, reports/briefing_notes.md

Run standalone:
    python -m src.briefing
"""
from __future__ import annotations

import argparse
import logging
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field

from src.common import EXPECTED_ENTITIES, PROCESSED_DIR, REPORTS_DIR, configure_logging, ensure_dirs
from src.llm import MissingAPIKeyError, LLMResult, generate_structured, get_client
from src.wallet import GLOBAL_MAJOR_ENTITIES

logger = logging.getLogger(__name__)

OUTPUT_PARQUET = PROCESSED_DIR / "briefing_notes.parquet"
OUTPUT_REPORT_MD = REPORTS_DIR / "briefing_notes.md"
NAMESPACE = "client_briefing_notes"


class ClientBriefing(BaseModel):
    headline: str = Field(
        description="One-sentence headline naming the single biggest opportunity in rand terms and its pillar, "
        "e.g. 'R193.8m expected-value opportunity, anchored in Transactional Banking'. Use the exact figures given."
    )
    summary: str = Field(
        description="3-5 sentence briefing note for a coverage banker preparing for a client call. Ground every "
        "claim strictly in the figures provided -- never invent a number, a product, or a fact not given. Plain "
        "language a non-technical senior banker can act on, not a data dump."
    )
    recommended_next_step: str = Field(
        description="One concrete, specific next action for the coverage team -- respect product sequencing "
        "(don't recommend leading with FX/Investment Banking if a sequencing risk was flagged)."
    )
    caveats: Optional[str] = Field(
        default=None,
        description="Any caveat the banker must know before acting (sequencing risk, a TAM-assumption breach, "
        "the global-major denominator distortion, low data confidence) -- null if genuinely none apply. Do not "
        "invent a caveat that isn't in the provided figures.",
    )


SYSTEM_INSTRUCTION = """You are a research analyst at Syn Bank, a South African corporate and investment bank, \
writing a one-page briefing note for a coverage banker ahead of a client meeting. You are given ONLY already-\
computed figures from Syn Bank's internal wallet-sizing and opportunity-ranking models -- you did not compute \
these yourself and must not second-guess, adjust, or recompute them. Your job is purely to translate structured \
figures into a short, clear, accurate narrative a busy senior banker can read in 30 seconds.

Rules:
- NEVER invent a number, product, competitor name, or fact not present in the figures you are given.
- Quote rand figures and percentages exactly as given (rounding for readability is fine, e.g. R193.8m).
- If a sequencing risk, TAM-assumption caveat, or global-major flag is present in the input, you MUST mention it \
in `caveats` -- do not omit a disclosed limitation to make the note sound more confident than the underlying data \
supports.
- Keep the tone factual and commercial, not promotional -- this is an internal working note, not marketing copy."""


def _build_prompt(entity_id: str, ctx: dict) -> str:
    lines = [
        f"entity_id: {entity_id}",
        f"entity_name: {ctx['entity_name']}",
        f"sector: {ctx['sector']}",
        f"is_dual_listed_global_major: {ctx['is_global_major']} (if true: TAM is based on GLOBAL revenue, not "
        f"South-Africa-specific -- the wallet gap is a global-scale upper bound, not a realistic SA coverage target)",
        "",
        "-- Opportunity ranking (Phase 6) --",
        f"total_expected_value_zar: {ctx['total_expected_value_zar']:.0f}",
        f"total_wallet_gap_zar: {ctx['total_wallet_gap_zar']:.0f}",
        f"top_pillar: {ctx['top_pillar']}",
        f"win_probability: {ctx['win_probability']:.2f}",
        f"any_sequencing_flag: {ctx['any_sequencing_flag']} (if true: a Global Markets/Investment Banking "
        f"opportunity here rests on a weak Transactional Banking relationship -- recommend deepening payment "
        f"flow first, not leading with FX/IB)",
        f"relationship_strength_score (Transactional Banking share of wallet): {ctx['relationship_strength_score']:.2f}",
        f"total_unknown_capture_potential_zar: {ctx['total_unknown_capture_tam_zar']:.0f} (wallet size Syn Bank "
        f"cannot currently measure its own capture of -- a diagnostic upper bound, not part of the ranked "
        f"expected value)",
        f"tam_assumption_breach: {ctx['tam_assumption_breach']} (if true: at least one wallet-size assumption "
        f"underlying this entity's figures is now KNOWN to be too conservative -- Syn Bank's own observed "
        f"revenue for one product exceeded the modelled total addressable market for it, meaning this entity's "
        f"true opportunity is plausibly LARGER than the figures above show, not smaller -- you MUST surface "
        f"this in caveats if true)",
    ]
    if ctx.get("competitor_credit_primary_zar", 0) or ctx.get("competitor_credit_secondary_zar", 0):
        lines += [
            "",
            "-- Competitor-credit signal (Phase 2) --",
            f"primary_tier_competitor_credit_flow_zar: {ctx['competitor_credit_primary_zar']:.0f} (high-confidence "
            f"evidence a competitor bank holds a credit facility Syn Bank is settling payment legs for)",
            f"secondary_tier_competitor_credit_flow_zar: {ctx['competitor_credit_secondary_zar']:.0f} (lower-confidence, same signal)",
        ]
    if ctx.get("total_revenue_zar_m") is not None:
        lines += [
            "",
            "-- Financials (Phase 3) --",
            f"total_revenue_R_millions: {ctx['total_revenue_zar_m']:.0f}",
        ]
        if ctx.get("foreign_revenue_pct") is not None:
            lines.append(f"foreign_revenue_pct: {ctx['foreign_revenue_pct']:.0f}")
    return "\n".join(lines)


def build_entity_context(
    entity_df: pd.DataFrame, competitor_events: pd.DataFrame, fin: pd.DataFrame, wallet_df: pd.DataFrame
) -> dict[str, dict]:
    ce = competitor_events.groupby(["entity_id", "signal_tier"])["value_zar"].sum().unstack(fill_value=0.0)
    breach_by_entity = wallet_df.groupby("entity_id")["tam_assumption_breach"].any()
    contexts = {}
    for _, row in entity_df.iterrows():
        eid = row["entity_id"]
        ctx = {
            "entity_name": row["entity_name"],
            "sector": row["sector"],
            "is_global_major": bool(row["is_global_major"]),
            "total_expected_value_zar": float(row["total_expected_value_zar"]),
            "total_wallet_gap_zar": float(row["total_wallet_gap_zar"]),
            "total_unknown_capture_tam_zar": float(row["total_unknown_capture_tam_zar"]),
            "top_pillar": row["top_pillar"],
            "win_probability": float(row["win_probability"]),
            "relationship_strength_score": float(row["relationship_strength_score"]),
            "any_sequencing_flag": bool(row["any_sequencing_flag"]),
            "tam_assumption_breach": bool(breach_by_entity.get(eid, False)),
            "competitor_credit_primary_zar": float(ce.loc[eid, "primary"]) if eid in ce.index and "primary" in ce.columns else 0.0,
            "competitor_credit_secondary_zar": float(ce.loc[eid, "secondary"]) if eid in ce.index and "secondary" in ce.columns else 0.0,
        }
        if eid in fin.index:
            fin_row = fin.loc[eid]
            ctx["total_revenue_zar_m"] = float(fin_row["total_revenue"]) if pd.notna(fin_row.get("total_revenue")) else None
            ctx["foreign_revenue_pct"] = float(fin_row["foreign_revenue_pct"]) if pd.notna(fin_row.get("foreign_revenue_pct")) else None
        else:
            ctx["total_revenue_zar_m"] = None
            ctx["foreign_revenue_pct"] = None
        contexts[eid] = ctx
    return contexts


def generate_briefings(contexts: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for entity_id, ctx in contexts.items():
        prompt = _build_prompt(entity_id, ctx)
        result: LLMResult = generate_structured(
            namespace=NAMESPACE,
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            response_schema=ClientBriefing,
            extra_cache_key=entity_id,
        )
        row = {"entity_id": entity_id, "entity_name": ctx["entity_name"]}
        if result.parsed is not None:
            parsed: ClientBriefing = result.parsed
            row.update(parsed.model_dump())
        else:
            row["headline"] = None
            row["summary"] = None
            row["recommended_next_step"] = None
            row["caveats"] = None
        rows.append(row)
        logger.info("Briefing generated: %s (%s)", entity_id, ctx["entity_name"])
    return pd.DataFrame(rows)


def render_markdown(df: pd.DataFrame) -> str:
    lines = ["# AI-Generated Client Briefing Notes", ""]
    lines.append(
        "Generated by Gemini (`src/briefing.py`, namespace `client_briefing_notes`) from already-computed "
        "model output only (Phases 2-6) -- never from raw data or free generation. Every prompt is logged "
        "verbatim at `prompts/client_briefing_notes/*.json`. This is the disclosure hackathon.txt requires: "
        "*\"Briefing notes are generated from model output, not free-generated — state this on the page.\"*"
    )
    for _, row in df.iterrows():
        lines.append(f"\n## {row['entity_name']} ({row['entity_id']})\n")
        if pd.isna(row["headline"]):
            lines.append("_Generation failed for this entity -- see logs._")
            continue
        lines.append(f"**{row['headline']}**\n")
        lines.append(row["summary"])
        lines.append(f"\n**Recommended next step:** {row['recommended_next_step']}")
        if pd.notna(row.get("caveats")) and row.get("caveats"):
            lines.append(f"\n**Caveat:** {row['caveats']}")
    return "\n".join(lines)


def main() -> pd.DataFrame:
    parser = argparse.ArgumentParser(description="Generate AI briefing notes from computed model output.")
    parser.add_argument("--entity", type=str, default=None, help="Single entity_id (debugging).")
    args = parser.parse_args()

    configure_logging()
    ensure_dirs()

    try:
        get_client()
    except MissingAPIKeyError as e:
        logger.warning("%s\nNo briefing notes can be generated without an LLM.", e)
        return pd.DataFrame()

    entity_df = pd.read_parquet(PROCESSED_DIR / "opportunity_ranking_entity.parquet")
    competitor_events = pd.read_parquet(PROCESSED_DIR / "competitor_credit_events.parquet")
    fin = pd.read_parquet(PROCESSED_DIR / "financial_baseline.parquet").set_index("entity_id")
    wallet_df = pd.read_parquet(PROCESSED_DIR / "wallet_model.parquet")

    if args.entity:
        entity_df = entity_df[entity_df.entity_id == args.entity]

    contexts = build_entity_context(entity_df, competitor_events, fin, wallet_df)
    df = generate_briefings(contexts)

    df.to_parquet(OUTPUT_PARQUET, index=False)
    logger.info("Wrote %s (%d rows)", OUTPUT_PARQUET, len(df))

    report = render_markdown(df)
    OUTPUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUTPUT_REPORT_MD)

    return df


if __name__ == "__main__":
    main()
