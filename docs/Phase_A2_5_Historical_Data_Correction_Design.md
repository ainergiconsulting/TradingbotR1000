# Phase A2.5 - Historical Data Correction Design

Date: 2026-07-24

Status: design gate before full corporate-action collection.

Scope: document the historical data correction architecture before Phase A2 proceeds to full current-universe corporate-action collection. This phase does not modify production trading logic, production configuration, launchers, scheduled tasks, broker state, or the existing historical OHLCV database.

## Objective

Define how TradingbotR1000 will preserve raw historical data, store corporate actions, generate corrected research datasets, prevent double adjustment, rebuild indicators, validate corrected data, and roll back safely.

## Programme Boundary

Program A - Production & Data Integrity owns this phase.

Program B - Scientific Research will consume corrected datasets after Program A validates them.

Massive remains a one-time historical correction input only. It must not become a recurring production dependency and must not be used to replace or re-download the existing approximately ten-year OHLCV database.

## Corporate-Action Storage

### Raw Provider Payloads

Raw one-time Massive payloads are stored under:

`C:\TradingbotR1000\data\source\massive\corporate_actions\by_symbol`

Each file is named:

`<canonical_symbol>.json`

These files preserve the provider response for audit. They are not edited after collection.

### Normalized Provider Tables

Provider-normalized tables are stored under:

`C:\TradingbotR1000\data\source\massive\corporate_actions`

Current tables:

- `splits.csv`
- `dividends.csv`
- `ticker_events.csv`
- `event_capabilities.csv`

Ticker/reference metadata is stored under:

`C:\TradingbotR1000\data\source\massive\reference\ticker_details.csv`

### Canonical Corporate-Action Store

After the Security Master exists, provider-specific records should be transformed into a canonical corporate-action store under:

`C:\TradingbotR1000\data\corporate_actions\v1`

Recommended files:

- `corporate_actions.csv`
- `corporate_action_sources.csv`
- `corporate_action_validation_report.json`
- `corporate_action_manifest.json`

The canonical store must use the permanent internal `canonical_security_id`. Massive ticker, IWB ticker, IBKR symbol, IBKR `conId`, CUSIP, ISIN, SEDOL and other identifiers are attributes, not primary keys.

## Supported Corporate-Action Event Types

The architecture must support:

- forward split;
- reverse split;
- cash dividend;
- stock dividend;
- ticker change;
- merger;
- acquisition;
- spin-off;
- delisting.

Some events may not be immediately available from current sources. Missing event classes must be recorded as `unavailable`, `schema_only`, or `manual_review_required`; they must not be silently ignored.

## Versioning Strategy

Every correction run creates a timestamped immutable run folder:

`C:\TradingbotR1000\data\processed\historical_correction\runs\run_YYYYMMDD_HHMMSS`

Each run contains:

- `manifest.json`
- `input_file_hashes.csv`
- `corporate_action_hashes.csv`
- `correction_parameters.json`
- `symbol_validation.csv`
- `correction_summary.json`
- `daily_bars_split_adjusted\*.csv`
- optional `daily_bars_total_return\*.csv`

No run may overwrite a previous run.

If a corrected dataset is later approved for use, create or update an explicit pointer file:

`C:\TradingbotR1000\data\processed\historical_correction\ACTIVE_DATASET.json`

The pointer must include:

- active run ID;
- creation timestamp;
- input hashes;
- algorithm version;
- validation status;
- approval note.

Do not promote a run by renaming folders or overwriting old outputs.

## Raw Historical Data Preservation

The following existing data must remain unchanged:

- `C:\TradingbotR1000\data\daily_bars\*.csv`
- `C:\TradingbotR1000\ibkr_r1000_results\historical_bars.massive_checkpoint.csv`
- `C:\TradingbotR1000\ibkr_r1000_results\historical_bars.csv`

Historical correction must be performed by generating derived datasets from raw inputs. Raw files are read-only inputs. Any repair or adjustment must write to a new processed output path.

## Corrected Dataset Generation

### Split-Adjusted OHLCV Dataset

Primary corrected research dataset:

`daily_bars_split_adjusted`

Generation rules:

1. Load raw unadjusted OHLCV bars.
2. Load canonical corporate-action events.
3. Sort split and reverse-split events by execution date.
4. For each bar date, compute the cumulative split adjustment factor from all split events after that bar date.
5. Adjust prices before each split event:
   - adjusted open = raw open * cumulative price factor;
   - adjusted high = raw high * cumulative price factor;
   - adjusted low = raw low * cumulative price factor;
   - adjusted close = raw close * cumulative price factor.
6. Adjust volume inversely:
   - adjusted volume = raw volume / cumulative price factor.
7. Preserve raw fields in the output or include a manifest-linked raw source reference.
8. Preserve the original date sequence and never synthesize missing bars.

For a forward split where `split_from = 1` and `split_to = 4`, bars before the execution date receive a price factor of `1 / 4` and a volume factor of `4`.

For a reverse split where `split_from = 5` and `split_to = 1`, bars before the execution date receive a price factor of `5 / 1` and a volume factor of `1 / 5`.

### Dividend-Aware Dataset

Dividend handling must be evaluated separately.

Cash dividends do not change split-adjusted OHLCV prices. A dividend-aware return dataset may be generated separately if the methodology is approved.

Possible dividend outputs:

- `daily_bars_split_adjusted`: price-continuity series only.
- `daily_bars_total_return`: total-return research series with dividend cash flows or reinvestment explicitly documented.

Do not mix total-return prices into production order pricing.

### Ticker Changes, Mergers, Acquisitions, Spin-Offs, Delistings

These events must be stored and reported. They must not automatically merge predecessor history unless all of the following are true:

1. The event linkage is confirmed.
2. The treatment is technically valid.
3. The impact on strategy rules is documented.
4. The user explicitly approves the combination.

Until then, event records are used for validation, warnings, and research limitations.

## Prevention Of Double Adjustment

The correction engine must prevent double adjustment with the following controls:

1. Input dataset metadata must state `adjustment_state = raw_unadjusted`.
2. The existing Massive progress metadata showing `adjusted: false` is supporting evidence, not sufficient by itself.
3. Correction runs must always read from raw source paths, never from prior adjusted output folders.
4. Every output manifest must state:
   - input dataset hash;
   - input adjustment state;
   - output adjustment state;
   - corporate-action source hash;
   - correction algorithm version.
5. If a split event exists but the raw bars already appear split-adjusted around the event date, mark `possible_double_adjustment_risk` and quarantine the symbol.
6. If an adjusted output is passed as input, fail closed.
7. Output folders must include the adjustment state in the path and manifest.

## Volume Adjustment Policy

Volume is adjusted only for splits and reverse splits.

For split-adjusted datasets:

- prices before the split date are multiplied by the cumulative price factor;
- volume before the split date is multiplied by the reciprocal of the cumulative price factor;
- adjusted volume may be stored as a decimal value for mathematical consistency;
- rounded integer volume may be generated only as a display/export field;
- raw volume remains preserved.

Dividends do not adjust volume.

Ticker changes, mergers, acquisitions, spin-offs, and delistings do not adjust volume unless a later approved event-specific methodology requires it.

## Indicator Rebuild Process

After a corrected dataset is generated:

1. Discard any cached indicators derived from raw unadjusted prices.
2. Rebuild all strategy indicators from the corrected close series:
   - 200-day moving average;
   - Bollinger bands;
   - RSI;
   - 150-day appreciation/ranking metric;
   - holding-period calendar logic.
3. Rebuild strategy eligibility from corrected completed closes.
4. Re-run research backtests using an explicit corrected dataset path.
5. Record dataset run ID and manifest hash in every research output.
6. Keep production strategy parameters unchanged.

No production runtime may silently switch to corrected research data until shadow validation and explicit approval are complete.

## Validation Methodology

Validation happens in layers:

### Layer 1 - Raw Data Quality

Reject a symbol if raw data contains:

- missing required schema fields;
- missing dates relative to the expected market calendar without an explainable reason;
- duplicate dates;
- duplicate bars;
- negative or zero prices;
- `high < low`;
- open outside high/low;
- close outside high/low;
- negative volume;
- inconsistent identifiers;
- dates outside the approved range.

### Layer 2 - Corporate-Action Coverage

For each symbol:

1. Load all split, dividend, ticker-change, merger, acquisition, spin-off, and delisting events available for that canonical security.
2. Verify that every event maps to exactly one `canonical_security_id`.
3. Flag events outside the local historical date range.
4. Flag expected events with no nearby trading bars.
5. Flag suspicious raw price gaps that have no corresponding corporate action.

### Layer 3 - Split Consistency

For each split or reverse split:

1. Locate the last trading bar before the event execution date.
2. Locate the first trading bar on or after the event execution date.
3. Compute:
   - `expected_price_ratio = split_from / split_to`;
   - `observed_gap_ratio = post_event_open / pre_event_close`.
4. Compute:
   - `split_gap_residual = observed_gap_ratio / expected_price_ratio`.
5. If `observed_gap_ratio` is close to `expected_price_ratio`, the raw data is consistent with an unadjusted split.
6. If `observed_gap_ratio` is close to `1.0` while a split event exists, flag `possible_already_adjusted_or_missing_raw_split_gap`.
7. If neither condition holds, flag `split_gap_inconsistent`.
8. After applying the split adjustment, verify that the adjusted overnight gap no longer contains the split-ratio discontinuity.

Initial tolerance policy:

- A split gap is considered consistent if `abs(log(split_gap_residual)) <= max(0.20, 5 * local_20_day_median_abs_return)`.
- A possible already-adjusted gap is flagged if `abs(log(observed_gap_ratio)) <= max(0.10, 3 * local_20_day_median_abs_return)` while the split ratio itself is material.
- These tolerance values must be reported in `correction_parameters.json` and may be refined only through documented validation.

### Layer 4 - Suspicious Gap Detection

For every adjacent trading-day pair:

1. Compute `raw_gap_ratio = current_open / prior_close`.
2. Flag a suspicious gap if:
   - `raw_gap_ratio >= 1.5`, or
   - `raw_gap_ratio <= 0.67`, or
   - `abs(log(raw_gap_ratio)) > max(0.35, 8 * local_20_day_median_abs_return)`.
3. If a split, reverse split, merger, acquisition, spin-off, delisting, or ticker event exists within a configurable event window, classify the gap as `corporate_action_explained`.
4. Otherwise classify it as `suspicious_gap_without_corporate_action`.

### Layer 5 - Dividend Consistency

For every dividend:

1. Verify the ex-dividend date is within the available local date range or record it as outside range.
2. Verify that a trading bar exists on or immediately after the ex-dividend date.
3. Store dividend amount, currency, dividend type, and split-adjusted amount where available.
4. Do not price-adjust OHLCV for cash dividends in the split-adjusted dataset.
5. If building a total-return dataset, validate the cash-flow or reinvestment treatment separately.

### Layer 6 - Corrected Output Quality

Reject corrected output if it contains:

- row-count mismatch versus raw input without explanation;
- date-order changes;
- duplicate dates;
- missing required adjusted fields;
- negative adjusted prices;
- `adjusted_high < adjusted_low`;
- adjusted open outside adjusted high/low;
- adjusted close outside adjusted high/low;
- negative adjusted volume;
- unresolved double-adjustment risk;
- unapplied material split events.

## Exact Meaning Of "Validate Historical Bars Against Corporate Actions"

The phrase means:

For each canonical security, compare the local raw historical OHLCV sequence with the independently collected corporate-action timeline to prove that:

1. known splits and reverse splits are visible in the raw data or otherwise explainable;
2. the correction engine applies exactly the expected split factors to pre-event bars;
3. no split factor is applied twice;
4. large unexplained price gaps are detected and reported;
5. dividend events are represented for return-analysis decisions;
6. ticker changes, mergers, acquisitions, spin-offs, and delistings are stored as structural events and do not silently corrupt the price history;
7. the generated corrected dataset passes OHLCV, date, volume, and identifier integrity checks.

It does not mean:

- re-downloading the full historical OHLCV database;
- replacing existing raw files;
- fabricating missing bars;
- combining predecessor tickers automatically;
- assuming dividends or delistings that are not present in the data.

## Validation Algorithm To Implement

For each symbol in the active universe:

1. Resolve the symbol to `canonical_security_id`.
2. Load raw local bars from `data\daily_bars`.
3. Load all available corporate actions for the canonical security.
4. Run raw data quality checks.
5. Build a sorted event timeline.
6. Detect suspicious raw gaps.
7. For every split/reverse split:
   - locate pre-event and post-event bars;
   - compute expected and observed ratios;
   - classify the event as `raw_split_consistent`, `possible_already_adjusted`, `split_gap_inconsistent`, or `not_observable`;
   - block automatic adjustment if `possible_already_adjusted` or `split_gap_inconsistent` is material.
8. Compute cumulative split factors.
9. Generate corrected OHLCV rows from raw rows.
10. Validate corrected OHLCV integrity.
11. Check that all material split events were applied exactly once.
12. Record dividend events and dividend treatment status.
13. Record structural events and whether they require manual review.
14. Write per-symbol validation output.
15. Promote the corrected symbol only if all blocking checks pass.
16. Write run-level validation summary.
17. Do not update any active dataset pointer unless the run-level validation passes and promotion is approved.

## Rollback Strategy

Rollback is simple because raw files are never modified.

If a correction run fails:

1. Mark the run folder as failed in its manifest.
2. Do not update `ACTIVE_DATASET.json`.
3. Keep previous processed outputs unchanged.
4. Keep production pointed at the current validated dataset.
5. Preserve failed-run reports for diagnosis.

If a promoted corrected dataset later needs rollback:

1. Update `ACTIVE_DATASET.json` to the previous approved run ID.
2. Record rollback timestamp and reason.
3. Do not delete the rejected run.
4. Re-run shadow validation before any future promotion.

## Phase A2.5 Acceptance Criteria

This design phase is complete when:

1. Storage locations are documented.
2. Versioning rules are documented.
3. Raw data preservation is explicit.
4. Corrected dataset generation rules are documented.
5. Double-adjustment prevention is documented.
6. Volume adjustment policy is documented.
7. Indicator rebuild process is documented.
8. Validation methodology and exact algorithm are documented.
9. Rollback strategy is documented.
10. Project progress separates planning completion from implementation completion.

