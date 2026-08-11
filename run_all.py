#!/usr/bin/env python
"""
Single reproducible entry point for the Syn Bank Share of Wallet
Intelligence Engine pipeline. Each phase is also independently runnable
(`python -m src.ingest`, `python -m src.forensics`, ...) — this script just
chains them in order with shared flags.

Usage:
    python run_all.py                    # run every phase built so far
    python run_all.py --until forensics  # stop after a given phase
    python run_all.py --no-llm           # regex baseline only, no LLM calls/API key needed
    python run_all.py --sample 200       # forensics: process a sample instead of all rows
    python run_all.py --mc-iterations 200  # uncertainty: faster/rougher Monte Carlo (default 2000, ~3min)

Phases (see METHODOLOGY.md for what each one does and why):
    1. ingest      -- src/ingest.py      (DuckDB load + profiling report)
    2. forensics   -- src/forensics.py   (competitor-credit memo extraction) [Gen AI #1]
    3. financials  -- src/financials.py  (external financial baseline)       [Gen AI #2]
    4. wallet      -- src/wallet.py      (total wallet + Syn Bank share)
    5. uncertainty -- src/uncertainty.py (Monte Carlo, sensitivity, triangulation)
    6. opportunity -- src/opportunity.py (expected-value ranking)
    7. briefing    -- src/briefing.py    (AI client briefing notes)          [Gen AI #3, Phase 8 support]
    8. cash_cycle  -- src/cash_cycle.py  (Phase 7 bonus (a): cash-cycle/seasonality timing, no LLM)
    9. latency_opt -- src/latency_optimization.py (Phase 7 bonus (b): model-routing before/after -- skipped by --no-llm)
       dashboard   -- app/dashboard.py (Streamlit -- run separately: `python -m streamlit run app/dashboard.py`,
                      not part of this CLI chain; reads briefing's output + everything above)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from src.common import configure_logging

logger = logging.getLogger("run_all")

PHASES = ["ingest", "forensics", "financials", "wallet", "uncertainty", "opportunity", "briefing", "cash_cycle", "latency_opt"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--until", choices=PHASES, default=PHASES[-1], help="Stop after this phase.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM calls in every phase that has one.")
    parser.add_argument("--sample", type=int, default=None, help="Forensics: sample N rows instead of the full set.")
    parser.add_argument("--max-workers", type=int, default=12, help="Forensics: concurrent LLM requests.")
    parser.add_argument("--mc-iterations", type=int, default=2000, help="Uncertainty: Monte Carlo iteration count.")
    args = parser.parse_args()

    configure_logging()
    run_until = PHASES[: PHASES.index(args.until) + 1]
    t_start = time.perf_counter()

    if "ingest" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 1 -- Ingestion & Profiling")
        logger.info("=" * 70)
        from src.ingest import main as ingest_main

        ingest_main()

    if "forensics" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 2 -- Forensic Extraction (Gen AI #1)")
        logger.info("=" * 70)
        from src.forensics import main as forensics_main

        sys.argv = ["forensics"]
        if args.no_llm:
            sys.argv.append("--no-llm")
        if args.sample:
            sys.argv += ["--sample", str(args.sample)]
        sys.argv += ["--max-workers", str(args.max_workers)]
        forensics_main()

    if "financials" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 3 -- External Financial Baseline (Gen AI #2)")
        logger.info("=" * 70)
        from src.financials import main as financials_main

        sys.argv = ["financials"]
        if args.no_llm:
            sys.argv.append("--no-llm")
        sys.argv += ["--max-workers", str(args.max_workers)]
        financials_main()

    if "wallet" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 4 -- Wallet Model")
        logger.info("=" * 70)
        from src.wallet import main as wallet_main

        wallet_main()

    if "uncertainty" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 5 -- Rigor Layer (Monte Carlo, sensitivity, triangulation)")
        logger.info("=" * 70)
        from src.uncertainty import main as uncertainty_main

        sys.argv = ["uncertainty", "--mc-iterations", str(args.mc_iterations)]
        uncertainty_main()

    if "opportunity" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 6 -- Opportunity Ranking")
        logger.info("=" * 70)
        from src.opportunity import main as opportunity_main

        opportunity_main()

    if "briefing" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 8 SUPPORT -- AI Client Briefing Notes (Gen AI #3)")
        logger.info("=" * 70)
        from src.briefing import main as briefing_main

        sys.argv = ["briefing"]
        briefing_main()

    if "cash_cycle" in run_until:
        logger.info("=" * 70)
        logger.info("PHASE 7(a) BONUS -- Cash-Cycle / Payment-Timing")
        logger.info("=" * 70)
        from src.cash_cycle import main as cash_cycle_main

        cash_cycle_main()

    if "latency_opt" in run_until:
        if args.no_llm:
            logger.info("Skipping Phase 7(b) latency/cost optimisation -- --no-llm was passed and this phase is LLM-only.")
        else:
            logger.info("=" * 70)
            logger.info("PHASE 7(b) BONUS -- Latency & Cost Optimisation")
            logger.info("=" * 70)
            from src.latency_optimization import main as latency_opt_main

            latency_opt_main()

    elapsed = time.perf_counter() - t_start
    logger.info("=" * 70)
    logger.info("Done through phase '%s' in %.1fs", args.until, elapsed)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
