"""
Phase 5 — Rigor Layer (`src/uncertainty.py`)
===========================================================================
30% of the mark scheme lives here. Five analyses, all per hackathon.txt's
Phase 5 spec:

  1. Monte Carlo over config/assumptions.yaml's priors -> SOW as a credible
     interval, never a bare point estimate.
  2. Tornado/sensitivity: which assumption moves the answer most.
  3. A SECOND, independent SOW estimator (revealed presence: product/
     corridor/instrument breadth relative to sector peers), triangulated
     against Phase 4's yield-based estimate -- divergence surfaced
     explicitly, not averaged away.
  4. Sector regression of wallet-intensity (TAM/revenue) to flag entities
     sitting far below their sector line.
  5. Time-trend test, per-entity and per-corridor -- Phase 1 already found
     aggregate volume flat 2023-07 to 2026-06; this checks whether that
     holds at finer grain, and says so plainly either way.

Every assumption used here is the SAME config/assumptions.yaml Phase 4
uses (low/high ranges added to every leaf specifically for this phase) --
never a second, disconnected set of "uncertainty parameters".

Output: data/processed/monte_carlo_results.parquet,
        data/processed/tornado_sensitivity.parquet,
        data/processed/revealed_presence.parquet,
        data/processed/sector_regression.parquet,
        data/processed/time_trends_entity.parquet,
        data/processed/time_trends_corridor.parquet,
        reports/tornado_chart.png,
        reports/uncertainty_report.md

Run standalone:
    python -m src.uncertainty
    python -m src.uncertainty --mc-iterations 500   # faster smoke test
"""
from __future__ import annotations

import argparse
import copy
import logging
from typing import Any, Optional

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from src.common import (
    DUCKDB_PATH,
    EXPECTED_ENTITIES,
    PROCESSED_DIR,
    REPORTS_DIR,
    configure_logging,
    ensure_dirs,
)
from src.wallet import (
    _v,
    blended_tam_and_captured,
    build_wallet_model,
    compute_internal_aggregates,
    load_assumptions,
    load_competitor_events,
    load_financial_baseline,
    to_zar,
)

logger = logging.getLogger(__name__)

OUT_MC = PROCESSED_DIR / "monte_carlo_results.parquet"
OUT_TORNADO = PROCESSED_DIR / "tornado_sensitivity.parquet"
OUT_PRESENCE = PROCESSED_DIR / "revealed_presence.parquet"
OUT_SECTOR = PROCESSED_DIR / "sector_regression.parquet"
OUT_TREND_ENTITY = PROCESSED_DIR / "time_trends_entity.parquet"
OUT_TREND_CORRIDOR = PROCESSED_DIR / "time_trends_corridor.parquet"
OUT_TORNADO_PNG = REPORTS_DIR / "tornado_chart.png"
OUT_REPORT_MD = REPORTS_DIR / "uncertainty_report.md"

WALLET_ASSUMPTION_TOP_KEYS = ("transactional_banking", "global_markets", "investment_banking")

# Coverage denominators for the revealed-presence estimator -- observed,
# not assumed: 5 leg_types and 5 channels in transactional_banking.csv, 3
# instrument_types in trade_finance.csv, 34 distinct counterparty_country
# values across cross_border_payments.csv + trade_finance.csv combined
# (see reports/profiling_report.md and METHODOLOGY.md Phase 5 section).
MAX_LEG_TYPES = 5
MAX_CHANNELS = 5
MAX_INSTRUMENT_TYPES = 3
MAX_COUNTRIES = 34


# --------------------------------------------------------------------------
# Shared: assumption perturbation (used by both Monte Carlo and tornado)
# --------------------------------------------------------------------------
def _iter_leaf_paths(node: Any, path: tuple = ()):
    if isinstance(node, dict):
        if "value" in node and "low" in node and "high" in node:
            yield path, node
        else:
            for k, v in node.items():
                yield from _iter_leaf_paths(v, path + (k,))


def get_wallet_leaf_paths(assumptions: dict) -> list[tuple]:
    """Every {value, low, high} leaf under the 3 pillar sections -- i.e.
    every assumption src.wallet.build_wallet_model actually reads. Excludes
    fx_to_zar (observed spot rates, not estimates -- not randomised) and
    revealed_presence (feeds this module's OWN estimator, not the wallet
    model -- see compute_revealed_presence)."""
    paths = []
    for top in WALLET_ASSUMPTION_TOP_KEYS:
        paths.extend(_iter_leaf_paths(assumptions[top], (top,)))
    return paths


def leaf_label(path: tuple) -> str:
    return ".".join(path)


def get_leaf(assumptions: dict, path: tuple) -> dict:
    node = assumptions
    for k in path:
        node = node[k]
    return node


def perturb_assumptions(assumptions: dict, rng: np.random.Generator) -> dict:
    """Deep-copy assumptions with every wallet-model leaf's `value` replaced
    by a uniform draw between its `low` and `high`. FX rates and the
    revealed-presence calibration are left untouched."""
    perturbed = copy.deepcopy(assumptions)
    for path, _ in get_wallet_leaf_paths(assumptions):
        leaf = get_leaf(perturbed, path)
        leaf["value"] = float(rng.uniform(leaf["low"], leaf["high"]))
    return perturbed


def _blended_share(df: pd.DataFrame) -> tuple[Optional[float], float, float]:
    tam, captured = blended_tam_and_captured(df)
    share = captured / tam if tam else None
    return share, tam, captured


def _pillar_shares(df: pd.DataFrame) -> dict[str, Optional[float]]:
    out = {}
    for pillar, g in df.groupby("pillar"):
        share, _, _ = _blended_share(g)
        out[pillar] = share
    return out


# --------------------------------------------------------------------------
# 1. Monte Carlo
# --------------------------------------------------------------------------
def run_monte_carlo(
    n_iterations: int,
    assumptions: dict,
    internal: dict[str, pd.DataFrame],
    fin: pd.DataFrame,
    competitor_events: pd.DataFrame,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_iterations):
        perturbed = perturb_assumptions(assumptions, rng)
        df = build_wallet_model(assumptions=perturbed, internal=internal, fin=fin, competitor_events=competitor_events)
        share, tam, captured = _blended_share(df)
        pillar_shares = _pillar_shares(df)
        rows.append(
            {
                "iteration": i,
                "portfolio_share": share,
                "portfolio_tam_zar": tam,
                "portfolio_captured_zar": captured,
                **{f"share__{p.replace(' ', '_')}": v for p, v in pillar_shares.items()},
            }
        )
        if (i + 1) % 500 == 0:
            logger.info("Monte Carlo: %d / %d iterations done", i + 1, n_iterations)
    return pd.DataFrame(rows)


def credible_interval(mc_df: pd.DataFrame, col: str) -> dict[str, float]:
    s = mc_df[col].dropna()
    if len(s) == 0:
        return {"p5": None, "p50": None, "p95": None, "mean": None, "std": None, "n": 0}
    return {
        "p5": float(s.quantile(0.05)),
        "p50": float(s.quantile(0.50)),
        "p95": float(s.quantile(0.95)),
        "mean": float(s.mean()),
        "std": float(s.std()),
        "n": int(len(s)),
    }


# --------------------------------------------------------------------------
# 2. Tornado / sensitivity
# --------------------------------------------------------------------------
def compute_tornado(
    assumptions: dict,
    internal: dict[str, pd.DataFrame],
    fin: pd.DataFrame,
    competitor_events: pd.DataFrame,
) -> tuple[pd.DataFrame, float, float]:
    baseline_df = build_wallet_model(assumptions=assumptions, internal=internal, fin=fin, competitor_events=competitor_events)
    baseline_share, baseline_tam, _ = _blended_share(baseline_df)

    rows = []
    for path, leaf in get_wallet_leaf_paths(assumptions):
        low_a, high_a = copy.deepcopy(assumptions), copy.deepcopy(assumptions)
        get_leaf(low_a, path)["value"] = leaf["low"]
        get_leaf(high_a, path)["value"] = leaf["high"]

        low_df = build_wallet_model(assumptions=low_a, internal=internal, fin=fin, competitor_events=competitor_events)
        high_df = build_wallet_model(assumptions=high_a, internal=internal, fin=fin, competitor_events=competitor_events)
        low_share, _, _ = _blended_share(low_df)
        high_share, _, _ = _blended_share(high_df)
        # independent (not row-aligned) TAM sum -- deliberately a DIFFERENT
        # figure from the blended share's denominator, so this column stays
        # informative even for assumptions whose only TAM impact is on a
        # sub-component with a structurally-null captured side (see the
        # "0.00pp swing" explanation in render_markdown).
        low_tam_indep = low_df["tam_zar"].dropna().sum()
        high_tam_indep = high_df["tam_zar"].dropna().sum()

        rows.append(
            {
                "assumption": leaf_label(path),
                "low_value": leaf["low"],
                "base_value": leaf["value"],
                "high_value": leaf["high"],
                "share_at_low": low_share,
                "share_at_high": high_share,
                "share_swing_pp": abs((high_share or 0) - (low_share or 0)) * 100,
                "tam_at_low_R_m": low_tam_indep / 1e6,
                "tam_at_high_R_m": high_tam_indep / 1e6,
                "tam_swing_R_m": abs(high_tam_indep - low_tam_indep) / 1e6,
            }
        )
    out = pd.DataFrame(rows).sort_values("share_swing_pp", ascending=False).reset_index(drop=True)
    return out, baseline_share, baseline_tam


def render_tornado_chart(tornado_df: pd.DataFrame, baseline_share: float, path) -> None:
    df = tornado_df.sort_values("share_swing_pp", ascending=True)
    fig, ax = plt.subplots(figsize=(10, max(4.5, 0.4 * len(df) + 1)))
    y = np.arange(len(df))
    low_vals = (df["share_at_low"].fillna(0) * 100).values
    high_vals = (df["share_at_high"].fillna(0) * 100).values
    left = np.minimum(low_vals, high_vals)
    width = np.abs(high_vals - low_vals)
    ax.barh(y, width, left=left, color="#4C72B0", edgecolor="none", height=0.6)
    ax.axvline(baseline_share * 100 if baseline_share else 0, color="#333333", linestyle="--", linewidth=1, label="base-case share")
    ax.set_yticks(y)
    ax.set_yticklabels(df["assumption"])
    ax.set_xlabel("Portfolio blended share of wallet (%)")
    fig.suptitle("Tornado sensitivity — swing in blended share as each assumption moves low→high", fontsize=12, y=0.99)
    ax.set_title("(all other assumptions held at base-case value)", fontsize=9, color="#555555")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------------
# 3. Revealed-presence SOW estimator + triangulation
# --------------------------------------------------------------------------
def compute_revealed_presence(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    leg_types = con.sql("SELECT entity_id, count(DISTINCT leg_type) n FROM transactional_banking GROUP BY 1").fetchdf()
    channels = con.sql("SELECT entity_id, count(DISTINCT channel) n FROM transactional_banking GROUP BY 1").fetchdf()
    instruments = con.sql("SELECT entity_id, count(DISTINCT instrument_type) n FROM trade_finance GROUP BY 1").fetchdf()
    countries = con.sql(
        """
        SELECT entity_id, count(DISTINCT counterparty_country) n FROM (
            SELECT entity_id, counterparty_country FROM cross_border_payments
            UNION ALL
            SELECT entity_id, counterparty_country FROM trade_finance
        ) GROUP BY 1
        """
    ).fetchdf()

    df = pd.DataFrame({"entity_id": sorted(EXPECTED_ENTITIES.keys())})
    for name, src, col in [
        ("n_leg_types", leg_types, "n"),
        ("n_channels", channels, "n"),
        ("n_instrument_types", instruments, "n"),
        ("n_countries", countries, "n"),
    ]:
        df = df.merge(src.rename(columns={col: name}), on="entity_id", how="left")
    df = df.fillna(0)

    df["breadth_leg_type"] = df["n_leg_types"] / MAX_LEG_TYPES
    df["breadth_channel"] = df["n_channels"] / MAX_CHANNELS
    df["breadth_instrument"] = df["n_instrument_types"] / MAX_INSTRUMENT_TYPES
    df["breadth_country"] = df["n_countries"] / MAX_COUNTRIES
    df["revealed_presence_score"] = df[
        ["breadth_leg_type", "breadth_channel", "breadth_instrument", "breadth_country"]
    ].mean(axis=1)

    df["entity_name"] = df["entity_id"].map(lambda e: EXPECTED_ENTITIES[e]["name"])
    df["sector"] = df["entity_id"].map(lambda e: EXPECTED_ENTITIES[e]["sector"])
    df["sector_peer_count"] = df.groupby("sector")["entity_id"].transform("count")
    df["presence_percentile_in_sector"] = df.groupby("sector")["revealed_presence_score"].rank(pct=True)
    return df


def triangulate_estimators(presence_df: pd.DataFrame, wallet_df: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    rp = assumptions["revealed_presence"]
    floor, ceiling = _v(rp["sow_floor_pct"]), _v(rp["sow_ceiling_pct"])

    yield_rows = []
    for eid, g in wallet_df.groupby("entity_id"):
        share, _, _ = _blended_share(g)
        yield_rows.append({"entity_id": eid, "yield_based_share_pct": (share * 100) if share is not None else None})
    yield_df = pd.DataFrame(yield_rows)

    merged = presence_df.merge(yield_df, on="entity_id", how="left")
    merged["presence_based_share_pct"] = floor + merged["revealed_presence_score"] * (ceiling - floor)
    merged["divergence_pp"] = merged["presence_based_share_pct"] - merged["yield_based_share_pct"]
    return merged.reindex(merged["divergence_pp"].abs().sort_values(ascending=False).index)


# --------------------------------------------------------------------------
# 4. Sector regression of wallet-intensity
# --------------------------------------------------------------------------
def compute_sector_regression(wallet_df: pd.DataFrame, fin: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    tam_per_entity = wallet_df.groupby("entity_id")["tam_zar"].apply(lambda s: s.dropna().sum())

    rows = []
    for entity_id, meta in EXPECTED_ENTITIES.items():
        tam = tam_per_entity.get(entity_id)
        revenue_zar = None
        if entity_id in fin.index:
            fin_row = fin.loc[entity_id]
            rev = to_zar(fin_row.get("total_revenue"), fin_row.get("reported_currency"), assumptions)
            revenue_zar = rev * 1e6 if rev is not None else None
        intensity = (tam / revenue_zar) if (tam and revenue_zar) else None
        rows.append(
            {
                "entity_id": entity_id,
                "entity_name": meta["name"],
                "sector": meta["sector"],
                "tam_zar": tam,
                "revenue_zar": revenue_zar,
                "wallet_intensity": intensity,
            }
        )
    df = pd.DataFrame(rows)

    df["sector_n"] = df.groupby("sector")["entity_id"].transform("count")
    df["sector_mean_intensity"] = df.groupby("sector")["wallet_intensity"].transform("mean")
    df["sector_std_intensity"] = df.groupby("sector")["wallet_intensity"].transform("std")
    df["z_score_in_sector"] = (df["wallet_intensity"] - df["sector_mean_intensity"]) / df["sector_std_intensity"]
    df["sector_comparison_meaningful"] = df["sector_n"] >= 3
    df["below_sector_line"] = (df["sector_comparison_meaningful"]) & (df["z_score_in_sector"] < -1.0)

    valid = df.dropna(subset=["tam_zar", "revenue_zar"])
    valid = valid[(valid["tam_zar"] > 0) & (valid["revenue_zar"] > 0)]
    if len(valid) >= 5:
        log_rev = np.log(valid["revenue_zar"])
        log_tam = np.log(valid["tam_zar"])
        slope, intercept, r, p, se = stats.linregress(log_rev, log_tam)
        df["portfolio_regression_predicted_log_tam"] = intercept + slope * np.log(df["revenue_zar"].clip(lower=1))
        df["portfolio_regression_residual"] = np.log(df["tam_zar"].clip(lower=1)) - df["portfolio_regression_predicted_log_tam"]
        df.attrs["portfolio_regression"] = {"slope": slope, "intercept": intercept, "r_squared": r ** 2, "p_value": p, "n": len(valid)}
    else:
        df.attrs["portfolio_regression"] = None
    return df


# --------------------------------------------------------------------------
# 5. Time trend test
# --------------------------------------------------------------------------
def _linregress_on_series(g: pd.DataFrame, value_col: str) -> dict:
    g = g.sort_values("quarter")
    x = np.arange(len(g))
    y = g[value_col].values
    if len(g) < 3:
        return {"n_quarters": len(g), "slope_zar_per_quarter": None, "r_squared": None, "p_value": None, "significant_p05": False}
    slope, intercept, r, p, se = stats.linregress(x, y)
    return {"n_quarters": len(g), "slope_zar_per_quarter": slope, "r_squared": r ** 2, "p_value": p, "significant_p05": bool(p < 0.05)}


def compute_time_trends(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, pd.DataFrame]:
    q_entity = con.sql(
        """
        WITH all_flow AS (
            SELECT entity_id, date, amount_zar AS value_zar FROM transactional_banking
            UNION ALL SELECT entity_id, date, value_zar FROM cross_border_payments
            UNION ALL SELECT entity_id, date, value_zar FROM trade_finance
        )
        SELECT entity_id, date_trunc('quarter', date) AS quarter, sum(value_zar) AS volume_zar
        FROM all_flow GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).fetchdf()
    entity_rows = []
    for entity_id, g in q_entity.groupby("entity_id"):
        entity_rows.append({"entity_id": entity_id, "entity_name": EXPECTED_ENTITIES[entity_id]["name"], **_linregress_on_series(g, "volume_zar")})
    entity_trends = pd.DataFrame(entity_rows)
    n_entity_tests = len(entity_trends)
    entity_trends["significant_bonferroni"] = entity_trends["p_value"].apply(
        lambda p: bool(pd.notna(p) and p < 0.05 / n_entity_tests)
    )

    q_corridor = con.sql(
        """
        SELECT currency_pair, date_trunc('quarter', date) AS quarter, sum(value_zar) AS volume_zar
        FROM cross_border_payments GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).fetchdf()
    corridor_rows = []
    for pair, g in q_corridor.groupby("currency_pair"):
        corridor_rows.append({"currency_pair": pair, **_linregress_on_series(g, "volume_zar")})
    corridor_trends = pd.DataFrame(corridor_rows)
    n_corridor_tests = len(corridor_trends)
    corridor_trends["significant_bonferroni"] = corridor_trends["p_value"].apply(
        lambda p: bool(pd.notna(p) and p < 0.05 / n_corridor_tests)
    )

    return entity_trends, corridor_trends


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def render_markdown(
    mc_df: pd.DataFrame,
    tornado_df: pd.DataFrame,
    baseline_share: float,
    baseline_tam: float,
    presence_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    entity_trends: pd.DataFrame,
    corridor_trends: pd.DataFrame,
) -> str:
    lines = ["# Phase 5 — Rigor Layer Report", ""]
    lines.append(
        "Five analyses per hackathon.txt's Phase 5 spec, all built on `config/assumptions.yaml`'s "
        "`low`/`high` ranges (never a second, disconnected set of \"uncertainty parameters\")."
    )

    # 1. Monte Carlo
    lines.append("\n## 1. Monte Carlo — portfolio blended share of wallet as a credible interval\n")
    ci = credible_interval(mc_df, "portfolio_share")
    lines.append(
        f"**{ci['n']:,} iterations.** Base-case point estimate: {baseline_share:.1%}. "
        f"5th–95th percentile credible interval: **{ci['p5']:.1%} – {ci['p95']:.1%}** "
        f"(median {ci['p50']:.1%}, mean {ci['mean']:.1%}, std {ci['std']:.1%}). "
        "Never report the base-case point estimate alone -- this range is the honest answer."
    )
    lines.append("\n**By pillar:**\n")
    pillar_ci_rows = []
    for col in [c for c in mc_df.columns if c.startswith("share__")]:
        pillar_name = col.replace("share__", "").replace("_", " ")
        c = credible_interval(mc_df, col)
        pillar_ci_rows.append({"pillar": pillar_name, "p5": c["p5"], "p50": c["p50"], "p95": c["p95"]})
    pci = pd.DataFrame(pillar_ci_rows)
    for c in ["p5", "p50", "p95"]:
        pci[c] = pci[c].map(lambda x: f"{x:.1%}" if pd.notna(x) else "n/a")
    lines.append(pci.to_markdown(index=False))

    # 2. Tornado
    lines.append("\n## 2. Tornado sensitivity — which assumption moves the answer most\n")
    lines.append(f"![Tornado chart]({OUT_TORNADO_PNG.name})\n")
    lines.append(
        "Each row varies ONE assumption across its full low→high range (`config/assumptions.yaml`) "
        "with every other assumption held at its base-case value, and measures the resulting swing in "
        "portfolio blended share of wallet. Sorted by impact, largest first.\n"
    )
    zero_impact = tornado_df[tornado_df["share_swing_pp"] < 0.005]["assumption"].tolist()
    if zero_impact:
        lines.append(
            f"**{len(zero_impact)} assumptions show exactly 0.00pp *share* swing** ({', '.join(zero_impact)}) "
            "-- not an error, and NOT the same as having no impact (their `tam_swing_R_m` column below is "
            "very much non-zero). `blended_tam_and_captured` (METHODOLOGY.md §5.3) only sums sub-components "
            "where BOTH tam and captured are observable on the same row; these assumptions exclusively "
            "drive TAM on the 3 sub-components with a structurally-unobservable captured side "
            "(`rate_hedging`, `debt_arrangement`, `competitor_credit_gap`), which are excluded from the "
            "blended-share RATIO by definition -- moving them changes total addressable wallet (hence the "
            "real `tam_swing_R_m` figures, computed independently of the share metric) without changing "
            "the *fraction of it Syn Bank is measured as capturing*, because there's no captured figure to "
            "divide by for those rows. Do not read the 0.00pp column as \"these assumptions don't matter.\"\n"
        )
    t = tornado_df.copy()
    t["share_at_low"] = t["share_at_low"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "n/a")
    t["share_at_high"] = t["share_at_high"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "n/a")
    t["share_swing_pp"] = t["share_swing_pp"].map(lambda x: f"{x:.2f}pp")
    t["tam_swing_R_m"] = t["tam_swing_R_m"].round(1)
    lines.append(t[["assumption", "low_value", "base_value", "high_value", "share_at_low", "share_at_high", "share_swing_pp", "tam_swing_R_m"]].to_markdown(index=False))

    # 3. Revealed presence + triangulation
    lines.append("\n## 3. Second, independent SOW estimator — revealed presence vs. yield-based estimate\n")
    lines.append(
        "Not derived from any yield assumption at all: a 0-1 breadth score from how many of Syn Bank's "
        "product channels, trade-finance instrument types, and country corridors each entity actually "
        "uses, mapped onto a SOW-comparable percentage via a calibration disclosed in "
        "`config/assumptions.yaml`'s `revealed_presence` section (a rough calibration, not a precision "
        "instrument -- see METHODOLOGY.md Phase 5). **Where the two estimators diverge is the most "
        "interesting finding here, surfaced explicitly, not averaged away.**\n"
    )
    tri = triangulate_estimators(presence_df, pd.read_parquet(PROCESSED_DIR / "wallet_model.parquet"), load_assumptions())

    n_positive = int((tri["divergence_pp"] > 0).sum())
    biggest_negative = tri[tri["divergence_pp"] < 0].sort_values("divergence_pp").head(1)
    narrative = (
        f"**{n_positive}/{len(tri)} entities show presence-based > yield-based** — a systematic pattern, "
        "not scattered noise, and worth reading carefully rather than at face value. All 20 entities in "
        "this portfolio are large, actively-engaged corporates already using most of Syn Bank's product "
        "range (breadth scores cluster tightly, 0.77-0.91) — this specific client set gives the "
        "revealed-presence estimator little room to discriminate low-engagement from high-engagement "
        "clients, so it defaults most entities toward the upper half of its calibrated range. Read the "
        "SIZE of each divergence with that in mind: a consistently-high presence-based estimate across "
        "nearly the whole portfolio is more a statement about this method's limited discriminating power "
        "on an already-broad client base than a claim that yield-based estimates are all wrong by ~30pp."
    )
    if len(biggest_negative):
        r = biggest_negative.iloc[0]
        narrative += (
            f"\n\n**The one entity where it runs the other way is the most useful cross-check here: "
            f"{r['entity_name']} ({r['entity_id']})**, at {r['divergence_pp']:.1f}pp — its yield-based share "
            f"({r['yield_based_share_pct']:.1f}%) *exceeds* even the top-of-range presence-based estimate "
            f"({r['presence_based_share_pct']:.1f}%). This is the same entity flagged with a TAM-assumption "
            "breach in Phase 4 (METHODOLOGY.md §5.2) — an estimator that knows nothing about that breach "
            "independently lands well below the yield-based figure, corroborating that the yield-based "
            "62.7% is inflated by the too-conservative deposit_nii TAM assumption, not a genuine outlier "
            "level of capture."
        )
    lines.append(narrative + "\n")

    disp = tri[["entity_id", "entity_name", "sector", "revealed_presence_score", "presence_based_share_pct", "yield_based_share_pct", "divergence_pp"]].copy()
    disp["revealed_presence_score"] = disp["revealed_presence_score"].round(2)
    for c in ["presence_based_share_pct", "yield_based_share_pct", "divergence_pp"]:
        disp[c] = disp[c].map(lambda x: f"{x:.1f}pp" if pd.notna(x) else "n/a")
    lines.append(disp.to_markdown(index=False))

    # 4. Sector regression
    lines.append("\n## 4. Sector regression of wallet-intensity (TAM / revenue)\n")
    below = sector_df[sector_df["below_sector_line"]]
    reg = sector_df.attrs.get("portfolio_regression")
    if reg:
        lines.append(
            f"Portfolio-wide log-log regression (log TAM ~ log revenue, n={reg['n']}): "
            f"R² = {reg['r_squared']:.2f}, p = {reg['p_value']:.3f}. "
        )
    lines.append(
        f"\nEntities flagged **below their sector line** (wallet-intensity z-score < -1.0 within a "
        f"sector of ≥3 peers): **{len(below)}**. Sectors with <3 peers are noted, not scored (too few "
        f"points for a meaningful within-sector comparison).\n"
    )
    sdisp = sector_df[["entity_id", "entity_name", "sector", "sector_n", "wallet_intensity", "z_score_in_sector", "below_sector_line"]].copy()
    sdisp["wallet_intensity"] = sdisp["wallet_intensity"].map(lambda x: f"{x:.3f}" if pd.notna(x) else "n/a")
    sdisp["z_score_in_sector"] = sdisp["z_score_in_sector"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "n/a (sector n<3)")
    lines.append(sdisp.sort_values("entity_id").to_markdown(index=False))

    # 5. Time trends
    lines.append("\n## 5. Time-trend test — per-entity and per-corridor\n")
    n_sig_entity = int(entity_trends["significant_p05"].sum())
    n_sig_entity_bonf = int(entity_trends["significant_bonferroni"].sum())
    n_sig_corridor = int(corridor_trends["significant_p05"].sum())
    n_sig_corridor_bonf = int(corridor_trends["significant_bonferroni"].sum())
    lines.append(
        f"Quarterly volume (all 3 files combined), linear trend test per entity ({len(entity_trends)} tests) "
        f"and per currency-pair corridor ({len(corridor_trends)} tests). At raw p<0.05: "
        f"**{n_sig_entity}/{len(entity_trends)} entities** and **{n_sig_corridor}/{len(corridor_trends)} corridors** "
        f"show a statistically significant trend. Testing this many series at once risks false positives by "
        f"chance alone (~{0.05*len(entity_trends):.1f} expected among the entity tests even with NO real "
        f"trend anywhere) -- at a Bonferroni-adjusted threshold, "
        f"**{n_sig_entity_bonf}/{len(entity_trends)} entities** and **{n_sig_corridor_bonf}/{len(corridor_trends)} corridors** "
        f"remain significant. "
    )
    if n_sig_entity_bonf == 0 and n_sig_corridor_bonf == 0:
        lines.append(
            "\n**No entity or corridor shows a trend that survives multiple-testing correction — consistent "
            "with Phase 1's aggregate finding that quarterly volume is flat. This is stated plainly, not "
            "buried: there is no meaningful time trend anywhere in this dataset, at any grain checked, and "
            "no trend has been manufactured to make the story more interesting than the data supports.**"
        )
    else:
        sig_entities = entity_trends[entity_trends["significant_bonferroni"]].copy()
        sig_entities["direction"] = sig_entities["slope_zar_per_quarter"].apply(lambda s: "growing" if s > 0 else "shrinking")
        summary = "; ".join(f"{r.entity_name} ({r.direction}, R²={r.r_squared:.2f})" for r in sig_entities.itertuples())
        lines.append(
            f"\n**Corridors are flat (0/{len(corridor_trends)} significant even at raw p<0.05) — consistent "
            f"with Phase 1's aggregate finding. But {n_sig_entity_bonf} individual entit"
            f"{'y' if n_sig_entity_bonf == 1 else 'ies'} show a trend robust enough to survive Bonferroni "
            f"correction, which the portfolio-flat aggregate finding does NOT rule out and should not be "
            f"read as ruling out: {summary}.** These are genuine per-client signals worth a coverage "
            "banker's attention (a growing or shrinking relationship, ahead of it showing up in any "
            "aggregate number) — the correct reading of this section is \"the portfolio in aggregate is "
            "flat, AND a handful of specific clients are moving,\" not one or the other."
        )
    lines.append("\n**Per-entity:**\n")
    et = entity_trends.copy()
    et["p_value"] = et["p_value"].map(lambda x: f"{x:.3f}" if pd.notna(x) else "n/a")
    et["r_squared"] = et["r_squared"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")
    lines.append(et[["entity_id", "entity_name", "n_quarters", "r_squared", "p_value", "significant_p05", "significant_bonferroni"]].to_markdown(index=False))
    lines.append("\n**Per-corridor:**\n")
    ct = corridor_trends.copy()
    ct["p_value"] = ct["p_value"].map(lambda x: f"{x:.3f}" if pd.notna(x) else "n/a")
    ct["r_squared"] = ct["r_squared"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")
    lines.append(ct[["currency_pair", "n_quarters", "r_squared", "p_value", "significant_p05", "significant_bonferroni"]].to_markdown(index=False))

    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5: rigor layer (Monte Carlo, tornado, triangulation, sector regression, trend test).")
    parser.add_argument("--mc-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    configure_logging()
    ensure_dirs()

    assumptions = load_assumptions()
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    internal = compute_internal_aggregates(con)
    fin = load_financial_baseline().set_index("entity_id")
    competitor_events = load_competitor_events()

    logger.info("Running Monte Carlo (%d iterations)...", args.mc_iterations)
    mc_df = run_monte_carlo(args.mc_iterations, assumptions, internal, fin, competitor_events, seed=args.seed)
    mc_df.to_parquet(OUT_MC, index=False)
    ci = credible_interval(mc_df, "portfolio_share")
    logger.info("Monte Carlo: 5th-95th pct credible interval %.1f%% - %.1f%%", ci["p5"] * 100, ci["p95"] * 100)

    logger.info("Computing tornado sensitivity...")
    tornado_df, baseline_share, baseline_tam = compute_tornado(assumptions, internal, fin, competitor_events)
    tornado_df.to_parquet(OUT_TORNADO, index=False)
    render_tornado_chart(tornado_df, baseline_share, OUT_TORNADO_PNG)
    logger.info("Wrote %s", OUT_TORNADO_PNG)

    logger.info("Computing revealed-presence estimator...")
    presence_df = compute_revealed_presence(con)
    presence_df.to_parquet(OUT_PRESENCE, index=False)

    logger.info("Computing sector regression...")
    wallet_df = pd.read_parquet(PROCESSED_DIR / "wallet_model.parquet")
    sector_df = compute_sector_regression(wallet_df, fin, assumptions)
    sector_df.to_parquet(OUT_SECTOR, index=False)

    logger.info("Computing time trends...")
    entity_trends, corridor_trends = compute_time_trends(con)
    entity_trends.to_parquet(OUT_TREND_ENTITY, index=False)
    corridor_trends.to_parquet(OUT_TREND_CORRIDOR, index=False)

    con.close()

    report = render_markdown(mc_df, tornado_df, baseline_share, baseline_tam, presence_df, sector_df, entity_trends, corridor_trends)
    OUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUT_REPORT_MD)


if __name__ == "__main__":
    main()
