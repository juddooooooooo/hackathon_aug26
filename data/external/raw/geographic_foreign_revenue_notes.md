# Foreign/offshore revenue % and geographic segment — research notes

Retrieved: 2026-08-11. Second-pass research, deliberately scoped to reasonable effort rather than
exhaustive: full destination-level segment disclosure is not consistently available for all 20
entities within a hackathon timeframe, and per METHODOLOGY.md's null-propagation principle, gaps
below are left as gaps for src/financials.py to null out, not filled with plausible-looking
guesses. Entities not listed here (E07 OUTsurance, E08 Sanlam, E09 Shoprite, E10 Bid Corporation,
E11 Pepkor, E12 Clicks) had no confidently-sourced foreign-revenue figure found in this pass --
null in the extraction, flagged as a known Phase 3 gap in METHODOLOGY.md, not a "0% foreign".

## E01 BHP Group
>60% of FY2025 (Jun 2025) revenue from China specifically (single largest destination), per
multiple 2025/2026 results commentary. Source: https://www.bhp.com/news/media-centre/releases/2025/08/bhp-results-for-the-full-year-ended-30-june-2025
Caveat: "foreign revenue %" as a concept is of limited relevance for BHP specifically -- its JSE
listing is a historical/dual-listing artefact and it has no material South-Africa-domestic
revenue base to begin with (~100% of revenue is already "foreign" from an SA vantage point).
Confidence: medium (specific >60% China figure found; full destination table not fetched).

## E02 Glencore
No specific destination breakdown sourced this pass. Qualitatively: Glencore is a globally
diversified commodity marketing/trading + mining group headquartered in Switzerland with
essentially no South African end-customer revenue base -- foreign revenue share is understood to
be near-100% but not backed by a specific cited percentage here. Null in extraction (no number
to cite), qualitative note only.

## E03 Anglo American
China 34% of FY2024 revenue ($9.43bn of ~$27.3bn), UK only 6% ($1.74bn). Source (via Statista,
citing Anglo American's own Country by Country Report 2024):
https://www.statista.com/statistics/1487978/anglo-american-revenue-by-destination
Primary source referenced: https://www.angloamerican.com/~/media/Files/A/Anglo-American-Group-v9/PLC/investors/annual-reporting/2025/anglo-american-country-by-country-report-2024.pdf
Confidence: high for the China/UK figures specifically; full destination table not fetched.
Same caveat as BHP -- SA-domestic revenue is a small fraction of the total, "foreign %" from an
SA vantage point is understood to be close to 100% overall.

## E04 AngloGold Ashanti
FY2024 gold income by operating region (not customer destination -- gold is sold into a fungible
bullion market, so operating jurisdiction is the more meaningful geographic split for this
entity): Africa $3,756m, Australia $1,394m, Americas $1,264m (of $6,414m gross incl.
equity-accounted JVs; $5,673m consolidated). South Africa itself is not broken out as a separate
material contributor in this split (the group's SA operations are smaller than its
Ghana/Guinea/DRC/Tanzania and Australia/Americas operations combined).
Source: https://reports.anglogoldashanti.com/24/wp-content/uploads/2025/03/AGA-AR24-REGIONAL-REVIEW.pdf
Confidence: medium (operating-region mix, not strict revenue-destination %).

## E05 Gold Fields
FY2024 revenue by operating region: Ghana 22.6%, Chile 16.2%, South Africa 12.2%, Peru 6.8%
(Australia region revenue not captured in this pass, but is a further material share -- Gold
Fields' largest single mine, St Ives/Gruyere, is in Australia).
Source: TradingKey revenue breakdown (secondary aggregator, citing Gold Fields' own reporting) --
https://www.tradingkey.com/markets/stocks/nasdaq-gfi/revenue
Confidence: medium (operating-region mix; South Africa's ~12% share is the clearest read for
domestic vs. foreign, implying ~88% foreign by this operating-region proxy).

## E06 Valterra Platinum
No specific destination % sourced. Qualitatively: PGM output is overwhelmingly export-sold
(automotive catalyst / jewellery / industrial demand concentrated in Japan, China, Europe, North
America -- one source noted Japan as the largest single destination market) with mining operations
based in South Africa and Zimbabwe (Unki, ~7% of concentrate output). Revenue is understood to be
very heavily export-weighted but no specific % is cited here -- null in extraction.

## E16 MTN Group
FY2024 group service revenue: South Africa 24.3% (R43,175m), Nigeria 22.9% (R40,755m) -- implying
non-South-Africa share of ~75.7% of group service revenue for FY2024 (South Africa is MTN's home
listing market; everything else, including its largest single foreign market Nigeria, counts as
foreign from Syn Bank's SA-domestic vantage point). Note the SA/Nigeria ranking flipped in 2024
vs. 2023 (Nigeria 35.1% / SA 19.9% in FY2023) due to a sharp Naira devaluation, not an underlying
operational shift -- flagged for Phase 5 trend analysis (volatile mix, not gradually drifting).
Source: https://www.mtn.com/wp-content/uploads/2025/03/MTN-Group-FY-24-results-complete-booklet-HR.pdf
Confidence: high (explicit %, primary source).

## E17 Vodacom Group
Two different cuts found, both from Vodacom's own reporting, genuinely in tension -- both kept
rather than reconciled to one number:
  - By CUSTOMER COUNT: ~76% of Vodacom's customers are outside South Africa (DRC, Egypt,
    Ethiopia, Kenya, Lesotho, Mozambique, Tanzania).
  - By SERVICE REVENUE (quarter ended 31 Dec 2025): South Africa R16.4bn vs. International R8.8bn
    -- International is ~35% of the SA+International total shown, i.e. South Africa still
    dominates revenue despite being a minority of customers (much higher ARPU in SA than the
    other African markets).
Source: https://www.vodacom.com/pdf/investor/quarterly-results/2025/vodacom-trading-update-3q26.pdf
Confidence: medium (a single quarter, not a full fiscal year; genuine revenue-vs-customer-count
divergence noted rather than collapsed to one figure).

## E18 The Bidvest Group
FY2025 South Africa revenue R91.01bn of R126.61bn total = ~71.9% domestic, ~28.1% international
(derived by calculation from the two disclosed totals, not a directly-stated %).
Source: https://bidvest.co.za/pdf/results/interim-results/2025/presentation.pdf (and FY2025
results archive: https://bidvest.co.za/financial-results-archive)
Confidence: medium (derived from two disclosed absolute figures, not a company-stated percentage).

## E19 Aspen Pharmacare
No single "% South Africa" figure found; company discloses revenue by region PER BUSINESS
SEGMENT instead. FY2024 (per aspen-reports.co.za business segment overview):
  - Over-the-Counter segment: Africa/Middle East 37%, Australasia 25%, Europe/CIS 20%,
    Americas 15%, Asia 3%.
  - Prescription segment: Africa/Middle East 45%, Australasia 39%, Americas 25%, Asia 6%,
    Europe/CIS 6% (note: percentages as scraped sum to >100%, likely a multi-region attribution
    or transcription artefact in the source page -- treat as directional, not precise).
Source: https://aspen-reports.co.za/reports/2024/pdf/business-segment-overviews.pdf
Confidence: low-medium (directional only; "Africa/Middle East" is a multi-country region, not a
clean South-Africa-vs-rest split, and Aspen is independently known in industry commentary to be
one of the JSE's most export-intensive/globally diversified manufacturers). No single South
Africa % -- null the headline foreign_revenue_pct field, keep this note as qualitative context.

## E13 NEPI Rockcastle
100% foreign by construction from a South African vantage point: the entire portfolio is Central
and Eastern European shopping centres (Romania, Poland, Bulgaria, Slovakia, Hungary, Croatia,
Serbia, Lithuania) -- a JSE listing with zero South African property exposure. High confidence,
qualitative (no SA revenue line exists to cite a % against).

## E20 Shaftesbury Capital plc
100% foreign by the same logic: entirely London West End real estate (Covent Garden, Carnaby,
Seven Dials), zero South African property exposure. High confidence, qualitative.

## E14 Prosus / E15 Naspers
Both entities' operating businesses (led by the Tencent stake, plus global classifieds/food
delivery/fintech/edtech platforms) are overwhelmingly non-South-African. No single clean % found
this pass; qualitative note only -- foreign revenue share understood to be very high (>90%) but
not backed by a specific cited figure here. Null the headline field.
