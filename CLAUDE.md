# CLAUDE.md

Orientation for any Claude Code agent (or human) picking up this repo cold.
Read this file first. Then:
- **`PLAN.md`** — the full phase-by-phase backlog (authoritative scope, what's
  done, what's next, verbatim spec for unbuilt phases).
- **`METHODOLOGY.md`** — rationale, data findings, and limitations for what
  IS built. Every assumption behind Phase 1–2 lives here.
- **`hackathon.txt`** — the official brief, for context on what's being judged.

Do not start writing phase code from memory of what "share of wallet
hackathons usually look like" — this repo has already made a lot of
specific, non-obvious decisions (see below). Read PLAN.md + METHODOLOGY.md
first or you will redo work or contradict an earlier decision.

## Status: Phase 2 of 8 complete

- [x] Phase 1 — Ingestion & profiling
- [x] Phase 2 — Forensic extraction (Gen AI #1)
- [ ] Phase 3 — External financial baseline (Gen AI #2) **← start here**
- [ ] Phase 4 — Wallet model
- [ ] Phase 5 — Rigor layer (Monte Carlo, sensitivity, triangulation)
- [ ] Phase 6 — Opportunity ranking
- [ ] Phase 7 — Bonus modules (cash-cycle timing, latency/cost optimisation)
- [ ] Phase 8 — Dashboard

Keep this checklist, `README.md`'s, and `PLAN.md`'s checkboxes in sync when
a phase completes.

## Must-know before you touch anything

1. **Domain rule**: share of wallet = revenue, never flow. R1bn of FX flow
   is not R1bn of wallet. Every rand figure in Phase 1/2's output
   (`reports/profiling_report.md`, `reports/forensics_report.md`) is
   **gross flow**, explicitly labelled as such. Phase 4 (not yet built) is
   where flow becomes revenue, via named yield assumptions in
   `config/assumptions.yaml` (skeleton exists, empty) — never hardcode a
   yield coefficient inline in `src/wallet.py` or anywhere else.
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
5. **Gemini, not Claude/OpenAI.** `src/llm.py` wraps `google-genai`. Every
   teammate needs their **own** `.env` with their **own** `GEMINI_API_KEY`
   — `.env` is gitignored on purpose and does **not** come through on
   `git pull`. Copy `.env.example` → `.env`, fill in a key from
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
   Every LLM-calling phase degrades gracefully to a regex/deterministic
   baseline with no key configured (clearly flagged in its output), so you
   *can* work on non-LLM code without one — but you won't get real Gen AI
   results to show until you add a key.
6. **Two real bugs already found & fixed in Phase 2 — don't reintroduce
   them.** Both have regression tests (`tests/test_forensics.py`,
   `tests/test_llm.py`):
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
- Cross-check every LLM extraction against a deterministic baseline and
  report a disagreement rate broken down by field, not just an aggregate —
  see `src/forensics.py`'s `disagreement_summary` /
  `confidence_calibration_table` for the level of detail expected. Don't
  ship an LLM component without this; it's the 20% Gen AI criterion's
  measurability requirement.
- Null propagates. **Never** fill a missing external figure (Phase 3) or
  an unresolved extraction (Phase 2-style) with a plausible-looking
  estimate — return `None`/null and let uncertainty widen downstream
  (Phase 5's job).
- Yield/intensity assumptions → `config/assumptions.yaml` only (Phase 4+),
  one named + sourced comment per assumption. Never inline a coefficient
  in modelling code.
- New logic that isn't obviously correct by inspection (regex baselines,
  null-handling, agreement/comparison logic) gets a `tests/test_*.py` unit
  test before you move on — the two bugs above were both exactly this kind
  of thing. Run `python -m pytest tests/ -q` before considering any change
  done (22 passing as of Phase 2).
- Update `METHODOLOGY.md` as you go (design rationale + a limitation you
  noticed), in the same session you build the phase — not as a last-minute
  writeup. Update this file's Session Log (below) before you end a session.

## How to run what exists

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in your OWN GEMINI_API_KEY
python run_all.py                     # Phases 1-2 (everything built so far)
python -m pytest tests/ -q            # 22 tests, all should pass, no API key needed
```

Raw CSVs go in `data/` as `transactional_banking.csv`,
`cross_border_payments.csv`, `trade_finance.csv` (gitignored — 392MB+33MB+3MB
exceeds GitHub's 100MB single-file limit; get them from the team). Everything
needed to inspect Phase 1–2 output *without* rerunning anything is already
committed: `reports/`, `prompts/`, `data/processed/*.parquet`.

## Session log

Append a dated entry here at the end of every session — a few lines: what
you built/changed, key decisions made, what you'd tell the next agent to do
first. **Do not delete earlier entries** — this is the handoff mechanism
between sessions/agents on this project.

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
