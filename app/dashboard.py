"""
Phase 8 — Executive Dashboard (`app/dashboard.py`)
===========================================================================
Streamlit dashboard per hackathon.txt's deliverables list: portfolio-level
summary ranking all 20 clients by expected value, per-client drill-down,
opportunity heatmap (client x pillar), AI-generated briefing notes for at
least 3 clients, and the competitor-credit finding as a dedicated view.

**Every number on this page is read from a parquet file already produced
by Phases 1-6 (or a live, deterministic DuckDB aggregation of the raw
ledgers for the per-client counterparty view) — nothing is recomputed with
different logic here.** Where a figure needs reshaping for display (a
groupby/pivot), that reshaping is noted in the code, not hidden.

Run:
    streamlit run app/dashboard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.common import EXPECTED_ENTITIES, KNOWN_COMPETITOR_BENEFICIARIES  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
DUCKDB_PATH = PROCESSED / "syn_bank.duckdb"

# --------------------------------------------------------------------------
# Palette — validated categorical/sequential/status colors (dataviz skill
# reference palette). Light AND dark variants are both defined here; the
# user picks which one applies via a sidebar toggle (`THEME` below), and
# every chart in this file reads its colors from the active theme dict
# rather than a hardcoded hex — this is what makes charts follow Streamlit's
# dark mode instead of staying light-surface regardless of app theme.
# --------------------------------------------------------------------------
THEMES = {
    "light": {
        "categorical": {
            "blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100",
            "magenta": "#e87ba4", "green": "#008300", "violet": "#4a3aa7", "red": "#e34948",
        },
        "status": {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"},
        "sequential": ["#eaf2fc", "#cde2fb", "#9ec5f4", "#5598e7", "#256abf", "#0d366b"],
        "surface": "#fcfcfb",
        "page": "#f9f9f7",
        "ink_primary": "#0b0b0b",
        "ink_secondary": "#52514e",
        "ink_muted": "#898781",
        "grid": "#e1e0d9",
        "baseline": "#c3c2b7",
    },
    "dark": {
        "categorical": {
            "blue": "#3987e5", "orange": "#d95926", "aqua": "#199e70", "yellow": "#c98500",
            "magenta": "#d55181", "green": "#008300", "violet": "#9085e9", "red": "#e66767",
        },
        "status": {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"},
        "sequential": ["#256abf", "#3987e5", "#5598e7", "#9ec5f4", "#cde2fb", "#eaf2fc"],
        "surface": "#1a1a19",
        "page": "#0d0d0d",
        "ink_primary": "#ffffff",
        "ink_secondary": "#c3c2b7",
        "ink_muted": "#898781",
        "grid": "#2c2c2a",
        "baseline": "#383835",
    },
}

st.set_page_config(page_title="Syn Bank — Share of Wallet Intelligence Engine", layout="wide", page_icon="🏦")

# Every Plotly chart in this file reads its colors from the ACTIVE Streamlit
# theme via st.context.theme.type ("light"/"dark") -- this is the theme the
# user already controls natively (top-right "⋮" menu -> Settings -> app
# theme, or their OS preference on first load). Streamlit's own chrome
# (sidebar, metrics, captions) already re-themes itself correctly when that's
# toggled; only the embedded Plotly charts were staying light-hardcoded
# regardless, which is the bug being fixed here. No custom CSS injection --
# fighting Streamlit's own stylesheet with broad selectors is fragile and,
# tried once here, made native text nearly unreadable in dark mode.
try:
    THEME_NAME = st.context.theme.type or "light"
except Exception:
    THEME_NAME = "light"
THEME = THEMES[THEME_NAME]
CATEGORICAL = THEME["categorical"]
PILLAR_COLOR = {
    "Transactional Banking": CATEGORICAL["blue"],
    "Global Markets": CATEGORICAL["orange"],
    "Investment Banking": CATEGORICAL["aqua"],
}
TIER_COLOR = {"primary": CATEGORICAL["blue"], "secondary": CATEGORICAL["orange"]}
STATUS = THEME["status"]
SEQUENTIAL_BLUE = THEME["sequential"]
INK_SECONDARY = THEME["ink_secondary"]
GRID = THEME["grid"]


def chart_layout(**overrides) -> dict:
    """Common Plotly layout kwargs for the active theme -- merge with
    per-chart overrides so every chart follows the sidebar toggle instead of
    hardcoding light-mode hex values."""
    base = dict(
        plot_bgcolor=THEME["surface"],
        paper_bgcolor=THEME["surface"],
        font=dict(color=THEME["ink_secondary"]),
        xaxis=dict(gridcolor=THEME["grid"], linecolor=THEME["baseline"], color=THEME["ink_secondary"]),
        yaxis=dict(gridcolor=THEME["grid"], linecolor=THEME["baseline"], color=THEME["ink_secondary"]),
    )
    for k, v in overrides.items():
        if k in ("xaxis", "yaxis") and isinstance(v, dict) and k in base:
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base




# --------------------------------------------------------------------------
# Data loading — every table here is a direct read of an already-computed
# Phase 1-6 output. No recomputation.
# --------------------------------------------------------------------------
@st.cache_data
def load_data() -> dict[str, pd.DataFrame]:
    def _read(name: str) -> pd.DataFrame:
        p = PROCESSED / name
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()

    return {
        "entity_ranking": _read("opportunity_ranking_entity.parquet"),
        "pillar_ranking": _read("opportunity_ranking_pillar.parquet"),
        "subcomponent_ranking": _read("opportunity_ranking_subcomponent.parquet"),
        "wallet_model": _read("wallet_model.parquet"),
        "competitor_events": _read("competitor_credit_events.parquet"),
        "financials": _read("financial_baseline.parquet"),
        "briefings": _read("briefing_notes.parquet"),
        "monte_carlo": _read("monte_carlo_results.parquet"),
        "tornado": _read("tornado_sensitivity.parquet"),
        "presence": _read("revealed_presence.parquet"),
        "sector_reg": _read("sector_regression.parquet"),
        "trends": _read("time_trends_entity.parquet"),
    }


@st.cache_resource
def get_con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DUCKDB_PATH), read_only=True)


@st.cache_data
def top_counterparties(entity_id: str, n: int = 10) -> pd.DataFrame:
    """Top-N counterparties by value for ONE client, across all 3 ledgers --
    the brief's explicit graph-visual constraint ("constrain to one client
    at a time, top-N counterparties by value... No 241k-edge hairballs").
    """
    con = get_con()
    df = con.sql(
        f"""
        WITH all_flow AS (
            SELECT beneficiary_name, amount_zar AS value_zar FROM transactional_banking WHERE entity_id = '{entity_id}'
            UNION ALL SELECT beneficiary_name, value_zar FROM cross_border_payments WHERE entity_id = '{entity_id}'
            UNION ALL SELECT beneficiary_name, value_zar FROM trade_finance WHERE entity_id = '{entity_id}'
        )
        SELECT beneficiary_name, sum(value_zar) AS total_value_zar, count(*) AS n_transactions
        FROM all_flow GROUP BY 1 ORDER BY 2 DESC LIMIT {n}
        """
    ).fetchdf()
    df["is_known_competitor_bank"] = df["beneficiary_name"].isin(KNOWN_COMPETITOR_BENEFICIARIES)
    return df


data = load_data()
if data["entity_ranking"].empty:
    st.error("No computed data found under `data/processed/`. Run `python run_all.py` first.")
    st.stop()


def r_fmt(x: float, decimals: int = 1) -> str:
    if pd.isna(x):
        return "n/a"
    if abs(x) >= 1e9:
        return f"R{x/1e9:,.{decimals}f}bn"
    if abs(x) >= 1e6:
        return f"R{x/1e6:,.{decimals}f}m"
    return f"R{x:,.0f}"


# --------------------------------------------------------------------------
# Page: Portfolio Summary
# --------------------------------------------------------------------------
def page_portfolio_summary():
    st.title("Portfolio Summary")
    st.caption("All figures trace back to `data/processed/*.parquet` — Phases 1–6. No number on this page is computed inline.")

    ent = data["entity_ranking"]
    main = ent[~ent.is_global_major].sort_values("total_expected_value_zar", ascending=False)
    mc = data["monte_carlo"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Portfolio blended share (base case)", f"{mc['portfolio_share'].median():.1%}" if len(mc) else "n/a")
        if len(mc):
            st.caption(f"5th–95th pct: {mc['portfolio_share'].quantile(0.05):.1%} – {mc['portfolio_share'].quantile(0.95):.1%}")
    with col2:
        st.metric("Total expected-value opportunity (SA-domestic)", r_fmt(main["total_expected_value_zar"].sum()))
    with col3:
        st.metric("Total wallet gap (SA-domestic)", r_fmt(main["total_wallet_gap_zar"].sum()))
    with col4:
        st.metric("Entities flagged (sequencing risk)", f"{int(main['any_sequencing_flag'].sum())}/{len(main)}")

    st.subheader("Ranked by expected value — SA-domestic entities")
    fig = go.Figure()
    fig.add_bar(
        y=main["entity_name"],
        x=main["total_expected_value_zar"] / 1e6,
        orientation="h",
        marker_color=CATEGORICAL["blue"],
        text=main["total_expected_value_zar"].map(lambda x: r_fmt(x)),
        textposition="outside",
        hovertemplate="%{y}<br>Expected value: R%{x:,.1f}m<extra></extra>",
    )
    fig.update_layout(**chart_layout(
        xaxis_title="Expected value (R millions)",
        yaxis=dict(autorange="reversed"),
        height=550,
        margin=dict(l=10, r=10, t=10, b=10),
    ))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Full SA-domestic ranking table"):
        st.caption("**Specific product** is the actual conversation to have — \"Transactional Banking\" alone doesn't say whether to pitch payment-fee pricing or cash management.")
        disp = main[["rank", "entity_id", "entity_name", "sector", "total_expected_value_zar", "total_wallet_gap_zar", "win_probability", "top_sub_component_label", "any_sequencing_flag"]].copy()
        disp.columns = ["Rank", "ID", "Entity", "Sector", "Expected value", "Wallet gap", "Win prob.", "Specific product", "Sequencing flag"]
        disp["Expected value"] = disp["Expected value"].map(r_fmt)
        disp["Wallet gap"] = disp["Wallet gap"].map(r_fmt)
        disp["Win prob."] = disp["Win prob."].map(lambda x: f"{x:.0%}")
        st.dataframe(disp, use_container_width=True, hide_index=True)

    st.subheader("⚠ Dual-listed global majors — shown separately, not part of the primary ranking")
    st.caption(
        "These entities' Phase 3 revenue is their entire GLOBAL figure, not South-Africa-specific — their TAM "
        "(and wallet gap) is inflated on a scale no SA-focused coverage effort could realistically close. See "
        "METHODOLOGY.md for the full explanation."
    )
    gm = ent[ent.is_global_major].sort_values("total_expected_value_zar", ascending=False)
    disp = gm[["entity_id", "entity_name", "sector", "total_expected_value_zar", "total_wallet_gap_zar"]].copy()
    disp.columns = ["ID", "Entity", "Sector", "Expected value", "Wallet gap"]
    disp["Expected value"] = disp["Expected value"].map(r_fmt)
    disp["Wallet gap"] = disp["Wallet gap"].map(r_fmt)
    st.dataframe(disp, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------
# Page: Client Drill-Down
# --------------------------------------------------------------------------
def page_client_drilldown():
    st.title("Client Drill-Down")

    ent = data["entity_ranking"].sort_values("entity_name")
    labels = {row.entity_id: f"{row.entity_name} ({row.entity_id})" for row in ent.itertuples()}
    entity_id = st.selectbox("Client", options=list(labels.keys()), format_func=lambda e: labels[e])

    row = ent[ent.entity_id == entity_id].iloc[0]
    if row["is_global_major"]:
        st.warning(
            "This is a dual-listed global major — its wallet figures are based on GLOBAL revenue, not "
            "South-Africa-specific. Read the gap size as an upper bound, not a realistic near-term target."
        )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Expected value", r_fmt(row["total_expected_value_zar"]))
    col2.metric("Wallet gap", r_fmt(row["total_wallet_gap_zar"]))
    col3.metric("Win probability", f"{row['win_probability']:.0%}")
    col4.metric("TB relationship strength", f"{row['relationship_strength_score']:.0%}")

    if row["any_sequencing_flag"]:
        st.error(
            "⚠ Product-sequencing risk: at least one Global Markets/Investment Banking recommendation for this "
            "client rests on a weak Transactional Banking relationship. Deepen the payment-flow relationship "
            "before pursuing FX/IB — win_probability has already been penalised in the ranking accordingly."
        )

    pillar = data["pillar_ranking"]
    PILLAR_ORDER = ["Transactional Banking", "Global Markets", "Investment Banking"]
    epillar = pillar[pillar.entity_id == entity_id].copy()
    epillar["pillar"] = pd.Categorical(epillar["pillar"], categories=PILLAR_ORDER, ordered=True)
    epillar = epillar.sort_values("pillar")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Wallet gap by pillar")
        fig = go.Figure()
        fig.add_bar(
            x=epillar["pillar"], y=epillar["wallet_gap_zar"] / 1e6,
            marker_color=[PILLAR_COLOR[p] for p in epillar["pillar"]],
            text=epillar["wallet_gap_zar"].map(r_fmt), textposition="outside",
            hovertemplate="%{x}<br>Wallet gap: R%{y:,.1f}m<extra></extra>",
        )
        fig.update_layout(**chart_layout(
            yaxis_title="Wallet gap (R millions)", height=380, margin=dict(l=10, r=10, t=10, b=10),
        ))
        st.plotly_chart(fig, use_container_width=True)
        unknown = epillar["unknown_capture_tam_zar"].sum()
        if unknown > 0:
            st.caption(f"Plus {r_fmt(unknown)} in unknown-capture potential (structurally unobservable — see METHODOLOGY.md).")

    with c2:
        st.subheader("Right-to-win signals")
        signals = {
            "Product breadth": row["breadth_score"],
            "TB relationship": row["relationship_strength_score"],
            "Momentum": row["momentum_score"],
            "Country adjacency": row["country_adjacency_score"],
        }
        fig = go.Figure()
        fig.add_bar(
            x=list(signals.values()), y=list(signals.keys()), orientation="h",
            marker_color=CATEGORICAL["violet"],
            text=[f"{v:.2f}" for v in signals.values()], textposition="outside",
        )
        fig.update_layout(**chart_layout(
            xaxis=dict(range=[0, 1]), height=380, margin=dict(l=10, r=10, t=10, b=10),
        ))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Wallet gap by specific product (sub-component)")
    st.caption(
        "The finest grain the model computes — this is the actual conversation to walk in with, not just the "
        "pillar. Bars colored by parent pillar; only 'confident' rows (both TAM and captured observable) shown."
    )
    esub = data["subcomponent_ranking"]
    esub = esub[esub.entity_id == entity_id].sort_values("wallet_gap_zar", ascending=True)
    if len(esub):
        fig = go.Figure()
        fig.add_bar(
            x=esub["wallet_gap_zar"] / 1e6, y=esub["sub_component_label"], orientation="h",
            marker_color=[PILLAR_COLOR.get(p, CATEGORICAL["blue"]) for p in esub["pillar"]],
            text=esub["wallet_gap_zar"].map(r_fmt), textposition="outside",
            hovertemplate="%{y}<br>Wallet gap: R%{x:,.1f}m<extra></extra>",
        )
        fig.update_layout(**chart_layout(
            xaxis_title="Wallet gap (R millions)", height=280 + 24 * len(esub),
            margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        ))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No sub-component-level rows for this client (all fell below the confidence threshold).")

    st.subheader("Top counterparties by value (this client only)")
    st.caption("Top 10 by observed value across all 3 ledgers — never a full network graph.")
    tc = top_counterparties(entity_id, n=10)
    if len(tc):
        colors = [STATUS["critical"] if b else CATEGORICAL["blue"] for b in tc["is_known_competitor_bank"]]
        fig = go.Figure()
        fig.add_bar(
            x=tc["total_value_zar"] / 1e6, y=tc["beneficiary_name"], orientation="h",
            marker_color=colors, text=tc["total_value_zar"].map(r_fmt), textposition="outside",
        )
        fig.update_layout(**chart_layout(
            xaxis_title="Total value (R millions)", yaxis=dict(autorange="reversed"),
            height=380, margin=dict(l=10, r=10, t=10, b=10),
        ))
        st.plotly_chart(fig, use_container_width=True)
        if tc["is_known_competitor_bank"].any():
            st.caption("🔴 Red bars = a known competitor-credit beneficiary (see Competitor-Credit Finding page).")

    fin = data["financials"]
    frow = fin[fin.entity_id == entity_id]
    if len(frow):
        st.subheader("Financial snapshot (Phase 3)")
        f = frow.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue", f"{f['total_revenue']:,.0f}m {f['reported_currency']}" if pd.notna(f.get("total_revenue")) else "n/a")
        c2.metric("Foreign revenue %", f"{f['foreign_revenue_pct']:.0f}%" if pd.notna(f.get("foreign_revenue_pct")) else "n/a")
        c3.metric("Total debt", f"{f['total_debt']:,.0f}m {f['reported_currency']}" if pd.notna(f.get("total_debt")) else "n/a")
        c4.metric("Fiscal year end", str(f.get("fiscal_year_end", "n/a")))


# --------------------------------------------------------------------------
# Page: Opportunity Heatmap
# --------------------------------------------------------------------------
def page_heatmap():
    st.title("Opportunity Heatmap — client × pillar")
    st.caption("Expected value (R millions) per entity per pillar. SA-domestic entities only — global majors excluded (see Portfolio Summary).")

    pillar = data["pillar_ranking"]
    ent = data["entity_ranking"]
    sa_ids = set(ent[~ent.is_global_major].entity_id)
    p = pillar[pillar.entity_id.isin(sa_ids)]

    pv = p.pivot_table(index="entity_name", columns="pillar", values="expected_value_zar", aggfunc="sum") / 1e6
    pv = pv.reindex(columns=["Transactional Banking", "Global Markets", "Investment Banking"])
    pv = pv.loc[pv.sum(axis=1).sort_values(ascending=False).index]

    fig = px.imshow(
        pv, color_continuous_scale=SEQUENTIAL_BLUE, aspect="auto",
        labels=dict(color="Expected value (R m)"),
        text_auto=".1f",
    )
    fig.update_layout(**chart_layout(height=650, margin=dict(l=10, r=10, t=30, b=10)))
    fig.update_xaxes(side="top")
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Transactional Banking dominates for every entity — expected, not a rendering artefact: its wallet-size "
        "formula scales off (revenue + cost of sales), a much larger base than Global Markets/Investment "
        "Banking's narrower slices. See METHODOLOGY.md §5.1 / §7.6."
    )


# --------------------------------------------------------------------------
# Page: AI Briefing Notes
# --------------------------------------------------------------------------
def page_briefings():
    st.title("AI-Generated Client Briefing Notes")
    st.info(
        "**Generated from already-computed model output only** (Phases 2–6 — opportunity ranking, wallet gaps, "
        "right-to-win signals, competitor-credit exposure, financials), never free-generated from raw data. "
        "Every prompt is logged verbatim at `prompts/client_briefing_notes/*.json`. See `src/briefing.py`."
    )

    briefings = data["briefings"]
    if briefings.empty:
        st.warning("No briefing notes found. Run `python -m src.briefing` (requires a GEMINI_API_KEY).")
        return

    ent = data["entity_ranking"].set_index("entity_id")
    briefings = briefings.merge(ent[["total_expected_value_zar", "is_global_major"]], left_on="entity_id", right_index=True, how="left")
    # sort SA-domestic entities first (by expected value), global majors after -- same split as every
    # other page, so the default view leads with realistic opportunities, not global majors' inflated figures
    briefings = briefings.sort_values(["is_global_major", "total_expected_value_zar"], ascending=[True, False])

    labels = {row.entity_id: row.entity_name for row in briefings.itertuples()}
    default_selection = briefings[~briefings.is_global_major]["entity_id"].head(5).tolist()
    selected = st.multiselect("Show clients", options=list(labels.keys()), format_func=lambda e: labels[e], default=default_selection)
    show = briefings[briefings.entity_id.isin(selected)] if selected else briefings.head(5)

    for _, row in show.iterrows():
        with st.container(border=True):
            st.subheader(f"{row['entity_name']} ({row['entity_id']})")
            if pd.isna(row["headline"]):
                st.caption("Generation failed for this entity.")
                continue
            st.markdown(f"**{row['headline']}**")
            st.write(row["summary"])
            st.markdown(f"**Recommended next step:** {row['recommended_next_step']}")
            if pd.notna(row.get("caveats")) and row.get("caveats"):
                st.warning(f"⚠ {row['caveats']}")


# --------------------------------------------------------------------------
# Page: Competitor-Credit Finding
# --------------------------------------------------------------------------
def page_competitor_credit():
    st.title("Competitor-Credit Finding")
    st.caption(
        "The narrative spine of this submission: Syn Bank is settling the payment legs of credit facilities "
        "that competitor banks originated — it holds the flow, not the credit relationship. See METHODOLOGY.md §2–3."
    )

    ev = data["competitor_events"]
    by_tier = ev.groupby("signal_tier")["value_zar"].sum()
    primary = by_tier.get("primary", 0.0)
    secondary = by_tier.get("secondary", 0.0)

    col1, col2, col3 = st.columns(3)
    col1.metric("Primary tier (high confidence)", r_fmt(primary))
    col2.metric("Secondary tier (lower confidence)", r_fmt(secondary))
    col3.metric("Total rows extracted", f"{len(ev):,}")

    st.subheader("By entity — primary vs. secondary tier")
    by_entity = ev.groupby(["entity_name", "signal_tier"])["value_zar"].sum().unstack(fill_value=0) / 1e6
    by_entity = by_entity.reindex(columns=["primary", "secondary"], fill_value=0)
    by_entity = by_entity.loc[by_entity.sum(axis=1).sort_values(ascending=False).index]

    fig = go.Figure()
    for tier in ["primary", "secondary"]:
        fig.add_bar(x=by_entity.index, y=by_entity[tier], name=tier.title(), marker_color=TIER_COLOR[tier])
    fig.update_layout(**chart_layout(
        barmode="stack", yaxis_title="Value (R millions)", height=450,
        margin=dict(l=10, r=10, t=10, b=10), legend_title_text="Confidence tier",
    ))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Sample extracted evidence")
    st.caption("Gemini's structured extraction from the memo field — `src/forensics.py`, logged at `prompts/forensics_memo_extraction/`.")
    sample = ev[ev.llm_facility_type.notna()].sample(min(10, len(ev)), random_state=42)
    disp = sample[["entity_name", "beneficiary_name", "memo", "llm_facility_type", "llm_confidence_score", "llm_reasoning"]].copy()
    disp.columns = ["Entity", "Beneficiary", "Memo", "Facility type (LLM)", "Confidence", "LLM reasoning"]
    st.dataframe(disp, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------
# Page: Rigor & Assumptions
# --------------------------------------------------------------------------
def page_rigor():
    st.title("Rigor & Assumptions")
    st.caption("Phase 5's stress-testing of every wallet-model assumption — see METHODOLOGY.md §6 for full derivations.")

    mc = data["monte_carlo"]
    if len(mc):
        st.subheader("Monte Carlo credible interval (2,000 iterations)")
        fig = px.histogram(mc, x="portfolio_share", nbins=40, color_discrete_sequence=[CATEGORICAL["blue"]])
        p5, p50, p95 = mc["portfolio_share"].quantile([0.05, 0.5, 0.95])
        fig.add_vline(x=p50, line_dash="dash", line_color=INK_SECONDARY, annotation_text="median")
        fig.update_layout(**chart_layout(
            xaxis_title="Portfolio blended share of wallet", yaxis_title="Iterations",
            height=350, margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(tickformat=".0%"), showlegend=False,
        ))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Base case never reported alone: 5th–95th percentile is {p5:.1%} – {p95:.1%}.")

    tornado_png = ROOT / "reports" / "tornado_chart.png"
    if tornado_png.exists():
        st.subheader("Tornado sensitivity")
        st.image(str(tornado_png))

    st.subheader("Entities below their sector's wallet-intensity line")
    sec = data["sector_reg"]
    below = sec[sec["below_sector_line"]][["entity_name", "sector", "wallet_intensity", "z_score_in_sector"]]
    if len(below):
        st.dataframe(below, use_container_width=True, hide_index=True)
    else:
        st.caption("None this run.")

    st.subheader("Entities with a Bonferroni-significant time trend")
    tr = data["trends"]
    sig = tr[tr["significant_bonferroni"]][["entity_name", "slope_zar_per_quarter", "r_squared", "p_value"]]
    if len(sig):
        sig = sig.copy()
        sig["direction"] = sig["slope_zar_per_quarter"].apply(lambda s: "📈 growing" if s > 0 else "📉 shrinking")
        st.dataframe(sig[["entity_name", "direction", "r_squared", "p_value"]], use_container_width=True, hide_index=True)
    else:
        st.caption("None this run.")


# --------------------------------------------------------------------------
# Nav
# --------------------------------------------------------------------------
st.sidebar.title("🏦 Syn Bank")
st.sidebar.caption("Share of Wallet Intelligence Engine")
page = st.sidebar.radio(
    "View",
    [
        "Portfolio Summary",
        "Client Drill-Down",
        "Opportunity Heatmap",
        "AI Briefing Notes",
        "Competitor-Credit Finding",
        "Rigor & Assumptions",
    ],
)
st.sidebar.divider()
st.sidebar.caption(f"{len(EXPECTED_ENTITIES)} entities · Phases 1–6 complete · data as of latest `run_all.py`")
st.sidebar.caption("Dark mode: **⋮ menu (top right) → Settings → App theme**. Charts follow it automatically.")

{
    "Portfolio Summary": page_portfolio_summary,
    "Client Drill-Down": page_client_drilldown,
    "Opportunity Heatmap": page_heatmap,
    "AI Briefing Notes": page_briefings,
    "Competitor-Credit Finding": page_competitor_credit,
    "Rigor & Assumptions": page_rigor,
}[page]()
