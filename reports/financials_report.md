# Phase 3 — External Financial Baseline Report

Entities processed: **20** / 20. No financial-statement PDFs were supplied with the hackathon data (see METHODOLOGY.md §0) -- every figure below is sourced from public filings / filings-derived aggregators, fetched once and committed at `data/external/raw/`, then extracted to this schema by Gemini (`src/financials.py`, namespace `financials_baseline_extraction`). Full source list: `reports/external_sources.md`.

## Coverage — non-null rate per field

| field               |   non_null_n | non_null_pct   |
|:--------------------|-------------:|:---------------|
| total_revenue       |           20 | 100%           |
| cost_of_sales       |           17 | 85%            |
| inventory           |           15 | 75%            |
| trade_receivables   |           17 | 85%            |
| trade_payables      |           18 | 90%            |
| total_debt          |           20 | 100%           |
| foreign_revenue_pct |            6 | 30%            |

**Flagged not-applicable** (business model doesn't have this line item, e.g. insurers/REITs):

| field             |   n_entities |
|:------------------|-------------:|
| cost_of_sales     |            4 |
| inventory         |            4 |
| trade_receivables |            2 |

## Confidence distribution by field

| field               |   high |   medium |   low |   null |
|:--------------------|-------:|---------:|------:|-------:|
| total_revenue       |     20 |        0 |     0 |      0 |
| cost_of_sales       |      0 |       17 |     0 |      3 |
| inventory           |     15 |        0 |     0 |      5 |
| trade_receivables   |     17 |        0 |     0 |      3 |
| trade_payables      |     18 |        0 |     0 |      2 |
| total_debt          |     20 |        0 |     0 |      0 |
| foreign_revenue_pct |      2 |        3 |     1 |     14 |

## Ground-truth accuracy

- Hand-labelled sample: **19 (entity, field) pairs** (`tests/financials_ground_truth.csv`), independently re-verified against primary sources.
- **Field-level accuracy: 19/19 (100.0%)** within ±2% tolerance for numeric fields, exact match for categorical.

| entity_id   | field               | match   | reason       | expected   | actual     |
|:------------|:--------------------|:--------|:-------------|:-----------|:-----------|
| E01         | total_revenue       | True    | 0.00% diff   | 51262.0    | 51262.0    |
| E01         | total_debt          | True    | 0.00% diff   | 24500.0    | 24500.0    |
| E03         | total_revenue       | True    | 0.00% diff   | 18546.0    | 18546.0    |
| E04         | total_debt          | True    | 0.00% diff   | 2281.0     | 2281.0     |
| E05         | foreign_revenue_pct | True    | 0.00% diff   | 87.8       | 87.8       |
| E06         | total_revenue       | True    | 0.00% diff   | 116330.0   | 116330.0   |
| E07         | total_revenue       | True    | 0.00% diff   | 39415.0    | 39415.0    |
| E08         | total_revenue       | True    | 0.00% diff   | 244797.0   | 244797.0   |
| E08         | cost_of_sales       | True    | correct_null |            |            |
| E09         | inventory           | True    | 0.00% diff   | 29748.0    | 29748.0    |
| E09         | total_debt          | True    | 0.00% diff   | 55876.0    | 55876.0    |
| E12         | total_revenue       | True    | 0.00% diff   | 47828.0    | 47828.0    |
| E13         | foreign_revenue_pct | True    | 0.00% diff   | 100.0      | 100.0      |
| E16         | fiscal_year_end     | True    | exact_str    | 2025-12-31 | 2025-12-31 |
| E17         | foreign_revenue_pct | True    | 0.00% diff   | 35.0       | 35.0       |
| E18         | foreign_revenue_pct | True    | 0.00% diff   | 28.1       | 28.1       |
| E19         | fiscal_year_end     | True    | exact_str    | 2025-06-30 | 2025-06-30 |
| E20         | inventory           | True    | correct_null |            |            |
| E02         | total_revenue       | True    | 0.00% diff   | 247535.0   | 247535.0   |

## Full baseline table

| entity_id   | entity_name             | sector             | fiscal_year_end   | reported_currency   |   total_revenue |   cost_of_sales |   inventory |   trade_receivables |   trade_payables |   total_debt |   foreign_revenue_pct |
|:------------|:------------------------|:-------------------|:------------------|:--------------------|----------------:|----------------:|------------:|--------------------:|-----------------:|-------------:|----------------------:|
| E01         | BHP Group               | mining             | 2025-06-30        | USD                 |        51262    |         32319   |       nan   |              nan    |            nan   |        24500 |                 100   |
| E02         | Glencore                | mining             | 2025-12-31        | USD                 |       247535    |        241672   |     32882   |            23826    |          35614   |        41486 |                 nan   |
| E03         | Anglo American          | mining             | 2025-12-31        | USD                 |        18546    |         17194   |      3013   |             3748    |           4879   |        15481 |                 nan   |
| E04         | AngloGold Ashanti       | mining             | 2025-12-31        | USD                 |         9893    |          5022   |      1076   |              426    |           1001   |         2281 |                 nan   |
| E05         | Gold Fields             | mining             | 2025-12-31        | USD                 |         8751    |          3680   |       782.6 |              380.7  |            908.1 |         3221 |                  87.8 |
| E06         | Valterra Platinum       | mining             | 2025-12-31        | ZAR                 |       116330    |         87734   |     28087   |             4095    |          15496   |         5267 |                 nan   |
| E07         | OUTsurance Group        | insurance          | 2025-06-30        | ZAR                 |        39415    |           nan   |       nan   |              nan    |            162   |          386 |                 nan   |
| E08         | Sanlam                  | insurance          | 2025-12-31        | ZAR                 |       244797    |           nan   |       nan   |              nan    |          67901   |        20099 |                 nan   |
| E09         | Shoprite Holdings       | consumer           | 2025-06-29        | ZAR                 |       252701    |        193692   |     29748   |             5706    |          34084   |        55876 |                 nan   |
| E10         | Bid Corporation         | consumer           | 2025-06-30        | ZAR                 |       235591    |        177918   |     19263   |            22885    |          29251   |        26206 |                 nan   |
| E11         | Pepkor Holdings         | consumer           | 2025-09-30        | ZAR                 |        95340    |         57388   |     18618   |            17462    |          12023   |        26903 |                 nan   |
| E12         | Clicks Group            | consumer           | 2025-08-31        | ZAR                 |        47828    |         36428   |      7819   |             1897    |           8367   |         4042 |                 nan   |
| E13         | NEPI Rockcastle         | real_estate        | 2025-12-31        | EUR                 |          930.66 |           nan   |       nan   |               86.93 |            nan   |         3106 |                 100   |
| E14         | Prosus                  | tech               | 2026-03-31        | USD                 |         9705    |          5198   |       271   |             1311    |           1109   |        17590 |                 nan   |
| E15         | Naspers                 | tech               | 2026-03-31        | USD                 |        10848    |          6027   |       347   |             1349    |           1170   |        18137 |                 nan   |
| E16         | MTN Group               | telecoms           | 2025-12-31        | ZAR                 |       226755    |         71464   |      1310   |            21920    |          21746   |       148580 |                 nan   |
| E17         | Vodacom Group           | telecoms           | 2026-03-31        | ZAR                 |       167652    |         75344   |      2112   |            33397    |          46181   |        94250 |                  35   |
| E18         | The Bidvest Group       | industrials_pharma | 2025-06-30        | ZAR                 |       126605    |         91540   |     14836   |            17142    |          10207   |        44508 |                  28.1 |
| E19         | Aspen Pharmacare        | industrials_pharma | 2025-06-30        | ZAR                 |        43363    |         24311   |     18009   |            10646    |           4084   |        36120 |                 nan   |
| E20         | Shaftesbury Capital plc | real_estate        | 2025-12-31        | GBP                 |          238.9  |            61.2 |       nan   |               41.3  |             98.1 |         1213 |                 100   |