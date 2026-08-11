"""
Phase 4 — Wallet Model (`src/wallet.py`)
===========================================================================
Builds the total addressable wallet (TAM) and Syn Bank's captured revenue,
per entity, under Syn Bank's own three pillars (Transactional Banking,
Global Markets, Investment Banking), converting every observed flow or
external exposure into rands of BANK REVENUE via named yield/intensity
assumptions in `config/assumptions.yaml` — never a hardcoded coefficient.

Numerator (captured) and denominator (TAM) are computed with the SAME
yield for every sub-component that has both sides observable, so
`share_of_wallet = captured / tam` is a like-for-like ratio, not an
apples-to-oranges comparison. Where the captured side is structurally
unobservable from the 3 source files (no derivatives book, no "loans Syn
Bank itself originated" table exists anywhere in the data), it is reported
as `None`, not zero — see METHODOLOGY.md Phase 4 section for exactly which
sub-components this applies to and why.

Inputs:
    config/assumptions.yaml                    every yield/intensity assumption
    data/processed/syn_bank.duckdb             internal ledgers (Phases 1)
    data/processed/financial_baseline.parquet  external financials (Phase 3)
    data/processed/competitor_credit_events.parquet (Phase 2)

Output: data/processed/wallet_model.parquet (long format: one row per
    entity_id x pillar x sub_component), reports/wallet_report.md

Run standalone:
    python -m src.wallet
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd
import yaml

from src.common import (
    CONFIG_DIR,
    DUCKDB_PATH,
    EXPECTED_ENTITIES,
    PROCESSED_DIR,
    REPORTS_DIR,
    configure_logging,
    ensure_dirs,
)

logger = logging.getLogger(__name__)

ASSUMPTIONS_PATH = CONFIG_DIR / "assumptions.yaml"
FINANCIAL_BASELINE_PARQUET = PROCESSED_DIR / "financial_baseline.parquet"
COMPETITOR_EVENTS_PARQUET = PROCESSED_DIR / "competitor_credit_events.parquet"
OUTPUT_PARQUET = PROCESSED_DIR / "wallet_model.parquet"
OUTPUT_REPORT_MD = REPORTS_DIR / "wallet_report.md"

# Dual-listed (or majority non-SA-operating) entities whose Phase 3
# `total_revenue` is a GLOBAL figure, not South-Africa-specific -- see
# METHODOLOGY.md Phase 4 section for why this matters for reading their
# share-of-wallet. E06 Valterra Platinum is deliberately excluded: its ZAR/
# JSE-native reporting reflects genuinely SA-based mining operations even
# though its customers are global.
GLOBAL_MAJOR_ENTITIES = frozenset({"E01", "E02", "E03", "E04", "E05", "E14", "E15", "E20"})


# --------------------------------------------------------------------------
# 0. Load assumptions + upstream phase outputs
# --------------------------------------------------------------------------
def load_assumptions() -> dict[str, Any]:
    with open(ASSUMPTIONS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _v(node: Any) -> float:
    """Pull the numeric `value` out of an assumptions.yaml leaf, whether it's
    a bare number or a {value, rationale} / {value, source} dict."""
    return float(node["value"]) if isinstance(node, dict) else float(node)


def to_zar(value: Optional[float], currency: Optional[str], assumptions: dict) -> Optional[float]:
    if value is None or pd.isna(value) or currency is None or pd.isna(currency):
        return None
    rate_node = assumptions["fx_to_zar"].get(currency)
    if rate_node is None:
        logger.warning("No FX rate for currency=%s -- leaving unconverted value as null.", currency)
        return None
    return value * _v(rate_node)


def load_financial_baseline() -> pd.DataFrame:
    return pd.read_parquet(FINANCIAL_BASELINE_PARQUET)


def load_competitor_events() -> pd.DataFrame:
    return pd.read_parquet(COMPETITOR_EVENTS_PARQUET)


# --------------------------------------------------------------------------
# 1. Internal-ledger aggregates (Syn Bank's own observed activity)
# --------------------------------------------------------------------------
def compute_internal_aggregates(con: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    payments_by_channel = con.sql(
        """
        SELECT entity_id, channel, count(*) AS n_payments, sum(amount_zar) AS value_zar
        FROM transactional_banking
        GROUP BY 1, 2
        """
    ).fetchdf()

    # Average operating balance implied by the ledger: daily net flow
    # (inbound - outbound) per entity, cumulative-summed into a running
    # balance ordered by date, floored at 0 (a negative running position
    # reflects net funding/overdraft, a different product to "deposit NII
    # on a positive balance" -- not modelled here, see METHODOLOGY.md).
    avg_balance = con.sql(
        """
        WITH daily_flow AS (
            SELECT entity_id, date,
                   sum(CASE WHEN direction = 'inbound' THEN amount_zar ELSE -amount_zar END) AS net_flow
            FROM transactional_banking
            GROUP BY entity_id, date
        ),
        running AS (
            SELECT entity_id, date,
                   sum(net_flow) OVER (PARTITION BY entity_id ORDER BY date
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_balance
            FROM daily_flow
        )
        SELECT entity_id, avg(GREATEST(running_balance, 0)) AS avg_balance_zar
        FROM running
        GROUP BY entity_id
        """
    ).fetchdf()

    fx_turnover = con.sql(
        """
        SELECT entity_id, count(*) AS n_payments, sum(value_zar) AS value_zar
        FROM cross_border_payments
        GROUP BY 1
        """
    ).fetchdf()

    trade_finance = con.sql(
        """
        SELECT entity_id, instrument_type,
               sum(value_zar) AS value_zar,
               sum(value_zar * tenor_days) AS value_tenor_days_zar
        FROM trade_finance
        GROUP BY 1, 2
        """
    ).fetchdf()

    return {
        "payments_by_channel": payments_by_channel,
        "avg_balance": avg_balance,
        "fx_turnover": fx_turnover,
        "trade_finance": trade_finance,
    }


# --------------------------------------------------------------------------
# 2. Transactional Banking
# --------------------------------------------------------------------------
def compute_transactional_banking(
    entity_id: str,
    fin_row: Optional[pd.Series],
    internal: dict[str, pd.DataFrame],
    assumptions: dict,
) -> list[dict]:
    rows = []
    tb = assumptions["transactional_banking"]

    # -- Payment fees --
    channel_counts = internal["payments_by_channel"]
    ent_channels = channel_counts[channel_counts.entity_id == entity_id]
    captured_fee_revenue = 0.0
    for _, r in ent_channels.iterrows():
        fee = tb["fee_per_payment_zar"].get(r["channel"])
        if fee is not None:
            captured_fee_revenue += r["n_payments"] * _v(fee)
    n_payments_total = ent_channels["n_payments"].sum() if len(ent_channels) else 0

    tam_fee_revenue = None
    if fin_row is not None:
        revenue_zar = to_zar(fin_row.get("total_revenue"), fin_row.get("reported_currency"), assumptions)
        cost_of_sales_zar = to_zar(fin_row.get("cost_of_sales"), fin_row.get("reported_currency"), assumptions)
        throughput = None
        if revenue_zar is not None:
            throughput = revenue_zar * 1e6 + (cost_of_sales_zar * 1e6 if cost_of_sales_zar is not None else 0)
        if throughput is not None:
            blended_fee = sum(_v(v) for v in tb["fee_per_payment_zar"].values()) / len(tb["fee_per_payment_zar"])
            tam_payment_count = throughput * _v(tb["payments_per_zar_throughput"])
            tam_fee_revenue = tam_payment_count * blended_fee

    rows.append(
        {
            "entity_id": entity_id,
            "pillar": "Transactional Banking",
            "sub_component": "payment_fees",
            "tam_zar": tam_fee_revenue,
            "captured_zar": captured_fee_revenue,
            "captured_observable": True,
            "note": f"{int(n_payments_total):,} Syn Bank payments observed" if n_payments_total else "no Syn Bank payments observed",
        }
    )

    # -- Deposit NII --
    bal = internal["avg_balance"]
    ent_bal = bal[bal.entity_id == entity_id]
    captured_avg_balance = float(ent_bal["avg_balance_zar"].iloc[0]) if len(ent_bal) else 0.0
    captured_nii = captured_avg_balance * (_v(tb["deposit_nii_margin_bps"]) / 10_000)

    tam_nii = None
    if fin_row is not None:
        revenue_zar = to_zar(fin_row.get("total_revenue"), fin_row.get("reported_currency"), assumptions)
        if revenue_zar is not None:
            tam_avg_balance = (revenue_zar * 1e6 / 365) * _v(tb["avg_balance_days_of_revenue"])
            tam_nii = tam_avg_balance * (_v(tb["deposit_nii_margin_bps"]) / 10_000)

    rows.append(
        {
            "entity_id": entity_id,
            "pillar": "Transactional Banking",
            "sub_component": "deposit_nii",
            "tam_zar": tam_nii,
            "captured_zar": captured_nii,
            "captured_observable": True,
            "note": f"implied avg balance R{captured_avg_balance:,.0f}",
        }
    )
    return rows


# --------------------------------------------------------------------------
# 3. Global Markets
# --------------------------------------------------------------------------
def compute_global_markets(
    entity_id: str,
    fin_row: Optional[pd.Series],
    internal: dict[str, pd.DataFrame],
    assumptions: dict,
) -> list[dict]:
    rows = []
    gm = assumptions["global_markets"]

    # -- FX hedging --
    fx = internal["fx_turnover"]
    ent_fx = fx[fx.entity_id == entity_id]
    captured_fx_turnover = float(ent_fx["value_zar"].iloc[0]) if len(ent_fx) else 0.0
    captured_fx_revenue = captured_fx_turnover * (_v(gm["fx_margin_bps"]) / 10_000)

    tam_fx_revenue = None
    if fin_row is not None and pd.notna(fin_row.get("foreign_revenue_pct")):
        revenue_zar = to_zar(fin_row.get("total_revenue"), fin_row.get("reported_currency"), assumptions)
        if revenue_zar is not None:
            foreign_revenue_zar = revenue_zar * 1e6 * (float(fin_row["foreign_revenue_pct"]) / 100)
            hedged_notional = foreign_revenue_zar * _v(gm["fx_hedge_ratio"])
            tam_fx_revenue = hedged_notional * (_v(gm["fx_margin_bps"]) / 10_000)

    rows.append(
        {
            "entity_id": entity_id,
            "pillar": "Global Markets",
            "sub_component": "fx_hedging",
            "tam_zar": tam_fx_revenue,
            "captured_zar": captured_fx_revenue,
            "captured_observable": True,
            "note": f"R{captured_fx_turnover:,.0f} observed FX turnover"
            + ("" if (fin_row is not None and pd.notna(fin_row.get("foreign_revenue_pct"))) else "; TAM null -- no foreign_revenue_pct sourced (Phase 3)"),
        }
    )

    # -- Rate hedging (IRS on floating-rate debt) -- TAM only, captured
    # structurally unobservable from the provided data (no derivatives book).
    tam_irs_revenue = None
    if fin_row is not None and pd.notna(fin_row.get("total_debt")):
        debt_zar = to_zar(fin_row.get("total_debt"), fin_row.get("reported_currency"), assumptions)
        if debt_zar is not None:
            floating_notional = debt_zar * 1e6 * _v(gm["floating_debt_ratio"])
            tam_irs_revenue = floating_notional * (_v(gm["irs_margin_bps"]) / 10_000)

    rows.append(
        {
            "entity_id": entity_id,
            "pillar": "Global Markets",
            "sub_component": "rate_hedging",
            "tam_zar": tam_irs_revenue,
            "captured_zar": None,
            "captured_observable": False,
            "note": "captured side not observable in provided data (no derivatives/swap book in any source file)",
        }
    )
    return rows


# --------------------------------------------------------------------------
# 4. Investment Banking
# --------------------------------------------------------------------------
def compute_investment_banking(
    entity_id: str,
    fin_row: Optional[pd.Series],
    internal: dict[str, pd.DataFrame],
    competitor_events: pd.DataFrame,
    assumptions: dict,
) -> list[dict]:
    rows = []
    ib = assumptions["investment_banking"]

    # -- Debt arrangement fees -- TAM from Phase 3's total_debt (company-
    # wide, source-agnostic); captured not directly observable.
    tam_arrangement = None
    if fin_row is not None and pd.notna(fin_row.get("total_debt")):
        debt_zar = to_zar(fin_row.get("total_debt"), fin_row.get("reported_currency"), assumptions)
        if debt_zar is not None:
            tam_arrangement = (debt_zar * 1e6) * (_v(ib["arrangement_fee_bps"]) / 10_000) / _v(ib["refinancing_cycle_years"])

    rows.append(
        {
            "entity_id": entity_id,
            "pillar": "Investment Banking",
            "sub_component": "debt_arrangement",
            "tam_zar": tam_arrangement,
            "captured_zar": None,
            "captured_observable": False,
            "note": "captured side not observable -- no 'loans Syn Bank originated' table in provided data; see competitor_credit_gap row for a confirmed-elsewhere lower bound",
        }
    )

    # -- Competitor-held credit gap (Phase 2 signal), revenue-equivalent
    # lower-bound proxy on the SAME arrangement-fee basis, for unit
    # consistency with the row above -- see assumptions.yaml comment.
    ent_events = competitor_events[competitor_events.entity_id == entity_id]
    competitor_flow = float(ent_events["value_zar"].sum()) if len(ent_events) else 0.0
    competitor_gap_revenue = competitor_flow * (_v(ib["competitor_facility_arrangement_bps"]) / 10_000)
    primary_flow = float(ent_events.loc[ent_events.signal_tier == "primary", "value_zar"].sum()) if len(ent_events) else 0.0

    rows.append(
        {
            "entity_id": entity_id,
            "pillar": "Investment Banking",
            "sub_component": "competitor_credit_gap",
            "tam_zar": None,  # already inside debt_arrangement's TAM; this is a diagnostic, not an additive TAM line
            "captured_zar": None,
            "captured_observable": False,
            "note": f"R{competitor_flow:,.0f} total competitor-credit flow (R{primary_flow:,.0f} primary-tier) -> "
            f"R{competitor_gap_revenue:,.0f} revenue-equivalent lower bound on wallet confirmed held elsewhere (Phase 2)",
        }
    )

    # -- Trade finance instruments -- captured fully computable; TAM
    # grossed up from captured via primary_bank_trade_finance_share.
    tf = internal["trade_finance"]
    ent_tf = tf[tf.entity_id == entity_id]
    captured_tf_revenue = 0.0
    for _, r in ent_tf.iterrows():
        bps_node = ib["instrument_bps_per_annum"].get(r["instrument_type"])
        if bps_node is not None:
            captured_tf_revenue += (r["value_tenor_days_zar"] / 365) * (_v(bps_node) / 10_000)

    share = _v(ib["primary_bank_trade_finance_share"])
    tam_tf_revenue = captured_tf_revenue / share if share else None

    rows.append(
        {
            "entity_id": entity_id,
            "pillar": "Investment Banking",
            "sub_component": "trade_finance_instruments",
            "tam_zar": tam_tf_revenue,
            "captured_zar": captured_tf_revenue,
            "captured_observable": True,
            "note": f"TAM grossed up from captured at {share:.0%} assumed primary-bank share (most assumption-driven TAM in the model)",
        }
    )
    return rows


# --------------------------------------------------------------------------
# 5. Assemble
# --------------------------------------------------------------------------
def add_share_and_breach_columns(df: pd.DataFrame) -> pd.DataFrame:
    """share_of_wallet = captured/tam wherever both sides are observable (null
    otherwise -- never treated as a 0% capture). tam_assumption_breach flags
    the logically-impossible captured > tam case explicitly rather than
    clipping it to 100%, which would hide a real signal that the TAM
    assumption is too conservative for that entity -- see
    METHODOLOGY.md Phase 4 section "TAM assumption breaches".
    """
    df = df.copy()
    df["share_of_wallet"] = df.apply(
        lambda r: (r["captured_zar"] / r["tam_zar"]) if pd.notna(r["tam_zar"]) and r["tam_zar"] and pd.notna(r["captured_zar"]) else None,
        axis=1,
    )
    df["tam_assumption_breach"] = df["share_of_wallet"].apply(lambda s: bool(pd.notna(s) and s > 1.0))
    return df


def build_wallet_model() -> pd.DataFrame:
    assumptions = load_assumptions()
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    internal = compute_internal_aggregates(con)
    con.close()

    fin = load_financial_baseline().set_index("entity_id")
    competitor_events = load_competitor_events()

    all_rows: list[dict] = []
    for entity_id in sorted(EXPECTED_ENTITIES.keys()):
        fin_row = fin.loc[entity_id] if entity_id in fin.index else None
        all_rows += compute_transactional_banking(entity_id, fin_row, internal, assumptions)
        all_rows += compute_global_markets(entity_id, fin_row, internal, assumptions)
        all_rows += compute_investment_banking(entity_id, fin_row, internal, competitor_events, assumptions)

    df = pd.DataFrame(all_rows)
    df["entity_name"] = df["entity_id"].map(lambda e: EXPECTED_ENTITIES[e]["name"])
    df["sector"] = df["entity_id"].map(lambda e: EXPECTED_ENTITIES[e]["sector"])
    df = add_share_and_breach_columns(df)
    return df


# --------------------------------------------------------------------------
# 6. Reporting
# --------------------------------------------------------------------------
def render_markdown(df: pd.DataFrame) -> str:
    lines = ["# Phase 4 — Wallet Model Report", ""]
    lines.append(
        "Every rand figure below is BANK REVENUE (fees + margin), not transaction flow -- "
        "converted via the named, sourced yield/intensity assumptions in `config/assumptions.yaml`. "
        "`tam_zar` = estimated total addressable wallet for that sub-component (all banks); "
        "`captured_zar` = Syn Bank's own revenue, computed from internal ledgers using the SAME yield. "
        "A blank `captured_zar` means the captured side is structurally unobservable from the provided "
        "data (not zero) -- see the `note` column and METHODOLOGY.md Phase 4 section."
    )
    lines.append("")

    lines.append("## Portfolio-level: total TAM and captured revenue by pillar (R millions)\n")
    pivot = df.groupby("pillar").agg(
        tam_R_m=("tam_zar", lambda s: s.dropna().sum() / 1e6),
        captured_R_m=("captured_zar", lambda s: s.dropna().sum() / 1e6),
    ).reset_index()
    pivot["share_of_wallet"] = (pivot["captured_R_m"] / pivot["tam_R_m"]).map(lambda x: f"{x:.1%}" if pd.notna(x) else "n/a")
    pivot["tam_R_m"] = pivot["tam_R_m"].round(1)
    pivot["captured_R_m"] = pivot["captured_R_m"].round(1)
    lines.append(pivot.to_markdown(index=False))

    total_tam = df["tam_zar"].dropna().sum() / 1e6
    total_captured = df["captured_zar"].dropna().sum() / 1e6
    lines.append(
        f"\n**Portfolio total (sum of observable sub-components): TAM R{total_tam:,.1f}m, "
        f"captured R{total_captured:,.1f}m, blended share {total_captured/total_tam:.1%}.** "
        "This blend only sums sub-components where both sides are observable -- rate_hedging and "
        "debt_arrangement's captured legs are excluded from this sum, not treated as R0 capture."
    )

    lines.append("\n## Per-entity summary (R millions, sum across observable sub-components)\n")
    ent_summary = df.groupby(["entity_id", "entity_name", "sector"]).agg(
        tam_R_m=("tam_zar", lambda s: s.dropna().sum() / 1e6),
        captured_R_m=("captured_zar", lambda s: s.dropna().sum() / 1e6),
    ).reset_index()
    ent_summary["share_of_wallet"] = (ent_summary["captured_R_m"] / ent_summary["tam_R_m"])
    ent_summary = ent_summary.sort_values("tam_R_m", ascending=False)
    ent_summary["tam_R_m"] = ent_summary["tam_R_m"].round(1)
    ent_summary["captured_R_m"] = ent_summary["captured_R_m"].round(1)
    ent_summary["share_of_wallet"] = ent_summary["share_of_wallet"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "n/a")
    lines.append(ent_summary.to_markdown(index=False))

    breaches = df[df["tam_assumption_breach"]]
    if len(breaches):
        lines.append(
            f"\n## ⚠ TAM assumption breaches ({len(breaches)} sub-component row(s))\n\n"
            "Captured revenue exceeding the estimated TAM is logically impossible for a genuine "
            "total-addressable-market figure -- it means the TAM assumption is demonstrably too "
            "conservative for that entity (directly-observed captured revenue beating what the "
            "assumption predicts for the WHOLE market), not that Syn Bank captured >100% of a real "
            "market. Not clipped to 100% -- that would hide the signal. See METHODOLOGY.md Phase 4 "
            "section.\n"
        )
        b = breaches[["entity_id", "entity_name", "pillar", "sub_component", "tam_zar", "captured_zar", "share_of_wallet"]].copy()
        b["tam_zar"] = b["tam_zar"].map(lambda x: f"{x:,.0f}")
        b["captured_zar"] = b["captured_zar"].map(lambda x: f"{x:,.0f}")
        b["share_of_wallet"] = b["share_of_wallet"].map(lambda x: f"{x:.1%}")
        lines.append(b.to_markdown(index=False))

    global_majors = sorted(set(GLOBAL_MAJOR_ENTITIES) & set(df["entity_id"]))
    if global_majors:
        names = ", ".join(f"{e} ({EXPECTED_ENTITIES[e]['name']})" for e in global_majors)
        lines.append(
            "\n## ⚠ Reading \"share of wallet\" for dual-listed global majors\n\n"
            f"{names} are dual-listed (JSE plus a primary global exchange) and Phase 3's `total_revenue` "
            "for them is the company's ENTIRE GLOBAL revenue, not a South-Africa-specific figure -- "
            "there is no clean external split of \"SA-related banking activity\" vs. \"rest of the "
            "world\" available in the source data. Every TAM figure above for these entities is "
            "therefore an upper bound on a global scale, not a realistic addressable market for a "
            "SA-focused bank -- their unusually LOW share-of-wallet numbers reflect an inflated "
            "denominator (global treasury mandates Syn Bank was never competing for), not necessarily "
            "a large realistic growth opportunity. Phase 6's opportunity ranking should discount or "
            "separately flag these entities rather than rank them purely on raw wallet-gap size."
        )

    lines.append("\n## Full sub-component detail\n")
    detail = df[["entity_id", "entity_name", "pillar", "sub_component", "tam_zar", "captured_zar", "share_of_wallet", "note"]].copy()
    detail["tam_zar"] = detail["tam_zar"].map(lambda x: f"{x:,.0f}" if pd.notna(x) else "")
    detail["captured_zar"] = detail["captured_zar"].map(lambda x: f"{x:,.0f}" if pd.notna(x) else "")
    detail["share_of_wallet"] = detail["share_of_wallet"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "")
    lines.append(detail.to_markdown(index=False))

    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> pd.DataFrame:
    configure_logging()
    ensure_dirs()

    df = build_wallet_model()
    df.to_parquet(OUTPUT_PARQUET, index=False)
    logger.info("Wrote %s (%d rows)", OUTPUT_PARQUET, len(df))

    report = render_markdown(df)
    OUTPUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUTPUT_REPORT_MD)

    total_tam = df["tam_zar"].dropna().sum() / 1e6
    total_captured = df["captured_zar"].dropna().sum() / 1e6
    logger.info("Portfolio: TAM R%.1fm, captured R%.1fm, blended share %.1f%%", total_tam, total_captured, total_captured / total_tam * 100)

    return df


if __name__ == "__main__":
    main()
