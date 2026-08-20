# TradingbotR1000 Planning Decisions Required

Date: 2026-07-24

This file lists only decisions needed before implementation. It avoids strategy-rule changes.

## Decision 1 - Security Master Storage

Question:

Should TradingbotR1000 use a central Security Master as the single source of truth for every security?

Recommended decision:

Approved refinement:

Yes. The Security Master shall use a permanent internal Canonical Security ID. IBKR symbol, IBKR `conId`, IWB ticker, Massive ticker, CUSIP, ISIN, SEDOL, FIGI and all other external identifiers are attributes of that internal ID rather than primary identifiers.

Recommended storage:

Use a SQLite Security Master stored under:

`C:\TradingbotR1000\data\security_master\security_master.sqlite3`

with a generated CSV export for review:

`C:\TradingbotR1000\data\security_master\security_master_export.csv`

Reason:

SQLite can enforce uniqueness for Canonical Security IDs and validated external identifiers, while CSV export keeps the mapping human-auditable.

Impact:

This is an architectural strengthening, not a strategy change.

## Decision 2 - Corporate-Action Adjustment Policy

Question:

Which historical dataset should be used for future research?

Recommended decision:

Preserve raw Massive bars unchanged, then create derived split-adjusted OHLCV and total-return research datasets. Use split-adjusted prices for technical indicators and research continuity. Use raw/live broker prices for live order pricing.

Reason:

The current local bars are unadjusted, and split distortions can invalidate technical indicators and returns.

Impact:

Research outputs may change after corrected data is used. Production strategy rules remain unchanged.

Required event coverage:

The architecture must support forward splits, reverse splits, cash dividends, stock dividends, ticker changes, mergers, acquisitions, spin-offs, and delistings. Event classes unavailable from current data sources must be represented explicitly as unavailable.

Design gate:

Before full current-universe corporate-action collection proceeds, Phase A2.5 must be accepted:

`C:\TradingbotR1000\docs\Phase_A2_5_Historical_Data_Correction_Design.md`

## Decision 3 - IWB Holdings Provider

Question:

Which source should update the daily IWB holdings file?

Recommended decision:

Use the official BlackRock/iShares IWB holdings file as the primary production source. Evaluate Massive ETF Global constituents as an optional secondary or research source only if the account is entitled to that dataset.

Reason:

The current strategy implementation already uses IWB holdings as the local Russell 1000 proxy. Keeping the primary provider aligned with the existing file minimizes disruption.

Impact:

No live trading change until the update workflow is implemented, validated, and promoted.

## Decision 3A - Massive Dependency Boundary

Question:

Should Massive remain part of normal production operations after historical correction?

Decision:

No. Massive shall not become a permanent production dependency. It may be used only during the initial historical correction phase to retrieve corporate actions, validate the existing local dataset, apply split adjustments, and evaluate dividend adjustments. The existing ten-year historical database must not be replaced or broadly re-downloaded.

Impact:

After correction, normal operation must require only daily IWB holdings updates and IBKR data/contract/account services.

## Decision 3B - Daily OHLCV Provider After Migration

Question:

Which provider should supply daily operational OHLCV updates after migration?

Decision:

Use IBKR for daily OHLCV updates after migration. Request only missing recent bars for existing constituents and minimum warm-up history for genuinely new IWB constituents not already present locally.

Impact:

No recurring Massive OHLCV downloads. The existing ten-year database is preserved and incrementally maintained.

## Decision 4 - Production Integration Timing

Question:

When should production begin using Security Master-backed universe and contract identities?

Recommended decision:

Use shadow mode first. The production bot should continue running on the current validated path while the new Security Master view produces comparison reports. Switch only after a dry-run scan proves equivalent or fully explained behavior.

Reason:

Identifier changes affect universe eligibility, order submission, reconciliation, and duplicate prevention.

Impact:

Requires explicit approval before a production runtime switch.

## Decision 5 - Market-Regime Research Inputs

Question:

Should market-regime research wait for corrected split-adjusted data?

Recommended decision:

Yes. First build a comprehensive daily market-state dataset after the adjusted research dataset exists, except for a limited preliminary audit clearly marked as unadjusted. Do not define bull/bear or other regimes until the market-state dataset has been analysed.

Reason:

Unadjusted split distortions could create false regime labels, false drawdowns, and false signals.

Impact:

This may delay regime analysis, but improves reliability.

## Decision 6 - Historical Russell 1000 Membership

Question:

Should point-in-time historical Russell 1000 membership be implemented now?

Recommended decision:

No. Defer it, document survivorship bias, and design the Security Master so historical membership can be added later.

Reason:

The current strategy and production workflow use the current IWB universe. Point-in-time membership is important but materially larger than the immediate data-integrity phase.

Impact:

Backtests remain survivorship-biased until historical membership is later added.

## Decision 7 - Future Strategy Changes

Question:

Should RSI > 60 or any regime-based activation rule be promoted to production now?

Recommended decision:

No. Keep production unchanged. Treat RSI > 60 and any regime framework as research evidence only until a separate Strategy Specification change is explicitly approved.

Reason:

The approved Strategy Specification v1.1 remains authoritative.

Impact:

No production trading rule changes in the next data-integrity phase.
