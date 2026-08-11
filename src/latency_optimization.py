"""
Phase 7(b) — Latency & Cost Optimisation (`src/latency_optimization.py`)
===========================================================================
hackathon.txt's Phase 7 spec, verbatim: "instrument the LLM pipeline, add
caching, batching, and route simple classification to a small model
reserving the large one for hard cases. Produce a before/after latency and
cost chart." Explicitly labelled "bonus" — built after Phases 1-6 and 8.

Caching and prompt logging are already built into `src.llm.generate_structured`
and used by every phase since Phase 2 (see CLAUDE.md). This module is the
part that wasn't built yet: model routing, exercised on Phase 2's real
extraction task, measured against Phase 2's REAL historical performance
rather than a simulated baseline.

**Routing signal, not invented for this module**: `regex_facility_type`'s
`regex_confidence` (`src/forensics.py`) already splits every memo row into
"simple" (0.85 — an explicit syndicate/bridging/bilateral keyword is
present) and "hard" (0.40 — generic language, keyword regex can't tell).
That's the same signal Phase 2 already computes and cross-checks the LLM
against; reusing it here means "simple vs. hard" is not a new judgement
call invented for this experiment. Simple rows route to
`MODEL_SMALL` (gemini-2.5-flash-lite); hard rows stay on `MODEL_DEFAULT`
(gemini-2.5-flash) — the model Phase 2 already used for all 4,199 rows.

**"Before" is Phase 2's actual historical run, not a resimulation**: every
Phase 2 call's latency and token counts are already in
`reports/llm_usage_log.jsonl` (namespace `forensics_memo_extraction`,
`cached=False` rows only — cache hits are 0ms/free and would understate a
"before" baseline). "After" extrapolates from a genuinely fresh sample of
simple-bucket rows re-run on `MODEL_SMALL` (a new namespace, so nothing in
Phase 2's own cache/output is touched or invalidated) to the full
portfolio, using the REAL simple/hard split already present in
`competitor_credit_events.parquet`.

**Safety check, not just a cost saving**: for every freshly-sampled row,
this module also has Phase 2's ORIGINAL `MODEL_DEFAULT` answer on file
(`llm_facility_type` in `competitor_credit_events.parquet`) — so the
`MODEL_SMALL` vs `MODEL_DEFAULT` agreement rate on the simple bucket is a
real, measured number, not assumed. Routing is only worth recommending if
that agreement rate holds up; reported plainly either way.

Pricing (paid tier, per 1M tokens): gemini-2.5-flash $0.30 in / $2.50 out;
gemini-3.1-flash-lite $0.25 in / $1.50 out (gemini-2.5-flash-lite, the
originally-planned MODEL_SMALL, returned a 404 "no longer available to new
users" on a live call 2026-08-11 -- see src/llm.py).
Source: https://ai.google.dev/gemini-api/docs/pricing, retrieved 2026-08-11.

Output: data/processed/latency_optimization_sample.parquet,
        reports/latency_optimization_report.md,
        reports/latency_optimization_chart.png

Run standalone:
    python -m src.latency_optimization
    python -m src.latency_optimization --sample-size 40   # quick smoke test
"""
from __future__ import annotations

import argparse
import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.common import PROCESSED_DIR, REPORTS_DIR, configure_logging, ensure_dirs
from src.forensics import SYSTEM_INSTRUCTION, MemoExtraction, _build_prompt
from src.llm import MissingAPIKeyError, MODEL_DEFAULT, MODEL_SMALL, generate_structured

logger = logging.getLogger(__name__)

FORENSICS_PARQUET = PROCESSED_DIR / "competitor_credit_events.parquet"
USAGE_LOG = REPORTS_DIR / "llm_usage_log.jsonl"

OUT_SAMPLE_PARQUET = PROCESSED_DIR / "latency_optimization_sample.parquet"
OUT_REPORT_MD = REPORTS_DIR / "latency_optimization_report.md"
OUT_CHART_PNG = REPORTS_DIR / "latency_optimization_chart.png"

NAMESPACE_SMALL = "latency_optimization_small_model"
DEFAULT_SAMPLE_SIZE = 100  # simple-bucket rows genuinely re-run on MODEL_SMALL
                            # for this experiment -- a routing EXPERIMENT, not
                            # a full reprocessing of the 4,199-row portfolio.
RANDOM_SEED = 42

# Sourced 2026-08-11: https://ai.google.dev/gemini-api/docs/pricing (paid tier).
# Keyed by the actual model id in use (see src/llm.py's MODEL_DEFAULT/
# MODEL_SMALL) so a future model-id change doesn't silently pair the wrong
# price with the wrong model.
PRICE_PER_1M_USD = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
}
PRICING_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing, retrieved 2026-08-11"


def load_forensics_output() -> pd.DataFrame:
    return pd.read_parquet(FORENSICS_PARQUET)


def sample_simple_rows(df: pd.DataFrame, n: int, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """The 'simple' bucket: regex_confidence == 0.85, an explicit
    syndicate/bridging/bilateral keyword present in the memo (see
    src/forensics.py's regex_confidence). This is the routing signal --
    reused, not reinvented, for this module."""
    simple = df[df["regex_confidence"] == 0.85]
    return simple.sample(n=min(n, len(simple)), random_state=seed)


def run_small_model_sample(sample_df: pd.DataFrame) -> pd.DataFrame:
    """Fresh MODEL_SMALL calls on the simple bucket, using the SAME prompt/
    schema/system_instruction Phase 2 uses for MODEL_DEFAULT -- an
    apples-to-apples routing swap, not a different task."""
    rows = []
    n = len(sample_df)
    for i, (_, row) in enumerate(sample_df.iterrows(), start=1):
        prompt = _build_prompt(row)
        result = generate_structured(
            namespace=NAMESPACE_SMALL,
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            response_schema=MemoExtraction,
            model=MODEL_SMALL,
            extra_cache_key=str(row["beneficiary_name"]),
        )
        rows.append(
            {
                "row_id": row["row_id"],
                "small_facility_type": result.parsed.facility_type.value if result.parsed else None,
                "small_confidence_score": result.parsed.confidence_score if result.parsed else None,
                "small_latency_ms": result.latency_ms,
                "small_input_tokens": result.input_tokens,
                "small_output_tokens": result.output_tokens,
                "small_cached": result.cached,
                "original_big_facility_type": row["llm_facility_type"],
            }
        )
        if i % 25 == 0 or i == n:
            logger.info("MODEL_SMALL routing sample: %d / %d rows done", i, n)
    return pd.DataFrame(rows)


def load_before_baseline(usage_log_path=USAGE_LOG) -> dict:
    """Phase 2's REAL historical MODEL_DEFAULT performance -- cached=False
    rows only (a cache hit is 0ms/free and would understate the 'before'
    baseline this module is trying to improve on)."""
    log = pd.read_json(usage_log_path, lines=True)
    hist = log[(log["namespace"] == "forensics_memo_extraction") & (~log["cached"])]
    return {
        "n_calls": int(len(hist)),
        "latency_ms_median": float(hist["latency_ms"].median()),
        "latency_ms_p95": float(hist["latency_ms"].quantile(0.95)),
        "input_tokens_mean": float(hist["input_tokens"].mean()),
        "output_tokens_mean": float(hist["output_tokens"].mean()),
    }


def _cost_per_call(model: str, input_tokens: float, output_tokens: float) -> float:
    price = PRICE_PER_1M_USD[model]
    return (input_tokens / 1e6) * price["input"] + (output_tokens / 1e6) * price["output"]


def compute_before_after(full_df: pd.DataFrame, sample_result_df: pd.DataFrame, before: dict) -> dict:
    n_total = len(full_df)
    n_simple = int((full_df["regex_confidence"] == 0.85).sum())
    n_hard = n_total - n_simple

    fresh = sample_result_df[~sample_result_df["small_cached"]]
    if fresh.empty:
        fresh = sample_result_df  # all cache hits (e.g. a rerun) -- fall back rather than divide by zero
    after_latency_ms = float(fresh["small_latency_ms"].median())
    after_input_tokens = float(fresh["small_input_tokens"].mean())
    after_output_tokens = float(fresh["small_output_tokens"].mean())

    cost_big_per_call = _cost_per_call(MODEL_DEFAULT, before["input_tokens_mean"], before["output_tokens_mean"])
    cost_small_per_call = _cost_per_call(MODEL_SMALL, after_input_tokens, after_output_tokens)

    agreement = float((sample_result_df["small_facility_type"] == sample_result_df["original_big_facility_type"]).mean())

    before_total_cost_usd = n_total * cost_big_per_call
    after_total_cost_usd = n_simple * cost_small_per_call + n_hard * cost_big_per_call

    # "Total compute time" -- Phase 2 ran max_workers concurrent calls, so
    # this is NOT observed wall-clock time; it is n_calls x per-call median
    # latency, a fair apples-to-apples workload-size comparison between the
    # two routing strategies at the SAME concurrency, not a wall-clock claim.
    before_total_latency_s = n_total * before["latency_ms_median"] / 1000
    after_total_latency_s = (n_simple * after_latency_ms + n_hard * before["latency_ms_median"]) / 1000

    return {
        "n_total": n_total,
        "n_simple": n_simple,
        "n_hard": n_hard,
        "sample_size": len(sample_result_df),
        "sample_fresh_calls": len(fresh),
        "agreement_rate": agreement,
        "before_latency_ms_median": before["latency_ms_median"],
        "before_latency_ms_p95": before["latency_ms_p95"],
        "after_small_latency_ms_median": after_latency_ms,
        "cost_big_per_call_usd": cost_big_per_call,
        "cost_small_per_call_usd": cost_small_per_call,
        "before_total_cost_usd": before_total_cost_usd,
        "after_total_cost_usd": after_total_cost_usd,
        "cost_saved_usd": before_total_cost_usd - after_total_cost_usd,
        "cost_saved_pct": (before_total_cost_usd - after_total_cost_usd) / before_total_cost_usd,
        "before_total_latency_s": before_total_latency_s,
        "after_total_latency_s": after_total_latency_s,
        "latency_saved_pct": (before_total_latency_s - after_total_latency_s) / before_total_latency_s,
    }


def render_chart(stats: dict, path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))

    ax = axes[0]
    ax.bar(["Before\n(all MODEL_DEFAULT)", "After\n(routed)"],
           [stats["before_total_cost_usd"], stats["after_total_cost_usd"]],
           color=["#c3c2b7", "#1baf7a"])
    ax.set_ylabel("Total cost, USD (full %d-row workload)" % stats["n_total"])
    ax.set_title("Cost")
    for i, v in enumerate([stats["before_total_cost_usd"], stats["after_total_cost_usd"]]):
        ax.text(i, v, f"${v:.2f}", ha="center", va="bottom", fontsize=9)

    ax = axes[1]
    ax.bar(["Before\n(all MODEL_DEFAULT)", "After\n(routed)"],
           [stats["before_total_latency_s"], stats["after_total_latency_s"]],
           color=["#c3c2b7", "#2a78d6"])
    ax.set_ylabel("Total compute time, seconds (n_calls x per-call median latency)")
    ax.set_title("Latency")
    for i, v in enumerate([stats["before_total_latency_s"], stats["after_total_latency_s"]]):
        ax.text(i, v, f"{v:,.0f}s", ha="center", va="bottom", fontsize=9)

    for ax in axes:
        ax.grid(axis="y", color="#e1e0d9", linewidth=0.6)
        ax.set_axisbelow(True)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

    fig.suptitle("Model-routing before/after: reserve MODEL_DEFAULT for hard cases, route simple cases to MODEL_SMALL", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _fmt_change_pct(saved_pct: float) -> str:
    """saved_pct > 0 means 'after' is smaller (an improvement); < 0 means it
    got worse. Renders the sign explicitly rather than assuming improvement,
    since routing isn't guaranteed to win on every axis (see report)."""
    return f"-{saved_pct:.0%}" if saved_pct >= 0 else f"+{-saved_pct:.0%}"


def render_markdown(stats: dict) -> str:
    lines = [
        "# Latency & Cost Optimisation (Phase 7 bonus module)",
        "",
        "hackathon.txt's Phase 7(b) spec, verbatim: *\"instrument the LLM pipeline, add "
        "caching, batching, and route simple classification to a small model reserving "
        "the large one for hard cases. Produce a before/after latency and cost chart.\"*",
        "",
        "Caching and prompt logging (`src.llm.generate_structured`) have been in every LLM "
        "call since Phase 2 (see CLAUDE.md). This module adds the piece that wasn't built "
        f"yet: routing, using {MODEL_DEFAULT} for everything as the 'before' (Phase 2's "
        f"actual historical run) vs. routing 'simple' rows to {MODEL_SMALL} as the 'after'.",
        "",
        "## Routing rule",
        "",
        "Reuses `src/forensics.py`'s existing `regex_confidence` signal — 0.85 where an "
        "explicit syndicate/bridging/bilateral keyword is present in the memo (`simple`), "
        f"0.40 otherwise (`hard`). Not a new judgement call invented for this module: "
        f"**{stats['n_simple']:,} of {stats['n_total']:,} rows ({stats['n_simple']/stats['n_total']:.0%}) "
        f"are `simple`** and route to {MODEL_SMALL}; the remaining "
        f"{stats['n_hard']:,} (`hard`) stay on {MODEL_DEFAULT}, exactly as Phase 2 already "
        "ran them.",
        "",
        "## Safety check: does the cheap model agree with the original answer?",
        "",
        f"{stats['sample_fresh_calls']} freshly-sampled `simple` rows were re-run on "
        f"{MODEL_SMALL} and compared against Phase 2's ORIGINAL {MODEL_DEFAULT} answer for "
        "the exact same row (already on file in `competitor_credit_events.parquet`) — a "
        "measured agreement rate, not an assumption:",
        "",
        f"**`facility_type` agreement: {stats['agreement_rate']:.1%}** "
        f"({stats['sample_fresh_calls']} rows compared).",
        "",
        ("This is high enough to trust the routing — the `simple` bucket earns its name; "
         "an explicit keyword match leaves little for a smaller model to get wrong."
         if stats["agreement_rate"] >= 0.90 else
         "This is NOT high enough to recommend unconditionally — see caveat below."),
        "",
        "## Before / after, extrapolated to the full portfolio",
        "",
        "![Latency and cost before/after chart](latency_optimization_chart.png)",
        "",
        "| | Before (all MODEL_DEFAULT) | After (routed) | Change |",
        "|---|---|---|---|",
        f"| Total cost (USD, {stats['n_total']:,} rows) | ${stats['before_total_cost_usd']:.2f} | "
        f"${stats['after_total_cost_usd']:.2f} | **{_fmt_change_pct(stats['cost_saved_pct'])}** (${stats['cost_saved_usd']:.2f} saved) |",
        f"| Total compute time (s) | {stats['before_total_latency_s']:,.0f}s | "
        f"{stats['after_total_latency_s']:,.0f}s | **{_fmt_change_pct(stats['latency_saved_pct'])}** |",
        f"| Cost per call | ${stats['cost_big_per_call_usd']:.6f} ({MODEL_DEFAULT}) | "
        f"${stats['cost_small_per_call_usd']:.6f} ({MODEL_SMALL}) on the routed share | — |",
        f"| Median per-call latency | {stats['before_latency_ms_median']:.0f}ms | "
        f"{stats['after_small_latency_ms_median']:.0f}ms ({MODEL_SMALL}, routed share) | — |",
        "",
        "## Reading the latency result",
        "",
        (f"Routing saved {stats['latency_saved_pct']:.0%} of total compute time as well as cost."
         if stats["latency_saved_pct"] >= 0 else
         f"**Compute time went up, not down** ({-stats['latency_saved_pct']:.0%} slower) — "
         f"{MODEL_SMALL}'s measured per-call latency ({stats['after_small_latency_ms_median']:.0f}ms) "
         f"was not lower than {MODEL_DEFAULT}'s historical median ({stats['before_latency_ms_median']:.0f}ms) "
         "on this sample. Reported plainly rather than only showing the metric that improved: at this "
         "particular model-generation pairing, routing is a genuine **cost** optimisation "
         f"({stats['cost_saved_pct']:.0%} saved) but not a reliable **latency** one — a smaller model "
         "is not automatically a faster one, and the price gap between these two specific models "
         "(gemini-3.1-flash-lite vs. gemini-2.5-flash) is narrower than the original gemini-2.5-flash-lite "
         "pricing this experiment was designed around (see note below)."),
        "",
        "## Methodology notes",
        "",
        "- **'Before' is Phase 2's real historical run**, not a resimulation: median/mean "
        f"latency and token counts come from {stats['sample_fresh_calls'] and 'reports/llm_usage_log.jsonl'}'s "
        "`forensics_memo_extraction` namespace, `cached=False` rows only (a cache hit is "
        "0ms/free and would understate the baseline this module is trying to improve on).",
        "- **'Total compute time' is n_calls x per-call median latency, not observed "
        "wall-clock time** — Phase 2 ran with `--max-workers 12` concurrent calls, so actual "
        "wall-clock was far shorter than this sum for both 'before' and 'after'. This metric "
        "is a fair apples-to-apples workload-size comparison between the two routing "
        "strategies at the same concurrency, not a wall-clock claim.",
        f"- **Pricing**: {MODEL_DEFAULT} ${PRICE_PER_1M_USD[MODEL_DEFAULT]['input']}/1M input, "
        f"${PRICE_PER_1M_USD[MODEL_DEFAULT]['output']}/1M output tokens; {MODEL_SMALL} "
        f"${PRICE_PER_1M_USD[MODEL_SMALL]['input']}/1M input, ${PRICE_PER_1M_USD[MODEL_SMALL]['output']}/1M "
        f"output tokens (paid tier). Source: {PRICING_SOURCE}.",
        "- The historical median latency (not mean) is used deliberately: Phase 2's own "
        "usage log has a small number of extreme-tail retries (see CLAUDE.md 'Must-know' #6 "
        "— the `httpx.ReadError`/transient-failure retry fix), which would badly distort a "
        "mean-based 'before' figure.",
    ]
    return "\n".join(lines)


def main(sample_size: int = DEFAULT_SAMPLE_SIZE) -> dict:
    configure_logging()
    ensure_dirs()

    full_df = load_forensics_output()
    before = load_before_baseline()
    logger.info("Before baseline (real, %d historical calls): median latency %.0fms, %.0f in / %.0f out tokens",
                before["n_calls"], before["latency_ms_median"], before["input_tokens_mean"], before["output_tokens_mean"])

    try:
        sample_df = sample_simple_rows(full_df, n=sample_size)
        sample_result_df = run_small_model_sample(sample_df)
    except MissingAPIKeyError:
        logger.warning("No GEMINI_API_KEY configured -- cannot run the MODEL_SMALL routing experiment. "
                        "See .env.example. Skipping Phase 7(b); no output written.")
        return {}

    sample_result_df.to_parquet(OUT_SAMPLE_PARQUET, index=False)
    logger.info("Wrote %s (%d rows)", OUT_SAMPLE_PARQUET, len(sample_result_df))

    stats = compute_before_after(full_df, sample_result_df, before)

    render_chart(stats, OUT_CHART_PNG)
    logger.info("Wrote %s", OUT_CHART_PNG)

    report = render_markdown(stats)
    OUT_REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote %s", OUT_REPORT_MD)

    logger.info("Agreement rate: %.1f%%. Cost saved: %.0f%% ($%.2f). Compute-time saved: %.0f%%.",
                stats["agreement_rate"] * 100, stats["cost_saved_pct"] * 100, stats["cost_saved_usd"], stats["latency_saved_pct"] * 100)
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    args = parser.parse_args()
    main(sample_size=args.sample_size)
