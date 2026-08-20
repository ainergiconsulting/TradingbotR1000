# Phase A2 Validation Findings Investigation

Generated: 2026-07-24T12:29:05Z

## Scope

This investigation classifies the non-passed Phase A2 validation findings using reusable Python analysis. It does not modify production runtime behavior, raw historical data, or corrected datasets.

## Summary

| Item | Count |
| --- | --- |
| Universe symbols | 1024 |
| Passed | 905 |
| Review required | 111 |
| Failed/blocking | 6 |
| Known exclusions | 2 |

## Cause Category Counts

| Cause category | Symbols |
| --- | --- |
| corporate_actions | 45 |
| data_source_limitation | 116 |
| historical_data_inconsistencies | 117 |
| symbol_mapping_problem | 2 |
| ticker_changes | 8 |

## Blocking Symbols

| Symbol | Primary cause | Cause categories | Evidence | Safest resolution |
| --- | --- | --- | --- | --- |
| HLT | corporate_action_historical_data_mismatch | corporate_actions;historical_data_inconsistencies | 1 split event(s) have raw price gaps inconsistent with the collected split factor; 1 suspicious gap(s) are explained by nearby corporate actions; 2017-01-04 reverse_split 3.0:1.0 observed=2.0920043811610074 residual=0.6973347937203358 class=split_gap_inconsistent | Quarantine before corrected dataset promotion; verify event dates and split factors against Security Master/corporate-action sources, then repair or exclude explicitly. |
| HEI.A | corporate_action_historical_data_mismatch | corporate_actions;historical_data_inconsistencies | 1 split event(s) appear already adjusted or missing the raw split gap; 2018-01-02 forward_split 4.0:5.0 observed=1.0037950664136621 residual=1.2547438330170775 class=possible_already_adjusted | Quarantine before corrected dataset promotion; verify event dates and split factors against Security Master/corporate-action sources, then repair or exclude explicitly. |
| DD | corporate_action_historical_data_mismatch | corporate_actions;data_source_limitation;historical_data_inconsistencies | 1 split event(s) have raw price gaps inconsistent with the collected split factor; 2 suspicious gap(s) are explained by nearby corporate actions; 438 missing market-calendar dates inside the local first/last bar range; 2019-06-03 reverse_split 3.0:1.0 observed=0.782437745740498 residual=0.2608125819134993 class=split_gap_inconsistent | Quarantine before corrected dataset promotion; verify event dates and split factors against Security Master/corporate-action sources, then repair or exclude explicitly. |
| HEI | corporate_action_historical_data_mismatch | corporate_actions;historical_data_inconsistencies | 1 split event(s) appear already adjusted or missing the raw split gap; 2018-01-02 forward_split 4.0:5.0 observed=1.0 residual=1.25 class=possible_already_adjusted | Quarantine before corrected dataset promotion; verify event dates and split factors against Security Master/corporate-action sources, then repair or exclude explicitly. |
| CGNX | corporate_action_historical_data_mismatch | corporate_actions;data_source_limitation;historical_data_inconsistencies | 1 split event(s) appear already adjusted or missing the raw split gap; 1 suspicious gap(s) have no nearby collected corporate action; 2017-11-16 forward_split 1.0:2.0 observed=1.0047975576070365 residual=2.009595115214073 class=possible_already_adjusted | Quarantine before corrected dataset promotion; verify event dates and split factors against Security Master/corporate-action sources, then repair or exclude explicitly. |
| APLD | corporate_action_historical_data_mismatch | corporate_actions;data_source_limitation;historical_data_inconsistencies | 1 split event(s) have raw price gaps inconsistent with the collected split factor; 1 suspicious gap(s) are explained by nearby corporate actions; 2 suspicious gap(s) have no nearby collected corporate action; 2022-04-13 reverse_split 6.0:1.0 observed=2.7647058823529416 residual=0.4607843137254903 class=split_gap_inconsistent | Quarantine before corrected dataset promotion; verify event dates and split factors against Security Master/corporate-action sources, then repair or exclude explicitly. |

## Review-Required Symbols

Review-required symbols are non-blocking warnings from the Phase A2 validator. They are dominated by missing dates and unexplained suspicious gaps.

| Primary cause | Symbols |
| --- | --- |
| missing_dates | 23 |
| missing_dates_and_unexplained_gaps | 19 |
| unexplained_price_gaps | 69 |

| Review-required detail | Symbols |
| --- | --- |
| Symbols with missing dates | 42 |
| Symbols with unexplained suspicious gaps | 88 |
| Symbols with both missing dates and unexplained gaps | 19 |
| Review symbols with material ticker-change evidence | 8 |

### Largest Missing-Date Findings

| Symbol | Missing dates | Rows | First date | Last date |
| --- | --- | --- | --- | --- |
| XE | 2165 | 235 | 2016-12-30 | 2026-07-21 |
| SGI | 2084 | 427 | 2016-07-25 | 2026-07-21 |
| Q | 2001 | 510 | 2016-07-25 | 2026-07-21 |
| TLN | 1908 | 603 | 2016-07-25 | 2026-07-21 |
| P | 1811 | 700 | 2016-07-25 | 2026-07-21 |
| CCC | 1362 | 1149 | 2016-07-25 | 2026-07-21 |
| IOT | 1210 | 1301 | 2016-07-25 | 2026-07-21 |
| FIG | 1149 | 1362 | 2016-07-25 | 2026-07-21 |
| ECHO | 1148 | 1363 | 2016-07-25 | 2026-07-21 |
| SN | 1118 | 1393 | 2016-07-25 | 2026-07-21 |

### Largest Unexplained-Gap Findings

| Symbol | Unexplained gaps | Rows | First date | Last date |
| --- | --- | --- | --- | --- |
| BMNR | 34 | 843 | 2022-03-03 | 2026-07-21 |
| SOLS | 18 | 525 | 2021-12-31 | 2026-07-21 |
| GME | 10 | 2511 | 2016-07-25 | 2026-07-21 |
| JAN | 6 | 1300 | 2019-09-11 | 2026-07-21 |
| AXSM | 4 | 2511 | 2016-07-25 | 2026-07-21 |
| SMMT | 4 | 2504 | 2016-07-27 | 2026-07-21 |
| AXON | 3 | 2021 | 2016-07-25 | 2026-07-21 |
| INSM | 3 | 2510 | 2016-07-25 | 2026-07-21 |
| BBIO | 3 | 1775 | 2019-06-27 | 2026-07-21 |
| ASND | 3 | 2511 | 2016-07-25 | 2026-07-21 |

## Known Massive Exclusions

| Symbol | Primary cause | Evidence | Safest resolution |
| --- | --- | --- | --- |
| NSA | known_symbol_exclusion | ibkr_value_only_no_smart_or_nyse_stock_contract | Exclude from automated corrected dataset and carry exclusion reason into the Security Master. |
| HOLX | known_symbol_exclusion | ibkr_unresolved_no_market_universe_symbol | Exclude from automated corrected dataset and carry exclusion reason into the Security Master. |

## Safest Resolution Strategy

1. Do not promote a corrected dataset containing unresolved blocking symbols.
2. Carry HOLX and NSA as explicit Security Master exclusions with their IBKR and Massive evidence.
3. Quarantine HLT, HEI.A, DD, HEI, CGNX and APLD until corporate-action dates, split factors and local raw bars are reconciled.
4. For the 111 review-required symbols, prioritise symbols with large missing-date counts or repeated unexplained gaps before any research dataset promotion.
5. Repair only confirmed data defects. Do not synthesize bars, silently combine predecessor histories, or double-adjust prices.

## Cause Determination

- Blocking symbols are caused by corporate-action and historical-bar inconsistencies. They are not safe for automatic correction or promotion.
- Review-required symbols are caused by missing local dates, unexplained suspicious gaps, or both. Some also have material ticker-change evidence, but the Phase A2 evidence does not show a project-wide symbol-mapping failure.
- HOLX and NSA are known exclusions caused by unresolved or unsuitable security resolution, evidenced by IBKR compatibility validation and Massive lookup failures.
- No production implementation defect was identified.

## Output Evidence

- Diagnostics CSV: `C:\TradingbotR1000\data\validation\historical_corporate_actions\phase_a2_finding_diagnostics.csv`
- Diagnostics summary JSON: `C:\TradingbotR1000\data\validation\historical_corporate_actions\phase_a2_finding_diagnostics_summary.json`

## Implementation Defect Assessment

No implementation defect was identified from the Phase A2 evidence. The findings are data-integrity findings: corporate-action/date mismatches, missing local dates, unexplained suspicious gaps, or known symbol exclusions. The validation code may still be refined in later phases, but no production runtime defect is indicated by this investigation.

