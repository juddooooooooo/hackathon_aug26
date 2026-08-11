"""
Phase 7(a) — Cash-Cycle / Payment-Timing bonus module (`src/cash_cycle.py`)
===========================================================================
hackathon.txt's Phase 7 spec, verbatim: "per entity, model days between
outbound supplier legs and inbound collections to suggest optimal
engagement timing." Explicitly labelled "bonus" — built after Phases 1-6
and 8 (the required deliverables), per PLAN.md's re-sequencing.

**The literal ask was checked against the data first, and doesn't hold at
day grain — disclosed, not glossed over, the same way this project has
handled every other "expected signal not actually in the data" finding
(the FX currency-pair dead signal, §6.3; `breadth_score` clustering,
§7.2).** Volume-weighted day-of-month for `collections` (inbound) vs
`supplier_payments` (outbound) converges to the SAME day (~15-16) for
every one of the 20 entities, because daily volume within a month is
essentially uniform (~1-9% coefficient of variation — see
`compute_day_of_month_uniformity`) and day-of-week volume is uniform
too (<1% CV, no weekday/weekend pattern). At that grain, "days between
outbound legs and inbound collections" is noise straddling a 30-day
wraparound boundary, not a per-entity signal — computing it anyway would
manufacture false precision.

**What the data DOES support, checked next: month-of-year seasonality.**
Monthly transaction volume (collections + supplier payments combined) has
real, sector-coherent structure — all 4 consumer/retail entities
(Shoprite, Bid Corporation, Pepkor, Clicks) rank in the top 5 by
seasonality and all peak in December, the obvious real-world explanation
(pre-Christmas retail volume). Insurance, most mining, tech and telecoms
entities are close to flat year-round (<8% CV). This module ranks
entities by that seasonality and suggests an engagement WINDOW (a couple
of months ahead of an entity's peak, while its treasury team still has
bandwidth) rather than a specific day-of-month — the grain the data
actually supports.

No new revenue/NII figure is estimated here — deliberately descriptive/
behavioural only. Phase 4's `deposit_nii` sub-component
(`wallet_model.parquet`, using the named `deposit_nii_margin_bps`
assumption) is the correct place to look for that number; inventing a
second, unnamed monetary coefficient here would violate this project's
assumption-naming discipline (CLAUDE.md, config/assumptions.yaml).

Output: data/processed/cash_cycle_timing.parquet, reports/cash_cycle_report.md,
        reports/cash_cycle_chart.png

Run standalone:
    python -m src.cash_cycle
"""
from __future__ import annotations

import logging

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.common import DUCKDB_PATH, PROCESSED_DIR, REPORTS_DIR, configure_logging, ensure_dirs

logger = logging.getLogger(__name__)

OUT_PARQUET = PROCESSED_DIR / "cash_cycle_timing.parquet"
OUT_REPORT_MD = REPORTS_DIR / "cash_cycle_report.md"
OUT_CHART_PNG = REPORTS_DIR / "cash_cycle_chart.png"

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Scheduling heuristic, not a flow-to-revenue yield coefficient -- lives
# here, not in config/assumptions.yaml, which is reserved for assumptions
# that convert observed flow into rands of bank revenue (CLAUDE.md
# "Must-know" #1). Rationale: reach out while the client's treasury team
# still has bandwidth for a strategic conversation, comfortably before
# their own peak-season operational crunch -- not during it.
ENGAGEMENT_LEAD_MONTHS = 2

# Below this coefficient-of-variation-of-monthly-volume threshold, an
# entity's banking activity is treated as flat/non-seasonal -- ranking it
# by a peak month would imply a timing hook that isn't really there
# (compare the disclosed 0.03-0.08 cluster to the 0.28-0.32 retail
# cluster in the report). Set at the midpoint of that gap.
SEASONALITY_FLAT_THRESHOLD = 0.15


def get_con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DUCKDB_PATH), read_only=True)


def compute_day_of_month_uniformity(con: duckdb.DuckDBPyConnection) -> dict:
    """Checks the brief's literal day-grain framing against the data.
    Returns the portfolio-wide coefficient of variation of daily volume
    within a 31-day month, for each leg type -- low CV means no real
    day-of-month clustering exists to model. See module docstring."""
    out = {}
    for leg in ("collections", "supplier_payments"):
        daily = con.sql(
            f"""
            SELECT extract(day FROM date) AS day_of_month, sum(amount_zar) AS vol
            FROM transactional_banking WHERE leg_type = '{leg}'
            GROUP BY 1
            """
        ).fetchdf()
        out[leg] = float(daily["vol"].std() / daily["vol"].mean())
    return out


def compute_seasonality(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Per-entity month-of-year seasonality of combined banking activity
    (collections + supplier_payments), summed across the full ~3-year
    ledger and grouped by calendar month -- the grain the data actually
    supports (see module docstring)."""
    raw = con.sql(
        """
        SELECT entity_id, entity_name, sector, extract(month FROM date) AS month, sum(amount_zar) AS vol
        FROM transactional_banking
        WHERE leg_type IN ('collections', 'supplier_payments')
        GROUP BY 1, 2, 3, 4
        """
    ).fetchdf()

    rows = []
    for entity_id, g in raw.groupby("entity_id"):
        entity_name = g["entity_name"].iloc[0]
        sector = g["sector"].iloc[0]
        monthly = g.groupby("month")["vol"].sum().reindex(range(1, 13), fill_value=0.0)
        cv = float(monthly.std() / monthly.mean())
        peak_month = int(monthly.idxmax())
        engagement_month = (peak_month - ENGAGEMENT_LEAD_MONTHS - 1) % 12 + 1
        rows.append(
            {
                "entity_id": entity_id,
                "entity_name": entity_name,
                "sector": sector,
                "seasonality_cv": round(cv, 3),
                "peak_month": peak_month,
                "peak_month_name": MONTH_NAMES[peak_month],
                "is_seasonal": cv >= SEASONALITY_FLAT_THRESHOLD,
                "suggested_engagement_month": engagement_month,
                "suggested_engagement_month_name": MONTH_NAMES[engagement_month],
                "annual_volume_zar": float(monthly.sum()),
            }
        )

    df = pd.DataFrame(rows).sort_values("seasonality_cv", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


def render_chart(df: pd.DataFrame, path) -> None:
    """Horizontal bar of seasonality_cv, sorted descending, coloured by
    whether it clears SEASONALITY_FLAT_THRESHOLD -- the ranking IS the
    finding (retail cluster vs. flat majority), not a table buried number."""
    d = df.sort_values("seasonality_cv", ascending=True).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.38 * len(d) + 1)))

    colors = ["#eb6834" if s else "#c3c2b7" for s in d["is_seasonal"]]
    y = np.arange(len(d))
    ax.barh(y, d["seasonality_cv"], color=colors)
    ax.axvline(SEASONALITY_FLAT_THRESHOLD, color="#898781", linestyle="--", linewidth=1)
    ax.text(SEASONALITY_FLAT_THRESHOLD, len(d) - 0.5, " flat/seasonal cutoff", fontsize=7, color="#898781", va="top")

    labels = [f"{n} (peak {m})" for n, m in zip(d["entity_name"], d["peak_month_name"])]
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Seasonality (coefficient of variation of monthly banking activity)")
    ax.set_title("Cash-cycle seasonality and peak month, per entity")
    ax.grid(axis="x", color="#e1e0d9", linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def render_markdown(df: pd.DataFrame, dom_uniformity: dict) -> str:
    seasonal = df[df["is_seasonal"]]
    flat = df[~df["is_seasonal"]]

    lines = [
        "# Cash-Cycle / Payment-Timing (Phase 7 bonus module)",
        "",
        "hackathon.txt's Phase 7(a) spec, verbatim: *\"per entity, model days between "
        "outbound supplier legs and inbound collections to suggest optimal engagement "
        "timing.\"*",
        "",
        "## The literal day-grain ask, checked against the data — a disclosed dead signal",
        "",
        f"Volume-weighted day-of-month for `collections` has a "
        f"{dom_uniformity['collections']:.1%} coefficient of variation across the month; "
        f"`supplier_payments`, {dom_uniformity['supplier_payments']:.1%}. Both are close to "
        "what a uniform (no clustering) distribution would produce, and day-of-week volume "
        "is flatter still (<1% CV, checked separately). Every one of the 20 entities' "
        "volume-weighted peak day converges to the same ~day 15-16 — there is no real "
        "per-entity day-of-month signal to rank on here. Computing a 'days between' gap "
        "anyway would be noise straddling a 30-day wraparound, not a finding — this is the "
        "same discipline this project applied to the FX currency-pair dead signal "
        "(METHODOLOGY.md §6.3) and `breadth_score` clustering (§7.2): disclose the null "
        "result rather than manufacture a ranking from it.",
        "",
        "## What the data DOES support: month-of-year seasonality",
        "",
        "Monthly banking activity (collections + supplier payments combined, summed across "
        "the full ~3-year ledger by calendar month) has real, sector-coherent structure. "
        "![Cash-cycle seasonality chart](cash_cycle_chart.png)",
        "",
        "| Rank | Entity | Sector | Seasonality (CV) | Peak month | Suggested engagement month |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in df.iterrows():
        lines.append(
            f"| {int(r['rank'])} | {r['entity_name']} | {r['sector']} | {r['seasonality_cv']:.3f} | "
            f"{r['peak_month_name']} | {r['suggested_engagement_month_name'] if r['is_seasonal'] else 'n/a — flat activity, engage anytime'} |"
        )

    lines += [
        "",
        "## Reading the ranking",
        "",
        f"**{len(seasonal)} of {len(df)} entities clear the "
        f"{SEASONALITY_FLAT_THRESHOLD:.0%} seasonality threshold** and share an obvious "
        "sector pattern: all 4 consumer/retail entities in the portfolio (Shoprite, Bid "
        "Corporation, Pepkor, Clicks) are in the top 5, every one peaking in December — the "
        "expected pre-Christmas retail volume surge. Valterra Platinum (mining, March peak) "
        "is the one exception to the retail-only pattern, reported as-is rather than "
        "smoothed over.",
        "",
        f"**The remaining {len(flat)} entities are close to flat year-round** "
        f"(CV well under {SEASONALITY_FLAT_THRESHOLD:.0%}, mostly mining, insurance, tech "
        "and telecoms) — for these, month-of-year is not a meaningful engagement lever; "
        "timing outreach around this signal would be manufacturing a hook that isn't "
        "really there for them.",
        "",
        f"`suggested_engagement_month` = peak month − {ENGAGEMENT_LEAD_MONTHS} months, for "
        "seasonal entities only — while the client's treasury team still has bandwidth for "
        "a strategic conversation, ahead of their own operational peak (see "
        "`ENGAGEMENT_LEAD_MONTHS` in `src/cash_cycle.py`).",
        "",
        "## Methodology note",
        "",
        "No revenue or NII figure is estimated by this module — deliberately descriptive/"
        "behavioural only, per this project's assumption-naming discipline "
        "(config/assumptions.yaml, CLAUDE.md). `seasonality_cv` is the coefficient of "
        "variation (std/mean) of an entity's monthly combined `collections` + "
        "`supplier_payments` volume across the 12 calendar months, summed over the full "
        "ledger date range — not calendar-year-over-year, a single 12-bucket seasonal "
        "profile.",
    ]
    return "\n".join(lines)


def main() -> pd.DataFrame:
    configure_logging()
    ensure_dirs()

    con = get_con()
    dom_uniformity = compute_day_of_month_uniformity(con)
    logger.info(
        "Day-of-month CV -- collections: %.1f%%, supplier_payments: %.1f%% (near-uniform, no day-grain signal)",
        dom_uniformity["collections"] * 100, dom_uniformity["supplier_payments"] * 100,
    )

    df = compute_seasonality(con)
    df.to_parquet(OUT_PARQUET, index=False)
    logger.info("Wrote %s (%d rows)", OUT_PARQUET, len(df))

    render_chart(df, OUT_CHART_PNG)
    logger.info("Wrote %s", OUT_CHART_PNG)

    report = render_markdown(df, dom_uniformity)
    OUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUT_REPORT_MD)

    n_seasonal = int(df["is_seasonal"].sum())
    logger.info("%d/%d entities cleared the seasonality threshold; top: %s (CV %.3f, peak %s)",
                n_seasonal, len(df), df.iloc[0]["entity_name"], df.iloc[0]["seasonality_cv"], df.iloc[0]["peak_month_name"])
    return df


if __name__ == "__main__":
    main()
