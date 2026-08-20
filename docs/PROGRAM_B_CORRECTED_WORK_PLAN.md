# Program B - Corrected Scientific Research Work Plan

Last updated: 2026-07-24

## Purpose

Program B is a scientific research programme. Its objective is to determine under which observable market conditions the approved R1000 strategy generates alpha, when the strategy is structurally weak, and whether the evidence supports normal operation, alternate already-tested settings, reduced exposure, or inactivity.

Program B does not modify the production trading system. Any production parameter change, filter, exposure rule, or deployment remains outside this phase and requires explicit approval.

## Source Plan And Refinement

This work plan supersedes the operational interpretation of `Program_B_Strategy_Optimization_and_Market_Regime_Plan.docx` while preserving its executable research structure.

The original working plan emphasized parameter optimization. The refined objective is narrower and more diagnostic:

1. Explain why the strategy was negative in 2019 but positive in 2021.
2. Identify the market-state variables that best explain performance.
3. Determine whether existing tested configurations behave differently under those conditions.
4. Decide whether evidence supports normal parameters, alternate tested parameters, reduced exposure, inactivity, or future research into a different strategy.

## Inputs

- Existing local Massive daily OHLCV files.
- Current approved TradingbotR1000 strategy implementation and configurable parameters.
- Existing corrected max-positions backtest outputs.
- Existing entry-limit, holding-period, RSI sensitivity, RSI robustness and trade-distribution outputs.
- Phase A3 Security Master exports and validation outputs.

## Exclusions And Limitations

The phase does not require or collect:

- VIX, macroeconomic, options, factor, sentiment or news data.
- Historical point-in-time Russell 1000 membership.
- External data downloads.
- New production runtime behavior.
- RSI optimization reruns unless a concrete defect is found.

Known limitations must remain explicit in all conclusions:

- Current-universe survivorship bias.
- No historical Russell 1000 membership by date.
- No dividend-adjusted return series in the current local bars.
- Corporate-action correction work remains in Program A and has not yet produced a promoted corrected dataset.

## Security Master Treatment

The Phase A3 Security Master is used as the authoritative security inventory for Program B universe validation.

The following symbols are quarantined or excluded from Program B analysis:

- HLT
- HEI.A
- DD
- HEI
- CGNX
- APLD
- HOLX
- NSA

These symbols must not block the remaining analysis. They are reported separately wherever they appear in previously completed backtest outputs.

## Execution Sequence

1. Build a validated Program B analysis universe from the Security Master and local OHLCV files.
2. Generate a daily market-state dataset from local OHLCV data only.
3. Reconstruct or rerun the baseline strategy only where required to apply Security Master quarantine consistently.
4. Confirm the 2019 negative and 2021 positive contrast.
5. Attach entry-time market-state variables to baseline trades.
6. Analyse conditional performance by trend, volatility, breadth, dispersion, drawdown and strategy opportunity variables.
7. Reuse completed non-RSI sensitivity studies for parameter-by-condition comparisons.
8. Validate candidate operating rules by subperiods, 2019, 2021, rolling windows and exclusion of strongest and weakest years.
9. Produce a final decision report and machine-readable summary.

## Decision Standard

No rule is acceptable unless it is:

- Observable using local data available at or before the strategy decision date.
- Simple enough to operate and audit.
- Supported by adequate sample size.
- Stable across subperiods and not dependent on a single year.
- Beneficial after considering risk, drawdown, trade count and capital utilisation.

If evidence is ambiguous, the correct decision is to keep the approved baseline unchanged and collect more evidence after Program A corrected data promotion.

