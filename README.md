# Syn Bank Share of Wallet Intelligence Engine

Data School Hackathon 2026 (Standard Bank CIB sponsored) submission. Estimates
each of Syn Bank's 20 JSE-listed corporate clients' total banking wallet
(in rands of *bank revenue*, not transaction flow), quantifies Syn Bank's
captured share across its three pillars (Transactional Banking, Global
Markets, Investment Banking), and ranks growth opportunities by expected
commercial value.

Read **[hackathon.txt](hackathon.txt)** for the brief and
**[METHODOLOGY.md](METHODOLOGY.md)** for every assumption, modelling choice,
and limitation behind this pipeline.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Data:** copy the three hackathon-provided CSVs into `data/` as
`transactional_banking.csv`, `cross_border_payments.csv`, and
`trade_finance.csv` (gitignored — 392MB+33MB+3MB exceeds GitHub's 100MB
single-file limit, so they're not in this repo).

**Gen AI (Gemini):** copy `.env.example` to `.env` and fill in a Gemini API
key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey):

```
GEMINI_API_KEY=your-key-here
```

Every phase that calls an LLM degrades gracefully to a regex/deterministic
baseline if no key is configured (clearly flagged in its output) — you can
run the whole pipeline without a key, just without the Gen AI components.

## Run

```bash
python run_all.py                    # every phase built so far, in order (Phases 1-6 + Phase 8's briefing step)
python run_all.py --until forensics   # stop after Phase 2
python run_all.py --no-llm            # skip all LLM calls
python run_all.py --sample 200        # Phase 2: sample instead of the full ~4,199 memo rows
python run_all.py --mc-iterations 200 # Phase 5: faster/rougher Monte Carlo (default 2000, ~3min)

python -m streamlit run app/dashboard.py        # Phase 8 dashboard -- interactive, run separately
```

Every phase is also independently runnable, e.g. `python -m src.ingest` or
`python -m src.forensics --sample 40`.

## Repo layout

```
config/assumptions.yaml        every yield/intensity assumption, named + sourced (Phase 4)
src/
  common.py                    shared paths, the 20-entity master list, the
                                competitor-beneficiary fingerprint constants
  llm.py                       Gemini client wrapper: prompt logging, response
                                caching, per-call usage ledger
  ingest.py                    Phase 1 -- DuckDB load + profiling report
  forensics.py                 Phase 2 -- competitor-credit memo extraction [Gen AI]
  financials.py                Phase 3 -- external financial baseline [Gen AI]
  wallet.py                    Phase 4 -- total wallet + Syn Bank's captured share
  uncertainty.py                Phase 5 -- Monte Carlo, sensitivity, triangulation
  opportunity.py               Phase 6 -- expected-value opportunity ranking
  briefing.py                  Phase 8 support -- AI client briefing notes [Gen AI #3]
  cash_cycle.py                Phase 7 bonus (a) -- cash-cycle/seasonality timing
  latency_optimization.py      Phase 7 bonus (b) -- model-routing before/after latency & cost
app/dashboard.py                Phase 8 -- Streamlit dashboard (run: python -m streamlit run app/dashboard.py)
data/external/raw/             Phase 3's fetched source text (committed, evidence for extraction)
data/processed/                derived tables (parquet) + the DuckDB database
reports/                       profiling/forensics/financials/... reports, LLM usage ledger, external_sources.md
prompts/                       every LLM call ever made, logged verbatim (Gen AI evidence)
tests/                         pytest unit tests (regex baselines, ground-truth checks)
notebooks/                     pipeline_walkthrough.ipynb -- executed walkthrough of every phase's real output
submission/                    hackathon submission package (one-pager + slides, PDF and editable HTML)
run_all.py                     single reproducible entry point
CLAUDE.md                      handoff doc: gotchas, conventions, session log -- read first
PLAN.md                        full phase-by-phase backlog (authoritative scope)
METHODOLOGY.md                 assumptions, rationale, limitations
```

## Status & handoff

Picking this up in a new session — human or agent? Read **[CLAUDE.md](CLAUDE.md)**
first: critical gotchas, working conventions, and a session log of what's
happened so far. **[PLAN.md](PLAN.md)** is the full phase-by-phase backlog
(original spec for every phase, done or not). Current status:

- [x] Phase 1 — Ingestion & profiling
- [x] Phase 2 — Forensic extraction (Gen AI #1)
- [x] Phase 3 — External financial baseline (Gen AI #2)
- [x] Phase 4 — Wallet model
- [x] Phase 5 — Rigor layer (Monte Carlo, sensitivity, triangulation)
- [x] Phase 6 — Opportunity ranking
- [x] Phase 7 — Bonus: cash-cycle timing, latency/cost optimisation
- [x] Phase 8 — Dashboard + AI briefing notes (Gen AI #3) — built ahead of Phase 7, see CLAUDE.md session log

All of hackathon.txt's required deliverables are built, plus the Phase 7 bonus modules.
