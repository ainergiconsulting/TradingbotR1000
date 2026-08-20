# TradingbotR1000 Security Master

Status: Phase A3 initial implementation.

The Security Master is the single authoritative offline mapping between internal security identity and supported external identifiers.

It does not change production runtime behavior. The production runtime continues to use the existing symbol mapping until a later shadow-validation phase explicitly integrates the Security Master.

## Location

SQLite database:

`C:\TradingbotR1000\data\security_master\security_master.sqlite3`

Audit exports:

- `C:\TradingbotR1000\data\security_master\security_master_export.csv`
- `C:\TradingbotR1000\data\security_master\security_master_identifiers.csv`
- `C:\TradingbotR1000\data\security_master\security_master_corporate_actions.csv`
- `C:\TradingbotR1000\data\security_master\security_master_manifest.json`
- `C:\TradingbotR1000\data\security_master\security_master_validation_report.json`

## Canonical Security ID

Every security has a permanent internal `canonical_security_id`.

External identifiers are attributes of the canonical security. They are not primary keys.

The builder preserves existing `canonical_security_id` values when rebuilding an existing Security Master. New securities receive the next available internal ID.

## Supported Identifier Types

Currently populated identifier attributes include:

- `canonical_symbol`
- `iwb_symbol`
- `massive_symbol`
- `historical_file`
- `ibkr_con_id`
- `ibkr_symbol`
- `ibkr_local_symbol`
- `ibkr_trading_class`
- `composite_figi`
- `share_class_figi`
- `cik`

Schema placeholders exist for future CUSIP, ISIN and SEDOL sources.

## Corporate Actions

The database supports:

- forward split;
- reverse split;
- cash dividend;
- stock dividend;
- ticker change;
- merger;
- acquisition;
- spin-off;
- delisting.

Current populated events come from the Phase A2 Massive collection:

- splits;
- dividends;
- ticker events;
- delisting metadata where available.

Mergers, acquisitions, spin-offs and stock dividends are schema-supported but are not inferred if the source data does not provide them.

## Build Command

```powershell
python -B tools\build_security_master.py
```

## Validation Command

```powershell
python -B tools\validate_security_master.py
```

## Current Validation Requirements

Validation verifies that:

- every current IWB symbol resolves to exactly one Security Master row;
- every tradable symbol has a verified IBKR stock contract;
- known exclusions `HOLX` and `NSA` remain explicitly excluded;
- Phase A2 blocking symbols remain marked as blocked for corrected-dataset promotion;
- share-class mappings remain represented;
- `HEI` and `HEI.A` remain distinct securities with distinct IBKR conIds;
- all supported corporate-action event types are registered;
- critical external identifiers are not ambiguous.

## Promotion Boundary

The Security Master may be used by later phases for shadow validation.

It must not replace production runtime symbol mapping until a later controlled production integration phase is approved.
