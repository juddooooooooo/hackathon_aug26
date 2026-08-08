"""Shared constants and utilities used across every pipeline phase.

Centralised here so that path locations, the canonical 20-entity list, and
the "known competitor beneficiary" fingerprint (the spine of the whole
submission — see METHODOLOGY.md) are each defined exactly once. No phase
module should redefine or re-derive these independently.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
CONFIG_DIR = ROOT / "config"
REPORTS_DIR = ROOT / "reports"
PROMPTS_DIR = ROOT / "prompts"
CACHE_DIR = ROOT / "cache"
TESTS_DIR = ROOT / "tests"

# Raw source files (renamed from the hackathon's original download names --
# see METHODOLOGY.md "Data received" -- to keep paths shell- and
# Makefile-safe on every OS).
TRANSACTIONAL_BANKING_CSV = DATA_DIR / "transactional_banking.csv"
CROSS_BORDER_PAYMENTS_CSV = DATA_DIR / "cross_border_payments.csv"
TRADE_FINANCE_CSV = DATA_DIR / "trade_finance.csv"

DUCKDB_PATH = PROCESSED_DIR / "syn_bank.duckdb"

REQUIRED_DIRS = (PROCESSED_DIR, REPORTS_DIR, PROMPTS_DIR, CACHE_DIR, CONFIG_DIR, TESTS_DIR)


def ensure_dirs() -> None:
    """Create every output directory the pipeline writes to.

    These are gitignored (except for small deliverable artefacts we choose to
    commit), so a fresh clone needs them created before any phase can write
    to them.
    """
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# The 20 JSE-listed corporate clients
# --------------------------------------------------------------------------
# Ground truth to assert against on every load. hackathon.txt describes a
# 50-client portfolio; only these 20 appear in every one of the three
# provided files. Flagged explicitly in METHODOLOGY.md rather than glossed
# over -- see "Data discrepancies".
EXPECTED_ENTITIES: dict[str, dict[str, str]] = {
    "E01": {"name": "BHP Group", "sector": "mining"},
    "E02": {"name": "Glencore", "sector": "mining"},
    "E03": {"name": "Anglo American", "sector": "mining"},
    "E04": {"name": "AngloGold Ashanti", "sector": "mining"},
    "E05": {"name": "Gold Fields", "sector": "mining"},
    "E06": {"name": "Valterra Platinum", "sector": "mining"},
    "E07": {"name": "OUTsurance Group", "sector": "insurance"},
    "E08": {"name": "Sanlam", "sector": "insurance"},
    "E09": {"name": "Shoprite Holdings", "sector": "consumer"},
    "E10": {"name": "Bid Corporation", "sector": "consumer"},
    "E11": {"name": "Pepkor Holdings", "sector": "consumer"},
    "E12": {"name": "Clicks Group", "sector": "consumer"},
    "E13": {"name": "NEPI Rockcastle", "sector": "real_estate"},
    "E14": {"name": "Prosus", "sector": "tech"},
    "E15": {"name": "Naspers", "sector": "tech"},
    "E16": {"name": "MTN Group", "sector": "telecoms"},
    "E17": {"name": "Vodacom Group", "sector": "telecoms"},
    "E18": {"name": "The Bidvest Group", "sector": "industrials_pharma"},
    "E19": {"name": "Aspen Pharmacare", "sector": "industrials_pharma"},
    "E20": {"name": "Shaftesbury Capital plc", "sector": "real_estate"},
}
EXPECTED_ENTITY_IDS = frozenset(EXPECTED_ENTITIES.keys())
N_EXPECTED_ENTITIES = len(EXPECTED_ENTITIES)

# --------------------------------------------------------------------------
# The competitor-credit fingerprint (the key finding — see METHODOLOGY.md)
# --------------------------------------------------------------------------
# Beneficiary names that appear ONLY on rows carrying the loan/facility memo
# template family, across all three source files. Synthetic data: these are
# fictitious counterparty labels the generator used to represent "some other
# bank", not real financial institutions (see hackathon.txt Data Disclaimer).
# Centralised here because ingest.py's profiling notes, forensics.py's
# deterministic regex baseline, and wallet.py's revenue-loss framing all need
# the exact same set.
KNOWN_COMPETITOR_BENEFICIARIES = frozenset(
    {
        "Halcyon Trade Bank",
        "Meridian Bank Ltd",
        "Northgate Financial Bank",
        "Solstice Capital Bank",
        "Crestwood Merchant Bank",
    }
)

# The four memo template phrases observed verbatim across all three files
# (see reports/profiling_report.md). Used by the regex baseline in
# forensics.py; the LLM extraction in the same module is cross-checked
# against this list to produce the disagreement-rate metric required by the
# Gen AI evaluation criterion.
MEMO_TEMPLATE_PHRASES = (
    "Bridging facility settlement",
    "Syndicate participation settlement",
    "Loan drawdown proceeds",
    "Settlement re: facility drawdown",
)


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def configure_logging(level: int = logging.INFO) -> None:
    """Configure a single, consistent console log format for every phase."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
