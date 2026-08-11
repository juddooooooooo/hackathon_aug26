# Phase 1 — Ingestion & Profiling Report

Generated: 2026-08-11T13:49:58

> **Every rand figure below is GROSS FLOW / EXPOSURE observed in the ledgers -- not bank revenue and not share of wallet.** Converting flow into revenue requires an explicit yield assumption (bps, fee-per-payment, NII margin, ...); that conversion happens in Phase 4 (`src/wallet.py`) using named, sourced assumptions in `config/assumptions.yaml`. See hackathon.txt's domain rule and METHODOLOGY.md.
## Entity master (20 expected clients — validated)
| entity_id   | entity_name             | sector             |
|:------------|:------------------------|:-------------------|
| E01         | BHP Group               | mining             |
| E02         | Glencore                | mining             |
| E03         | Anglo American          | mining             |
| E04         | AngloGold Ashanti       | mining             |
| E05         | Gold Fields             | mining             |
| E06         | Valterra Platinum       | mining             |
| E07         | OUTsurance Group        | insurance          |
| E08         | Sanlam                  | insurance          |
| E09         | Shoprite Holdings       | consumer           |
| E10         | Bid Corporation         | consumer           |
| E11         | Pepkor Holdings         | consumer           |
| E12         | Clicks Group            | consumer           |
| E13         | NEPI Rockcastle         | real_estate        |
| E14         | Prosus                  | tech               |
| E15         | Naspers                 | tech               |
| E16         | MTN Group               | telecoms           |
| E17         | Vodacom Group           | telecoms           |
| E18         | The Bidvest Group       | industrials_pharma |
| E19         | Aspen Pharmacare        | industrials_pharma |
| E20         | Shaftesbury Capital plc | real_estate        |

## `transactional_banking`
- Source: `C:\Users\juddj\OneDrive\Desktop\projects\standardbank_hackathon\data\transactional_banking.csv`
- Rows: 2,802,875
- Distinct entities: 20 / 20
- Date range: 2023-07-01 to 2026-06-30
- Amount column (gross flow, NOT revenue): n=2,802,875, sum=R405,442,910,069, mean=R144,653, range=[R205, R64,832,718]

**Null rates (%)**

| column           |   null_pct |
|:-----------------|-----------:|
| memo             |    99.8695 |
| transaction_id   |     0      |
| entity_name      |     0      |
| sector           |     0      |
| date             |     0      |
| entity_id        |     0      |
| leg_type         |     0      |
| direction        |     0      |
| currency         |     0      |
| amount_zar       |     0      |
| channel          |     0      |
| beneficiary_name |     0      |
| reference        |     0      |
| currency_norm    |     0      |

**Categorical cardinality**

| column        |   n_distinct |
|:--------------|-------------:|
| sector        |            7 |
| leg_type      |            5 |
| direction     |            2 |
| channel       |            5 |
| currency      |            2 |
| currency_norm |            1 |

*sector* top values:

| value              |       n |
|:-------------------|--------:|
| consumer           | 1368943 |
| insurance          |  625472 |
| mining             |  287297 |
| telecoms           |  219106 |
| industrials_pharma |  215109 |
| tech               |   82727 |
| real_estate        |    4221 |

*leg_type* top values:

| value               |       n |
|:--------------------|--------:|
| collections         | 1131589 |
| supplier_payments   |  976857 |
| intercompany_sweeps |  672410 |
| payroll             |   16592 |
| tax                 |    5427 |

*direction* top values:

| value    |       n |
|:---------|--------:|
| inbound  | 1467474 |
| outbound | 1335401 |

*channel* top values:

| value             |       n |
|:------------------|--------:|
| EFT               | 1261649 |
| RTC               |  560663 |
| Internal Transfer |  419770 |
| SWIFT             |  280539 |
| Debit Order       |  280254 |

*currency* top values:

| value   |       n |
|:--------|--------:|
| ZAR     | 2774594 |
| zar     |   28281 |

*currency_norm* top values:

| value   |       n |
|:--------|--------:|
| ZAR     | 2802875 |

**Free-text columns (id/reference/memo — null rate + cardinality only)**

| column           |   n_distinct |   n_non_null |
|:-----------------|-------------:|-------------:|
| beneficiary_name |          358 |      2802875 |
| reference        |      1502146 |      2802875 |
| memo             |         3643 |         3657 |

## `cross_border_payments`
- Source: `C:\Users\juddj\OneDrive\Desktop\projects\standardbank_hackathon\data\cross_border_payments.csv`
- Rows: 241,117
- Distinct entities: 20 / 20
- Date range: 2023-07-01 to 2026-06-30
- Amount column (gross flow, NOT revenue): n=241,117, sum=R133,746,695,986, mean=R554,696, range=[R1,095, R92,965,121]

**Null rates (%)**

| column               |   null_pct |
|:---------------------|-----------:|
| memo                 |    99.8142 |
| counterparty_country |     1.52   |
| entity_name          |     0      |
| entity_id            |     0      |
| transaction_id       |     0      |
| date                 |     0      |
| sector               |     0      |
| currency_pair        |     0      |
| direction            |     0      |
| value_zar            |     0      |
| corridor_type        |     0      |
| beneficiary_name     |     0      |
| reference            |     0      |

**Categorical cardinality**

| column               |   n_distinct |
|:---------------------|-------------:|
| sector               |            7 |
| direction            |            2 |
| currency_pair        |            5 |
| counterparty_country |           34 |
| corridor_type        |            3 |

*sector* top values:

| value              |     n |
|:-------------------|------:|
| consumer           | 91300 |
| telecoms           | 48800 |
| mining             | 28197 |
| tech               | 24150 |
| insurance          | 23123 |
| industrials_pharma | 20875 |
| real_estate        |  4672 |

*direction* top values:

| value    |      n |
|:---------|-------:|
| outbound | 125794 |
| inbound  | 115323 |

*currency_pair* top values:

| value   |     n |
|:--------|------:|
| EUR/ZAR | 48339 |
| GBP/ZAR | 48285 |
| USD/ZAR | 48243 |
| AED/ZAR | 48189 |
| CNY/ZAR | 48061 |

*counterparty_country* top values:

| value                |     n |
|:---------------------|------:|
| Botswana             | 14233 |
| Brazil               | 12600 |
| Japan                | 12404 |
| United Kingdom       | 12356 |
| India                | 12324 |
| United Arab Emirates | 12317 |
| Netherlands          | 12251 |
| Germany              | 12247 |
| China                | 12192 |
| Switzerland          | 12160 |
| United States        | 12143 |
| Zambia               | 11395 |
| Ghana                | 11030 |
| Namibia              |  7958 |
| Kenya                |  7069 |

*corridor_type* top values:

| value        |      n |
|:-------------|-------:|
| trade        | 109187 |
| intercompany | 107969 |
| other        |  23961 |

**Free-text columns (id/reference/memo — null rate + cardinality only)**

| column           |   n_distinct |   n_non_null |
|:-----------------|-------------:|-------------:|
| beneficiary_name |          180 |       241117 |
| reference        |       227434 |       241117 |
| memo             |          445 |          448 |

## `trade_finance`
- Source: `C:\Users\juddj\OneDrive\Desktop\projects\standardbank_hackathon\data\trade_finance.csv`
- Rows: 20,303
- Distinct entities: 20 / 20
- Date range: 2023-07-01 to 2026-06-30
- Amount column (gross flow, NOT revenue): n=20,303, sum=R38,476,306,723, mean=R1,895,105, range=[R7,494, R138,163,681]

**Null rates (%)**

| column                     |   null_pct |
|:---------------------------|-----------:|
| memo                       |    99.537  |
| counterparty_country       |     1.5712 |
| instrument_id              |     0      |
| sector                     |     0      |
| date                       |     0      |
| entity_id                  |     0      |
| entity_name                |     0      |
| direction                  |     0      |
| instrument_type            |     0      |
| value_zar                  |     0      |
| tenor_days                 |     0      |
| commodity_or_contract_type |     0      |
| status                     |     0      |
| beneficiary_name           |     0      |
| reference                  |     0      |

**Categorical cardinality**

| column                     |   n_distinct |
|:---------------------------|-------------:|
| sector                     |            7 |
| instrument_type            |            3 |
| direction                  |            2 |
| counterparty_country       |           34 |
| commodity_or_contract_type |           15 |
| status                     |            4 |

*sector* top values:

| value              |    n |
|:-------------------|-----:|
| consumer           | 8238 |
| mining             | 5123 |
| industrials_pharma | 3484 |
| telecoms           | 2726 |
| insurance          |  556 |
| tech               |  126 |
| real_estate        |   50 |

*instrument_type* top values:

| value              |    n |
|:-------------------|-----:|
| letters_of_credit  | 8134 |
| export_collections | 6793 |
| guarantees         | 5376 |

*direction* top values:

| value   |     n |
|:--------|------:|
| import  | 11294 |
| export  |  9009 |

*counterparty_country* top values:

| value                |    n |
|:---------------------|-----:|
| Netherlands          | 1496 |
| Switzerland          | 1496 |
| United Kingdom       | 1477 |
| India                | 1461 |
| China                | 1455 |
| Germany              | 1453 |
| Brazil               | 1450 |
| United Arab Emirates | 1420 |
| Japan                | 1415 |
| United States        | 1404 |
| Zambia               |  960 |
| Ghana                |  847 |
| Nigeria              |  708 |
| Kenya                |  702 |
| Botswana             |  366 |

*commodity_or_contract_type* top values:

| value                     |    n |
|:--------------------------|-----:|
| bid_bond                  | 1823 |
| advance_payment_guarantee | 1794 |
| performance_guarantee     | 1759 |
| platinum_group_metals     | 1291 |
| electronics               | 1290 |
| coal                      | 1277 |
| copper                    | 1273 |
| telecom_equipment         | 1254 |
| pharmaceuticals           | 1242 |
| iron_ore                  | 1240 |
| chemicals                 | 1240 |
| gold                      | 1234 |
| agri_produce              | 1205 |
| consumer_goods            | 1200 |
| manufactured_goods        | 1181 |

*status* top values:

| value   |    n |
|:--------|-----:|
| settled | 8632 |
| active  | 7066 |
| issued  | 2995 |
| expired | 1610 |

**Free-text columns (id/reference/memo — null rate + cardinality only)**

| column           |   n_distinct |   n_non_null |
|:-----------------|-------------:|-------------:|
| beneficiary_name |           45 |        20303 |
| reference        |        20134 |        20303 |
| memo             |           94 |           94 |

## Competitor-credit memo fingerprint — numeric cross-tab (Phase 1; interpreted in Phase 2)

Rows where `memo` is non-null, split by whether `beneficiary_name` is one of the 5 recurring non-Syn-Bank names (`Halcyon Trade Bank`, `Meridian Bank Ltd`, `Northgate Financial Bank`, `Solstice Capital Bank`, `Crestwood Merchant Bank`). See METHODOLOGY.md.

| table                 |   n_memo_rows |   sum_memo_zar |   n_bank_beneficiary |   sum_bank_beneficiary_zar |
|:----------------------|--------------:|---------------:|---------------------:|---------------------------:|
| cross_border_payments |           448 |    2.4043e+08  |                  448 |                2.4043e+08  |
| trade_finance         |            94 |    1.63095e+08 |                    0 |                0           |
| transactional_banking |          3657 |    5.9722e+08  |                 1544 |                4.52369e+08 |

**NEW — not in the original brief:** transactional_banking.csv also carries a `memo` column. 3,657 non-null rows (R597,220,361) split into 1,544 rows to the same 5 known counterparties (R452,369,428) and 2,113 rows to ordinary trade counterparties carrying identical template language (R144,850,932). See Phase 2 output for interpretation.