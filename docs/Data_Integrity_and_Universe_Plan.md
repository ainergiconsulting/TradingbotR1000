# TradingbotR1000 Data Integrity And Universe Plan

Date: 2026-07-24

Scope: implementation plan only. This document defines the next data and universe architecture work without changing runtime behavior.

## Goals

1. Preserve the current production trading system while improving data integrity.
2. Replace ticker-only identity with a central Security Master using a permanent internal Canonical Security ID.
3. Automate daily IWB universe ingestion safely.
4. Use Massive only during the initial historical correction phase to capture corporate actions needed for split-adjusted and dividend-aware research datasets.
5. Keep production strategy rules unchanged.
6. Keep current Tradingbot2607-derived operational architecture intact.

## Non-Goals

- Do not implement historical point-in-time Russell 1000 membership in the immediate phase.
- Do not change production ranking, entry, exit, sizing, reserve, or limit-price logic.
- Do not switch production to a new dataset until validation has passed in shadow mode.
- Do not combine predecessor histories unless a specific corporate-action mapping is confirmed and approved.
- Do not synthesize missing bars.
- Do not replace or re-download the existing approximately ten-year historical database.
- Do not introduce Massive as a recurring production dependency.

## Programme Boundary

Program A - Production & Data Integrity:

- daily IWB holdings download and dated snapshots;
- additions/removals detection;
- central Security Master;
- IBKR contract resolution;
- IBKR daily OHLCV updates after migration;
- minimum warm-up history for genuinely new IWB constituents;
- validation and rejection of corrupted data.

Program B - Scientific Research:

- corrected historical datasets;
- market-state features;
- market-regime discovery;
- conditional performance analysis.

Program B must consume validated data from Program A but must not modify production behavior.

## Current Data Sources

| Source | Current path | Use today | Limitation |
|---|---|---|---|
| IWB holdings | `C:\TradingbotR1000\IWB_holdings.csv` | Current Russell 1000 proxy universe | Static local file; not daily refreshed |
| Per-symbol bars | `C:\TradingbotR1000\data\daily_bars` | Production market scan and research | Unadjusted OHLCV; no dividends or split factors |
| Massive checkpoint | `C:\TradingbotR1000\ibkr_r1000_results\historical_bars.massive_checkpoint.csv` | Existing historical evidence | Large flat file; already downloaded; should not be re-downloaded |
| Symbol compatibility cache | `C:\TradingbotR1000\ibkr_r1000_results\symbol_compatibility_validation.csv` | Evidence of Massive/IWB/IBKR compatibility | Validation output, not central runtime authority |
| IBKR broker snapshot | `C:\TradingbotR1000\current_reference\PaperTradingR1000\state\broker_snapshot.json` | Live positions, account values, open orders, executions | Runtime snapshot, not a security master |

## Target Data Layers

```text
Raw immutable inputs
  data/source/iwb_holdings/YYYYMMDD_iwb_holdings.csv
  data/source/massive/corporate_actions/splits.csv
  data/source/massive/corporate_actions/dividends.csv
  data/source/massive/reference/tickers.csv
  data/source/massive/reference/ticker_events.csv
  data/source/ibkr/daily_updates/*.csv

Validated identity layer
  data/security_master/security_master.sqlite3
  data/security_master/security_master_export.csv
  data/security_master/security_master_validation_report.json

Processed research datasets
  data/processed/daily_bars_split_adjusted/v1/*.csv
  data/processed/daily_bars_total_return/v1/*.csv
  data/processed/market_regime_features/v1/*.csv

Production runtime adapters
  current_reference/PaperTradingR1000/symbol_mapping.py
  current_reference/PaperTradingR1000/config_files/universe_config.json
  current_reference/PaperTradingR1000/trading_engine.py
  current_reference/PaperTradingR1000/automated_broker.py
  current_reference/PaperTradingR1000/reconciliation.py
```

The target should remain compatible with existing CSV/JSON runtime patterns. SQLite is recommended for the Security Master because it can enforce uniqueness, preserve validation history, and avoid duplicate mapping logic. CSV exports should be generated for auditability.

Massive is limited to one-time historical correction inputs. After the historical correction phase, normal operation should require only IWB and IBKR.

## Security Master

### Purpose

The Security Master becomes the single source of truth for every security. It should resolve the same security identity for:

- historical-data calculations;
- strategy signals;
- portfolio positions;
- pending orders;
- automated order persistence;
- reconciliation;
- manual console display;
- Telegram reports;
- order submission.

### Required Fields

| Field | Purpose |
|---|---|
| `canonical_security_id` | Permanent internal project ID; primary identity for the security |
| `company_name` | Name from IWB or reference provider |
| `iwb_symbol` | Symbol as supplied by IWB |
| `canonical_symbol` | Normalized project symbol |
| `massive_symbol` | Symbol accepted by Massive/Polygon data |
| `massive_active` | Massive active status |
| `massive_primary_exchange` | Massive primary exchange |
| `massive_cik` | CIK when available |
| `massive_composite_figi` | Composite FIGI when available |
| `massive_share_class_figi` | Share-class FIGI when available |
| `cusip_or_us_code` | US security code when available from IWB or ETF Global |
| `isin` | ISIN when available |
| `sedol` | SEDOL when available |
| `ibkr_symbol` | IBKR symbol |
| `ibkr_local_symbol` | IBKR local symbol |
| `ibkr_trading_class` | IBKR trading class |
| `ibkr_con_id` | IBKR contract ID |
| `ibkr_sec_type` | Expected `STK` |
| `ibkr_currency` | Expected `USD` |
| `ibkr_exchange` | Expected `SMART` for order routing |
| `ibkr_primary_exchange` | Verified primary exchange |
| `membership_status` | Current member, removed, candidate, excluded |
| `first_seen_in_iwb` | First local IWB snapshot date |
| `last_seen_in_iwb` | Last local IWB snapshot date |
| `listing_date` | Massive listing date when available |
| `delisted_date` | Massive delisting date when available |
| `validation_status` | Resolved, ambiguous, invalid, excluded, pending |
| `validation_reason` | Human-readable reason |
| `resolution_method` | CUSIP, ISIN, FIGI, explicit alias, deterministic normalization, manual exclusion |
| `last_verified_at_utc` | Latest IBKR/Massive validation timestamp |

All external identifiers are attributes of `canonical_security_id`. External identifiers must never become the primary key because tickers, CUSIPs, FIGIs, and broker contract details can change or become unavailable.

### Identifier Resolution Hierarchy

Use the following order:

1. Stable identifier from ETF source when available: CUSIP or US code.
2. ISIN.
3. FIGI or share-class FIGI.
4. Exact Massive active ticker and metadata match.
5. Existing explicit alias in `symbol_mapping.py`.
6. Deterministic share-class normalization: dots, dashes, slashes, and spaces.
7. IBKR contract search filtered by stock, USD, SMART routing, and expected primary exchange.
8. Manual exclusion with documented reason.

Do not allow a ticker-only match to override a stable-identifier mismatch.

## Daily IWB Universe Update Workflow

### Proposed Workflow

1. Acquire latest IWB holdings into a temporary file.
2. Validate schema before replacing or promoting anything.
3. Require expected columns, including at minimum ticker, name, asset class, market value, weight, exchange, and currency when present.
4. Confirm the holdings as-of date and processed/download timestamp.
5. Normalize all tickers through the Security Master.
6. Compare against the previous accepted universe snapshot.
7. Produce a universe delta report:
   - added securities;
   - removed securities;
   - ticker changes;
   - unresolved mappings;
   - non-USD or non-equity rows;
   - duplicate rows.
8. Promote the new universe only if:
   - all tradable securities resolve or have approved exclusions;
   - no critical schema changes are present;
   - the file date is newer than the current production snapshot;
   - the row count and weight totals pass sanity checks.
9. Keep the previous valid snapshot as fallback.
10. Write runtime-readable output only after atomic validation succeeds.

### Recommended Update Timing

Run after the fund provider has published current holdings and before the next strategy cycle. The workflow should be independent from the trading cycle. If the universe update fails, the bot should continue using the last validated universe and report the failure.

## New Security Onboarding

For every newly added IWB security:

1. Add a pending Security Master record.
2. Resolve stable identifiers where available.
3. Resolve and qualify the IBKR stock contract.
4. Download only the minimum required IBKR warm-up daily OHLCV history when the symbol is genuinely new and not already present in the local database.
5. Attach any available corporate-action metadata from existing local corporate-action stores or approved non-recurring correction sources.
6. Validate at least 200 completed daily closes before allowing strategy eligibility.
7. Mark as tradable only after IBKR contract resolution and local data validation pass.

If any step fails, mark the security `excluded` or `pending` with a clear reason. The runtime must report the symbol as not tradable rather than silently ignoring it.

## Removed Security Handling

For securities removed from the current IWB universe:

1. Preserve the Security Master record and historical data.
2. Mark `membership_status = removed`.
3. Do not generate new BUY signals for removed securities.
4. Continue monitoring existing positions if the account still holds them.
5. Allow SELL and reconciliation workflows to operate safely until the position is gone.
6. Keep previous holdings snapshots for audit and research.

Do not delete historical data for removed symbols.

## Corporate Actions

Detailed correction design:

`C:\TradingbotR1000\docs\Phase_A2_5_Historical_Data_Correction_Design.md`

The architecture must support:

- forward split;
- reverse split;
- cash dividend;
- stock dividend;
- ticker changes;
- mergers;
- acquisitions;
- spin-offs;
- delistings.

Some event classes may not be immediately available from current data sources. Missing event classes must be represented explicitly as unavailable rather than ignored.

### Massive Sources To Integrate

Based on current Massive documentation, use Massive only during the initial historical correction phase:

- `GET /stocks/v1/splits` provides split events, split ratios, adjustment type, and cumulative historical adjustment factors.
- `GET /stocks/v1/dividends` provides cash dividends, ex-dividend dates, split-adjusted cash amounts, distribution type, and historical adjustment factors.
- `GET /v3/reference/tickers` and `GET /v3/reference/tickers/{ticker}` provide active/delisted status, primary exchange, listing date, and identifiers.
- `GET /vX/reference/tickers/{id}/events` is documented for ticker-change and event timelines.
- `GET /etf-global/v1/constituents` can provide ETF holdings with effective dates, processed dates, weights, and stable identifiers if the account is entitled to the dataset.

After the historical correction phase, no recurring Massive downloads should exist and no Massive subscription should be required for normal operation.

### Adjustment Policy

Preserve raw downloaded OHLCV exactly as received.

Create derived datasets:

- split-adjusted OHLCV for technical indicators and price-continuity research;
- total-return research series where dividends are reinvested or explicitly modeled;
- raw/latest prices for live order price calculations.

Production order submission must continue to use live broker-appropriate raw prices and IBKR contract identity. Historical adjustments must not change live limit-order pricing unless explicitly designed and approved.

### Split Handling

For each split event:

1. Store the event in the raw corporate-action table.
2. Validate event ticker against the Security Master.
3. Apply split adjustment to dates before the execution date.
4. Adjust OHLC prices and reverse-adjust volume consistently.
5. Record adjustment factors and output hashes.
6. Validate against Massive adjusted bars where possible.

### Dividend Handling

For each dividend event:

1. Store raw cash amount, split-adjusted cash amount, ex-date, pay date, distribution type, and currency.
2. Do not alter split-adjusted OHLCV unless creating a separate total-return dataset.
3. For research returns, document whether dividends are ignored, cash-paid, or reinvested.
4. Treat special dividends separately from recurring dividends.

## Data Quality Controls

Every promoted symbol dataset should validate:

- required schema fields present;
- missing dates;
- duplicate dates;
- duplicate bars;
- unique `(symbol, date)` rows;
- strict ascending dates;
- OHLC prices positive;
- no negative prices;
- `high >= low`;
- `low <= open <= high`;
- `low <= close <= high`;
- suspicious price gaps without matching corporate actions;
- volume non-negative;
- inconsistent volumes;
- no future dates;
- no dates outside the requested range;
- no stale latest bar relative to market calendar;
- no impossible split-related price discontinuities after adjustment;
- minimum 200 completed closes for strategy eligibility;
- symbol and Security Master identity match;
- inconsistent identifiers across IWB, local files, Massive correction data, IBKR contracts, positions, and orders.

Corrupted data must be rejected automatically and reported. It must not be silently repaired, interpolated, or promoted.

## Production Runtime Integration Plan

The runtime should migrate gradually:

1. Add read-only Security Master loader.
2. Continue supporting current `symbol_mapping.py` as a compatibility facade.
3. Make strategy universe records include `security_id`, canonical symbol, Massive symbol, and IBKR contract identity.
4. Make `trading_engine.py` load universe from the validated Security Master view.
5. Make `automated_broker.py` submit using validated IBKR contract identity where available.
6. Make reconciliation and automated order persistence store `security_id` and `ibkr_con_id`.
7. Keep existing JSON reports backward-compatible by retaining the current symbol fields.
8. Run shadow validation before switching production to the new data view.

## Operational Failure Modes

| Failure | Required behavior |
|---|---|
| IWB update unavailable | Continue with last validated universe; log warning |
| IWB file schema changed | Reject new file; preserve previous universe |
| Security unresolved | Exclude from BUY eligibility; report reason |
| IBKR contract ambiguous | Exclude until manually resolved |
| Corporate-action data unavailable | Block adjusted-dataset promotion; do not alter raw data |
| Split-adjusted validation mismatch | Quarantine symbol; preserve old valid processed data |
| Corrupted IBKR daily update | Reject update; keep previous valid data |
| Manual investable capital exceeds NLV | Block new BUY orders; allow safe SELL processing |
| Persistence failure | Fail closed for new BUY submissions |

## Validation Evidence Required Before Runtime Switch

- Rebuilt Security Master covers all current IWB symbols.
- Every tradable security has a validated IBKR stock contract or explicit exclusion.
- Historical file mapping is complete and one-to-one for tradable symbols.
- Split-adjusted dataset passes cross-checks.
- Historical bars are validated against corporate actions using the Phase A2.5 algorithm.
- The production scan in shadow mode produces the same symbol eligibility and strategy outputs where adjustment does not alter historical data.
- Any changed signals caused by split-adjustment are listed and explained.
- Automated broker uses the same security identity as historical calculations.
- Control Console and Telegram display the same canonical symbols and exclusion reasons.

## Acceptance Criteria

This phase is complete only when:

1. Raw data is preserved.
2. Security Master is the single identity source.
3. Daily IWB updates are atomic, resumable, and auditable.
4. Corporate-action data is ingested and versioned.
5. Adjusted research datasets are reproducible.
6. Production can run in shadow mode from the new identity/data layer.
7. No production strategy rule has changed.
