# CLAUDE.md

Orientation for any Claude Code agent (or human) picking up this repo cold.
Read this file first. Then:
- **`PLAN.md`** — the full phase-by-phase backlog (authoritative scope, what's
  done, what's next, verbatim spec for unbuilt phases).
- **`METHODOLOGY.md`** — rationale, data findings, and limitations for what
  IS built. Every assumption behind Phase 1–6 and Phase 8 lives here.
- **`hackathon.txt`** — the official brief, for context on what's being judged.

Do not start writing phase code from memory of what "share of wallet
hackathons usually look like" — this repo has already made a lot of
specific, non-obvious decisions (see below). Read PLAN.md + METHODOLOGY.md
first or you will redo work or contradict an earlier decision.

## Status: Phase 8 of 8 complete (Phase 7 skipped for now, see below)

- [x] Phase 1 — Ingestion & profiling
- [x] Phase 2 — Forensic extraction (Gen AI #1)
- [x] Phase 3 — External financial baseline (Gen AI #2)
- [x] Phase 4 — Wallet model
- [x] Phase 5 — Rigor layer (Monte Carlo, sensitivity, triangulation)
- [x] Phase 6 — Opportunity ranking
- [ ] Phase 7 — Bonus modules (cash-cycle timing, latency/cost optimisation) **← only phase left**
- [x] Phase 8 — Dashboard (+ AI briefing notes, Gen AI #3) — built ahead of Phase 7, see session log

All of hackathon.txt's REQUIRED deliverables are now built. Phase 7 is
explicitly "bonus" in the brief — worth doing if there's time, not a gap
in the submission if there isn't.

Keep this checklist, `README.md`'s, and `PLAN.md`'s checkboxes in sync when
a phase completes.

## Must-know before you touch anything

1. **Domain rule**: share of wallet = revenue, never flow. R1bn of FX flow
   is not R1bn of wallet. Every rand figure in Phase 1/2's raw output
   (`reports/profiling_report.md`, `reports/forensics_report.md`) is
   **gross flow**, explicitly labelled as such. Phase 4 (`src/wallet.py`)
   is where flow becomes revenue, via named yield assumptions in
   `config/assumptions.yaml` (fully populated) — never hardcode a yield
   coefficient inline in `src/wallet.py` or anywhere else; every fee/margin/
   bps figure in that file has a rationale comment, most are informed
   market-practice estimates (not published rate cards — SA banks don't
   publish these), each a designated Phase 5 sensitivity-analysis input.
2. **20 clients, not 50.** hackathon.txt says 50; the data has 20
   (E01–E20), validated consistent across all 3 files. Ground truth list:
   `src.common.EXPECTED_ENTITIES`. This is intentional and documented
   (METHODOLOGY.md §0), not a bug to "fix" — don't go looking for the
   other 30.
3. **No financial-statement PDFs were supplied**, despite hackathon.txt's
   data table implying they would be. Phase 3 sources the 20 clients'
   figures from public filings directly — hackathon.txt's "Data" and
   "Hints and Tips" sections explicitly invite and expect this (JSE SENS,
   investor-relations pages, annual reports, National Treasury, CIPC,
   DealMakers SA, Bloomberg open data). Cite every source — see
   METHODOLOGY.md "External sources" section and `reports/external_sources.md`.
4. **The key finding is bigger than briefed.** hackathon.txt's competitor-
   credit signal (settling payment legs of competitor-originated credit
   facilities) is confirmed at **R692.8m primary-tier + R307.9m
   secondary-tier** (~4,199 rows across all 3 files), not the ~R403m
   implied by the brief's 2-file description. Full derivation:
   METHODOLOGY.md §2.1 and §3. This is the number Phase 4+ should build
   against.
5. **LLMs have a fiscal-year recency bias — watch for it in any future
   phase that has the model pick "the latest" anything.** Phase 3's first
   run picked FY2024 instead of the genuinely-latest FY2025/FY2026 for
   10/20 entities, because the model defaulted to a year that felt more
   familiar from its own training distribution even when the source text
   unambiguously showed a later year. Fixed by anchoring the system
   instruction to today's date and an explicit "scan every period-end,
   pick the single latest one on or before today" algorithm — see
   METHODOLOGY.md §4.1 and `src/financials.py`'s `SYSTEM_INSTRUCTION` for
   the pattern to reuse if Phase 4+ ever needs "most recent X" out of an LLM.
6. **Gemini, not Claude/OpenAI.** `src/llm.py` wraps `google-genai`. Every
   teammate needs their **own** `.env` with their **own** `GEMINI_API_KEY`
   — `.env` is gitignored on purpose and does **not** come through on
   `git pull`. Copy `.env.example` → `.env`, fill in a key from
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
   Every LLM-calling phase degrades gracefully to a regex/deterministic
   baseline with no key configured (clearly flagged in its output), so you
   *can* work on non-LLM code without one — but you won't get real Gen AI
   results to show until you add a key.
7. **Wallet-model and rigor-layer facts Phase 6 (opportunity ranking) MUST
   account for, not just inherit blindly:**
   - `GLOBAL_MAJOR_ENTITIES` (`src/wallet.py`: E01 BHP, E02 Glencore, E03
     Anglo American, E04 AngloGold Ashanti, E05 Gold Fields, E14 Prosus,
     E15 Naspers, E20 Shaftesbury) report GLOBAL revenue in Phase 3, not
     SA-specific — their TAM/share-of-wallet numbers are not on the same
     footing as the other 12 entities. Do not rank them in the same list
     by raw wallet-gap size without addressing this — see METHODOLOGY.md
     §5.2.
   - `df["tam_assumption_breach"]` in `wallet_model.parquet` flags rows
     where captured revenue exceeds the modelled TAM (currently just
     Pepkor's `deposit_nii`) — this means the TAM assumption is too
     conservative for that entity, not that Syn Bank captured >100% of a
     real market. Never silently clip `share_of_wallet` to 100%; it hides
     a real signal. See METHODOLOGY.md §5.2. Phase 5's independent
     revealed-presence estimator (METHODOLOGY.md §6.3) corroborates this
     specific finding from a completely different data source — Pepkor is
     the one entity where that second estimator lands BELOW the
     yield-based figure, worth citing together if Phase 6 discounts
     Pepkor's ranked opportunity size.
   - `captured_zar` is `None` (not `0`) for 3 sub-components
     (`rate_hedging`, `debt_arrangement`, `competitor_credit_gap`) — no
     derivatives book or "loans Syn Bank originated" table exists in any
     source file, so these are structurally unobservable, not zero-capture
     opportunities. Any Phase 6 ranking logic that treats a `None` as `0`
     will systematically over-rank these as "total loss" opportunities
     when the truth is "unknown."
   - Report `wallet_gap`/`expected_value` using Phase 5's Monte Carlo
     credible interval (`data/processed/monte_carlo_results.parquet`,
     portfolio 5.3% base case, 3.1%-6.8% 5th-95th percentile — METHODOLOGY.md
     §6.1), not the bare Phase 4 point estimate. A ranking built on a point
     estimate alone re-introduces exactly the false precision Phase 5 exists
     to correct.
   - `data/processed/sector_regression.parquet`'s `below_sector_line` flag
     (2 entities: Valterra Platinum, Clicks Group) and
     `time_trends_entity.parquet`'s `significant_bonferroni` flag (5
     entities trending independent of the flat portfolio aggregate — BHP,
     Anglo American, OUTsurance, Sanlam, NEPI Rockcastle, METHODOLOGY.md
     §6.5) are both genuine, targeted signals worth folding into
     win_probability or timing — don't let Phase 6 rediscover these from
     scratch when they're already computed.
8. **Phase 6 opportunity-ranking facts Phase 7/8 need**:
   `data/processed/opportunity_ranking_entity.parquet` is the headline,
   ranked, one-row-per-entity output the Phase 8 dashboard's "portfolio-
   level summary" should read directly, not re-derive. Its `is_global_major`
   column is how the SA-domestic/global-major split (item #7 above) is
   already applied — filter on it rather than re-importing
   `GLOBAL_MAJOR_ENTITIES` and redoing the split. `total_expected_value_zar`
   is the ranking metric, not `total_wallet_gap_zar` — the whole point of
   Phase 6 was ranking by expected value, not raw gap size; don't let a
   later phase quietly regress to sorting by gap. Its `top_pillar` column
   is Transactional Banking for all 20 entities by design (§7.6) — a
   dashboard drill-down should still show all 3 pillars per entity
   (`opportunity_ranking_pillar.parquet`), not just the top one.
9. **Phase 8 facts, if you're building Phase 7 (the only phase left)**:
   there's now a THIRD Gen AI component (`src/briefing.py`, namespace
   `client_briefing_notes`) — if Phase 7's latency/cost work wants a
   second data point beyond Phase 2's `gemini-2.5-flash` baseline, this
   is available too, and already logs latency/tokens to the same
   `reports/llm_usage_log.jsonl`. The dashboard (`app/dashboard.py`) is
   NOT part of `run_all.py`'s CLI chain (it's `streamlit run`, an
   interactive app, not a batch step) — `run_all.py`'s `briefing` step
   only regenerates the briefing notes the dashboard reads, nothing
   dashboard-specific needs to change if you extend the pipeline further
   upstream. If Phase 7 produces new output worth surfacing, add a 7th
   dashboard page rather than a separate app.
10. **Real bugs already found & fixed — don't reintroduce them.** All have
   regression tests (`tests/test_forensics.py`, `tests/test_llm.py`,
   `tests/test_financials.py`):
   - `a == b` on a pandas Series containing `None`/`NaN` is **not** the
     same as scalar `a == b`: `None == None` is `False` on a Series (SQL
     NULL semantics), not `True`. This silently inflated a disagreement
     rate from 20% to a bogus 66.7% before it was caught. Use
     `src.forensics._null_safe_eq(a, b)` for any future nullable-field
     Series comparison — never write `col_a == col_b` directly when either
     side can be null.
   - `google-genai`'s own internal retry doesn't catch every transient
     error — a 4,199-row run had 20 rows (0.5%) silently fail on a bare
     `httpx.ReadError` with zero retries. `src.llm._is_retryable` retries
     `httpx.TransportError` / `TimeoutError` / `ConnectionError` in
     addition to `APIError` codes 429/500/502/503/504. Keep it that way if
     you touch retry logic.
   - A ground-truth scorer that treats "extracted null" as *always* a
     mismatch is wrong whenever the ground truth itself expects null (e.g.
     `cost_of_sales` for an insurer) — it penalises the pipeline for
     correctly declining to invent a figure. `src.financials.
     score_against_ground_truth` special-cases an empty
     `ground_truth_value` as "expected null"; see
     `tests/test_financials.py`'s `test_expected_null_*` tests for the
     shape of this bug if you write another ground-truth scorer.

## Working conventions established so far — follow these, don't reinvent

- Every phase is a standalone `src/<phase>.py` with a `main()`, runnable as
  `python -m src.<phase>`, and chained by `run_all.py` (extend `PHASES` and
  the phase-dispatch block there as each new phase lands).
- Shared paths/constants → `src/common.py`. Never redefine
  `EXPECTED_ENTITIES`, `KNOWN_COMPETITOR_BENEFICIARIES`, or path constants
  locally inside a phase module.
- **All LLM calls go through `src.llm.generate_structured()`** — never call
  the `google.genai` SDK directly from a phase module. It handles prompt
  logging (`prompts/<namespace>/*.json`), response caching
  (`cache/<namespace>/*.json`, gitignored, content-addressed so reruns
  after a fix are free), and the usage ledger
  (`reports/llm_usage_log.jsonl`) for you. Give each phase its own
  `namespace` string.
- Every LLM response schema is a `pydantic.BaseModel` (+ `Enum` for closed
  categories) with a real `description=` on every field — it's part of the
  JSON schema Gemini actually sees, not just documentation. See
  `forensics.py`'s `MemoExtraction` for the pattern.
- Cross-check every LLM extraction against *something* independent and
  report a measurable accuracy figure, not just an aggregate vibe — two
  patterns established so far, use whichever fits: (a) a deterministic
  regex/rule-based baseline compared row-by-row with a disagreement rate
  broken down by field (`src/forensics.py`'s `disagreement_summary` /
  `confidence_calibration_table`), for when a cheap non-LLM baseline
  exists; (b) a small hand-labelled ground-truth sample independently
  re-verified against primary/alternate sources, scored field-by-field
  (`src/financials.py`'s `score_against_ground_truth` +
  `tests/financials_ground_truth.csv`), for when it doesn't. Don't ship an
  LLM component without one of these; it's the 20% Gen AI criterion's
  measurability requirement.
- Null propagates. **Never** fill a missing external figure or an
  unresolved extraction with a plausible-looking estimate — return
  `None`/null and let uncertainty widen downstream (Phase 5's job). Give
  the LLM schema an explicit way to say "this field doesn't apply to this
  entity" distinct from "not found" when the two are genuinely different
  (see `not_applicable_fields` in `src/financials.py`) — collapsing them
  into one null hides a real modelling fact.
- Yield/intensity assumptions → `config/assumptions.yaml` only (Phase 4+),
  one named + sourced comment per assumption. Never inline a coefficient
  in modelling code.
- **Spot-check extracted values against the raw source text yourself,
  entity by entity, before trusting a clean pipeline run or a passing
  ground-truth score** — Phase 3's fiscal-year-selection bug (see
  "Must-know" #5) affected 10/20 entities and would not have been caught
  by the ground-truth sample alone if that sample had been built *after*
  the buggy run instead of independently. A green `pytest` run is not the
  same thing as correct output.
- New logic that isn't obviously correct by inspection (regex baselines,
  null-handling, agreement/comparison/scoring logic) gets a
  `tests/test_*.py` unit test before you move on — every bug above was
  exactly this kind of thing. Run `python -m pytest tests/ -q` before
  considering any change done (43 passing as of Phase 4).
- Update `METHODOLOGY.md` as you go (design rationale + a limitation you
  noticed), in the same session you build the phase — not as a last-minute
  writeup. Update this file's Session Log (below) before you end a session.

## How to run what exists

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in your OWN GEMINI_API_KEY
python run_all.py                     # Phases 1-6 + the Phase 8 briefing-notes step (everything
                                       #   built so far EXCEPT Phase 7, which is still open),
                                       #   ~3-4 min -- Phase 5's Monte Carlo defaults to 2000
                                       #   iterations; --mc-iterations 200 for a faster/rougher run
streamlit run app/dashboard.py        # Phase 8 dashboard -- separate from run_all.py, interactive
python -m pytest tests/ -q            # 70 tests, all should pass, no API key needed
```

Raw CSVs go in `data/` as `transactional_banking.csv`,
`cross_border_payments.csv`, `trade_finance.csv` (gitignored — 392MB+33MB+3MB
exceeds GitHub's 100MB single-file limit; get them from the team). Everything
needed to inspect Phase 1–6/8 output *without* rerunning anything is already
committed: `reports/`, `prompts/`, `data/processed/*.parquet`,
`data/external/raw/` (Phase 3's fetched source text).

## Session log

Append a dated entry here at the end of every session — a few lines: what
you built/changed, key decisions made, what you'd tell the next agent to do
first. **Do not delete earlier entries** — this is the handoff mechanism
between sessions/agents on this project. **When citing a METHODOLOGY.md
section, cite it by heading text, not a hardcoded `§N` number** — every
phase added so far has renumbered everything after it, and old entries'
`§N` references go stale the moment the next phase lands. A few earlier
entries below still have hardcoded numbers with an inline "renumbered
since" correction; don't add more of those, just avoid the number
entirely going forward.

### 2026-08-08 — Claude (Sonnet 5), initial build

Built Phase 1 (`src/ingest.py`) and Phase 2 (`src/forensics.py` +
`src/llm.py`) end to end, all 4,199 memo rows processed with Gemini
2.5 Flash. Found the competitor-credit signal is ~3x bigger than briefed
(`transactional_banking.csv` carries the same fingerprint; hackathon.txt
only describes 2 of the 3 files). Found + fixed 2 real bugs during
validation (see "Must-know" #6 above) — both were caught by actually
running the pipeline at small scale before scaling up, not by inspection;
recommend the same discipline for later phases. 22 tests passing.
Repo scaffolding (`run_all.py`, `requirements.txt`, `.gitignore`,
`README.md`, `METHODOLOGY.md`, `PLAN.md`, this file) is in place and
should not need restructuring for later phases, just extending.

**Next agent: start Phase 3 (`src/financials.py`) per `PLAN.md`.** Key
thing to internalise before starting: no PDFs were supplied, so this is
real sourcing against public filings (JSE SENS / investor relations /
annual reports) for the 20 entities in `src.common.EXPECTED_ENTITIES`, to
a strict schema, with a source URL + confidence flag on every figure, and
a hand-labelled `tests/financials_ground_truth.csv` to report field-level
accuracy against. Nothing gets invented — null propagates. Log every
source in `reports/external_sources.md`.

### 2026-08-11 — Claude (Sonnet 5), Phase 3

Built Phase 3 (`src/financials.py`) end to end: 20 entities' core financials
(revenue, cost of sales, inventory, trade receivables/payables, total debt)
sourced from stockanalysis.com (a filings-derived aggregator, used for
cross-company consistency — no PDFs exist, see "Must-know" #3), foreign
revenue % from targeted per-entity research, all raw fetched text committed
at `data/external/raw/` before any LLM touches it (same "evidence first"
discipline as Phase 2). Gemini extraction to a strict schema mirrors
Phase 2's shape (confidence per field, cached + logged the same way).

**Found and fixed a real, significant bug**: the first full run picked the
wrong (stale) fiscal year for 10/20 entities — a genuine LLM recency/
anchoring bias, not a prompt-engineering afterthought; see "Must-know" #5
and METHODOLOGY.md §4.1 for the root-cause story and the fix (explicit
today's-date anchoring + an explicit period-selection algorithm in the
system instruction). This is the kind of thing that's easy to miss if you
only look at whether the pipeline *runs* cleanly rather than *spot-check
the actual extracted values* — do the same discipline for Phase 4+.
Also surfaced (not resolved) a genuine cross-aggregator definitional
disagreement on Anglo American's cost of sales (METHODOLOGY.md §4.2) —
don't be surprised if this recurs on other entities in later phases;
disclose it, don't silently pick a source.

Final: ground-truth accuracy 19/19 (100.0%) after the fix, 31/31 tests
passing, `python run_all.py` runs Phases 1-3 end to end in ~25s (fully
cached). `foreign_revenue_pct` coverage is honestly low (30%, 6/20) and
`debt_maturity_profile`/`undrawn_facilities` were scoped out of the schema
entirely (see METHODOLOGY.md's Limitations section — its number keeps
shifting as phases are added, search by heading text, not a hardcoded §
number, in any session-log entry including this one) — both worth
reconsidering if Phase 4's Investment Banking pillar ends up needing them
more than expected. (Verdict, Phase 4 session below: it didn't —
`total_debt` alone was sufficient for the debt-arrangement TAM.)

**Next agent: start Phase 4 (`src/wallet.py`) per `PLAN.md`.** This is
where `config/assumptions.yaml` (currently an empty skeleton) gets
populated for real — every yield/intensity coefficient named and sourced,
never inline. Phase 2's `competitor_credit_events.parquet` (primary/
secondary tier) and Phase 3's `financial_baseline.parquet` are both ready
to build against. Read METHODOLOGY.md §4.3 before trusting
`foreign_revenue_pct` or `cost_of_sales` at face value for every entity —
both have entity-specific caveats logged, not uniform confidence.

### 2026-08-11 — Claude (Sonnet 5), Phase 4 (same day, continued session)

Built Phase 4 (`src/wallet.py`) end to end and fully populated
`config/assumptions.yaml` (was an empty skeleton). Three pillars per
hackathon.txt (Transactional Banking, Global Markets, Investment Banking),
each sub-component computing TAM and Syn Bank's captured revenue with the
SAME yield so `share_of_wallet = captured/tam` is like-for-like. Where the
captured side is structurally unobservable from the 3 source files (no
derivatives book, no "loans Syn Bank originated" table) it's reported as
`None`, never `0` — see "Must-know" #7 for exactly which 3 sub-components.

**Two findings surfaced deliberately, not smoothed over** (full detail:
METHODOLOGY.md §5.2, "Must-know" #7): a TAM-assumption breach on Pepkor's
`deposit_nii` (captured > TAM — flagged via `tam_assumption_breach`
column, not clipped to 100%), and a structural distortion for 8 dual-
listed "global major" entities whose Phase 3 revenue is global not
SA-specific, inflating their TAM denominator and making their low
share-of-wallet numbers non-comparable to the other 12 entities.
**Phase 6 must read `GLOBAL_MAJOR_ENTITIES` and `tam_assumption_breach`
before ranking anyone — this is not optional cleanup, it changes the
ranking.**

Result: portfolio TAM R18.6bn, captured R977.3m, blended share 5.3% (sum
of sub-components observable on the SAME row — an independent-sum version
was briefly wrong at 4.6%, found and fixed same-session before Phase 5
built on it, see METHODOLOGY.md §5.3). 43/43 tests passing (12 new),
`python run_all.py` runs Phases 1-4 end to end in ~15s (fully cached).
`config/assumptions.yaml`'s fee/margin/bps figures are disclosed as
informed market-practice estimates (no SA bank publishes a corporate
pricing rate card), each named as a Phase 5 Monte Carlo/sensitivity
target — this is intentional, not a placeholder to "fix" later; Phase 5's
whole job is to quantify what these estimates being wrong does to the
answer.

**Next agent: start Phase 5 (`src/uncertainty.py`) per `PLAN.md`.** 30% of
the mark scheme lives here. Priority order per the brief: (1) Monte Carlo
over `config/assumptions.yaml`'s priors → report SOW as a credible
interval; (2) tornado/sensitivity chart identifying which assumption moves
the answer most (the payment-intensity and trade-finance-share assumptions
are flagged in the yaml comments as the least-anchored — good candidates
to come out on top, worth checking if they don't); (3) a second,
independent SOW estimator based on revealed presence/product breadth to
triangulate against the yield-based estimate in `wallet_model.parquet`
— where the two diverge is explicitly called out in the brief as "the most
interesting slide in the deck," don't bury it; (4) sector regression of
wallet-intensity; (5) time-trend test (the brief already tells you
aggregate volume is flat 2023-07 to 2026-06 — check whether that holds
per-entity too, and say so either way, don't manufacture a trend that
isn't there). Read METHODOLOGY.md's Phase 4 section and its Limitations
section in full before starting (section numbers keep shifting as phases
are added — search by heading text) — several Phase 4 outputs (the TAM
breach, the global-majors cohort, the 3 structurally-unobservable sub-components) are
exactly the kind of thing a credible interval and a tornado chart should
visibly reflect, not paper over.

### 2026-08-11 — Claude (Sonnet 5), Phase 5 (same day, continued session)

Built Phase 5 (`src/uncertainty.py`) end to end: Monte Carlo (2,000
iterations), tornado sensitivity, the revealed-presence second SOW
estimator + triangulation, sector regression, and the time-trend test —
all five per hackathon.txt's spec, all built on `config/assumptions.yaml`
(added `low`/`high` to every leaf, same file Phase 4 uses, never a second
set of parameters). Refactored `src.wallet.build_wallet_model` to accept
pre-loaded data so 2,000 iterations run in ~3 minutes instead of
re-hitting DuckDB/parquet every draw.

**Found and fixed a real bug in Phase 4 before Phase 5 built on it**: the
portfolio blended share was computed by summing `tam_zar` and
`captured_zar` independently (dropna per column) rather than only over
rows where both are observable — this double-dipped `fx_hedging`'s
captured leg (always observable) against a null TAM for the 14/20 entities
missing `foreign_revenue_pct`, inflating the blended share from a correct
5.3% to a wrong 4.6%. Fixed (`src.wallet.blended_tam_and_captured`,
row-aligned, regression-tested) — caught by actually re-deriving the
number by hand before trusting it, not by the pipeline raising an
exception. **Every Phase 4 figure quoted anywhere in the docs was updated
to the corrected 5.3%/R18.6bn/R977.3m** — check you're not looking at a
stale 4.6%/R25.9bn figure if you find one anywhere (should be none left,
but this is exactly the kind of thing that hides in a stale comment).

Results: portfolio blended share credible interval **3.1%-6.8%** (never
report the 5.3% point estimate alone). Tornado top-4 all in Transactional
Banking, confirming `payments_per_zar_throughput` as the least-anchored
assumption empirically, not just by comment. 5 assumptions show 0.00pp
*share* swing by construction (only move TAM on sub-components with a
null captured side) — real TAM impact shown via a separate independent-sum
column so this isn't misread as "doesn't matter." Revealed-presence
estimator diverges systematically high vs. yield-based for 17/20 entities
(this specific client set is uniformly broad-usage, limiting the method's
discriminating power — a limitation of the method on THIS portfolio, not
a claim the yield-based numbers are wrong) — except Pepkor, where it
independently corroborates the Phase 4 TAM-breach finding. Sector
regression flags 2 entities (Valterra Platinum, Clicks Group) below their
sector line; muted for most pillars by construction since Transactional
Banking's TAM is deliberately proportional to revenue. Time trends: 0/5
corridors significant (confirms Phase 1), but 5/20 entities show a
Bonferroni-surviving trend (BHP, Anglo American, OUTsurance, Sanlam, NEPI
Rockcastle) — both facts stated together, neither hidden. 57/57 tests
passing (13 new). Full derivation: METHODOLOGY.md §6.

**Next agent: start Phase 6 (`src/opportunity.py`) per `PLAN.md`.** Rank
by `expected_value = wallet_gap × win_probability × margin`, not raw gap
size. Everything Phase 6 needs from Phases 4-5 is already computed, not
raw material to re-derive — see "Must-know" #7 above for the specific
files/columns/entity flags to build against (`GLOBAL_MAJOR_ENTITIES`,
`tam_assumption_breach`, the Monte Carlo credible interval, the
below-sector-line and Bonferroni-trending entity lists). Respect product
sequencing (FX follows payment flow, not the reverse — flag any
recommendation that violates this, per PLAN.md's Phase 6 spec). Read
METHODOLOGY.md's Phase 5 section and its Limitations section before
starting (section numbers keep shifting as phases are added — search by
heading text, not a hardcoded § number, in this or any older session-log
entry).

### 2026-08-11 — Claude (Sonnet 5), Phase 6 (same day, continued session)

Built Phase 6 (`src/opportunity.py`) end to end: ranks all 20 entities by
`expected_value = wallet_gap × win_probability × margin` per hackathon.txt's
formula, reusing Phase 4/5 outputs directly rather than re-deriving
signals (`win_probability` = weighted blend of Phase 5's revealed-presence
breadth, Transactional Banking relationship strength, the Bonferroni-trend
momentum signal, and country-corridor adjacency — all 4 signals the brief
names explicitly). `wallet_gap` keeps the same row-alignment discipline as
Phase 4/5 — only counted where captured is directly observable, the 3
structurally-unobservable sub-components report a separate
`unknown_capture_potential_zar` diagnostic instead of a false-precision
blend. `margin` is a NEW `net_margin_realization` assumption (65% base
case), not a second application of Phase 4's yields — wallet_gap is
already revenue, applying a bps yield again would double-count margin.

Product-sequencing enforcement (hackathon.txt: "flag any recommendation
that violates this") found a real, portfolio-level result, not noise:
**30/40 Global Markets/Investment Banking rows are sequencing-flagged**,
directly reflecting Phase 4's already-known thin Transactional Banking
capture (4.9% blended share) — win_probability is halved for these, not
zeroed, and the report says explicitly this is a portfolio finding, not
30 isolated edge cases. Global majors ranked in a fully separate section
per the Phase 4/5 handoff instruction (Glencore alone would otherwise show
a R3.13bn "opportunity" that's purely a global-revenue-denominator
artefact). `breadth_score` shows the same near-1.0, low-discriminating-
power pattern already found in Phase 5 for this portfolio — disclosed
again here rather than silently reduced to look more useful. Top
SA-domestic opportunity: **Shoprite Holdings**, R193.8m expected value.

67/67 tests passing (10 new). `run_all.py` chains Phase 6. Docs updated:
METHODOLOGY.md (§7, all of 7.1-7.6 + limitations), CLAUDE.md (must-know
#8 for what Phase 7/8 should read directly, not rebuild), PLAN.md,
README.md.

**Next agent: Phase 7 (bonus modules) or Phase 8 (dashboard) per
`PLAN.md`.** Recommendation, not a decision made unilaterally — check with
whoever's steering the submission before picking: hackathon.txt's
Deliverables list makes the dashboard a REQUIRED submission component
(portfolio summary, per-client drill-down, opportunity heatmap, AI
briefing notes for 3+ clients, the competitor-credit finding as a
dedicated view) with real weight in the 10% Presentation & Storytelling
criterion, while Phase 7 is explicitly labelled "bonus" in both
hackathon.txt and PLAN.md — Phase 8 is very likely the higher-priority
next step for a submission that has to ship, not just score well on
technical merit. If you build Phase 8, `data/processed/opportunity_ranking_entity.parquet`
is the direct source for the portfolio-summary view (see "Must-know" #8)
— don't recompute it inside the dashboard.

### 2026-08-11 — Claude (Sonnet 5), Phase 8 (same day, continued session)

User picked Phase 8 over Phase 7 (asked explicitly rather than assumed —
see the prior entry's recommendation). Built `src/briefing.py` (Gen AI
component #3 — AI client briefing notes, all 20 entities, grounded
strictly in Phase 2-6 output via the same `generate_structured` pipeline
every other Gen AI phase uses) and `app/dashboard.py` (Streamlit, 6 pages:
Portfolio Summary, Client Drill-Down, Opportunity Heatmap, AI Briefing
Notes, Competitor-Credit Finding, Rigor & Assumptions). Loaded the
`dataviz` skill before writing any chart code — categorical/sequential/
status colours below are its validated reference palette, not picked by
eye.

**Found and fixed two real gaps, both by actually checking the output,
not by assuming the code was correct because it ran:**
- `src/briefing.py`'s context builder omitted `tam_assumption_breach`
  entirely — Pepkor's briefing (the one entity it applies to) silently
  dropped a finding already established three phases ago. Caught by
  reading Pepkor's specific output, not by a general review. Fixed, all
  20 briefings regenerated.
- The dashboard was verified by actually launching it (`streamlit run`)
  and driving it headlessly with Playwright through all 6 pages —
  screenshots reviewed, `console --errors` checked (zero). This caught
  two real issues a code read would not have: the wallet-gap-by-pillar
  chart's category order wasn't pinned (varied per entity, breaking
  cross-client comparability — fixed with an explicit `Categorical`
  dtype), and the AI Briefing Notes page defaulted to showing global
  majors first (their inflated expected-value figures dominate any
  unfiltered sort) instead of the SA-domestic entities every other page
  treats as primary. **Lesson for whoever builds Phase 7 or touches the
  dashboard again: `pytest` passing and the app launching without a
  Python exception are NOT the same as the app being correct — drive it
  and look at it.**

70/70 tests passing (3 new, `tests/test_briefing.py` — `test_uncertainty.py`-
style pure-function tests; no `tests/test_dashboard.py`, the dashboard was
verified by driving it, not by a unit-test suite, see METHODOLOGY.md §9
limitations). `run_all.py`'s `briefing` step regenerates the dashboard's
AI notes (the dashboard itself is `streamlit run app/dashboard.py`,
separate from the CLI chain — it's an interactive app, not a batch step).
Docs updated: METHODOLOGY.md (§8, both sub-sections + limitations),
CLAUDE.md (must-know #9 + this entry), PLAN.md, README.md.

**All of hackathon.txt's REQUIRED deliverables are now built.** Only
Phase 7 (explicitly "bonus" in the brief) remains open — see PLAN.md for
its spec (cash-cycle timing, LLM latency/cost optimisation) if there's
time to build it. If not, this is a complete, submittable pipeline as-is.
