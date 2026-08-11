# Engineering Plan — Syn Bank Share of Wallet Intelligence Engine

This is the full phase-by-phase build plan for this submission, as scoped
at project kickoff (from hackathon.txt plus the team's own engineering
decisions on top of it). It is the **authoritative backlog** — `CLAUDE.md`'s
"what's next" is a pointer here, not a duplicate, and `README.md`'s status
checklist should always agree with the checkboxes below.

**Rule for whoever is working:** when you finish a phase, mark its checkbox,
add a short "**Built as:**" note (files + output paths + one-line result),
and link to the relevant METHODOLOGY.md section for the full rationale. Do
**not** delete or shorten the original spec text below when a phase is
done — later phases reference earlier design decisions, and the next agent
needs the full original ask, not just a summary of what got built.

---

## What we are building

A "Share of Wallet Intelligence Engine" for Syn Bank, a fictional SA
corporate and investment bank. For each of the 20 real JSE-listed corporate
clients actually present in the data (see "Data discrepancies" in
METHODOLOGY.md §0 — hackathon.txt says 50) we must:

  (a) estimate their TOTAL banking wallet in rands of bank revenue,
  (b) measure what share Syn Bank captures,
  (c) rank the gaps by expected commercial value,
  (d) explain each recommendation in language a non-technical senior banker
      can act on.

### Scoring weights that must drive every design decision
- 40% Business Insight & Commercial Acumen
- 30% Analytical Rigor
- 20% Gen AI Application
- 10% Presentation & Storytelling

### Critical domain rule — do not get this wrong
Share of wallet is a share of the **fee and margin pool** a client pays to
banks. It is **not** a share of transaction volume. R1bn of FX flow is not
R1bn of wallet; it is roughly R1–3m of revenue at 10–30bps. Every pillar
must convert observed flow or exposure into rands of **bank revenue** using
an explicit, named, documented yield assumption. All yield and intensity
assumptions live in a single config file (`config/assumptions.yaml`) with a
source or rationale comment on every line. **Never hardcode a coefficient
inline.**

### The key finding (narrative spine of the whole submission)
`memo` columns across the source files are >99.5% null. The non-null rows
cluster into 4 template phrases (syndicate participation / bridging
facility / loan drawdown / facility drawdown settlement) tied to 5
recurring counterparty names that read as banks. **Interpretation: Syn Bank
is settling the payment legs of credit facilities that competitors
originated. It holds the flow and has lost the credit.**

As briefed, this was verified in `cross_border_payments.csv` (R240m, 448
rows) and `trade_finance.csv` (~R163m, ~94 rows, non-bank beneficiaries).
**Phase 1 profiling found the same fingerprint is ~3x bigger**:
`transactional_banking.csv` carries it too (not mentioned in hackathon.txt)
— see METHODOLOGY.md §2.1 and §3 for the full, verified numbers
(**R692.8m primary-tier + R307.9m secondary-tier**, ~4,199 rows total).
This is now the number every later phase should build against, not the
original R403m.

---

## Phase 1 — Ingestion & profiling ✅ DONE

Load the three CSVs. `transactional_data.csv` (i.e. `transactional_banking.csv`)
is large: use DuckDB reading the CSV directly. The other two are small
(33MB, 3MB) — pandas is fine, do NOT build chunking infrastructure for
them. Emit a profiling report: row counts, entity coverage, date ranges,
null rates, cardinality of every categorical. Assert the 20 expected
entity_ids are present and fail loudly if not.

**Built as:** `src/ingest.py`. Output: `reports/profiling_report.{json,md}`.
Entity ground truth: `src.common.EXPECTED_ENTITIES`. Full writeup:
METHODOLOGY.md §2.

## Phase 2 — Forensic extraction [Gen AI component 1] ✅ DONE

Isolate all non-null memo rows across both files (~542 rows — small, so
this is cheap). Use an LLM to extract structured fields from the free text:
`lender_name`, `facility_type` (syndicate|bridging|bilateral|other),
`external_reference`, `confidence_score`. Cache by memo string hash so
reruns are free. Cross-check LLM output against a deterministic regex
baseline and REPORT THE DISAGREEMENT RATE — we need a measurable accuracy
claim for the 20% Gen AI criterion. Output:
`data/processed/competitor_credit_events.parquet`.

**Built as:** `src/forensics.py` + `src/llm.py` (shared Gemini wrapper: all
future LLM phases must go through `src.llm.generate_structured`, not call
the SDK directly). Scope expanded to all 3 files / 4,199 rows once Phase 1
found the third vein (see above). Output:
`data/processed/competitor_credit_events.parquet`,
`reports/forensics_report.md`, `prompts/forensics_memo_extraction/*.json`
(4,199 logged calls). **Result: 36.7% overall disagreement, but 100.0%
agreement on `lender_name` and `external_reference` — all disagreement is
the LLM resolving the regex baseline's ambiguous `other` bucket into
`bilateral`, at a confidence that's monotonic in the evidence available
(0.60 → 0.90). Full breakdown: METHODOLOGY.md §3.**

---

## Phase 3 — External financial baseline [Gen AI component 2] ✅ DONE

For the 20 real listed entities, build a structured table of the latest
annual report figures: total revenue, foreign/offshore revenue %, cost of
sales, inventory, trade payables, trade receivables, total debt, debt
maturity profile, undrawn facilities, and geographic segment breakdown.
Where PDFs are supplied, use an LLM to extract to a strict JSON schema.
**CRITICAL: never let the model invent a number.** Every extracted value
must carry a source page reference and a confidence flag. Hand-label a
15–20 field sample into `tests/financials_ground_truth.csv` and report
field-level extraction accuracy. If a figure cannot be sourced, emit null
and let it propagate as widened uncertainty downstream — do NOT fill gaps
with plausible-looking estimates.

> **No PDFs were actually supplied** alongside the 3 CSVs (see
> METHODOLOGY.md §0 "Discrepancy 2"). This phase means real sourcing
> against public filings for the 20 entities in
> `src.common.EXPECTED_ENTITIES` (JSE SENS, company investor-relations
> pages, annual reports — hackathon.txt's Data section explicitly invites
> this, see also its "Hints and Tips" section). LLM's job shifts from
> "extract from a supplied PDF" to "extract from fetched/pasted filing
> text to the same strict schema" — the "never invent a number, cite a
> source, confidence-flag everything" requirement is unchanged. **Cite
> every external source in `reports/external_sources.md`** — entity,
> figure, value, source URL, retrieval date.

**Built as:** `src/financials.py`, raw source text committed at
`data/external/raw/`. Output: `data/processed/financial_baseline.parquet`,
`reports/financials_report.md`, `reports/external_sources.md`,
`prompts/financials_baseline_extraction/*.json`. **Result: ground-truth
accuracy 19/19 (100.0%)** on the hand-labelled sample
(`tests/financials_ground_truth.csv`) after finding and fixing a
systematic LLM fiscal-year-selection bug affecting 10/20 entities (see
METHODOLOGY.md §4.1) and disclosing a genuine cross-aggregator
definitional discrepancy on Anglo American's cost of sales rather than
silently picking a number (§4.2). `foreign_revenue_pct` coverage is
honestly low (30%, 6/20) — not backfilled. Debt maturity profile and
undrawn facilities were **not** built as separate fields this phase — see
METHODOLOGY.md §10 limitations; `total_debt`'s current/non-current split is
available in the raw source files if Phase 4 needs a coarser proxy.

## Phase 4 — Wallet model ✅ DONE

Build the total wallet bottom-up, structured under Syn Bank's OWN three
pillars as named in hackathon.txt: **Transactional Banking, Global
Markets, Investment Banking**. Suggested drivers (refine as the data
allows):

- **Transactional Banking**: revenue + opex → payment volume → fee per
  payment; average balances → deposit NII.
- **Global Markets**: foreign revenue + foreign COGS + FX debt → hedged
  notional → bps on turnover; floating-rate debt → IRS notional.
- **Investment Banking**: debt schedule, maturity wall, undrawn facilities
  → arrangement fees + margin; trade instruments → value × tenor_days/365
  × instrument-specific bps (guarantees price differently from LCs; use
  the `status` field to identify outstanding vs settled).

Then compute Syn Bank's captured revenue from internal data using the SAME
yields, so numerator and denominator are in identical units.

> Feeds from Phase 2's `competitor_credit_events.parquet` (primary/secondary
> tier split) directly into the Investment Banking pillar's competitor-held
> credit exposure. Every yield assumption goes in `config/assumptions.yaml`
> (skeleton already created) with a source/rationale comment — see
> CLAUDE.md "Must-know" #1.

**Built as:** `src/wallet.py`, `config/assumptions.yaml` fully populated
(with `low`/`high` ranges on every estimate, added for Phase 5). Output:
`data/processed/wallet_model.parquet` (long format, one row per entity ×
pillar × sub-component), `reports/wallet_report.md`. **Result: portfolio
TAM R18.6bn, captured R977.3m, blended share 5.3%** (sum of sub-components
where BOTH sides are observable on the SAME row — an independent-sum
version of this blend was briefly wrong at 4.6%, found and fixed before
Phase 5 built on it, see METHODOLOGY.md §5.3). Findings surfaced rather
than smoothed over: (1) a "TAM assumption breach" on Pepkor's
`deposit_nii` (captured exceeds TAM — the 15-day-of-revenue assumption is
demonstrably too conservative for that entity, flagged not clipped); (2)
dual-listed global majors (BHP, Glencore, Anglo American, AngloGold
Ashanti, Gold Fields, Prosus, Naspers, Shaftesbury) report GLOBAL not
SA-specific revenue, inflating their TAM denominator and making their low
share-of-wallet numbers not directly comparable to SA-domestic entities —
**Phase 6 must treat this cohort separately, not rank by raw gap size**;
(3) Investment Banking's row-aligned blended share is exactly 45.0% by
construction, not a real capture rate (its only observable sub-component's
TAM is derived from captured at a fixed 45% share) — a visible
illustration of a documented limitation, not a new finding to chase.
Three sub-components (`rate_hedging`, `debt_arrangement`,
`competitor_credit_gap`) have a captured side that's structurally
unobservable from the provided data (no derivatives book, no
"loans Syn Bank originated" table) — reported `None`, excluded from
blended shares, not treated as R0 capture. Full derivation: METHODOLOGY.md
§5. `debt_maturity_profile`/`undrawn_facilities` (Phase 3's scoped-out
fields) were not needed — `total_debt` alone drives the debt-arrangement
TAM.

## Phase 5 — Rigor layer ✅ DONE (30% of the marks lives here)

1. Monte Carlo over the assumption priors → report SOW as a credible
   interval, never a bare point estimate.
2. Tornado/sensitivity chart: which assumption moves the answer most.
3. A SECOND, independent SOW estimator based on revealed presence (share
   of observed corridors, instrument types and product breadth relative
   to sector peers of similar revenue). Triangulate the two. **Where they
   diverge is the most interesting slide in the deck — surface it
   explicitly.**
4. Sector regression of wallet-intensity (wallet / revenue) to flag
   clients sitting far below their sector line on any pillar.
5. Test for per-entity and per-corridor time trend. Aggregate quarterly
   volume is FLAT across 2023-07 to 2026-06 (R10.4–12.7bn, no drift) — if
   there is no per-client trend either, **SAY SO in limitations. Do not
   manufacture a trend.**

**Built as:** `src/uncertainty.py`; `config/assumptions.yaml` extended with
`low`/`high` on every leaf (same file Phase 4 uses, not a second set of
parameters). Output: `data/processed/monte_carlo_results.parquet`,
`tornado_sensitivity.parquet`, `revealed_presence.parquet`,
`sector_regression.parquet`, `time_trends_entity.parquet`,
`time_trends_corridor.parquet`, `reports/tornado_chart.png`,
`reports/uncertainty_report.md`. **Results, all five in one pass:**
(1) portfolio blended share credible interval **3.1%–6.8%** (base case
5.3%, median 4.6%) over 2,000 iterations; (2) tornado top-4 all in
Transactional Banking, `payments_per_zar_throughput` largest (3.3pp) —
confirms the assumption already flagged as least-anchored in
`config/assumptions.yaml`; 5 assumptions show 0.00pp *share* swing by
construction (they only move TAM on sub-components with a structurally-
null captured side) — real, non-zero TAM impact shown separately, not
hidden; (3) revealed-presence estimator diverges systematically from the
yield-based one for 17/20 entities (this portfolio's clients are all
already broad users, limiting the method's power to discriminate) — the
one exception, Pepkor at –21.5pp, independently corroborates Phase 4's TAM
assumption breach finding; (4) sector regression flags 2 entities below
their sector line (Valterra Platinum, Clicks Group), R²=0.82 portfolio-
wide — genuinely informative signal concentrates in `debt_arrangement`/
`trade_finance_instruments` since Transactional Banking's TAM is
proportional to revenue by construction, muting that pillar's regression
by design, disclosed not hidden; (5) time trends: 0/5 corridors
significant even at raw p<0.05 (confirms Phase 1's aggregate flatness),
but **5/20 entities show a trend robust to Bonferroni correction** (BHP,
Anglo American, OUTsurance, Sanlam, NEPI Rockcastle) — both facts true at
once, neither hidden. Full derivation: METHODOLOGY.md §6.

## Phase 6 — Opportunity ranking ✅ DONE

Rank by EXPECTED VALUE, not gap size:

```
expected_value = wallet_gap × win_probability × margin
```

Derive `win_probability` from right-to-win signals available in the data:
existing product breadth with the client, corridor adjacency, whether we
already hold the transactional relationship, share momentum if it exists.
**Respect product sequencing** — you win FX off the back of payment flow,
not the reverse. Flag any recommendation that violates this.

> Corridor-gap note: there are only 5 currency pairs and ALL 20 entities
> use all 5, so currency-gap detection is dead (confirmed in Phase 1
> profiling — see `reports/profiling_report.md`). Country coverage ranges
> 10–22 of 34 and IS meaningful — compare against each client's published
> geographic segments (Phase 3 output).

**Built as:** `src/opportunity.py`; `config/assumptions.yaml` extended
with an `opportunity_ranking` section (`net_margin_realization`,
`win_probability_weights`, sequencing threshold/penalty — all named +
rationale'd, same file every phase uses). Output:
`data/processed/opportunity_ranking_entity.parquet` (headline, one row
per entity, ranked), `opportunity_ranking_pillar.parquet` (detail),
`reports/opportunity_report.md`. `wallet_gap` only counts sub-components
where captured is directly observable (the same row-alignment discipline
as Phase 4/5); the 3 structurally-unobservable-captured sub-components
contribute to a separate `unknown_capture_potential_zar` diagnostic,
never blended into the ranked figure. `win_probability` reuses Phase 5's
signals directly (revealed-presence breadth, Transactional Banking share
as relationship strength, the Bonferroni-trend signal as momentum,
country coverage as adjacency) rather than re-deriving them.

**Result: top SA-domestic opportunity is Shoprite Holdings** (R193.8m
expected value, R555.5m wallet gap, Transactional Banking). Dual-listed
global majors ranked in a separate section per Phase 4/5's explicit
handoff instruction (Glencore alone would otherwise show a R3.13bn
"opportunity" purely from its inflated global-revenue TAM denominator).
**Product-sequencing flag fires on 30/40 Global Markets/Investment
Banking rows** — a real portfolio-level finding (Syn Bank's
Transactional Banking capture is thin almost everywhere, per Phase 4's
4.9% blended TB share), not an over-triggered threshold. Pepkor ranks
lower (8th) than its raw size might suggest because its Phase 4 TAM
assumption breach floors its `deposit_nii` gap at 0 — the honest
propagation of a finding disclosed two phases ago, not a new issue.
`breadth_score` shows the same low-discriminating-power pattern already
found in Phase 5 (this portfolio's clients are all already broad
product users) — disclosed, not hidden. Full derivation: METHODOLOGY.md
§7.

## Phase 7 — Bonus modules ✅ DONE (built after 1–6 and 8, per the re-sequencing below)

> Built AFTER Phase 8 instead of before it — hackathon.txt's Deliverables
> list makes the dashboard a required submission component; this phase is
> explicitly labelled "bonus" in hackathon.txt itself. See CLAUDE.md's
> Phase 8 session log entry for the full reasoning.

(a) **Cash cycle / payment timing**: per entity, model days between
outbound supplier legs and inbound collections to suggest optimal
engagement timing.

**Built as:** `src/cash_cycle.py`. The literal "days between" ask was
checked against the data FIRST and doesn't hold at day grain — volume-
weighted day-of-month for `collections` vs `supplier_payments` converges
to the same day (~15-16) for every one of the 20 entities, because daily
volume within a month is ~uniform (7-8% CV) and day-of-week volume is
uniform too (<1% CV). Disclosed as a dead signal, the same discipline
already applied to the FX currency-pair dead signal (§6.3) and
`breadth_score` clustering (§7.2), rather than manufacturing a ranking
from noise straddling a 30-day wraparound. Pivoted to the grain the data
DOES support: month-of-year seasonality. 7 of 20 entities clear a 15% CV
threshold, and the pattern is sector-coherent — all 4 consumer/retail
entities (Shoprite, Bid Corporation, Pepkor, Clicks) rank in the top 5,
every one peaking in December (pre-Christmas retail volume). No revenue
figure is estimated (descriptive/behavioural only, per the assumption-
naming discipline). Output: `data/processed/cash_cycle_timing.parquet`,
`reports/cash_cycle_report.md`, `reports/cash_cycle_chart.png`. 3 tests
in `tests/test_cash_cycle.py`.

(b) **Latency**: instrument the LLM pipeline, add caching, batching, and
route simple classification to a small model reserving the large one for
hard cases. Produce a before/after latency and cost chart.

> Phase 2 already has the raw material for (b): `src/llm.py` logs latency
> + token counts for every call to `reports/llm_usage_log.jsonl`, and
> `MODEL_SMALL` is already wired up but unused — Phase 7 is where it gets
> used, with a real before/after comparison against Phase 2's
> `gemini-2.5-flash` baseline.

**Built as:** `src/latency_optimization.py`. Caching/prompt-logging were
already live since Phase 2 (`src.llm.generate_structured`) — this module
adds the piece that wasn't built yet: routing, using Phase 2's existing
`regex_confidence` signal (0.85 = explicit keyword match = "simple", 0.40
= "hard") to send simple rows to `MODEL_SMALL`, hard rows staying on
`MODEL_DEFAULT` exactly as Phase 2 already ran them. `gemini-2.5-flash-lite`
(the originally-planned `MODEL_SMALL`) returned a 404 "no longer available
to new users" on a live call — swapped to `gemini-3.1-flash-lite`
(confirmed working, pricing sourced from ai.google.dev/gemini-api/docs/pricing).
"Before" is Phase 2's REAL historical run (`reports/llm_usage_log.jsonl`,
not resimulated); "after" extrapolates a fresh 100-row `MODEL_SMALL`
sample to the full 4,199-row workload. Safety check: 100% `facility_type`
agreement between the fresh `MODEL_SMALL` answers and Phase 2's original
`MODEL_DEFAULT` answers on the same rows. Result: 11% cost saved, ~flat
compute time (gemini-3.1-flash-lite's price gap vs. gemini-2.5-flash is
narrower than the originally-planned pairing, and it isn't reliably
faster per-call — reported plainly rather than only showing the metric
that improved). Output: `data/processed/latency_optimization_sample.parquet`,
`reports/latency_optimization_report.md`, `reports/latency_optimization_chart.png`.
5 tests in `tests/test_latency_optimization.py`.

## Phase 8 — Dashboard ✅ DONE

Streamlit. Must contain, per the brief's deliverables list:
- portfolio-level summary ranking all 20 clients by expected value
- per-client drill-down
- opportunity heatmap (client × pillar)
- AI-generated briefing notes for AT LEAST 3 clients
- the competitor-credit finding as a dedicated view

Every number shown must trace back to a computed value. Briefing notes are
generated from model output, not free-generated — state this on the page.
Graph visuals: constrain to one client at a time, top-N counterparties by
value, annotated with the insight. No 241k-edge hairballs.

**Built as:** `app/dashboard.py` (Streamlit, 6 pages: Portfolio Summary,
Client Drill-Down, Opportunity Heatmap, AI Briefing Notes, Competitor-
Credit Finding, Rigor & Assumptions — the last one added beyond the
brief's minimum since 30% of the mark scheme is analytical rigor and it
deserved visibility). `src/briefing.py` is the new (third) Gen AI
component the AI-briefing-notes requirement needed — generates one for
all 20 entities (not just the required 3), grounded strictly in Phase
2–6's already-computed output, through the same `generate_structured`
pipeline (prompt logging, caching) every other Gen AI phase uses. Output:
`data/processed/briefing_notes.parquet`, `reports/briefing_notes.md`,
`prompts/client_briefing_notes/*.json`.

Run: `streamlit run app/dashboard.py` (separate from `run_all.py`'s CLI
chain, which now includes `briefing` as its 7th phase to keep the
dashboard's briefing notes fresh).

**Verified by actually driving the running app** (Playwright, headless,
screenshotted all 6 pages, zero console errors), not just checking the
code imports — caught and fixed two real issues this way: the wallet-gap-
by-pillar chart's category order wasn't pinned (varied per entity,
breaking cross-client comparability), and the briefing-notes page
defaulted to showing global majors first (their inflated expected-value
figures dominate any unfiltered sort) instead of the realistic SA-
domestic opportunities every other page treats as primary. Full
derivation: METHODOLOGY.md §8.

---

## Non-negotiables (apply to every phase, not just one)

- Reproducible: `requirements.txt` pinned, single `python run_all.py`
  entry point (chains every phase; extend it as each phase lands).
- Every assumption documented in `METHODOLOGY.md` with rationale and
  limitation, written incrementally per phase — not as a last-minute
  writeup.
- Do not fabricate financial figures. Null propagates; it does not get
  filled.
- Log all LLM prompts to `prompts/` — the brief requires evidence of the
  Gen AI workflow. (Handled automatically by `src.llm.generate_structured`
  — do not bypass it.)
- The brief mentions 50 clients; the data has 20. Noted in
  METHODOLOGY.md §0 rather than glossed over.
