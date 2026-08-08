# Phase 2 — Forensic Extraction Report

Total memo-bearing rows processed: **4,199** (primary tier: 1,992, secondary tier: 2,207)

| source_file           |    n | value_zar    |
|:----------------------|-----:|:-------------|
| cross_border_payments |  448 | R240,429,956 |
| trade_finance         |   94 | R163,095,270 |
| transactional_banking | 3657 | R597,220,361 |

**By confidence tier**

| signal_tier   |    n | value_zar    |
|:--------------|-----:|:-------------|
| primary       | 1992 | R692,799,384 |
| secondary     | 2207 | R307,946,202 |

## Regex baseline — facility_type distribution

| facility_type   |    n |
|:----------------|-----:|
| other           | 2082 |
| bridging        | 1080 |
| syndicate       | 1037 |

## LLM (gemini-2.5-flash) vs. regex baseline

- Rows scored by both: 4,199
- **Overall disagreement rate: 36.7%**
  - facility_type: 36.7%
  - lender_name: 0.0%
  - external_reference: 0.0%
- LLM confidence_score: mean 0.82, median 0.90
- Cache hits this run: 4,199 / 4,199

**Disagreement rate by confidence tier**

| signal_tier   |   disagreement_rate |
|:--------------|--------------------:|
| primary       |            0.487952 |
| secondary     |            0.257816 |

**facility_type confusion (regex baseline vs. LLM)**

| regex     | llm       |    n |
|:----------|:----------|-----:|
| bridging  | bridging  | 1080 |
| other     | bilateral | 1541 |
| other     | other     |  541 |
| syndicate | syndicate | 1037 |

**Confidence calibration on the ambiguous regex='other' bucket** (explicit 'loan' language and/or a bank-shaped beneficiary name = more corroborating evidence = higher stated confidence; note the mean_confidence column is monotonic in the amount of evidence, both within and across templates)

| memo_template                    | beneficiary_is_bank   | llm_call   |   n |   mean_confidence |
|:---------------------------------|:----------------------|:-----------|----:|------------------:|
| Loan drawdown proceeds           | False                 | bilateral  | 544 |             0.7   |
| Loan drawdown proceeds           | True                  | bilateral  | 455 |             0.9   |
| Settlement re: facility drawdown | False                 | bilateral  |  25 |             0.7   |
| Settlement re: facility drawdown | False                 | other      | 533 |             0.602 |
| Settlement re: facility drawdown | True                  | bilateral  | 517 |             0.804 |
| Settlement re: facility drawdown | True                  | other      |   8 |             0.8   |

**Sample disagreements** (10 of 1541)

| source_file           | entity_name       | beneficiary_name                      | memo                                          | regex_facility_type   | llm_facility_type   | regex_lender_name        | llm_lender_name          | llm_reasoning                                                                                                                                |
|:----------------------|:------------------|:--------------------------------------|:----------------------------------------------|:----------------------|:--------------------|:-------------------------|:-------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------|
| transactional_banking | Naspers           | Northgate Financial Bank              | Settlement re: facility drawdown - ref 682322 | other                 | bilateral           | Northgate Financial Bank | Northgate Financial Bank | The memo explicitly states 'facility drawdown' and the beneficiary is a bank, suggesting a bilateral credit relationship.                    |
| transactional_banking | Bid Corporation   | Solstice Capital Bank                 | Settlement re: facility drawdown - ref 366725 | other                 | bilateral           | Solstice Capital Bank    | Solstice Capital Bank    | The beneficiary is a bank and the memo explicitly mentions a facility drawdown with a reference.                                             |
| transactional_banking | Aspen Pharmacare  | Crestwood Merchant Bank               | Loan drawdown proceeds - ext. ref 421058      | other                 | bilateral           | Crestwood Merchant Bank  | Crestwood Merchant Bank  | The memo explicitly states 'Loan drawdown proceeds' and the beneficiary is a merchant bank, indicating a bilateral loan facility.            |
| transactional_banking | Gold Fields       | Karoo Explosives & Blasting Services  | Loan drawdown proceeds - ext. ref 204187      | other                 | bilateral           |                          |                          | The memo indicates a 'Loan drawdown proceeds' with an external reference, but the beneficiary is not a bank.                                 |
| transactional_banking | MTN Group         | Network Network Equipment Supplies    | Loan drawdown proceeds - ext. ref 536058      | other                 | bilateral           |                          |                          | The memo indicates a 'Loan drawdown proceeds' with an external reference, but the beneficiary is not a bank.                                 |
| transactional_banking | Prosus            | Meridian Bank Ltd                     | Loan drawdown proceeds - ext. ref 719959      | other                 | bilateral           | Meridian Bank Ltd        | Meridian Bank Ltd        | The memo explicitly states 'Loan drawdown proceeds' and the beneficiary is a bank, indicating a bilateral facility.                          |
| transactional_banking | Aspen Pharmacare  | Chemtech Industrial Supplies          | Loan drawdown proceeds - ext. ref 728482      | other                 | bilateral           |                          |                          | The memo indicates a loan drawdown, but the beneficiary is an industrial supplier, not a bank.                                               |
| transactional_banking | The Bidvest Group | Crestwood Merchant Bank               | Loan drawdown proceeds - ext. ref 935145      | other                 | bilateral           | Crestwood Merchant Bank  | Crestwood Merchant Bank  | The memo explicitly states 'Loan drawdown proceeds' and the beneficiary is a merchant bank, indicating a bilateral loan facility.            |
| transactional_banking | The Bidvest Group | Ferrostaal Active Ingredients Trading | Loan drawdown proceeds - ext. ref 909067      | other                 | bilateral           |                          |                          | The memo explicitly states 'Loan drawdown proceeds' but the beneficiary is not a bank, suggesting a bilateral loan from another institution. |
| transactional_banking | Aspen Pharmacare  | Halcyon Trade Bank                    | Settlement re: facility drawdown - ref 151380 | other                 | bilateral           | Halcyon Trade Bank       | Halcyon Trade Bank       | The memo explicitly mentions 'facility drawdown' and the beneficiary is a bank, suggesting a bilateral credit relationship.                  |