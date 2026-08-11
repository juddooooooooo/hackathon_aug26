# External sources

hackathon.txt explicitly invites supplementing the synthetic internal data with public sources,
provided they're cited (see its "Data" section). Every external figure pulled into Phase 3
(`src/financials.py`) is sourced from one of the URLs below. Raw fetched text is committed
verbatim at `data/external/raw/` — this table is the index into it, not a substitute for it.

Retrieved: 2026-08-11, via `stockanalysis.com` (a filings-derived aggregator, used for
cross-company consistency at 20-entity scale — see METHODOLOGY.md §4) for core financials, plus
targeted company/press sources for foreign-revenue and geographic-segment figures.

## Core financials (revenue, cost of sales, inventory, receivables, payables, debt)

| Entity | entity_id | Source | Raw file |
|---|---|---|---|
| BHP Group | E01 | https://stockanalysis.com/stocks/BHP/financials/ , https://stockanalysis.com/stocks/BHP/financials/balance-sheet/ | `data/external/raw/E01_BHP_Group.md` |
| Glencore | E02 | https://stockanalysis.com/quote/otc/GLNCY/financials/ , https://stockanalysis.com/quote/otc/GLNCY/financials/balance-sheet/ | `data/external/raw/E02_Glencore.md` |
| Anglo American | E03 | https://stockanalysis.com/quote/lon/AAL/financials/ , https://stockanalysis.com/quote/lon/AAL/financials/balance-sheet/ | `data/external/raw/E03_Anglo_American.md` |
| AngloGold Ashanti | E04 | https://stockanalysis.com/stocks/AU/financials/ , https://stockanalysis.com/stocks/AU/financials/balance-sheet/ | `data/external/raw/E04_AngloGold_Ashanti.md` |
| Gold Fields | E05 | https://stockanalysis.com/stocks/GFI/financials/ , https://stockanalysis.com/stocks/GFI/financials/balance-sheet/ | `data/external/raw/E05_Gold_Fields.md` |
| Valterra Platinum | E06 | https://stockanalysis.com/quote/jse/VAL/financials/ , https://stockanalysis.com/quote/jse/VAL/financials/balance-sheet/ | `data/external/raw/E06_Valterra_Platinum.md` |
| OUTsurance Group | E07 | https://stockanalysis.com/quote/jse/OUT/financials/ , https://stockanalysis.com/quote/jse/OUT/financials/balance-sheet/ | `data/external/raw/E07_OUTsurance_Group.md` |
| Sanlam | E08 | https://stockanalysis.com/quote/jse/SLM/financials/ , https://stockanalysis.com/quote/jse/SLM/financials/balance-sheet/ | `data/external/raw/E08_Sanlam.md` |
| Shoprite Holdings | E09 | https://stockanalysis.com/quote/jse/SHP/financials/ , https://stockanalysis.com/quote/jse/SHP/financials/balance-sheet/ | `data/external/raw/E09_Shoprite_Holdings.md` |
| Bid Corporation | E10 | https://stockanalysis.com/quote/jse/BID/financials/ , https://stockanalysis.com/quote/jse/BID/financials/balance-sheet/ | `data/external/raw/E10_Bid_Corporation.md` |
| Pepkor Holdings | E11 | https://stockanalysis.com/quote/jse/PPH/financials/ , https://stockanalysis.com/quote/jse/PPH/financials/balance-sheet/ | `data/external/raw/E11_Pepkor_Holdings.md` |
| Clicks Group | E12 | https://stockanalysis.com/quote/jse/CLS/financials/ , https://stockanalysis.com/quote/jse/CLS/financials/balance-sheet/ | `data/external/raw/E12_Clicks_Group.md` |
| NEPI Rockcastle | E13 | https://stockanalysis.com/quote/jse/NRP/financials/ , https://stockanalysis.com/quote/jse/NRP/financials/balance-sheet/ | `data/external/raw/E13_NEPI_Rockcastle.md` |
| Prosus | E14 | https://stockanalysis.com/quote/ams/PRX/financials/ , https://stockanalysis.com/quote/ams/PRX/financials/balance-sheet/ | `data/external/raw/E14_Prosus.md` |
| Naspers | E15 | https://stockanalysis.com/quote/jse/NPN/financials/ , https://stockanalysis.com/quote/jse/NPN/financials/balance-sheet/ | `data/external/raw/E15_Naspers.md` |
| MTN Group | E16 | https://stockanalysis.com/quote/jse/MTN/financials/ , https://stockanalysis.com/quote/jse/MTN/financials/balance-sheet/ | `data/external/raw/E16_MTN_Group.md` |
| Vodacom Group | E17 | https://stockanalysis.com/quote/jse/VOD/financials/ , https://stockanalysis.com/quote/jse/VOD/financials/balance-sheet/ | `data/external/raw/E17_Vodacom_Group.md` |
| The Bidvest Group | E18 | https://stockanalysis.com/quote/jse/BVT/financials/ , https://stockanalysis.com/quote/jse/BVT/financials/balance-sheet/ | `data/external/raw/E18_Bidvest_Group.md` |
| Aspen Pharmacare | E19 | https://stockanalysis.com/quote/jse/APN/financials/ , https://stockanalysis.com/quote/jse/APN/financials/balance-sheet/ | `data/external/raw/E19_Aspen_Pharmacare.md` |
| Shaftesbury Capital plc | E20 | https://stockanalysis.com/quote/lon/SHC/financials/ , https://stockanalysis.com/quote/lon/SHC/financials/balance-sheet/ | `data/external/raw/E20_Shaftesbury_Capital.md` |

Cross-check sources used to spot-verify specific figures (not the primary extraction input, see
METHODOLOGY.md §4.2 for what this surfaced):
- BHP total debt: https://www.bhp.com/news/media-centre/releases/2025/08/bhp-results-for-the-full-year-ended-30-june-2025
- Glencore net debt: https://www.glencore.com/media-and-insights/news/preliminary-results-2024
- AngloGold Ashanti adjusted net debt: https://www.nasdaq.com/press-release/anglogold-ashanti-delivers-nine-fold-increase-2024-free-cash-flow-942m-versus-prior
- Anglo American cost of sales (definitional discrepancy vs. stockanalysis.com): https://finance.yahoo.com/quote/NGLOY/financials/
- Gold Fields cash cost of sales (narrower definition than "cost of sales"): Gold Fields FY2024 results commentary (via WebSearch, no single stable URL captured)
- Valterra Platinum net cash position: https://www.valterraplatinum.com/media/press-releases/2025/17-02-2025

## Foreign/offshore revenue % and geographic segment

See `data/external/raw/geographic_foreign_revenue_notes.md` for the full per-entity writeup
(source URL, figure, confidence, and caveats for each). Entities with a citable figure: E01 BHP,
E03 Anglo American, E05 Gold Fields, E13 NEPI Rockcastle, E16 MTN Group, E17 Vodacom Group, E18
Bidvest Group, E20 Shaftesbury Capital. Primary sources used:

- Anglo American revenue by destination (China 34%, UK 6%, FY2024): https://www.statista.com/statistics/1487978/anglo-american-revenue-by-destination (citing Anglo American's own Country by Country Report 2024: https://www.angloamerican.com/~/media/Files/A/Anglo-American-Group-v9/PLC/investors/annual-reporting/2025/anglo-american-country-by-country-report-2024.pdf)
- AngloGold Ashanti FY2024 regional review: https://reports.anglogoldashanti.com/24/wp-content/uploads/2025/03/AGA-AR24-REGIONAL-REVIEW.pdf
- Gold Fields FY2024 revenue by operating region: https://www.tradingkey.com/markets/stocks/nasdaq-gfi/revenue
- MTN Group FY2024 results booklet: https://www.mtn.com/wp-content/uploads/2025/03/MTN-Group-FY-24-results-complete-booklet-HR.pdf
- Vodacom Group quarterly trading update (Dec 2025): https://www.vodacom.com/pdf/investor/quarterly-results/2025/vodacom-trading-update-3q26.pdf
- Bidvest Group interim results presentation (2025): https://bidvest.co.za/pdf/results/interim-results/2025/presentation.pdf
- Aspen Pharmacare business segment overview (2024, directional only — not used as a headline %): https://aspen-reports.co.za/reports/2024/pdf/business-segment-overviews.pdf
- NEPI Rockcastle portfolio composition (100% CEE, qualitative): https://en.wikipedia.org/wiki/NEPI_Rockcastle

## Ground-truth verification sources

`tests/financials_ground_truth.csv` cites its own source per row. Distinct from the extraction
inputs above where noted (independent re-verification, not re-reading the same source):
- BHP FY2025 results release (primary): https://www.bhp.com/news/media-centre/releases/2025/08/bhp-results-for-the-full-year-ended-30-june-2025
- Anglo American cost-of-sales cross-check: https://finance.yahoo.com/quote/NGLOY/financials/
- MTN Group FY2024 results booklet (primary): https://www.mtn.com/wp-content/uploads/2025/03/MTN-Group-FY-24-results-complete-booklet-HR.pdf
- NEPI Rockcastle portfolio composition: https://en.wikipedia.org/wiki/NEPI_Rockcastle
