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
METHODOLOGY.md §5 limitations; `total_debt`'s current/non-current split is
available in the raw source files if Phase 4 needs a coarser proxy.

## Phase 4 — Wallet model ⬜

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

## Phase 5 — Rigor layer ⬜ (30% of the marks lives here)

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

## Phase 6 — Opportunity ranking ⬜

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

## Phase 7 — Bonus modules ⬜ (only after 1–6 are working)

(a) **Cash cycle / payment timing**: per entity, model days between
outbound supplier legs and inbound collections to suggest optimal
engagement timing.

(b) **Latency**: instrument the LLM pipeline, add caching, batching, and
route simple classification to a small model reserving the large one for
hard cases. Produce a before/after latency and cost chart.

> Phase 2 already has the raw material for (b): `src/llm.py` logs latency
> + token counts for every call to `reports/llm_usage_log.jsonl`, and
> `MODEL_SMALL` (`gemini-2.5-flash-lite`) is already wired up but unused —
> Phase 7 is where it gets used, with a real before/after comparison
> against Phase 2's `gemini-2.5-flash` baseline.

## Phase 8 — Dashboard ⬜

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
