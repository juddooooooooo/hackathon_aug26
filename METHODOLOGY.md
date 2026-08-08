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

## External sources (Phase 3 onward)

hackathon.txt explicitly invites supplementing the synthetic internal data
with public sources (annual reports, JSE SENS, National Treasury, CIPC,
DealMakers SA, Bloomberg open data, investor-relations pages), provided
they're cited. Every external figure pulled into this pipeline (Phase 3
financial baselines, and any competitive-intelligence context used in
briefing notes) will be logged in `reports/external_sources.md` with:
entity, figure, value, source URL, retrieval date, and the confidence flag
carried alongside it in the data. Nothing gets folded into a model input
without a citation attached — this is what lets Phase 3's "never let the
model invent a number" rule be checked by a human.

## 4. Limitations (running list — extended every phase)

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
