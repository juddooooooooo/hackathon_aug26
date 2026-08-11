# Phase 6 — Opportunity Ranking Report

`expected_value = wallet_gap x win_probability x margin` (hackathon.txt's own formula). `wallet_gap` only counts sub-components where captured revenue is directly observable -- the 3 structurally-unobservable-captured sub-components (`rate_hedging`, `debt_arrangement`, `competitor_credit_gap`) contribute to `total_unknown_capture_tam_zar` instead, reported separately as an upper-bound diagnostic, never blended into the ranked figure. `margin` = `net_margin_realization` (config/assumptions.yaml) -- NOT a second application of Phase 4's yield assumptions, which already convert flow to gross revenue.

## Portfolio ranking — SA-domestic entities (primary list)

**`top_pillar` is Transactional Banking for all 20 entities** — not a coincidence or an artefact worth second-guessing. TB's TAM formula scales off (revenue + cost_of_sales), a much larger base than the narrower FX-turnover or debt-specific slices Global Markets/Investment Banking draw on (METHODOLOGY.md §5.1) — a broad relationship's largest single addressable pillar being Transactional Banking is a well-established pattern in corporate banking, not a modelling quirk. **`win_probability` in this table is the entity-level base score, BEFORE the sequencing penalty** applied to specific Global Markets/Investment Banking rows below (see 'Full pillar-level detail') — shown unadjusted here because it never differs from the post-adjustment figure for an entity's *top* pillar (Transactional Banking is never itself sequencing-flagged).

|   rank | entity_id   | entity_name       | sector             |   total_expected_value_R_m |   total_wallet_gap_R_m | win_probability   | top_pillar            | any_sequencing_flag   |
|-------:|:------------|:------------------|:-------------------|---------------------------:|-----------------------:|:------------------|:----------------------|:----------------------|
|      1 | E09         | Shoprite Holdings | consumer           |                     193.77 |                  555.5 | 54%               | Transactional Banking | True                  |
|      2 | E10         | Bid Corporation   | consumer           |                     168.46 |                  517   | 51%               | Transactional Banking | True                  |
|      3 | E16         | MTN Group         | telecoms           |                     141.91 |                  414.4 | 54%               | Transactional Banking | True                  |
|      4 | E17         | Vodacom Group     | telecoms           |                     123.69 |                  394.5 | 52%               | Transactional Banking | True                  |
|      5 | E08         | Sanlam            | insurance          |                     106.02 |                  306.1 | 53%               | Transactional Banking | False                 |
|      6 | E18         | The Bidvest Group | industrials_pharma |                     104.04 |                  316.1 | 54%               | Transactional Banking | True                  |
|      7 | E06         | Valterra Platinum | mining             |                      84.55 |                  266.8 | 49%               | Transactional Banking | True                  |
|      8 | E11         | Pepkor Holdings   | consumer           |                      47.29 |                  101.5 | 72%               | Transactional Banking | False                 |
|      9 | E12         | Clicks Group      | consumer           |                      36.08 |                  109.8 | 51%               | Transactional Banking | True                  |
|     10 | E19         | Aspen Pharmacare  | industrials_pharma |                      29.47 |                   84.1 | 54%               | Transactional Banking | False                 |
|     11 | E07         | OUTsurance Group  | insurance          |                      22.08 |                   65.5 | 52%               | Transactional Banking | True                  |
|     12 | E13         | NEPI Rockcastle   | real_estate        |                      12.99 |                   48.2 | 52%               | Transactional Banking | True                  |

## ⚠ Dual-listed global majors — ranked separately, not mixed into the list above

Per METHODOLOGY.md §5.2/§6.3: these entities' Phase 3 revenue is their entire GLOBAL figure, not South-Africa-specific, inflating their TAM (and therefore wallet_gap) on a scale no SA-focused coverage effort could realistically close. Ranked here for completeness, not as priority recommendations.

|   rank | entity_id   | entity_name             | sector      |   total_expected_value_R_m |   total_wallet_gap_R_m | win_probability   | top_pillar            | any_sequencing_flag   |
|-------:|:------------|:------------------------|:------------|---------------------------:|-----------------------:|:------------------|:----------------------|:----------------------|
|      1 | E02         | Glencore                | mining      |                    3131.87 |                 9839.7 | 49%               | Transactional Banking | True                  |
|      2 | E01         | BHP Group               | mining      |                     932.56 |                 2587.2 | 55%               | Transactional Banking | False                 |
|      3 | E03         | Anglo American          | mining      |                     191.56 |                  602.7 | 49%               | Transactional Banking | False                 |
|      4 | E05         | Gold Fields             | mining      |                     110.69 |                  412.1 | 50%               | Transactional Banking | True                  |
|      5 | E15         | Naspers                 | tech        |                     110.51 |                  368.2 | 46%               | Transactional Banking | True                  |
|      6 | E04         | AngloGold Ashanti       | mining      |                     106.62 |                  313.3 | 53%               | Transactional Banking | True                  |
|      7 | E14         | Prosus                  | tech        |                      97.6  |                  322.5 | 47%               | Transactional Banking | True                  |
|      8 | E20         | Shaftesbury Capital plc | real_estate |                       3.66 |                   15.7 | 44%               | Transactional Banking | True                  |

## ⚠ Product-sequencing risk flags (30/40 Global Markets/Investment Banking rows)

These Global Markets / Investment Banking opportunities are flagged because the entity's Transactional Banking relationship (the foundation hackathon.txt says cross-sell should be built on) is below the sequencing-readiness threshold -- win_probability has already been penalised accordingly in the ranking above, not silently treated as a normal-confidence opportunity.

**30/40 is the large majority, and that is itself a real finding, not an over-triggered flag** — it directly reflects Phase 4's headline result that Syn Bank's Transactional Banking capture is thin almost everywhere in this portfolio (blended TB share 4.9%, METHODOLOGY.md §5.4). Read this section as "most Global Markets/ Investment Banking opportunities in this portfolio need the payment-flow relationship deepened first," a portfolio-level commercial insight, not a list of 30 isolated edge cases.

| entity_id   | entity_name             | pillar             | relationship_strength_score   | wallet_gap_zar   |
|:------------|:------------------------|:-------------------|:------------------------------|:-----------------|
| E05         | Gold Fields             | Global Markets     | 7.4%                          | R143.3m          |
| E17         | Vodacom Group           | Global Markets     | 0.1%                          | R52.3m           |
| E18         | The Bidvest Group       | Global Markets     | 5.2%                          | R32.7m           |
| E13         | NEPI Rockcastle         | Global Markets     | 0.4%                          | R19.4m           |
| E16         | MTN Group               | Investment Banking | 8.4%                          | R15.7m           |
| E10         | Bid Corporation         | Investment Banking | 6.6%                          | R13.8m           |
| E18         | The Bidvest Group       | Investment Banking | 5.2%                          | R12.1m           |
| E09         | Shoprite Holdings       | Investment Banking | 6.1%                          | R10.6m           |
| E02         | Glencore                | Investment Banking | 0.6%                          | R10.8m           |
| E05         | Gold Fields             | Investment Banking | 7.4%                          | R6.0m            |
| E04         | AngloGold Ashanti       | Investment Banking | 7.2%                          | R4.8m            |
| E20         | Shaftesbury Capital plc | Global Markets     | 0.6%                          | R5.7m            |
| E17         | Vodacom Group           | Investment Banking | 0.1%                          | R1.9m            |
| E06         | Valterra Platinum       | Investment Banking | 0.2%                          | R1.4m            |
| E07         | OUTsurance Group        | Investment Banking | 0.8%                          | R0.8m            |
| E15         | Naspers                 | Investment Banking | 1.1%                          | R0.6m            |
| E12         | Clicks Group            | Investment Banking | 0.3%                          | R0.5m            |
| E14         | Prosus                  | Investment Banking | 2.3%                          | R0.3m            |
| E20         | Shaftesbury Capital plc | Investment Banking | 0.6%                          | R0.1m            |
| E13         | NEPI Rockcastle         | Investment Banking | 0.4%                          | R0.0m            |
| E07         | OUTsurance Group        | Global Markets     | 0.8%                          | R0.0m            |
| E06         | Valterra Platinum       | Global Markets     | 0.2%                          | R0.0m            |
| E02         | Glencore                | Global Markets     | 0.6%                          | R0.0m            |
| E04         | AngloGold Ashanti       | Global Markets     | 7.2%                          | R0.0m            |
| E10         | Bid Corporation         | Global Markets     | 6.6%                          | R0.0m            |
| E09         | Shoprite Holdings       | Global Markets     | 6.1%                          | R0.0m            |
| E12         | Clicks Group            | Global Markets     | 0.3%                          | R0.0m            |
| E15         | Naspers                 | Global Markets     | 1.1%                          | R0.0m            |
| E14         | Prosus                  | Global Markets     | 2.3%                          | R0.0m            |
| E16         | MTN Group               | Global Markets     | 8.4%                          | R0.0m            |

## Right-to-win signal detail (entity level, feeds win_probability)

**`breadth_score` clusters near 1.0 for nearly every entity** — the same low-discriminating-power pattern already disclosed for Phase 5's revealed-presence estimator (METHODOLOGY.md §6.3): all 20 entities in this portfolio already use nearly Syn Bank's full leg-type/channel/instrument range, so this signal contributes little variation to win_probability in practice. The signals actually driving the spread below are `relationship_strength_score` and `country_adjacency_score` — disclosed here rather than let a reader assume all 4 signals are pulling equal weight.

| entity_id   | entity_name             |   breadth_score |   relationship_strength_score |   momentum_score |   country_adjacency_score |   win_probability |
|:------------|:------------------------|----------------:|------------------------------:|-----------------:|--------------------------:|------------------:|
| E01         | BHP Group               |            1    |                          0.12 |              0.8 |                      0.29 |              0.55 |
| E02         | Glencore                |            1    |                          0.01 |              0.5 |                      0.44 |              0.49 |
| E03         | Anglo American          |            1    |                          0.18 |              0.2 |                      0.47 |              0.49 |
| E04         | AngloGold Ashanti       |            1    |                          0.07 |              0.5 |                      0.53 |              0.53 |
| E05         | Gold Fields             |            1    |                          0.07 |              0.5 |                      0.41 |              0.5  |
| E06         | Valterra Platinum       |            1    |                          0    |              0.5 |                      0.44 |              0.49 |
| E07         | OUTsurance Group        |            1    |                          0.01 |              0.8 |                      0.29 |              0.52 |
| E08         | Sanlam                  |            1    |                          0.25 |              0.2 |                      0.59 |              0.53 |
| E09         | Shoprite Holdings       |            1    |                          0.06 |              0.5 |                      0.62 |              0.54 |
| E10         | Bid Corporation         |            1    |                          0.07 |              0.5 |                      0.44 |              0.51 |
| E11         | Pepkor Holdings         |            1    |                          0.64 |              0.5 |                      0.62 |              0.72 |
| E12         | Clicks Group            |            1    |                          0    |              0.5 |                      0.53 |              0.51 |
| E13         | NEPI Rockcastle         |            1    |                          0    |              0.8 |                      0.29 |              0.52 |
| E14         | Prosus                  |            1    |                          0.02 |              0.5 |                      0.29 |              0.47 |
| E15         | Naspers                 |            1    |                          0.01 |              0.5 |                      0.29 |              0.46 |
| E16         | MTN Group               |            1    |                          0.08 |              0.5 |                      0.56 |              0.54 |
| E17         | Vodacom Group           |            1    |                          0    |              0.5 |                      0.59 |              0.52 |
| E18         | The Bidvest Group       |            1    |                          0.05 |              0.5 |                      0.65 |              0.54 |
| E19         | Aspen Pharmacare        |            1    |                          0.13 |              0.5 |                      0.5  |              0.54 |
| E20         | Shaftesbury Capital plc |            0.93 |                          0.01 |              0.5 |                      0.29 |              0.44 |

## Full pillar-level detail

| entity_id   | entity_name             | pillar                |   wallet_gap_zar |   unknown_capture_tam_zar |   win_probability_adjusted |   expected_value_zar | sequencing_flag   |
|:------------|:------------------------|:----------------------|-----------------:|--------------------------:|---------------------------:|---------------------:|:------------------|
| E02         | Glencore                | Transactional Banking |    9,828,933,609 |                         0 |                       0.49 |        3,130,153,959 | False             |
| E01         | BHP Group               | Transactional Banking |    1,592,745,006 |                         0 |                       0.55 |          574,111,082 | False             |
| E01         | BHP Group               | Global Markets        |      981,220,320 |               158,350,360 |                       0.55 |          353,684,650 | False             |
| E09         | Shoprite Holdings       | Transactional Banking |      544,860,002 |                         0 |                       0.54 |          191,899,314 | False             |
| E03         | Anglo American          | Transactional Banking |      595,098,861 |                         0 |                       0.49 |          189,148,944 | False             |
| E10         | Bid Corporation         | Transactional Banking |      503,205,455 |                         0 |                       0.51 |          166,172,347 | False             |
| E16         | MTN Group               | Transactional Banking |      398,788,811 |                         0 |                       0.54 |          139,176,278 | False             |
| E17         | Vodacom Group           | Transactional Banking |      340,289,721 |                         0 |                       0.52 |          114,561,108 | False             |
| E15         | Naspers                 | Transactional Banking |      367,672,507 |                         0 |                       0.46 |          110,421,535 | False             |
| E04         | AngloGold Ashanti       | Transactional Banking |      308,514,902 |                         0 |                       0.53 |          105,793,362 | False             |
| E08         | Sanlam                  | Transactional Banking |      303,861,867 |                         0 |                       0.53 |          105,244,575 | False             |
| E14         | Prosus                  | Transactional Banking |      322,248,350 |                         0 |                       0.47 |           97,559,810 | False             |
| E18         | The Bidvest Group       | Transactional Banking |      271,361,316 |                         0 |                       0.54 |           96,112,659 | False             |
| E05         | Gold Fields             | Transactional Banking |      262,810,500 |                         0 |                       0.5  |           86,201,168 | False             |
| E06         | Valterra Platinum       | Transactional Banking |      265,380,158 |                         0 |                       0.49 |           84,327,859 | False             |
| E11         | Pepkor Holdings         | Transactional Banking |       89,942,204 |                         0 |                       0.72 |           41,913,971 | False             |
| E12         | Clicks Group            | Transactional Banking |      109,263,957 |                         0 |                       0.51 |           36,000,898 | False             |
| E19         | Aspen Pharmacare        | Transactional Banking |       80,110,546 |                         0 |                       0.54 |           28,073,343 | False             |
| E05         | Gold Fields             | Global Markets        |      143,311,580 |                20,818,225 |                       0.25 |           23,502,915 | True              |
| E07         | OUTsurance Group        | Transactional Banking |       64,744,807 |                         0 |                       0.52 |           21,940,463 | False             |
| E13         | NEPI Rockcastle         | Transactional Banking |       28,704,738 |                         0 |                       0.52 |            9,701,960 | False             |
| E17         | Vodacom Group           | Global Markets        |       52,320,717 |                37,700,000 |                       0.26 |            8,807,083 | True              |
| E18         | The Bidvest Group       | Global Markets        |       32,694,527 |                17,803,200 |                       0.27 |            5,789,989 | True              |
| E11         | Pepkor Holdings         | Investment Banking    |       11,538,260 |                67,257,500 |                       0.72 |            5,376,945 | False             |
| E01         | BHP Group               | Investment Banking    |       13,225,189 |               989,689,750 |                       0.55 |            4,767,070 | False             |
| E13         | NEPI Rockcastle         | Global Markets        |       19,442,311 |                23,221,947 |                       0.26 |            3,285,669 | True              |
| E20         | Shaftesbury Capital plc | Transactional Banking |        9,899,702 |                         0 |                       0.44 |            2,834,828 | False             |
| E16         | MTN Group               | Investment Banking    |       15,661,156 |               371,450,000 |                       0.27 |            2,732,852 | True              |
| E03         | Anglo American          | Investment Banking    |        7,581,067 |               625,362,736 |                       0.49 |            2,409,601 | False             |
| E10         | Bid Corporation         | Investment Banking    |       13,832,310 |                65,515,000 |                       0.25 |            2,283,906 | True              |
| E18         | The Bidvest Group       | Investment Banking    |       12,082,697 |               111,270,000 |                       0.27 |            2,139,767 | True              |
| E09         | Shoprite Holdings       | Investment Banking    |       10,644,986 |               139,690,000 |                       0.27 |            1,874,578 | True              |
| E02         | Glencore                | Investment Banking    |       10,783,678 |             1,675,847,713 |                       0.24 |            1,717,102 | True              |
| E19         | Aspen Pharmacare        | Investment Banking    |        3,976,307 |                90,300,000 |                       0.54 |            1,393,427 | False             |
| E05         | Gold Fields             | Investment Banking    |        5,988,285 |               130,113,906 |                       0.25 |              982,071 | True              |
| E04         | AngloGold Ashanti       | Investment Banking    |        4,802,622 |                92,142,136 |                       0.26 |              823,438 | True              |
| E20         | Shaftesbury Capital plc | Global Markets        |        5,707,923 |                10,811,663 |                       0.22 |              817,246 | True              |
| E08         | Sanlam                  | Investment Banking    |        2,228,126 |                50,247,500 |                       0.53 |              771,726 | False             |
| E17         | Vodacom Group           | Investment Banking    |        1,924,760 |               235,625,000 |                       0.26 |              323,993 | True              |
| E06         | Valterra Platinum       | Investment Banking    |        1,413,081 |                13,167,500 |                       0.24 |              224,512 | True              |
| E07         | OUTsurance Group        | Investment Banking    |          802,959 |                   965,000 |                       0.26 |              136,052 | True              |
| E15         | Naspers                 | Investment Banking    |          577,419 |               732,653,184 |                       0.23 |               86,707 | True              |
| E12         | Clicks Group            | Investment Banking    |          507,846 |                10,105,000 |                       0.25 |               83,664 | True              |
| E14         | Prosus                  | Investment Banking    |          288,162 |               710,556,845 |                       0.23 |               43,620 | True              |
| E20         | Shaftesbury Capital plc | Investment Banking    |           72,275 |                67,572,894 |                       0.22 |               10,348 | True              |
| E13         | NEPI Rockcastle         | Investment Banking    |           35,391 |               145,137,168 |                       0.26 |                5,981 | True              |
| E08         | Sanlam                  | Global Markets        |                0 |                 8,039,600 |                       0.53 |                    0 | False             |
| E07         | OUTsurance Group        | Global Markets        |                0 |                   154,400 |                       0.26 |                    0 | True              |
| E06         | Valterra Platinum       | Global Markets        |                0 |                 2,106,800 |                       0.24 |                    0 | True              |
| E02         | Glencore                | Global Markets        |                0 |               268,135,634 |                       0.24 |                    0 | True              |
| E03         | Anglo American          | Global Markets        |                0 |               100,058,038 |                       0.49 |                    0 | False             |
| E04         | AngloGold Ashanti       | Global Markets        |                0 |                14,742,742 |                       0.26 |                    0 | True              |
| E10         | Bid Corporation         | Global Markets        |                0 |                10,482,400 |                       0.25 |                    0 | True              |
| E09         | Shoprite Holdings       | Global Markets        |                0 |                22,350,400 |                       0.27 |                    0 | True              |
| E11         | Pepkor Holdings         | Global Markets        |                0 |                10,761,200 |                       0.72 |                    0 | False             |
| E12         | Clicks Group            | Global Markets        |                0 |                 1,616,800 |                       0.25 |                    0 | True              |
| E15         | Naspers                 | Global Markets        |                0 |               117,224,509 |                       0.23 |                    0 | True              |
| E14         | Prosus                  | Global Markets        |                0 |               113,689,095 |                       0.23 |                    0 | True              |
| E16         | MTN Group               | Global Markets        |                0 |                59,432,000 |                       0.27 |                    0 | True              |
| E19         | Aspen Pharmacare        | Global Markets        |                0 |                14,448,000 |                       0.54 |                    0 | False             |