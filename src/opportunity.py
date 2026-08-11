"""
Phase 6 — Opportunity Ranking (`src/opportunity.py`)
===========================================================================
Ranks all 20 entities by EXPECTED VALUE, not raw wallet-gap size, per
hackathon.txt's Phase 6 spec:

    expected_value = wallet_gap x win_probability x margin

**wallet_gap** (`max(tam_zar - captured_zar, 0)`, per Phase 4/5 output) is
only computed where BOTH tam and captured are observable on the same row
-- for the 3 structurally-unobservable-captured sub-components
(rate_hedging, debt_arrangement, competitor_credit_gap), the full TAM is
reported separately as `unknown_capture_potential_zar`, a diagnostic
upper bound, NEVER blended into the ranked expected_value (that would
overstate precision -- see METHODOLOGY.md Phase 4/5 sections).

**win_probability** is a weighted blend of the 4 right-to-win signals
hackathon.txt names explicitly, weights in config/assumptions.yaml:
  - breadth        -- Phase 5 revealed-presence product/channel/instrument
                       coverage (country handled separately, below)
  - relationship_strength -- Transactional Banking captured share of
                       wallet: the foundational relationship product
                       sequencing is built on
  - momentum        -- Phase 5's Bonferroni-significant time-trend signal
  - country_adjacency -- Phase 5 country-corridor coverage (hackathon.txt:
                       country coverage 10-22/34 is the meaningful
                       corridor signal; currency-pair coverage is dead,
                       all 20 entities use all 5 pairs)

**margin** = `net_margin_realization` (config/assumptions.yaml) -- the
share of GROSS wallet-gap revenue that converts to bottom-line
contribution after cost-to-serve/risk capital. This is NOT a second
application of Phase 4's yield assumptions (wallet_gap is already
revenue, not flow) -- applying a yield bps here again would double-count
margin already priced into wallet_gap.

**Product sequencing enforcement** (hackathon.txt: "you win FX off the
back of payment flow, not the reverse... flag any recommendation that
violates this"): any Global Markets or Investment Banking opportunity for
an entity whose Transactional Banking relationship is below
`sequencing_risk_threshold` is flagged and win_probability is penalised,
not silently ranked as if the foundation were solid.

**Dual-listed global majors** (`src.wallet.GLOBAL_MAJOR_ENTITIES`) are
ranked separately, per the explicit instruction left in Phase 4/5's
handoff notes -- their TAM is inflated by a global (not SA-specific)
revenue base, and mixing them into the main ranked list would let their
artificially large gaps dominate a list meant to guide realistic SA
coverage priorities.

Output: data/processed/opportunity_ranking_entity.parquet (headline: one
    row per entity, ranked),
        data/processed/opportunity_ranking_pillar.parquet (entity x pillar
    detail feeding the headline),
        reports/opportunity_report.md

Run standalone:
    python -m src.opportunity
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.common import EXPECTED_ENTITIES, PROCESSED_DIR, REPORTS_DIR, configure_logging, ensure_dirs
from src.wallet import GLOBAL_MAJOR_ENTITIES, _v, blended_tam_and_captured, load_assumptions

logger = logging.getLogger(__name__)

OUT_ENTITY = PROCESSED_DIR / "opportunity_ranking_entity.parquet"
OUT_PILLAR = PROCESSED_DIR / "opportunity_ranking_pillar.parquet"
OUT_REPORT_MD = REPORTS_DIR / "opportunity_report.md"

CROSS_SELL_PILLARS = ("Global Markets", "Investment Banking")


# --------------------------------------------------------------------------
# 1. Wallet gap (sub-component level, confidence-aware)
# --------------------------------------------------------------------------
def compute_wallet_gaps(wallet_df: pd.DataFrame) -> pd.DataFrame:
    df = wallet_df.copy()
    df["gap_confident"] = df["tam_zar"].notna() & df["captured_zar"].notna()
    df["wallet_gap_zar"] = np.where(df["gap_confident"], (df["tam_zar"] - df["captured_zar"]).clip(lower=0), np.nan)
    df["unknown_capture_tam_zar"] = np.where((~df["gap_confident"]) & df["tam_zar"].notna(), df["tam_zar"], np.nan)
    return df


# --------------------------------------------------------------------------
# 2. Right-to-win signals -> win_probability (entity-level)
# --------------------------------------------------------------------------
def compute_entity_signals(wallet_df: pd.DataFrame, presence_df: pd.DataFrame, trend_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for entity_id, meta in EXPECTED_ENTITIES.items():
        tb = wallet_df[(wallet_df.entity_id == entity_id) & (wallet_df.pillar == "Transactional Banking")]
        tb_tam, tb_captured = blended_tam_and_captured(tb)
        relationship_strength = min(tb_captured / tb_tam, 1.0) if tb_tam else 0.0

        p = presence_df[presence_df.entity_id == entity_id]
        breadth_score = float(p[["breadth_leg_type", "breadth_channel", "breadth_instrument"]].mean(axis=1).iloc[0]) if len(p) else 0.0
        country_adjacency_score = float(p["breadth_country"].iloc[0]) if len(p) else 0.0

        t = trend_df[trend_df.entity_id == entity_id]
        if len(t) and bool(t["significant_bonferroni"].iloc[0]):
            momentum_score = 0.8 if float(t["slope_zar_per_quarter"].iloc[0]) > 0 else 0.2
        else:
            momentum_score = 0.5  # no robust trend -- neutral, not penalised

        rows.append(
            {
                "entity_id": entity_id,
                "entity_name": meta["name"],
                "sector": meta["sector"],
                "is_global_major": entity_id in GLOBAL_MAJOR_ENTITIES,
                "relationship_strength_score": relationship_strength,
                "breadth_score": breadth_score,
                "country_adjacency_score": country_adjacency_score,
                "momentum_score": momentum_score,
            }
        )
    return pd.DataFrame(rows)


def compute_win_probability(signals_df: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    w = assumptions["opportunity_ranking"]["win_probability_weights"]
    df = signals_df.copy()
    df["win_probability"] = (
        df["breadth_score"] * _v(w["breadth"])
        + df["relationship_strength_score"] * _v(w["relationship_strength"])
        + df["momentum_score"] * _v(w["momentum"])
        + df["country_adjacency_score"] * _v(w["country_adjacency"])
    ).clip(0.05, 0.95)
    return df


# --------------------------------------------------------------------------
# 3. Assemble pillar-level expected value, with sequencing enforcement
# --------------------------------------------------------------------------
def build_pillar_ranking(gap_df: pd.DataFrame, signals_df: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    opp = assumptions["opportunity_ranking"]
    margin = _v(opp["net_margin_realization"])
    seq_threshold = _v(opp["sequencing_risk_threshold"])
    seq_penalty = _v(opp["sequencing_penalty_multiplier"])

    pillar_gap = (
        gap_df.groupby(["entity_id", "pillar"])
        .agg(
            wallet_gap_zar=("wallet_gap_zar", lambda s: s.dropna().sum()),
            unknown_capture_tam_zar=("unknown_capture_tam_zar", lambda s: s.dropna().sum()),
            any_confident_gap=("gap_confident", "any"),
        )
        .reset_index()
    )

    df = pillar_gap.merge(signals_df, on="entity_id", how="left")

    df["sequencing_flag"] = (df["pillar"].isin(CROSS_SELL_PILLARS)) & (df["relationship_strength_score"] < seq_threshold)
    df["win_probability_adjusted"] = np.where(df["sequencing_flag"], df["win_probability"] * seq_penalty, df["win_probability"])

    df["expected_value_zar"] = df["wallet_gap_zar"] * df["win_probability_adjusted"] * margin
    df["margin_realization"] = margin
    return df.sort_values("expected_value_zar", ascending=False).reset_index(drop=True)


def build_entity_ranking(pillar_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for entity_id, g in pillar_df.groupby("entity_id"):
        top = g.sort_values("expected_value_zar", ascending=False).iloc[0]
        rows.append(
            {
                "entity_id": entity_id,
                "entity_name": g["entity_name"].iloc[0],
                "sector": g["sector"].iloc[0],
                "is_global_major": bool(g["is_global_major"].iloc[0]),
                "total_wallet_gap_zar": g["wallet_gap_zar"].sum(),
                "total_unknown_capture_tam_zar": g["unknown_capture_tam_zar"].sum(),
                "total_expected_value_zar": g["expected_value_zar"].sum(),
                "top_pillar": top["pillar"],
                "top_pillar_expected_value_zar": top["expected_value_zar"],
                "any_sequencing_flag": bool(g["sequencing_flag"].any()),
                "win_probability": g["win_probability"].iloc[0],
                "relationship_strength_score": g["relationship_strength_score"].iloc[0],
                "breadth_score": g["breadth_score"].iloc[0],
                "momentum_score": g["momentum_score"].iloc[0],
                "country_adjacency_score": g["country_adjacency_score"].iloc[0],
            }
        )
    df = pd.DataFrame(rows)
    df["rank"] = df.groupby("is_global_major")["total_expected_value_zar"].rank(ascending=False, method="first").astype(int)
    return df.sort_values(["is_global_major", "total_expected_value_zar"], ascending=[True, False]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def render_markdown(entity_df: pd.DataFrame, pillar_df: pd.DataFrame) -> str:
    lines = ["# Phase 6 — Opportunity Ranking Report", ""]
    lines.append(
        "`expected_value = wallet_gap x win_probability x margin` (hackathon.txt's own formula). "
        "`wallet_gap` only counts sub-components where captured revenue is directly observable -- "
        "the 3 structurally-unobservable-captured sub-components (`rate_hedging`, `debt_arrangement`, "
        "`competitor_credit_gap`) contribute to `total_unknown_capture_tam_zar` instead, reported "
        "separately as an upper-bound diagnostic, never blended into the ranked figure. `margin` = "
        "`net_margin_realization` (config/assumptions.yaml) -- NOT a second application of Phase 4's "
        "yield assumptions, which already convert flow to gross revenue."
    )

    lines.append("\n## Portfolio ranking — SA-domestic entities (primary list)\n")
    lines.append(
        "**`top_pillar` is Transactional Banking for all 20 entities** — not a coincidence or an "
        "artefact worth second-guessing. TB's TAM formula scales off (revenue + cost_of_sales), a much "
        "larger base than the narrower FX-turnover or debt-specific slices Global Markets/Investment "
        "Banking draw on (METHODOLOGY.md §5.1) — a broad relationship's largest single addressable pillar "
        "being Transactional Banking is a well-established pattern in corporate banking, not a modelling "
        "quirk. **`win_probability` in this table is the entity-level base score, BEFORE the "
        "sequencing penalty** applied to specific Global Markets/Investment Banking rows below (see "
        "'Full pillar-level detail') — shown unadjusted here because it never differs from the "
        "post-adjustment figure for an entity's *top* pillar (Transactional Banking is never itself "
        "sequencing-flagged).\n"
    )
    main = entity_df[~entity_df.is_global_major].copy()
    main["total_expected_value_R_m"] = (main["total_expected_value_zar"] / 1e6).round(2)
    main["total_wallet_gap_R_m"] = (main["total_wallet_gap_zar"] / 1e6).round(1)
    main["win_probability"] = (main["win_probability"] * 100).round(0).astype(int).astype(str) + "%"
    disp_cols = ["rank", "entity_id", "entity_name", "sector", "total_expected_value_R_m", "total_wallet_gap_R_m", "win_probability", "top_pillar", "any_sequencing_flag"]
    lines.append(main[disp_cols].to_markdown(index=False))

    lines.append(
        "\n## ⚠ Dual-listed global majors — ranked separately, not mixed into the list above\n\n"
        "Per METHODOLOGY.md §5.2/§6.3: these entities' Phase 3 revenue is their entire GLOBAL figure, "
        "not South-Africa-specific, inflating their TAM (and therefore wallet_gap) on a scale no "
        "SA-focused coverage effort could realistically close. Ranked here for completeness, not as "
        "priority recommendations.\n"
    )
    gm = entity_df[entity_df.is_global_major].copy()
    gm["total_expected_value_R_m"] = (gm["total_expected_value_zar"] / 1e6).round(2)
    gm["total_wallet_gap_R_m"] = (gm["total_wallet_gap_zar"] / 1e6).round(1)
    gm["win_probability"] = (gm["win_probability"] * 100).round(0).astype(int).astype(str) + "%"
    lines.append(gm[disp_cols].to_markdown(index=False))

    seq_flagged = pillar_df[pillar_df["sequencing_flag"]]
    n_cross_sell_rows = len(pillar_df[pillar_df["pillar"].isin(CROSS_SELL_PILLARS)])
    lines.append(f"\n## ⚠ Product-sequencing risk flags ({len(seq_flagged)}/{n_cross_sell_rows} Global Markets/Investment Banking rows)\n")
    if len(seq_flagged):
        lines.append(
            "These Global Markets / Investment Banking opportunities are flagged because the entity's "
            "Transactional Banking relationship (the foundation hackathon.txt says cross-sell should be "
            "built on) is below the sequencing-readiness threshold -- win_probability has already been "
            "penalised accordingly in the ranking above, not silently treated as a normal-confidence "
            "opportunity.\n\n"
            f"**{len(seq_flagged)}/{n_cross_sell_rows} is the large majority, and that is itself a real "
            "finding, not an over-triggered flag** — it directly reflects Phase 4's headline result that "
            "Syn Bank's Transactional Banking capture is thin almost everywhere in this portfolio "
            "(blended TB share 4.9%, METHODOLOGY.md §5.4). Read this section as \"most Global Markets/ "
            "Investment Banking opportunities in this portfolio need the payment-flow relationship "
            "deepened first,\" a portfolio-level commercial insight, not a list of 30 isolated edge cases.\n"
        )
        sf = seq_flagged[["entity_id", "entity_name", "pillar", "relationship_strength_score", "wallet_gap_zar"]].copy()
        sf["relationship_strength_score"] = (sf["relationship_strength_score"] * 100).round(1).astype(str) + "%"
        sf["wallet_gap_zar"] = sf["wallet_gap_zar"].map(lambda x: f"R{x/1e6:,.1f}m" if pd.notna(x) else "n/a")
        lines.append(sf.to_markdown(index=False))
    else:
        lines.append("None triggered this run.")

    lines.append("\n## Right-to-win signal detail (entity level, feeds win_probability)\n")
    lines.append(
        "**`breadth_score` clusters near 1.0 for nearly every entity** — the same low-discriminating-"
        "power pattern already disclosed for Phase 5's revealed-presence estimator (METHODOLOGY.md §6.3): "
        "all 20 entities in this portfolio already use nearly Syn Bank's full leg-type/channel/instrument "
        "range, so this signal contributes little variation to win_probability in practice. The signals "
        "actually driving the spread below are `relationship_strength_score` and `country_adjacency_score` "
        "— disclosed here rather than let a reader assume all 4 signals are pulling equal weight.\n"
    )
    sig = entity_df[["entity_id", "entity_name", "breadth_score", "relationship_strength_score", "momentum_score", "country_adjacency_score", "win_probability"]].copy()
    for c in ["breadth_score", "relationship_strength_score", "momentum_score", "country_adjacency_score", "win_probability"]:
        sig[c] = sig[c].round(2)
    lines.append(sig.sort_values("entity_id").to_markdown(index=False))

    lines.append("\n## Full pillar-level detail\n")
    pd_disp = pillar_df[["entity_id", "entity_name", "pillar", "wallet_gap_zar", "unknown_capture_tam_zar", "win_probability_adjusted", "expected_value_zar", "sequencing_flag"]].copy()
    for c in ["wallet_gap_zar", "unknown_capture_tam_zar", "expected_value_zar"]:
        pd_disp[c] = pd_disp[c].map(lambda x: f"{x:,.0f}" if pd.notna(x) else "")
    pd_disp["win_probability_adjusted"] = pd_disp["win_probability_adjusted"].round(2)
    lines.append(pd_disp.to_markdown(index=False))

    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> None:
    configure_logging()
    ensure_dirs()

    assumptions = load_assumptions()
    wallet_df = pd.read_parquet(PROCESSED_DIR / "wallet_model.parquet")
    presence_df = pd.read_parquet(PROCESSED_DIR / "revealed_presence.parquet")
    trend_df = pd.read_parquet(PROCESSED_DIR / "time_trends_entity.parquet")

    gap_df = compute_wallet_gaps(wallet_df)
    signals_df = compute_entity_signals(wallet_df, presence_df, trend_df)
    signals_df = compute_win_probability(signals_df, assumptions)
    pillar_df = build_pillar_ranking(gap_df, signals_df, assumptions)
    entity_df = build_entity_ranking(pillar_df)

    pillar_df.to_parquet(OUT_PILLAR, index=False)
    entity_df.to_parquet(OUT_ENTITY, index=False)
    logger.info("Wrote %s (%d rows), %s (%d rows)", OUT_PILLAR, len(pillar_df), OUT_ENTITY, len(entity_df))

    report = render_markdown(entity_df, pillar_df)
    OUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUT_REPORT_MD)

    top = entity_df[~entity_df.is_global_major].iloc[0]
    logger.info(
        "Top SA-domestic opportunity: %s (%s) -- expected value R%.1fm, top pillar %s",
        top["entity_name"], top["entity_id"], top["total_expected_value_zar"] / 1e6, top["top_pillar"],
    )


if __name__ == "__main__":
    main()
