"""
Phase 1 — Ingestion & Profiling
================================
Loads the three Syn Bank source files, materialises them into a single
DuckDB database (``data/processed/syn_bank.duckdb``) that every downstream
phase reuses, and emits a profiling report: row counts, entity coverage,
date ranges, null rates, and categorical cardinality for every column worth
enumerating.

transactional_banking.csv (392MB, ~2.8m rows) is read straight off disk by
DuckDB and never materialised whole into pandas. The two small files
(cross_border_payments.csv ~33MB, trade_finance.csv ~3MB) are also loaded
through DuckDB so every later phase queries one engine instead of
re-parsing CSVs; pandas is used only for the report tables themselves,
which are tiny aggregates by the time they leave DuckDB.

Also runs a first-pass numeric cross-tab of the "competitor-credit"
fingerprint (see METHODOLOGY.md) across all three files' memo columns. The
brief's key finding was verified on cross_border_payments.csv and
trade_finance.csv only; this phase checks transactional_banking.csv's memo
column too, on the "assert what we already know, flag what's new"
principle profiling exists for. The narrative interpretation of that
cross-tab is Phase 2's job (src/forensics.py) — this module only reports
counts and rand totals.

Run standalone:
    python -m src.ingest
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from src.common import (
    CACHE_DIR,
    CROSS_BORDER_PAYMENTS_CSV,
    DUCKDB_PATH,
    EXPECTED_ENTITIES,
    EXPECTED_ENTITY_IDS,
    KNOWN_COMPETITOR_BENEFICIARIES,
    N_EXPECTED_ENTITIES,
    PROCESSED_DIR,
    REPORTS_DIR,
    TRADE_FINANCE_CSV,
    TRANSACTIONAL_BANKING_CSV,
    configure_logging,
    ensure_dirs,
)

logger = logging.getLogger(__name__)


class EntityCoverageError(RuntimeError):
    """Raised when a source file's entity_id set doesn't exactly match the
    20 expected clients. This is the "fail loudly" check the brief asks for
    -- everything downstream (yields, wallet sizing, rankings) assumes a
    stable, complete 20-entity universe."""


class RawFileMissingError(RuntimeError):
    """Raised when a required raw CSV isn't in data/. Raw CSVs are
    gitignored (392MB+33MB+3MB exceeds GitHub's 100MB single-file limit) so
    a fresh clone needs them dropped in by hand -- see README.md."""


# --------------------------------------------------------------------------
# Per-table schema declarations (drives generic profiling below)
# --------------------------------------------------------------------------
TABLE_SCHEMAS: dict[str, dict[str, Any]] = {
    "transactional_banking": {
        "csv": TRANSACTIONAL_BANKING_CSV,
        "id_col": "transaction_id",
        "amount_col": "amount_zar",
        "date_col": "date",
        # currency_norm is a derived column (UPPER(TRIM(currency))) added at
        # load time -- kept alongside raw `currency` so the report shows the
        # ZAR/zar case inconsistency explicitly rather than silently fixing it.
        "categorical_cols": ["sector", "leg_type", "direction", "channel", "currency", "currency_norm"],
        "free_text_cols": ["beneficiary_name", "reference", "memo"],
    },
    "cross_border_payments": {
        "csv": CROSS_BORDER_PAYMENTS_CSV,
        "id_col": "transaction_id",
        "amount_col": "value_zar",
        "date_col": "date",
        "categorical_cols": ["sector", "direction", "currency_pair", "counterparty_country", "corridor_type"],
        "free_text_cols": ["beneficiary_name", "reference", "memo"],
    },
    "trade_finance": {
        "csv": TRADE_FINANCE_CSV,
        "id_col": "instrument_id",
        "amount_col": "value_zar",
        "date_col": "date",
        "categorical_cols": [
            "sector",
            "instrument_type",
            "direction",
            "counterparty_country",
            "commodity_or_contract_type",
            "status",
        ],
        "free_text_cols": ["beneficiary_name", "reference", "memo"],
    },
}

# Cap how many distinct values of a categorical column get written into the
# report. None of our columns actually hit this (max cardinality is
# counterparty_country at 34) -- it's a safety valve, not a real limit.
MAX_CATEGORY_VALUES = 60


def _require_raw_files() -> None:
    for name, path in [
        ("transactional_banking.csv", TRANSACTIONAL_BANKING_CSV),
        ("cross_border_payments.csv", CROSS_BORDER_PAYMENTS_CSV),
        ("trade_finance.csv", TRADE_FINANCE_CSV),
    ]:
        if not path.exists():
            raise RawFileMissingError(
                f"Missing {name} at {path}. Raw CSVs are gitignored (too large for "
                f"GitHub) -- copy the three hackathon-provided files into data/ "
                f"before running the pipeline. See README.md."
            )


def build_duckdb() -> duckdb.DuckDBPyConnection:
    """Materialise all three raw CSVs into a persisted DuckDB file.

    Idempotent: reruns DROP/CREATE the tables fresh rather than appending.
    """
    ensure_dirs()
    _require_raw_files()
    con = duckdb.connect(str(DUCKDB_PATH))

    logger.info("Materialising transactional_banking.csv (392MB, ~2.8m rows) via DuckDB ...")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE transactional_banking AS
        SELECT *, UPPER(TRIM(currency)) AS currency_norm
        FROM read_csv_auto('{TRANSACTIONAL_BANKING_CSV.as_posix()}')
        """
    )

    logger.info("Loading cross_border_payments.csv ...")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cross_border_payments AS
        SELECT * FROM read_csv_auto('{CROSS_BORDER_PAYMENTS_CSV.as_posix()}')
        """
    )

    logger.info("Loading trade_finance.csv ...")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE trade_finance AS
        SELECT * FROM read_csv_auto('{TRADE_FINANCE_CSV.as_posix()}')
        """
    )

    return con


# --------------------------------------------------------------------------
# Entity master validation
# --------------------------------------------------------------------------
def validate_entity_master(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Assert every table contains exactly the 20 expected entity_ids, and
    that entity_id -> (entity_name, sector) agrees across all three files
    and matches the hardcoded ground truth in src.common.EXPECTED_ENTITIES.

    Raises EntityCoverageError with a specific diff on any violation.
    Returns the validated entity master as a DataFrame (entity_id sorted).
    """
    per_table_ids: dict[str, set[str]] = {}
    combos: dict[str, set[tuple[str, str]]] = {}  # entity_id -> {(name, sector), ...}

    for table in TABLE_SCHEMAS:
        df = con.sql(f"SELECT DISTINCT entity_id, entity_name, sector FROM {table}").fetchdf()
        per_table_ids[table] = set(df["entity_id"])
        for _, row in df.iterrows():
            combos.setdefault(row["entity_id"], set()).add((row["entity_name"], row["sector"]))

    errors: list[str] = []

    for table, ids in per_table_ids.items():
        missing = EXPECTED_ENTITY_IDS - ids
        extra = ids - EXPECTED_ENTITY_IDS
        if missing:
            errors.append(f"{table}: missing expected entity_ids {sorted(missing)}")
        if extra:
            errors.append(f"{table}: unexpected entity_ids not in the 20-client master {sorted(extra)}")
        if len(ids) != N_EXPECTED_ENTITIES:
            errors.append(f"{table}: expected {N_EXPECTED_ENTITIES} distinct entity_ids, found {len(ids)}")

    for entity_id, name_sector_set in combos.items():
        if len(name_sector_set) > 1:
            errors.append(f"{entity_id}: inconsistent (entity_name, sector) across files: {name_sector_set}")
        expected = EXPECTED_ENTITIES.get(entity_id)
        if expected is not None and name_sector_set:
            actual_name, actual_sector = next(iter(name_sector_set))
            if (actual_name, actual_sector) != (expected["name"], expected["sector"]):
                errors.append(
                    f"{entity_id}: data says ({actual_name}, {actual_sector}), "
                    f"hardcoded ground truth says ({expected['name']}, {expected['sector']})"
                )

    if errors:
        raise EntityCoverageError(
            "Entity master validation FAILED -- the 20-client universe has drifted "
            "from the ground truth every downstream phase assumes:\n  - " + "\n  - ".join(errors)
        )

    logger.info("Entity master validated: all 20 expected entity_ids present and consistent across all 3 files.")
    return pd.DataFrame(
        [{"entity_id": eid, "entity_name": v["name"], "sector": v["sector"]} for eid, v in sorted(EXPECTED_ENTITIES.items())]
    )


# --------------------------------------------------------------------------
# Generic profiling
# --------------------------------------------------------------------------
def profile_table(con: duckdb.DuckDBPyConnection, table: str, schema: dict[str, Any]) -> dict[str, Any]:
    logger.info("Profiling %s ...", table)
    columns_df = con.sql(f"DESCRIBE {table}").fetchdf()
    all_cols = columns_df["column_name"].tolist()

    n_rows = con.sql(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    null_expr = ", ".join(f"ROUND(100.0 * SUM(CASE WHEN \"{c}\" IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS \"{c}\"" for c in all_cols)
    null_rates = con.sql(f"SELECT {null_expr} FROM {table}").fetchdf().iloc[0].to_dict()

    date_col = schema.get("date_col")
    date_range = None
    if date_col:
        mind, maxd = con.sql(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}").fetchone()
        date_range = {"min": str(mind), "max": str(maxd)}

    amount_col = schema.get("amount_col")
    amount_stats = None
    if amount_col:
        n_amt, min_a, max_a, sum_a, avg_a = con.sql(
            f"SELECT COUNT({amount_col}), MIN({amount_col}), MAX({amount_col}), SUM({amount_col}), AVG({amount_col}) FROM {table}"
        ).fetchone()
        amount_stats = {
            "n": int(n_amt),
            "min": float(min_a),
            "max": float(max_a),
            "sum": float(sum_a),
            "mean": float(avg_a),
        }

    entity_coverage = con.sql(f"SELECT COUNT(DISTINCT entity_id) FROM {table}").fetchone()[0]

    categoricals: dict[str, Any] = {}
    for col in schema.get("categorical_cols", []):
        vc = con.sql(
            f'SELECT "{col}" AS value, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC LIMIT {MAX_CATEGORY_VALUES}'
        ).fetchdf()
        categoricals[col] = {
            "n_distinct": int(con.sql(f'SELECT COUNT(DISTINCT "{col}") FROM {table}').fetchone()[0]),
            "value_counts": dict(zip(vc["value"].astype(str), vc["n"].astype(int))),
        }

    free_text: dict[str, Any] = {}
    for col in schema.get("free_text_cols", []):
        n_distinct, n_nonnull = con.sql(
            f'SELECT COUNT(DISTINCT "{col}"), COUNT("{col}") FROM {table}'
        ).fetchone()
        free_text[col] = {"n_distinct": int(n_distinct), "n_non_null": int(n_nonnull)}

    return {
        "table": table,
        "source_csv": str(schema["csv"]),
        "n_rows": int(n_rows),
        "columns": list(zip(columns_df["column_name"], columns_df["column_type"])),
        "null_rate_pct": {k: (None if pd.isna(v) else float(v)) for k, v in null_rates.items()},
        "date_range": date_range,
        "amount_stats": amount_stats,
        "n_distinct_entities": int(entity_coverage),
        "categoricals": categoricals,
        "free_text": free_text,
    }


# --------------------------------------------------------------------------
# The competitor-credit fingerprint: numeric cross-tab only (Phase 1 scope).
# Interpretation and LLM extraction happen in Phase 2 (src/forensics.py).
# --------------------------------------------------------------------------
def competitor_memo_flag(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    bank_list_sql = ", ".join(f"'{b}'" for b in sorted(KNOWN_COMPETITOR_BENEFICIARIES))
    out: dict[str, Any] = {}

    # cross_border_payments: brief's original verified finding.
    out["cross_border_payments"] = con.sql(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE memo IS NOT NULL) AS n_memo_rows,
            COALESCE(SUM(value_zar) FILTER (WHERE memo IS NOT NULL), 0) AS sum_memo_zar,
            COUNT(*) FILTER (WHERE memo IS NOT NULL AND beneficiary_name IN ({bank_list_sql})) AS n_bank_beneficiary,
            COALESCE(SUM(value_zar) FILTER (WHERE memo IS NOT NULL AND beneficiary_name IN ({bank_list_sql})), 0) AS sum_bank_beneficiary_zar,
            COUNT(*) FILTER (WHERE memo IS NOT NULL AND corridor_type = 'trade') AS n_labelled_trade
        FROM cross_border_payments
        """
    ).fetchdf().iloc[0].to_dict()

    # trade_finance: brief's second verified vein (non-bank beneficiaries).
    out["trade_finance"] = con.sql(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE memo IS NOT NULL) AS n_memo_rows,
            COALESCE(SUM(value_zar) FILTER (WHERE memo IS NOT NULL), 0) AS sum_memo_zar,
            COUNT(*) FILTER (WHERE memo IS NOT NULL AND beneficiary_name IN ({bank_list_sql})) AS n_bank_beneficiary,
            COALESCE(SUM(value_zar) FILTER (WHERE memo IS NOT NULL AND beneficiary_name IN ({bank_list_sql})), 0) AS sum_bank_beneficiary_zar
        FROM trade_finance
        """
    ).fetchdf().iloc[0].to_dict()

    # transactional_banking: NOT mentioned in the brief -- this phase checks
    # it anyway because it has its own memo column, and it turns out to
    # carry the same fingerprint at larger rand value. Flagged prominently
    # for the user/team to decide whether to fold into the headline number.
    out["transactional_banking"] = con.sql(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE memo IS NOT NULL) AS n_memo_rows,
            COALESCE(SUM(amount_zar) FILTER (WHERE memo IS NOT NULL), 0) AS sum_memo_zar,
            COUNT(*) FILTER (WHERE memo IS NOT NULL AND beneficiary_name IN ({bank_list_sql})) AS n_bank_beneficiary,
            COALESCE(SUM(amount_zar) FILTER (WHERE memo IS NOT NULL AND beneficiary_name IN ({bank_list_sql})), 0) AS sum_bank_beneficiary_zar,
            COUNT(*) FILTER (WHERE memo IS NOT NULL AND beneficiary_name NOT IN ({bank_list_sql})) AS n_non_bank_beneficiary,
            COALESCE(SUM(amount_zar) FILTER (WHERE memo IS NOT NULL AND beneficiary_name NOT IN ({bank_list_sql})), 0) AS sum_non_bank_beneficiary_zar
        FROM transactional_banking
        """
    ).fetchdf().iloc[0].to_dict()

    return out


# --------------------------------------------------------------------------
# Report rendering
# --------------------------------------------------------------------------
def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return str(o)
    if hasattr(o, "item"):  # numpy scalars
        return o.item()
    raise TypeError(f"Not JSON serialisable: {type(o)}")


def render_markdown(profiles: dict[str, dict], entity_df: pd.DataFrame, competitor_flag: dict) -> str:
    lines: list[str] = []
    lines.append("# Phase 1 — Ingestion & Profiling Report")
    lines.append(f"\nGenerated: {datetime.now().isoformat(timespec='seconds')}\n")
    lines.append(
        "> **Every rand figure below is GROSS FLOW / EXPOSURE observed in the ledgers "
        "-- not bank revenue and not share of wallet.** Converting flow into revenue "
        "requires an explicit yield assumption (bps, fee-per-payment, NII margin, ...); "
        "that conversion happens in Phase 4 (`src/wallet.py`) using named, sourced "
        "assumptions in `config/assumptions.yaml`. See hackathon.txt's domain rule and "
        "METHODOLOGY.md."
    )

    lines.append("## Entity master (20 expected clients — validated)")
    lines.append(entity_df.to_markdown(index=False))

    for table, p in profiles.items():
        lines.append(f"\n## `{table}`")
        lines.append(f"- Source: `{p['source_csv']}`")
        lines.append(f"- Rows: {p['n_rows']:,}")
        lines.append(f"- Distinct entities: {p['n_distinct_entities']} / {N_EXPECTED_ENTITIES}")
        if p["date_range"]:
            lines.append(f"- Date range: {p['date_range']['min']} to {p['date_range']['max']}")
        if p["amount_stats"]:
            a = p["amount_stats"]
            lines.append(
                f"- Amount column (gross flow, NOT revenue): n={a['n']:,}, sum=R{a['sum']:,.0f}, "
                f"mean=R{a['mean']:,.0f}, range=[R{a['min']:,.0f}, R{a['max']:,.0f}]"
            )

        lines.append("\n**Null rates (%)**\n")
        null_df = pd.DataFrame(
            [{"column": k, "null_pct": v} for k, v in p["null_rate_pct"].items()]
        ).sort_values("null_pct", ascending=False)
        lines.append(null_df.to_markdown(index=False))

        if p["categoricals"]:
            lines.append("\n**Categorical cardinality**\n")
            cat_summary = pd.DataFrame(
                [{"column": k, "n_distinct": v["n_distinct"]} for k, v in p["categoricals"].items()]
            )
            lines.append(cat_summary.to_markdown(index=False))
            for col, info in p["categoricals"].items():
                lines.append(f"\n*{col}* top values:\n")
                vc_df = pd.DataFrame(list(info["value_counts"].items()), columns=["value", "n"])
                lines.append(vc_df.head(15).to_markdown(index=False))

        if p["free_text"]:
            lines.append("\n**Free-text columns (id/reference/memo — null rate + cardinality only)**\n")
            ft_df = pd.DataFrame(
                [{"column": k, "n_distinct": v["n_distinct"], "n_non_null": v["n_non_null"]} for k, v in p["free_text"].items()]
            )
            lines.append(ft_df.to_markdown(index=False))

    lines.append("\n## Competitor-credit memo fingerprint — numeric cross-tab (Phase 1; interpreted in Phase 2)")
    lines.append(
        "\nRows where `memo` is non-null, split by whether `beneficiary_name` is one of the 5 "
        "recurring non-Syn-Bank names (`Halcyon Trade Bank`, `Meridian Bank Ltd`, `Northgate "
        "Financial Bank`, `Solstice Capital Bank`, `Crestwood Merchant Bank`). See METHODOLOGY.md.\n"
    )
    cf_rows = []
    for table, d in competitor_flag.items():
        cf_rows.append(
            {
                "table": table,
                "n_memo_rows": int(d.get("n_memo_rows") or 0),
                "sum_memo_zar": float(d.get("sum_memo_zar") or 0),
                "n_bank_beneficiary": int(d.get("n_bank_beneficiary") or 0),
                "sum_bank_beneficiary_zar": float(d.get("sum_bank_beneficiary_zar") or 0),
            }
        )
    lines.append(pd.DataFrame(cf_rows).to_markdown(index=False))

    tb = competitor_flag["transactional_banking"]
    lines.append(
        f"\n**NEW — not in the original brief:** transactional_banking.csv also carries a `memo` "
        f"column. {int(tb['n_memo_rows']):,} non-null rows (R{float(tb['sum_memo_zar']):,.0f}) split into "
        f"{int(tb['n_bank_beneficiary']):,} rows to the same 5 known counterparties "
        f"(R{float(tb['sum_bank_beneficiary_zar']):,.0f}) and {int(tb['n_non_bank_beneficiary']):,} rows "
        f"to ordinary trade counterparties carrying identical template language "
        f"(R{float(tb['sum_non_bank_beneficiary_zar']):,.0f}). See Phase 2 output for interpretation."
    )

    return "\n".join(lines)


def main() -> dict[str, Any]:
    configure_logging()
    con = build_duckdb()
    entity_df = validate_entity_master(con)

    profiles = {table: profile_table(con, table, schema) for table, schema in TABLE_SCHEMAS.items()}
    competitor_flag = competitor_memo_flag(con)

    ensure_dirs()
    json_path = REPORTS_DIR / "profiling_report.json"
    md_path = REPORTS_DIR / "profiling_report.md"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "entity_master": entity_df.to_dict(orient="records"),
        "tables": profiles,
        "competitor_memo_flag": competitor_flag,
    }
    json_path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    md_path.write_text(render_markdown(profiles, entity_df, competitor_flag), encoding="utf-8")

    logger.info("Wrote %s and %s", json_path, md_path)
    con.close()
    return payload


if __name__ == "__main__":
    main()
