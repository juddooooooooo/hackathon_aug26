# Methodology — Syn Bank Share of Wallet Intelligence Engine

This document explains every assumption, modelling choice, and limitation
behind the pipeline, in the order the pipeline itself runs. It is written
incrementally as each phase is built (see `src/`) rather than reconstructed
after the fact, so section numbering follows the phases in `run_all.py`.

Scoring weights this whole design optimises for (hackathon.txt):
**40% Business Insight & Commercial Acumen, 30% Analytical Rigor, 20% Gen AI
Application, 10% Presentation & Storytelling.**

---

## 0. Data received — and discrepancies from the brief

Three CSVs, dropped in `data/` (renamed from their hackathon download names
— `transactional_banking (1).csv` → `transactional_banking.csv`, etc. —
for cross-platform path safety; content untouched):

| File | Size | Rows | Grain |
|---|---|---|---|
| `transactional_banking.csv` | 392MB | 2,802,875 | Domestic ledger legs (collections, supplier payments, intercompany sweeps, payroll, tax) |
| `cross_border_payments.csv` | 33MB | 241,117 | SWIFT-style cross-border payment messages |
| `trade_finance.csv` | 3MB | 20,303 | Trade instruments (LCs, guarantees, export collections) |

**Discrepancy 1 — client count.** hackathon.txt describes "a portfolio of 50
JSE-listed corporate clients." All three files consistently contain exactly
**20** distinct `entity_id` values (E01–E20), validated to agree on
`entity_name` and `sector` across all three files (`src/ingest.py
validate_entity_master`, which fails loudly if this ever drifts). We build
against the 20 entities actually present and note the discrepancy here
rather than silently assuming 50.

**Discrepancy 2 — no financial-statement PDFs supplied.** hackathon.txt's
data table mentions "a mapped set of public financial statement inputs."
No such files were provided alongside the three CSVs. Phase 3
(`src/financials.py`) therefore sources the 20 clients' annual report
figures from public filings directly (JSE SENS, company investor-relations
pages, annual reports) rather than extracting from supplied PDFs — see
Phase 3 section below once built. Every external figure is cited by URL and
carries a source/confidence flag; nothing is invented.

## 1. The domain rule that drives every design decision

**Share of wallet is a share of the fee-and-margin pool a client pays to
banks — not a share of transaction volume.** R1bn of FX flow observed in the
ledgers is not R1bn of wallet; at a plausible 10–30bps all-in margin it's
roughly R1–3m of *revenue*. Every pillar in this pipeline converts observed
flow or exposure into rands of bank revenue using an explicit, named,
sourced yield assumption. All such assumptions live in
`config/assumptions.yaml` (built in Phase 4) with a rationale/source comment
on every line — never hardcoded inline in modelling code.

Every profiling/EDA artefact this pipeline produces is labelled to make this
distinction impossible to miss (e.g. `reports/profiling_report.md` opens
with an explicit "this is gross flow, not revenue" banner).

## 2. Phase 1 — Ingestion & profiling (`src/ingest.py`)

- `transactional_banking.csv` (392MB) is read directly off disk by DuckDB —
  never materialised whole into pandas. The two smaller files are also
  loaded through DuckDB so every later phase queries one persisted engine
  (`data/processed/syn_bank.duckdb`) instead of re-parsing CSVs.
- **Entity master validation** (`validate_entity_master`): asserts all 20
  expected `entity_id`s are present in every file, with consistent
  `entity_name`/`sector`, matching a hardcoded ground-truth table in
  `src/common.py`. Raises `EntityCoverageError` and stops the pipeline if
  the data ever drifts from this — "fail loudly," per the brief.
- **Data quality fixes applied, documented, not silent:**
  - `currency` has a case inconsistency (`ZAR` 2,774,594 rows vs. `zar`
    28,281 rows in `transactional_banking.csv`). A derived `currency_norm =
    UPPER(TRIM(currency))` column is added alongside the raw column so the
    report shows the issue explicitly rather than fixing it invisibly.
  - `counterparty_country` is ~1.5% null in both `cross_border_payments.csv`
    and `trade_finance.csv` — carried through as null, not imputed.
- Full output: `reports/profiling_report.{json,md}`.

### 2.1 The competitor-credit fingerprint — verified, and larger than briefed

The brief's key finding (verified in `cross_border_payments.csv` and
`trade_finance.csv`): a `memo` field that is >99.5% null across every file
has non-null rows that cluster into 4 template phrases ("Syndicate
participation settlement", "Bridging facility settlement", "Loan drawdown
proceeds", "Settlement re: facility drawdown"), each followed by a
free-text reference number. In `cross_border_payments.csv`, all 448
non-null-memo rows (R240.4m) pay one of 5 recurring counterparty names
(`Halcyon Trade Bank`, `Meridian Bank Ltd`, `Northgate Financial Bank`,
`Solstice Capital Bank`, `Crestwood Merchant Bank`) that appear *only* on
these templated rows, and are mislabelled `corridor_type = 'trade'` in
100% of cases (it isn't trade — it's credit settlement). In
`trade_finance.csv`, a further 94 rows (R163.1m) carry identical memo
language but on instruments with *non-bank* beneficiaries.

**Phase 1 profiling found the same fingerprint in `transactional_banking.csv`
too — not mentioned in the original brief.** That file has its own `memo`
column (99.87% null), and its 3,657 non-null rows split cleanly along
`leg_type`:

| | leg_type | beneficiary | rows | R value |
|---|---|---|---:|---:|
| Same 5 counterparties | `intercompany_sweeps` | one of the 5 known names | 1,544 | R452.4m |
| Ordinary trade counterparties | `supplier_payments` | ordinary supplier (e.g. "Metro Retail Supplies") | 2,113 | R144.9m |

This is a clean, mechanical split (100% of `intercompany_sweeps`-with-memo
rows go to the 5 known names; 100% of `supplier_payments`-with-memo rows go
to ordinary counterparties) — not a judgement call. It roughly **triples**
the high-confidence portion of the headline finding (R240.4m → R692.8m
combining `cross_border_payments` + `transactional_banking` bank-beneficiary
rows) and adds a much larger secondary-tier pool (R144.9m vs. the
previously-known R163.1m). See `reports/profiling_report.md` §"Competitor-
credit memo fingerprint" for the numeric cross-tab; interpretation and
per-row extraction happens in Phase 2.

## 3. Phase 2 — Forensic extraction (`src/forensics.py`) [Gen AI #1]

**Scope.** All 4,199 non-null-memo rows across all three files (1,992
"primary" tier + 2,207 "secondary" tier — see below), not just the ~542
rows in the two files the brief describes. Still cheap: a few thousand
short-text classifications.

**Two-tier confidence, by construction (not by LLM judgement).** A row is
`primary` tier if `beneficiary_name` is one of the 5 recurring counterparties
that *only ever* appear on templated memo rows (high confidence this is
genuine competitor-credit settlement); `secondary` tier otherwise (same
template language, ordinary counterparty — could be loan proceeds being
on-forwarded to a supplier, could be a labelling artefact of the synthetic
data generator; we cannot distinguish the two from the data alone). The
secondary tier is reported separately and is **not** added to the primary
tier's rand total in the headline finding — see Phase 4/6 for how each tier
is treated in the wallet model and opportunity ranking.

**Why the LLM sees `memo` + `beneficiary_name` jointly, not memo alone.**
Every observed memo is one of exactly 4 short templates; none names a
lender inline. `lender_name` is only recoverable by judging whether
`beneficiary_name` denotes a financial institution — a real (if narrow) NLP
judgement call, not a lookup. Feeding memo-only text would leave
`lender_name` null on 100% of rows, which would make the field vacuous.

**Regex baseline (deterministic, `src/forensics.py`):**
- `facility_type`: keyword match on `syndicat|bridg|bilateral` (word-boundary,
  case-insensitive) → `syndicate`/`bridging`/`bilateral`; else `other`. Two
  of the four real templates ("Loan drawdown proceeds", "Settlement re:
  facility drawdown") contain none of these keywords and fall to `other` —
  this is deliberately where the LLM has room to add judgement beyond the
  baseline (see disagreement rate below).
- `external_reference`: regex `ref\.?\s*(\d+)` extracts the number following
  "ref" in the memo text — a different number from Syn Bank's own
  structured `reference` column (verified: e.g. `reference=LOAN-492997`,
  `memo="...- ref 897009"` — two different numbers), presumably the
  counterparty's own deal reference.
- `lender_name`: word-boundary match on "Bank" in `beneficiary_name` —
  **deliberately not** a lookup against the known-5 list (that would make
  the baseline circular). Verified clean on this dataset: every
  `beneficiary_name` containing "Bank" across all three files is either one
  of the 5 known names, or one of two generic correspondent-banking labels
  (`Bank Correspondent Transfer`, `FX Settlement - Correspondent Bank`)
  that never co-occur with a non-null memo row in practice. Pinned down in
  `tests/test_forensics.py`.
- `confidence`: a rule-based proxy (0.85 if an explicit facility-type
  keyword matched, else 0.40) — not a calibrated probability, exists only
  so the LLM's `confidence_score` has a deterministic number to sit next to.

**LLM extraction:** Google Gemini (`gemini-2.5-flash`, temperature 0,
thinking disabled — a short classification task doesn't need extended
reasoning, and keeping it off keeps the Phase 7 latency/cost baseline
honest), structured output via a strict Pydantic schema
(`MemoExtraction`: `lender_name`, `facility_type`, `external_reference`,
`confidence_score`, plus `reasoning` — one extra field beyond the brief's
minimum 4, added for auditability). Every call is cached by a hash of
`(model, system_instruction, prompt, beneficiary_name)` — not memo text
alone, because a memo-only hash would collide two different beneficiaries
sharing the same templated memo string (see `src/llm.py`). Every live call
is logged to `prompts/forensics_memo_extraction/*.json` (evidence of the
Gen AI workflow) and every call (hit or miss) is appended to
`reports/llm_usage_log.jsonl` (latency + token counts feeding the Phase 7
before/after chart).

**Disagreement-rate methodology:** for every row scored by both methods,
compare `facility_type`, `lender_name` (normalised), and
`external_reference` (normalised); `agree_all` requires all three to match.
Reported overall, per-field, per confidence-tier, and as a
`regex_facility_type × llm_facility_type` confusion table (so "the LLM
disagreed" is never a black box — you can see exactly which category pairs
it reclassified). See `reports/forensics_report.md` for the actual numbers
from this run.

**Results (full run, all 4,199 rows, `gemini-2.5-flash`):** overall
disagreement rate **36.7%** — but that number on its own is misleading
until you see where it lives. `lender_name` and `external_reference`
agreement are **100.0%** (0% disagreement) across all 4,199 rows: the LLM
never invents a lender the beneficiary field doesn't support, and never
misreads the embedded reference number. **All** of the 36.7% comes from
`facility_type`, and *only* from the regex baseline's `other` bucket (2,082
rows) — the two keyword-bearing categories (`bridging`, `syndicate`) agree
100% with the LLM, 1,080/1,080 and 1,037/1,037. Confusion table:

| regex | llm | n |
|---|---|---:|
| bridging | bridging | 1,080 |
| syndicate | syndicate | 1,037 |
| other | **bilateral** | 1,541 |
| other | other | 541 |

The LLM resolves 74% of the ambiguous `other` bucket into `bilateral`,
using exactly two evidence signals — and its `confidence_score` tracks
*how many* of those two signals are present, monotonically:

| memo template | beneficiary reads as bank | LLM call | n | mean confidence |
|---|---|---|---:|---:|
| "Loan drawdown proceeds" | yes | bilateral | 455 | **0.90** |
| "Loan drawdown proceeds" | no | bilateral | 544 | 0.70 |
| "Settlement re: facility drawdown" | yes | bilateral | 517 | 0.80 |
| "Settlement re: facility drawdown" | no | bilateral | 25 | 0.70 |
| "Settlement re: facility drawdown" | yes | other | 8 | 0.80 |
| "Settlement re: facility drawdown" | no | **other** | 533 | 0.60 |

Two signals ("loan" language + a bank-shaped counterparty) → 0.90.  One
signal → 0.70–0.80. Zero signals → the model declines to guess and stays
`other`, at its lowest stated confidence (0.60) — it is not just
classifying, it is visibly hedging in proportion to the evidence it
actually has. This is the "measurable" half of the Gen AI criterion: a
human reviewer can audit *why* every one of the 1,541 reclassifications
happened (`llm_reasoning` is stored per row in the parquet and is a direct
quote of the model's stated rationale), and the confidence signal is
internally consistent enough to threshold on (e.g. "surface only
`confidence_score` ≥ 0.8 reclassifications to a coverage banker").

Disagreement rate is higher on the `primary` tier (48.8%) than `secondary`
(25.8%) — primary-tier rows are disproportionately the "beneficiary is a
named bank" cases, which is exactly the sub-population the LLM is most
willing to commit `bilateral` on (0.80–0.90 confidence), so this is the
calibration behaving as expected, not a red flag.

By value: **primary tier R692.8m** (1,992 rows) / **secondary tier R307.9m**
(2,207 rows) across all three files combined. See `reports/forensics_report.md`
for the full report (regenerated by `python -m src.forensics`) and
`data/processed/competitor_credit_events.parquet` for the row-level output
feeding Phase 4.

**One limitation surfaced by this run, not smoothed over:** the `other`→`bilateral`
call for "Loan drawdown proceeds" rows fires 100% of the time regardless of
whether the beneficiary reads as a bank (999/999) — the model appears to
treat the word "loan" (singular) as sufficient on its own to imply a
single-lender structure, even with zero named counterparty. That's a
defensible linguistic reading, not a hallucination (it never invents a
*name*, only a *category*), but it means the `bilateral` label on the
544 non-bank-beneficiary "Loan drawdown proceeds" rows is inferred from
word choice alone, at correspondingly lower confidence (0.70) — flagged
here so it isn't presented with false precision.

## 4. Phase 3 — External financial baseline (`src/financials.py`) [Gen AI #2]

**Sourcing.** hackathon.txt explicitly invites supplementing the synthetic
internal data with public sources (annual reports, JSE SENS, National
Treasury, CIPC, DealMakers SA, Bloomberg open data, investor-relations
pages), provided they're cited — see §0 "Discrepancy 2" for why this phase
does real sourcing instead of PDF extraction. For cross-company consistency
at 20-entity scale, core financials (revenue, cost of sales, inventory,
trade receivables/payables, total debt) are sourced from
[stockanalysis.com](https://stockanalysis.com), a filings-derived
aggregator, using each entity's JSE listing where covered
(`stockanalysis.com/quote/jse/<TICKER>`) and its primary global listing
otherwise (dual-listed miners: BHP, Glencore, Anglo American, AngloGold
Ashanti, Gold Fields; Prosus on Euronext Amsterdam; Shaftesbury Capital on
LSE — same consolidated group accounts regardless of listing venue).
Foreign/offshore revenue share is sourced separately per entity from each
company's own results commentary where a specific figure exists — this is
inherently less standardisable and is null for entities where no confident
citable figure was found (11 of 20), consistent with the "null propagates"
rule rather than estimated from adjectives like "highly diversified."

Every fetch is saved verbatim at `data/external/raw/<entity_id>_*.md`
(income statement + balance sheet, with source URLs) and
`data/external/raw/geographic_foreign_revenue_notes.md` (foreign-revenue
research, one section per entity) — this is the Phase 3 analogue of
Phase 2's memo text: raw material that an LLM then extracts from, not
something hand-transcribed into the final schema.

**Extraction schema and pipeline shape mirror Phase 2 deliberately**
(`FinancialBaselineExtraction`, Gemini `gemini-2.5-flash`, structured
output, cached + logged via the same `src.llm.generate_structured`): every
numeric field carries its own `*_confidence` (`high`/`medium`/`low`), and a
`not_applicable_fields` list lets the model distinguish "this business
model doesn't have inventory" (insurers, REITs) from "not found in the
source text" — collapsing those two into one null would hide a genuine
modelling decision (Phase 4 needs to know insurers structurally have no
trade-finance-style inventory demand, not that we failed to find a number).
`cost_of_sales` is explicitly allowed to be *derived* (`revenue -
gross_profit`) when not directly disclosed, flagged `medium` confidence and
`cost_of_sales_is_derived=true` rather than left null — most of the fetched
income statements show gross profit but not cost of revenue as its own
line, so a strict "only extract labelled line items" rule would have left
this field almost entirely empty.

### 4.1 A systematic bug found, root-caused, and fixed mid-phase

The first full run picked the wrong fiscal year for **10 of 20 entities** —
FY2024 instead of the genuinely most-recently-completed year (FY2025, or
FY2026 for March-year-end entities), despite the later year's figures being
present and unambiguous in the same source text. This was not a uniform
"always picks the second-newest column" bug (Vodacom, Naspers, Prosus, BHP,
Glencore, Valterra, NEPI Rockcastle all picked correctly the first time) —
root cause traced to the model defaulting to a year that felt more familiar
from its own training distribution when the correct answer required
reasoning past that prior, most visibly on Anglo American, where a note we
ourselves added explaining FY2025's unusual revenue drop (an active
portfolio-restructuring year) appears to have given the model a reason to
prefer the "more normal-looking" FY2024 instead of the correct FY2025.

**Fix:** the system instruction now states today's date explicitly
(2026-08-11), gives an explicit fiscal-year-selection algorithm ("scan
every period-ending date in the text, pick the single latest one on or
before today"), and explicitly instructs that an unusual-looking latest
year is a reason to *keep* using it with a caveat, never a reason to fall
back. Re-running after this change fixed all 10 entities in one pass — see
`src/financials.py`'s `SYSTEM_INSTRUCTION` for the exact wording, and
`tests/financials_ground_truth.csv`'s E19/E16 entries, which exist
specifically as a regression check for this. **This is deliberately kept
in the writeup rather than quietly re-run until clean** — it's a concrete,
measured example of an LLM recency/anchoring bias, the kind of thing the
brief's Gen AI criterion asks to be surfaced, not hidden.

### 4.2 A cross-source definitional discrepancy, disclosed not resolved

Spot-checking Anglo American's FY2024 cost of sales against a second
aggregator (Yahoo Finance) surfaced a large, genuine disagreement:
stockanalysis.com's income statement implies cost of sales of ~$27.5bn
(gross profit **–**$228m) for FY2024, while Yahoo Finance shows cost of
revenue ~$14.1bn (gross profit +$13.2bn) for the same company-year. Both
numbers are internally consistent with *something* real — Anglo American
recognised $3.8bn of net impairments in FY2024, and the two aggregators
most likely differ on whether impairments sit inside "cost of sales" or
below it. This was **not** resolved by picking a winner; it's disclosed
here and the pipeline's `cost_of_sales_is_derived` + `medium` confidence
flag on every derived figure exists precisely so a result like this can't
be mistaken for a precise, agreed-upon number. Anyone building on
`cost_of_sales` downstream (Phase 4's Transactional Banking driver) should
treat it as directional for companies with a large impairment/exceptional
item in the reference year, not a clean COGS line.

### 4.3 Results

**Coverage** (20/20 entities, after the fiscal-year fix): `total_revenue`
100%, `total_debt` 100%, `trade_payables` 90%, `trade_receivables` 85%,
`cost_of_sales` 85% (4 correctly `not_applicable` — 2 insurers, 2 REITs),
`inventory` 75% (same 4 `not_applicable`, plus genuine gaps), `foreign_revenue_pct`
**30%** (6/20) — the one field where "we didn't find a clean citable number"
dominates, by design not filled in. See `reports/financials_report.md` for
the full per-field confidence breakdown.

**Ground-truth accuracy: 19/19 (100.0%)** on a hand-labelled sample
(`tests/financials_ground_truth.csv`) spanning core revenue/debt figures,
derived fields, not-applicable handling, and the fiscal-year-selection
regression check above — independently re-verified against primary/
alternate sources (BHP's and MTN's own results releases, Yahoo Finance,
Wikipedia for NEPI Rockcastle's portfolio composition), not just re-read
from the same aggregator the pipeline used.

## 5. Phase 4 — Wallet model (`src/wallet.py`)

Builds, per entity, per sub-component under Syn Bank's own three pillars
(Transactional Banking, Global Markets, Investment Banking): a **TAM**
(total addressable wallet, all banks) and Syn Bank's **captured** revenue,
both in rands of bank revenue via the named yield/intensity assumptions in
`config/assumptions.yaml`. Every fee/margin/bps assumption is disclosed as
an *informed market-practice estimate* with a plausible range in its
comment, not a scraped published rate card (SA banks don't publish these)
— each is a designated Phase 5 Monte Carlo / tornado-sensitivity input.
FX spot rates (USD/GBP/EUR → ZAR, needed because Phase 3's entities report
in 4 different currencies while every internal ledger is 100% ZAR) are the
one genuinely-sourced figures in the file — see `reports/external_sources.md`.

**Design principle:** captured and TAM are computed with the *same* yield
for every sub-component where both sides are observable, so
`share_of_wallet = captured / tam` is a like-for-like ratio. Three
sub-components (`rate_hedging`, `debt_arrangement`, and the diagnostic
`competitor_credit_gap` row) have a captured side that is **structurally
unobservable** from the three source files — no derivatives/swap book and
no "loans Syn Bank itself originated" table exists anywhere in the
provided data. These are reported with `captured_zar = None`, not `0` —
conflating "we don't know" with "Syn Bank captured nothing" would
understate the pillar's true (unknown) capture and overstate the
opportunity size.

### 5.1 Pillar-by-pillar

**Transactional Banking** — `payment_fees`: captured = observed Syn Bank
transaction count per channel (`transactional_banking.csv`) × a
channel-specific fee (SWIFT priced highest, Internal Transfer lowest, per
market practice); TAM = (`total_revenue` + `cost_of_sales`, Phase 3) as a
gross-throughput proxy × a payments-per-rand intensity assumption × a
blended fee — the "revenue + opex → payment volume" driver named
explicitly in the brief. `deposit_nii`: captured = an average operating
balance computed **directly from the ledger** (daily net inflow/outflow
per entity, cumulative-summed into a running balance, floored at 0,
averaged over the 3-year window — no assumption needed for this side) ×
a deposit margin; TAM = `total_revenue` × an assumed days-of-revenue
operating-cash-balance × the same margin.

**Global Markets** — `fx_hedging`: captured = observed
`cross_border_payments.csv` turnover (100% coverage) × an FX margin
(hackathon.txt's own worked example, 10–30bps); TAM = `foreign_revenue_pct`
(Phase 3, only 30% coverage — null-propagates for the other 70%, per
METHODOLOGY.md §4.3) × `total_revenue` × an assumed hedge ratio × the same
margin. `rate_hedging` (IRS on floating-rate debt): TAM only, from
`total_debt` × an assumed floating-rate share × an IRS margin — captured
is structurally unobservable (see above).

**Investment Banking** — `trade_finance_instruments`: fully computable
both sides from `trade_finance.csv` — captured = Σ(`value_zar` ×
`tenor_days`/365 × an **instrument-specific** bps, guarantees priced
above LCs above export collections, per the brief's explicit instruction);
TAM is grossed up from captured by an assumed "share of a client's
trade-finance business a primary-but-not-sole bank typically holds" —
flagged in `config/assumptions.yaml` as the single most assumption-driven
TAM in the model, since no external trade-finance-market-size figure
exists anywhere in Phase 3. `debt_arrangement`: TAM = `total_debt`
(company-wide, source-agnostic — genuinely the full market regardless of
which bank(s) hold it) × an arrangement-fee bps, amortised over an
assumed refinancing cycle; captured is structurally unobservable.
`competitor_credit_gap` (diagnostic, not additive to the TAM above): Phase
2's `competitor_credit_events.parquet` flow, converted to a
revenue-equivalent using the *same* arrangement-fee bps as `debt_arrangement`
— explicitly flagged as a lower-bound proxy (settlement-leg payment value
is not the same thing as confirmed facility principal) confirming wallet
held elsewhere, feeding Phase 6's opportunity ranking directly rather than
being folded into a single TAM number with false precision.

### 5.2 Two findings this run surfaced, not smoothed over

**TAM assumption breaches.** Pepkor Holdings' `deposit_nii` sub-component
shows `share_of_wallet = 121.4%` — captured (R95.2m, computed directly
from the ledger) exceeds the assumed TAM (R78.4m, from a 15-day-of-revenue
heuristic). This is logically impossible for a genuine total-addressable
market and was **not clipped to 100%** — clipping would hide the real
signal, which is that the 15-day assumption is demonstrably too
conservative for at least this entity (a high-volume cash-generative
retail group plausibly runs materially larger consolidated collection
balances than a blanket days-of-revenue heuristic predicts). Flagged
programmatically (`tam_assumption_breach` column) and in
`reports/wallet_report.md`'s dedicated callout — a concrete, named example
for Phase 5's sensitivity work, not a bug papered over.

**Dual-listed global majors distort their own denominator.** BHP,
Glencore, Anglo American, AngloGold Ashanti, Gold Fields, Prosus, Naspers,
and Shaftesbury Capital (`GLOBAL_MAJOR_ENTITIES` in `src/wallet.py`) report
`total_revenue` (Phase 3) as their **entire global** figure — there is no
South-Africa-specific revenue split available anywhere in the source data.
Every TAM computed from that revenue is therefore an upper bound on a
*global* scale, not a realistic addressable market for a SA-focused bank:
these entities' unusually low share-of-wallet numbers (e.g. BHP's payment-
fees share is 0.4%) reflect an inflated denominator — Syn Bank was never
competing for BHP's global treasury mandate — not a large realistic growth
opportunity. Reported prominently rather than left for a reader to
discover by accident; **Phase 6 should discount or separately flag this
cohort rather than rank them purely on raw wallet-gap size** (see the
dedicated callout in `reports/wallet_report.md`).

### 5.3 A bug found computing the blend, fixed before Phase 5 built on it

The first version of the portfolio-level blend summed `tam_zar` and
`captured_zar` **independently** (`dropna()` per column, then sum) rather
than only over rows where both are observable. This double-dips:
`fx_hedging`'s captured leg is observable for every entity (we always see
FX turnover in `cross_border_payments.csv`), but its TAM is null for the
14/20 entities missing `foreign_revenue_pct` — an independent-sum blend
counted that captured revenue (R218.9m across those 14 entities) in the
numerator with no matching TAM in the denominator, inflating the blended
portfolio share from a correct 5.3% to a wrong 4.6%. Fixed
(`src.wallet.blended_tam_and_captured`, row-aligned sum, regression-tested
in `tests/test_wallet.py`) before this number propagated into Phase 5 or
Phase 6 — caught by the same discipline as every other bug on this
project: check the actual numbers, don't trust that a script running
without an exception means the output is correct.

### 5.4 Results

Portfolio-level (sum of observable sub-components on the SAME row,
`reports/wallet_report.md`): **TAM R18.6bn, captured R977.3m, blended
share 5.3%.** By pillar: **Investment Banking 45.0%** — but this figure is
circular by construction (§5.1: its only row-aligned sub-component,
`trade_finance_instruments`, has TAM *derived from* captured at a fixed
45% share, so it cannot show anything other than exactly 45% — a visible,
concrete illustration of the limitation already flagged in
`config/assumptions.yaml`, not a real 45% capture rate). Transactional
Banking 4.9%, Global Markets 3.8% (now a much smaller, more honestly-based
blend — only the 6 entities with a sourced `foreign_revenue_pct`
contribute). Per-entity share ranges from 0.6% (Valterra Platinum) to
62.7% (Pepkor Holdings, partly inflated by the TAM assumption breach
above — read alongside §5.2, not at face value).

## 6. Phase 5 — Rigor layer (`src/uncertainty.py`)

30% of the mark scheme lives in this phase. Five analyses per hackathon.txt's
own Phase 5 spec, all built on the SAME `config/assumptions.yaml` Phase 4
uses — `low`/`high` ranges were added to every leaf specifically for this
phase (see the file's own comments), never a second, disconnected set of
"uncertainty parameters" invented after the fact.

**Performance note, since it shapes the design:** `src/wallet.py`'s
`build_wallet_model()` was refactored to accept pre-loaded internal
ledgers / financials / competitor events, so Monte Carlo iterations only
re-run the (cheap) yield arithmetic, not the (expensive) DuckDB/parquet
reads — 2,000 iterations run in under 3 minutes.

### 6.1 Monte Carlo credible interval

Every wallet-model assumption (17 leaves under `transactional_banking`,
`global_markets`, `investment_banking` — FX spot rates excluded, they're
observed facts not estimates) is sampled uniformly between its `low` and
`high` bound, 2,000 times, recomputing the full wallet model each draw.
**Result: portfolio blended share 5.3% base case, 5th–95th percentile
credible interval 3.1%–6.8%** (median 4.6%). By pillar, Investment
Banking's interval is wide (36.1%–53.9%) because — as §6.2 below makes
explicit — its only row-aligned sub-component is *mechanically* bounded by
the `primary_bank_trade_finance_share` assumption's own low/high range.
**The headline number for this submission is the interval, not the 5.3%
point estimate** — reporting a bare point estimate for a figure this
assumption-dependent would misrepresent the actual precision achieved.

### 6.2 Tornado sensitivity

Each of the 17 assumptions is varied across its full range with every
other assumption held at its base-case value; the resulting swing in
portfolio blended share is measured and ranked (`reports/tornado_chart.png`,
`data/processed/tornado_sensitivity.parquet`). **Top 4, all in
Transactional Banking**: `payments_per_zar_throughput` (3.3pp swing —
exactly the assumption flagged in `config/assumptions.yaml` as
least-anchored, confirmed empirically, not just by intuition),
`fee_per_payment_zar.SWIFT`, `avg_balance_days_of_revenue`,
`deposit_nii_margin_bps`.

**5 assumptions show exactly 0.00pp swing** on the blended-share metric —
not a bug, and specifically not evidence those assumptions don't matter.
`blended_tam_and_captured` (§5.3) only sums sub-components where BOTH
sides are observable on the same row; `floating_debt_ratio`,
`refinancing_cycle_years`, `arrangement_fee_bps`, `irs_margin_bps`, and
`competitor_facility_arrangement_bps` exclusively drive TAM on the 3
sub-components with a structurally-unobservable captured side, which are
excluded from the share RATIO by construction. Their real, non-zero
effect on total addressable wallet is shown separately via an
*independent* (not row-aligned) TAM sum in the same table's
`tam_swing_R_m` column — e.g. `arrangement_fee_bps` alone swings TAM by
over R6bn despite a 0.00pp effect on the share metric. Reported both ways
deliberately, so neither column can be misread in isolation.

### 6.3 Second, independent SOW estimator — revealed presence

Not derived from any yield assumption: a 0–1 breadth score per entity from
how many of Syn Bank's product channels (5), trade-finance instrument
types (3), and country corridors (of 34 observed) each entity actually
uses — pure observed coverage ratios, no assumption needed for the score
itself. Mapped onto a SOW-comparable percentage via a disclosed
calibration (`revealed_presence.sow_floor_pct` / `sow_ceiling_pct` in
`config/assumptions.yaml`, 5%–45% base case) explicitly flagged as a rough
calibration, not a precision instrument.

**Where the two estimators diverge is the most interesting finding here**
(hackathon.txt's own words) — and the pattern is systematic, not scattered
noise: **17/20 entities show presence-based meaningfully above
yield-based**, often by 25–40 percentage points. This is not read as "the
yield-based estimates are all wrong" — all 20 entities in this portfolio
are large, actively-engaged corporates already using most of Syn Bank's
product range (breadth scores cluster tightly, 0.77–0.91), which gives the
revealed-presence method little room to *discriminate* within this
specific, already-broad client set. The size of the systematic divergence
is itself evidence about the METHOD's limited power here, not a claim
about the true SOW.

**The one entity that runs the other way is the genuinely useful
cross-check**: Pepkor Holdings, at –21.5pp — its yield-based share (62.7%)
*exceeds* even the top of the presence-based range (41.2%). This is the
same entity flagged with a TAM-assumption breach in Phase 4 (§5.2) — an
estimator built from completely different inputs, with no knowledge of
that breach, independently lands well below the yield-based figure. That
corroborates the Phase 4 finding: Pepkor's 62.7% is inflated by an
over-conservative `avg_balance_days_of_revenue` assumption, not a genuine
outlier level of capture. This is triangulation actually doing its job —
two independent methods bracketing a more plausible truth.

### 6.4 Sector regression of wallet-intensity

`wallet_intensity = TAM / revenue` computed per entity (blended across all
observable TAM sub-components), then compared within-sector (z-score,
sectors with <3 peers explicitly marked "not scored," not force-fit to a
meaningless statistic) and via a portfolio-wide log-log regression
(log TAM ~ log revenue, n=20, R²=0.82). **2 entities flagged below their
sector line**: Valterra Platinum (mining, z=–1.15) and Clicks Group
(consumer, z=–1.09) — both marginal breaches just past the -1.0 threshold,
not dramatic outliers.

**Why this analysis is structurally muted for most pillars, disclosed
rather than hidden**: because `payments_per_zar_throughput` and
`avg_balance_days_of_revenue` make Transactional Banking's TAM
*deliberately proportional to revenue* by construction (a fixed global
coefficient × revenue, for every entity), wallet-intensity for that pillar
is nearly constant across the whole portfolio by design — a sector
regression on it would mostly just confirm the assumption is applied
uniformly, not reveal anything new. The genuinely informative signal
concentrates in the sub-components where TAM does NOT scale purely with
revenue: `debt_arrangement` (driven by `total_debt`, which varies
independently of revenue) and `trade_finance_instruments` (driven by
Syn Bank's own observed activity). This is a structural property of the
Phase 4 model, not a flaw in the regression — flagged so a reader doesn't
expect this analysis to surface more than it structurally can.

### 6.5 Time-trend test

Quarterly volume (all 3 source files combined), linear trend test per
entity (20 tests) and per currency-pair corridor (5 tests — hackathon.txt
already notes there are only 5, all used by all 20 entities). **At raw
p<0.05: 9/20 entities and 0/5 corridors show a significant trend.**
Testing 25 series at once risks ~1.25 false positives by chance alone even
with no real trend anywhere — at a **Bonferroni-adjusted threshold, 5/20
entities and 0/5 corridors remain significant**.

**Corridors are flat, fully consistent with Phase 1's aggregate finding**
(quarterly volume R10.4–12.7bn, no drift, 2023-07 to 2026-06) — stated
plainly, not manufactured into something more interesting than the data
supports. **But 5 individual entities DO show a trend robust enough to
survive Bonferroni correction**: BHP Group (growing, R²=0.75), Anglo
American (shrinking, R²=0.92), OUTsurance Group (growing, R²=0.94), Sanlam
(shrinking, R²=0.99), NEPI Rockcastle (growing, R²=0.84). The correct
reading is **both** things at once — "the portfolio in aggregate is flat"
AND "a handful of specific clients are moving" — not one fact overriding
the other. These 5 are genuine per-client signals worth a coverage
banker's attention independent of the portfolio-level story.

## 7. Phase 6 — Opportunity ranking (`src/opportunity.py`)

hackathon.txt's formula: `expected_value = wallet_gap × win_probability ×
margin`. Ranks all 20 entities — the deliverable the brief's dashboard
section explicitly asks for ("portfolio-level summary ranking all 20
clients by expected value").

### 7.1 wallet_gap — confidence-aware, not a blind subtraction

`wallet_gap = max(tam_zar − captured_zar, 0)`, computed ONLY for
sub-components where both sides are observable on the same row (the same
`blended_tam_and_captured` discipline as Phase 4/5 — METHODOLOGY.md §5.3).
For the 3 structurally-unobservable-captured sub-components
(`rate_hedging`, `debt_arrangement`, `competitor_credit_gap`), the full
TAM is reported as `unknown_capture_potential_zar` — a separate,
clearly-labelled upper bound, never blended into the ranked
`expected_value`. Folding an unmeasurable capture into a confident-looking
ranked number would be exactly the kind of false precision this project
has avoided at every prior phase.

### 7.2 win_probability — the 4 right-to-win signals, as named in the brief

A weighted blend (weights in `config/assumptions.yaml`, sum to 1.0,
named + rationale'd like every other assumption):

- **breadth (30%)** — Phase 5's `revealed_presence.parquet`
  leg-type/channel/instrument coverage (country handled separately,
  below, to avoid double-counting the same underlying signal).
- **relationship_strength (30%)** — Transactional Banking's captured
  share of wallet, computed the same row-aligned way as everywhere else
  in this pipeline. This is the foundational-relationship signal product
  sequencing (§7.3) is built on.
- **momentum (20%)** — Phase 5's Bonferroni-significant time-trend signal
  (`time_trends_entity.parquet`): 0.8 if growing, 0.2 if shrinking, 0.5
  (neutral, not penalised) if no trend survives multiple-testing
  correction.
- **country_adjacency (20%)** — Phase 5's country-corridor coverage (of
  34 observed). hackathon.txt is explicit that currency-pair coverage is
  a dead signal (all 20 entities use all 5 pairs) but country coverage
  (10–22 of 34) is meaningful — this is that signal, reused rather than
  re-derived.

Clipped to [0.05, 0.95] — a right-to-win estimate this coarse should
never claim certainty in either direction.

**Disclosed limitation, found immediately on inspection**: `breadth_score`
clusters near 1.0 for nearly every entity (`reports/opportunity_report.md`
"Right-to-win signal detail") — the same low-discriminating-power issue
already found for Phase 5's revealed-presence estimator (§6.3), for the
same underlying reason (this portfolio's clients are all already broad
users). In practice, `relationship_strength` and `country_adjacency`
drive nearly all the variation in `win_probability`; `breadth`'s 30%
weight is real but contributes little differentiation on THIS specific
20-entity portfolio. Not corrected — the weight is honestly disclosed as
specified, not silently reduced to make the output look more
discriminating than the underlying signal actually is.

### 7.3 margin, and why it isn't a second yield application

`margin = net_margin_realization` (`config/assumptions.yaml`, 65% base
case, 55–75% range) — the share of GROSS wallet-gap revenue that converts
to bottom-line contribution after cost-to-serve and risk-adjusted capital
charges. This is deliberately NOT a second pass of Phase 4's yield
assumptions: `wallet_gap` is already denominated in bank revenue (fees +
spread already priced in via `config/assumptions.yaml`'s bps/fee
assumptions) — applying a yield a second time here would double-count
margin already inside the number.

### 7.4 Product-sequencing enforcement

hackathon.txt: *"you win FX off the back of payment flow, not the
reverse... Flag any recommendation that violates this."* Any Global
Markets or Investment Banking opportunity for an entity whose
`relationship_strength_score` is below `sequencing_risk_threshold` (10%)
is flagged (`sequencing_flag`) and has `win_probability` halved
(`sequencing_penalty_multiplier`), not zeroed — a real deprioritisation,
not an impossibility claim. Transactional Banking itself is never
sequencing-flagged (it is the foundational pillar, not a cross-sell on
top of one).

**Result: 30 of 40 Global Markets/Investment Banking rows are flagged**
(`reports/opportunity_report.md`). This is a real, portfolio-level
finding, not an over-triggered threshold — it directly reflects Phase 4's
headline result that Syn Bank's Transactional Banking capture is thin
almost everywhere in this portfolio (blended TB share 4.9%, §5.4). Read as
"most cross-sell opportunities in this portfolio need the payment-flow
relationship deepened first," not thirty isolated edge cases.

### 7.5 Global majors ranked separately, dual-listed entities excluded from the primary list

Per the explicit instruction carried forward from Phases 4–5 (§5.2, §6.3):
`GLOBAL_MAJOR_ENTITIES`' TAM is inflated by using entire-global (not
SA-specific) revenue. Mixing them into the primary ranked list would let
their artificially large gaps dominate — Glencore alone shows a
**R3.13bn** expected value, an order of magnitude above every SA-domestic
entity, purely a function of the denominator problem already disclosed,
not a real, actionable coverage opportunity of that scale. Reported in a
clearly-separated section for completeness, never presented as a top
recommendation.

### 7.6 Results

**Top SA-domestic opportunity: Shoprite Holdings** (R193.8m expected
value, R555.5m wallet gap, Transactional Banking). Top 5: Shoprite, Bid
Corporation, MTN Group, Vodacom Group, Sanlam. `top_pillar` is
Transactional Banking for all 20 entities — expected, not a modelling
artefact: TB's TAM scales off (revenue + cost_of_sales), a much larger
base than Global Markets/Investment Banking's narrower slices (§5.1), and
a broad relationship's single largest addressable pillar being
Transactional Banking is well-established corporate-banking practice, not
a surprise this pipeline manufactured.

**Pepkor's ranking (8th) is lower than its raw wallet size might suggest,
and that's the TAM-assumption breach propagating correctly, not a new
error**: its `deposit_nii` wallet_gap floors at 0 (captured already
exceeds the too-conservative TAM assumption — §5.2), shrinking its total
gap. This is the honest, connected consequence of a finding disclosed
three phases ago, not something to "fix" here — Pepkor's TRUE opportunity
is plausibly larger than this ranking shows, exactly because the
underlying TAM assumption undercounts a demonstrably high-cash-flow
retailer, and Phase 5's independent revealed-presence estimator already
corroborated this (§6.3).

### 7.7 Sub-component ranking — "Transactional Banking" is a pillar, not a product

User feedback on the first version of this ranking (and the briefing
notes it feeds, §8.1): every entity's `top_pillar` was Transactional
Banking, and the briefing notes said so without ever naming which
Transactional Banking product. That's a real information loss, not a
wording problem — `wallet_model.parquet` already computes
`wallet_gap`/`captured`/`tam` at sub-component grain (`payment_fees`,
`deposit_nii`, `fx_hedging`, `rate_hedging`, `debt_arrangement`,
`trade_finance_instruments`, `competitor_credit_gap`); `build_pillar_ranking`
aggregated it away with a `groupby(["entity_id", "pillar"])` before it
ever reached the ranked output.

Fixed with `build_subcomponent_ranking()` — the same `wallet_gap ×
win_probability_adjusted × margin` formula as §7.1–7.3, but computed at
sub-component grain and exposed as
`data/processed/opportunity_ranking_subcomponent.parquet` and a
"Full sub-component detail" section in `reports/opportunity_report.md`.
Each entity's top sub-component (`top_sub_component_label`) is now
carried into `build_entity_ranking`'s output and required — by field
description, not just convention — in `src/briefing.py`'s headline and
recommended-next-step generation (§8.1).

**Result, and it's a genuine finding**: 19 of 20 entities' single
largest opportunity is specifically `payment_fees` ("Payment fees
(transaction volume & pricing)") — not a generation default, but a
consequence of §7.6's TAM-scaling explanation taken one level deeper:
`payment_fees`'s TAM base (transaction volume × pricing intensity) is
larger than any other Transactional Banking sub-component's for
essentially every corporate in this portfolio. The one exception,
**OUTsurance (E07) → `deposit_nii`**, is explained by the same mechanism
running in reverse: insurers carry no `cost_of_sales` line, which is part
of `payment_fees`'s TAM formula (§5.1) — removing that term shrinks
OUTsurance's `payment_fees` TAM below its `deposit_nii` TAM, so
cash-management/NII becomes its largest lever instead. This is exactly
the kind of portfolio-level differentiation the pillar-only ranking was
hiding.

## 8. Phase 8 — Dashboard (`app/dashboard.py`) and AI briefing notes (`src/briefing.py`) [Gen AI #3]

Built ahead of Phase 7 (bonus modules) — hackathon.txt's Deliverables list
makes the dashboard a required submission component, while Phase 7 is
explicitly labelled "bonus" in both hackathon.txt and PLAN.md. See
CLAUDE.md's session log for the full reasoning.

### 8.1 AI-generated client briefing notes — the third Gen AI component

hackathon.txt: *"AI-generated briefing notes for AT LEAST 3 clients...
generated from model output, not free-generated — state this on the
page."* `src/briefing.py` generates one for **all 20 entities** (well
beyond the minimum), through the same `src.llm.generate_structured`
pipeline as Phases 2 and 3 (prompt logging, caching, usage ledger — see
`prompts/client_briefing_notes/*.json`).

**The "generated from model output, not free-generated" constraint is
enforced structurally, not just by instruction**: the prompt fed to
Gemini contains ONLY already-computed figures — Phase 6's expected value/
wallet gap/win probability, Phase 2's competitor-credit flow by
confidence tier, Phase 3's revenue/foreign-revenue/debt, and explicit
boolean flags for every disclosed caveat (`is_global_major`,
`any_sequencing_flag`, `tam_assumption_breach`). The system instruction
requires every disclosed flag to be surfaced in `caveats` if true, and
forbids inventing a number, product, or fact — the model's only job is
turning structured figures into readable prose, never sourcing a claim
itself.

**A real gap found and fixed before generating the full batch**: the
first version's context builder omitted `tam_assumption_breach` entirely
— Pepkor Holdings' briefing (the one entity this flag applies to) came
back with `caveats: None`, silently dropping a finding already
established in Phase 4/5/6. Added the flag to the context and an explicit
instruction to surface it; regenerated — Pepkor's note now correctly
states the true opportunity is plausibly larger than the ranked figure
shows. Caught by actually reading the generated output for the specific
entity most likely to expose the gap, not by assuming the schema was
complete because the code ran without error — the same discipline every
earlier phase's bug-catches relied on.

### 8.2 Dashboard — every number traces to a Phase 1–6 parquet file

Six views, all reading `data/processed/*.parquet` directly (a live
DuckDB aggregation for the one place raw-ledger detail is needed — the
per-client top-counterparties chart, an explicit hackathon.txt
requirement, see below):

- **Portfolio Summary** — the ranked list `reports/opportunity_report.md`
  already produces, rendered as a chart + table, plus the Phase 5 Monte
  Carlo credible interval as the headline share figure (not the bare
  point estimate). Global majors shown in a clearly separate section
  throughout, never mixed into the primary ranking.
- **Client Drill-Down** — per-entity KPIs, wallet gap by pillar (fixed
  pillar order and colour across every entity, so a banker can compare
  entities without re-reading the axis), a wallet-gap-by-sub-component
  chart (§7.7 — the specific-product grain, colour-linked to its parent
  pillar), the 4 right-to-win signals, and a financial snapshot.
- **Opportunity Heatmap** — client × pillar, sequential single-hue
  colourscale (magnitude encoding, per the dataviz method), SA-domestic
  entities only.
- **AI Briefing Notes** — §8.1's output, with the required "generated
  from model output" disclosure prominently on the page, defaulting to
  the top 5 SA-domestic entities (not global majors, which would
  otherwise dominate any expected-value sort).
- **Competitor-Credit Finding** — the R692.8m primary / R307.9m secondary
  headline as dedicated KPIs, a by-entity stacked chart, and a sample of
  the actual LLM-extracted evidence (memo text, classification, reasoning)
  — the narrative spine of the whole submission gets its own page, not a
  buried table.
- **Rigor & Assumptions** — Phase 5's Monte Carlo histogram, tornado
  chart, below-sector-line entities, and Bonferroni-significant trend
  entities. Not on hackathon.txt's required list, added because 30% of
  the mark scheme is analytical rigor and a dashboard that hides that
  work under-sells it.

**Top-N counterparties, one client at a time** (hackathon.txt: *"Graph
visuals: constrain to one client at a time, top-N counterparties by
value... No 241k-edge hairballs"*): a live DuckDB query, top 10 by value
across all 3 ledgers for the SELECTED client only — never a network graph
of the full dataset. Known competitor-credit beneficiaries
(`src.common.KNOWN_COMPETITOR_BENEFICIARIES`) are highlighted in the
status-critical colour with a caption explaining why, connecting this
view back to the Phase 2 finding rather than presenting it as an
unexplained colour choice.

**Verified by actually driving the running app**, not just checking the
code imports cleanly: launched via `streamlit run`, driven headlessly
with Playwright through all 6 pages, screenshots reviewed, zero console
errors. Caught and fixed two real issues this way that static review
would have missed — the pillar chart's category order wasn't pinned
(varied entity to entity, undermining cross-client comparability) and the
briefing-notes page's default selection led with global majors (inflated
figures) instead of the realistic SA-domestic opportunities every other
page treats as primary.

### 8.3 Dark mode — theme-aware charts, not a forced repaint

Every chart originally hardcoded a light-surface `plot_bgcolor`/
`paper_bgcolor` (`#fcfcfb`), so switching Streamlit's own theme to dark
(top-right "⋮" → Settings → "Choose app theme") left the embedded Plotly
charts light-surfaced against a dark page — the user-reported bug. First
attempt (a custom sidebar toggle + injected CSS forcing Streamlit's own
elements dark) was wrong and reverted: verified via Playwright screenshot,
the injected CSS fought Streamlit's own stylesheet on broad selectors and
left page text almost unreadable. Correct fix: Streamlit 1.52 exposes
`st.context.theme.type` (`"light"`/`"dark"`), the theme the user already
controls via that native menu — no custom toggle needed. Every chart now
looks up a `THEMES["light"|"dark"]` dict (both variants populated from the
`dataviz` skill's validated palette, categorical/sequential/status/ink/grid
tokens for both surfaces, not just the light half used before) through a
shared `chart_layout()` helper.

**Known limitation**: `st.context.theme.type` does not update mid-session
on the in-place rerun the Settings dialog triggers — only Streamlit's own
chrome (which is React-side, not a script rerun) updates instantly; the
Python-rendered charts pick up the new theme on the next full page
reload. Not fixed (no clean fix without client-side JS); harmless in
practice since a full reload is the normal way this app gets opened.

## 9. Phase 7 — Bonus modules (`src/cash_cycle.py`, `src/latency_optimization.py`)

Built after Phases 1–6 and 8, per the re-sequencing explained in §8's
opening note — hackathon.txt labels this phase "bonus" explicitly.

### 9.1 Cash-cycle / payment timing (`src/cash_cycle.py`)

hackathon.txt's ask, verbatim: *"per entity, model days between outbound
supplier legs and inbound collections to suggest optimal engagement
timing."*

**The literal ask was checked against the data before building anything,
and doesn't hold at day grain.** Volume-weighted day-of-month for
`collections` (inbound) vs `supplier_payments` (outbound) converges to
the same day (~15–16) for every one of the 20 entities: daily volume
within a month has only a 7–8% coefficient of variation (close to what a
uniform, non-clustered distribution would produce), and day-of-week
volume is flatter still (<1% CV — no weekday/weekend pattern either). At
that grain, "days between" is noise straddling a 30-day wraparound
boundary, not a per-entity signal. **Disclosed as a dead signal**, the
same discipline this project already applied to the FX currency-pair dead
signal (§6.3) and `breadth_score` clustering (§7.2) — reporting a null
result honestly rather than manufacturing a ranking that isn't really
there.

**What the data DOES support: month-of-year seasonality.** Monthly
banking activity (collections + supplier payments combined, summed across
the ~3-year ledger by calendar month) has real, sector-coherent structure.
7 of 20 entities clear a 15% coefficient-of-variation threshold, and the
pattern isn't random: **all 4 consumer/retail entities in the portfolio**
(Shoprite Holdings, Bid Corporation, Pepkor Holdings, Clicks Group) **rank
in the top 5, every one peaking in December** — the expected pre-Christmas
retail volume surge. Valterra Platinum (mining, March peak) is the one
exception to the retail-only pattern, reported as-is. The remaining 13
entities (mostly mining, insurance, tech, telecoms) are close to flat
year-round — for these, month-of-year is not treated as a meaningful
engagement lever.

Each seasonal entity gets a `suggested_engagement_month` = peak month − 2
(a scheduling heuristic disclosed in-module, not a revenue-yield
coefficient, so it lives in `src/cash_cycle.py`, not
`config/assumptions.yaml`). **No revenue or NII figure is estimated by
this module** — deliberately descriptive/behavioural only; monetising a
"cash-cycle timing" insight would require inventing an unnamed
"capturable balance %" coefficient with no basis in the data, exactly
what this project's assumption-naming discipline exists to prevent (§1,
CLAUDE.md). Phase 4's `deposit_nii` sub-component (already using the
named `deposit_nii_margin_bps` assumption) is the correct place to look
for that number.

### 9.2 Latency & cost optimisation (`src/latency_optimization.py`)

hackathon.txt's ask, verbatim: *"instrument the LLM pipeline, add caching,
batching, and route simple classification to a small model reserving the
large one for hard cases. Produce a before/after latency and cost
chart."*

Caching and prompt logging (`src.llm.generate_structured`) have been live
since Phase 2 — every LLM call in this codebase already gets them. This
module adds the piece that wasn't built yet: model routing, using
`src/forensics.py`'s existing `regex_confidence` signal (0.85 = an
explicit syndicate/bridging/bilateral keyword is present = "simple", 0.40
otherwise = "hard") to decide which model handles which row. Not a new
judgement call invented for this module — it's the same signal Phase 2
already computes and cross-checks the LLM against.

**A real bug, found by actually making a call, not by trusting the model
list**: the originally-planned `MODEL_SMALL` (`gemini-2.5-flash-lite`)
returned `404 NOT_FOUND — "no longer available to new users"` on the
first live `generate_content` call, despite appearing in
`client.models.list()`. Swapped to `gemini-3.1-flash-lite`, confirmed
callable with a live test call before committing to it in code. Pricing
for both models sourced fresh from
[ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)
(retrieved 2026-08-11) rather than reusing PLAN.md's original
gemini-2.5-flash-lite figures, which no longer apply to the model
actually in use.

**"Before" is Phase 2's real historical run, not a resimulation**: median
latency and mean token counts come straight from
`reports/llm_usage_log.jsonl`'s `forensics_memo_extraction` namespace,
`cached=False` rows only. Median, not mean, deliberately — the log
carries a small extreme-tail of retries from the bug already documented
in CLAUDE.md "Must-know" #6, which would badly distort a mean-based
baseline. **"After" is a genuine fresh 100-row sample** of `simple`-bucket
rows re-run on `MODEL_SMALL`, extrapolated to the full 4,199-row workload
using the real simple/hard split already present in
`competitor_credit_events.parquet` (2,117 / 2,082, ~50/50).

**Safety check, not just a cost claim**: every freshly-sampled row also
has Phase 2's ORIGINAL `MODEL_DEFAULT` answer on file, so the
`MODEL_SMALL`-vs-original agreement rate is measured, not assumed —
**100% `facility_type` agreement** on this sample. High enough to trust
the routing for the `simple` bucket: an explicit keyword match leaves
little for a smaller model to get wrong.

**Result, reported plainly even though it isn't a clean win on both
axes**: **11% cost saved** ($1.24 → $1.10 for the full workload), but
compute time is roughly flat (a ~1% swing, within noise). This specific
model-generation pairing (gemini-3.1-flash-lite vs. gemini-2.5-flash) has
a narrower price gap than the originally-planned gemini-2.5-flash-lite
pairing, and a smaller model is not automatically a faster one — the
report states this explicitly rather than showing only the metric that
improved. Read this as a genuine **cost** optimisation, not a reliable
**latency** one, for the model generation actually available at the time
this was built.

## 10. Limitations (running list — extended every phase)

- **AI briefing notes inherit every upstream limitation already disclosed
  in Phases 2–6** — they are a faithful narration of the computed figures,
  not an independent check on them. A briefing note reads as more
  confident prose than the underlying numbers necessarily deserve unless
  the reader has also seen the `caveats` field (or read this document);
  the dashboard surfaces `caveats` prominently for exactly this reason,
  but a printed/exported briefing note without that context would not.
- **Phase 7's cash-cycle module found no per-entity day-grain signal in
  the data** (§9.1) — the brief's literal "days between outbound legs and
  inbound collections" framing assumes a temporal offset that this
  synthetic dataset's transaction timing doesn't encode at day or
  day-of-week grain. The module answers the spirit of the ask (suggest
  optimal engagement timing) at the grain the data actually supports
  (month-of-year seasonality) instead — disclosed as a pivot, not silently
  substituted.
- **Phase 7's latency/cost module depends on a specific Gemini model being
  callable at run time** (§9.2) — `gemini-2.5-flash-lite` was retired for
  new API keys between when `MODEL_SMALL`'s default was first written and
  when Phase 7 actually exercised it, a real example of how fast this
  model landscape moves. `gemini-3.1-flash-lite` is confirmed working as
  of 2026-08-11, but a future re-run of this module on a different API
  key/date could hit the same class of failure — `src/llm.py`'s
  `MODEL_SMALL` is overridable via `GEMINI_MODEL_SMALL` for exactly this
  reason.
- **The dashboard was verified by driving it manually (Playwright,
  screenshots, console-error checks), not by an automated UI test suite**
  — there is no `tests/test_dashboard.py`. A future regression in
  `app/dashboard.py` would not be caught by `pytest tests/ -q` the way a
  `src/` module's regression would be.
- **Phase 6's `win_probability` is a 4-signal weighted heuristic, not a
  calibrated probability** — there is no historical win/loss outcome data
  anywhere in the provided files to calibrate against (this is a common
  constraint for a brand-new coverage-prioritisation tool, not specific to
  this dataset). Treat the resulting ranking as a reasoned, disclosed
  prioritisation aid, not a statistically validated probability.
- **`breadth_score` has low discriminating power on this specific
  portfolio** (§7.2) — real, disclosed, not corrected by re-weighting
  after the fact to produce a more differentiated-looking result.
- **Entity-level `win_probability` in the primary ranking table is
  pre-sequencing-adjustment** (§7.2) — it equals the post-adjustment
  figure for Transactional Banking (never itself sequencing-flagged, and
  always the `top_pillar` in this run) but NOT for an entity's Global
  Markets/Investment Banking rows, which carry their own adjusted figure
  in the pillar-level detail table. Reading the entity-level column as
  "the" win probability for every pillar would be a mistake.
- **No entity-level Monte Carlo credible interval** — Phase 5's Monte
  Carlo runs at portfolio and pillar grain only (`monte_carlo_results.parquet`);
  Phase 6's ranking uses Phase 4's point-estimate `wallet_model.parquet`
  directly. An entity's true rank could plausibly shift within Phase 5's
  wider portfolio-level uncertainty band — a natural extension if this
  pipeline is developed further, not built this phase, a deliberate scope
  boundary rather than an oversight.
- **`net_margin_realization` is a single portfolio-wide assumption**, not
  differentiated by pillar — a corporate-lending-heavy Investment Banking
  opportunity plausibly carries a different risk-adjusted capital charge
  than a Transactional Banking one. Simplified to one figure for this
  phase; disclosed as a simplification, not hidden.

- **Every fee/margin/bps assumption in `config/assumptions.yaml` is an
  informed market-practice estimate, not a published rate card** (see §5
  intro) — this is the single biggest source of uncertainty in the whole
  wallet model, by design the thing Phase 5's Monte Carlo / tornado
  sensitivity analysis exists to quantify. Point estimates in
  `reports/wallet_report.md` should not be read as more precise than a
  midpoint of a plausible range.
- **The TAM assumption breach on Pepkor's `deposit_nii` (§5.2) is not an
  isolated one-off**: any entity whose Syn Bank-observed cash flow is
  large relative to its external revenue could trip the same check.
  Flagged programmatically rather than fixed by hand-tuning the 15-day
  assumption until this one case disappears — that would be curve-fitting
  to a single data point, not a real fix.
- **Dual-listed global majors' share-of-wallet numbers are not directly
  comparable to SA-domestic entities' numbers** (§5.2) — no SA-specific
  revenue split exists in the source data to correct for this. Any
  cross-entity ranking (Phase 6) must treat this cohort separately, not
  sort them into the same list by raw wallet-gap size.
- **Insurers' `payment_fees` TAM throughput uses `total_revenue` alone**
  (no `cost_of_sales` — not a meaningful concept for an insurer, correctly
  `null` per Phase 3 — see METHODOLOGY.md §4), which is a smaller
  denominator than non-insurers' `revenue + cost_of_sales` throughput
  base. This is directionally defensible (insurers genuinely have a
  smaller gross-transaction-value base relative to revenue than a
  retailer), but it means Sanlam's and OUTsurance's `payment_fees` shares
  are not on a perfectly like-for-like basis with the other 18 entities —
  flagged rather than corrected with an invented insurer-specific
  intensity assumption this phase.
- **`rate_hedging`, `debt_arrangement`, and `competitor_credit_gap` have a
  structurally unobservable captured side** — reported as `None`, not
  `0`, and excluded from every blended/summed share-of-wallet figure.
  This means the Investment Banking pillar's 1.5% blended share (§5.3)
  undercounts Syn Bank's true capture of debt-related revenue by an
  unknown amount, not a known one — the honest reading is "this pillar's
  measured share is a lower bound with an unquantified gap," not "this
  pillar's capture is genuinely only 1.5%."
- **`trade_finance_instruments`' TAM (grossed up from captured at an
  assumed 45% primary-bank share) is circular by construction** — it
  cannot show Syn Bank capturing more or less than 45% of this specific
  sub-component's TAM by design, since TAM is *derived from* captured, not
  independently estimated. It exists to give the sub-component a
  revenue-comparable TAM figure at all (no external trade-finance-market
  size exists in the data) but should not be read as an independent
  signal the way `debt_arrangement`'s TAM (from Phase 3's `total_debt`) is.
- **20 vs. 50 clients**: see §0. Every per-client statistic in this
  submission covers the 20 entities actually in the data.
- **No supplied financial-statement PDFs**: see §0; Phase 3 sources
  external filings directly and cites them.
- **Secondary-tier competitor-credit rows (§2.1) are not proof of intent**:
  the data is synthetic; we cannot distinguish "loan proceeds on-forwarded
  through an ordinary-looking payment" from "a labelling artefact of the
  data generator." We report the tier distinctly and do not let it inflate
  the primary-tier headline number.
- **Regex baseline's `lender_name` heuristic is not perfectly precise**
  in general (two generic correspondent-banking labels also contain
  "Bank") — clean on this dataset only because those labels never carry a
  non-null memo. Documented and tested rather than silently assumed.
- **`foreign_revenue_pct` coverage is genuinely low (30%, 6/20)** — see
  §4.3. Where a specific number does exist it is sometimes a **different
  vintage year** than the entity's core financials (Gold Fields' 87.8%
  is FY2024 operating-region data sitting alongside FY2025 revenue/debt
  figures, because no FY2025 geographic breakdown was fetched) — flagged
  per-entity in `tests/financials_ground_truth.csv`'s notes rather than
  silently reconciled. Phase 4/6 should treat this field as directional
  evidence, not a precise same-year percentage, for every entity where it
  is populated.
- **LLM fiscal-year recency bias, found and fixed (§4.1)** — logged here as
  a limitation of the underlying model, not just a bug that got patched.
  The fix (explicit today's-date anchoring + an explicit selection
  algorithm in the prompt) worked on this run, but there's no guarantee it
  generalises to a future re-run with different source text without the
  same spot-check discipline that caught it here (compare extracted
  `fiscal_year_end` against the raw source's own most-recent column,
  entity by entity, don't just trust a green pytest run).
- **Two data aggregators can materially disagree on a "clean" income-
  statement line** (§4.2, Anglo American cost of sales) — any
  `cost_of_sales_is_derived=true` figure inherits whichever gross-profit
  definition the underlying source used, which is not guaranteed
  consistent company-to-company, especially in a year with large
  impairments or exceptional items.
- **`debt_maturity_profile` and `undrawn_facilities` were scoped out of the
  Phase 3 schema entirely, not attempted-and-nulled.** hackathon.txt's Phase
  3 spec asks for both; a full multi-year maturity ladder and a specific
  undrawn-facility headroom figure are disclosed in annual report debt
  notes far less consistently than the fields that made it into
  `FinancialBaselineExtraction`, and sourcing them reliably for 20 entities
  was judged not to fit a hackathon timeframe against the fields that feed
  Phase 4's drivers most directly. If a later phase needs a maturity-wall
  proxy, `total_debt`'s current-vs-non-current split IS in the committed
  raw source files (`data/external/raw/*.md`) even though it never made it
  into the schema — worth re-extracting rather than re-fetching.
- **Core financials are sourced from a single aggregator (stockanalysis.com)
  for cross-company consistency**, not independently verified against each
  company's own primary filing for every figure — a deliberate scope
  tradeoff for 20-entity coverage within a hackathon timeframe. The
  ground-truth sample cross-checks a sample against alternate/primary
  sources (§4.3) rather than every figure; treat Phase 3 output as a
  well-evidenced baseline, not an audited one.
