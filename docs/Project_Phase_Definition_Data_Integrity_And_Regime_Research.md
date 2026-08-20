# TradingbotR1000 Next Phase Definition

Date: 2026-07-24

This document consolidates the approved planning package for the next complete project phase.

## Programmes

### Program A - Production & Data Integrity

Objective: build a robust, autonomous, production-ready trading system.

### Program B - Scientific Research

Objective: determine under which market conditions the strategy generates alpha and when it should reduce exposure or remain inactive.

## Phase Name

Program A/B Foundation: Data Integrity, Universe Automation, Security Master, And Market-State Research

## Purpose

TradingbotR1000 now has a migrated paper-trading runtime and a corrected local research framework. The next phase should protect production operations while addressing data integrity and universe identity risks that limit both trading reliability and research validity.

Massive is limited to the one-time historical correction phase. After correction, normal production operation should rely on IWB for holdings and IBKR for contracts, market data, account state, and daily OHLCV updates.

## Deliverables In This Planning Package

- `C:\TradingbotR1000\docs\Current_State_Audit.md`
- `C:\TradingbotR1000\docs\Data_Integrity_and_Universe_Plan.md`
- `C:\TradingbotR1000\docs\Market_Regime_Research_Plan.md`
- `C:\TradingbotR1000\docs\Implementation_Roadmap.md`
- `C:\TradingbotR1000\docs\Planning_Decisions_Required.md`

## Approved Constraints For Later Implementation

- Preserve the approved Strategy Specification.
- Keep production RSI > 50 until explicitly changed.
- Keep Tradingbot2607-derived architecture and operational entry points.
- Avoid duplicate controllers, consoles, state stores, or order paths.
- Preserve all raw historical data.
- Do not invent historical Russell 1000 membership.
- Do not treat tickers as stable security IDs.
- Make the Canonical Security ID the permanent internal security identity.
- Do not plan recurring Massive downloads or a recurring Massive subscription.
- Do not replace or re-download the existing ten-year historical dataset.
- Do not route live or paper orders through research-only code.

## Recommended Execution Order

1. Establish baseline hashes and progress tracking.
2. Ingest one-time Massive corporate-action and reference data for historical correction only.
3. Build a central Security Master.
4. Add daily IWB holdings update with validation and fallback.
5. Add IBKR daily OHLCV update workflow for incremental operation.
6. Build corrected adjusted research datasets.
7. Run production shadow validation.
8. Build the market-state dataset.
9. Define regimes only after market-state analysis.
10. Defer production strategy changes until separate approval.

## Approval Gate

Implementation should not begin until the user approves the roadmap and resolves or accepts the open planning decisions in:

`C:\TradingbotR1000\docs\Planning_Decisions_Required.md`
