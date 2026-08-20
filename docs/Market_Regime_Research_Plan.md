# TradingbotR1000 Market Regime Research Plan

Date: 2026-07-24

Scope: research plan only. No strategy parameter, production runtime, or automated trading behavior is changed by this document.

## Objective

Determine which market conditions explain TradingbotR1000 performance, drawdown, idle capital, trade frequency, and signal quality. The next research goal is not to optimize another single parameter, but to build a scientific basis for understanding when the approved strategy generates alpha and when it should reduce exposure or remain inactive.

## Current Research Baselines

Production baseline:

- `max_positions = 5`
- entry limit = 97%
- RSI exit threshold = 50
- maximum holding period = 10 trading days
- dynamic sizing based on current NLV
- no leverage and no negative cash

Research baseline:

- Same as production baseline except RSI exit threshold = 60.

Production remains RSI > 50 until the approved Strategy Specification is changed explicitly.

## Why Regime Research Is Next

Completed research established:

- max-position increases did not improve the baseline;
- idle capital was not primarily caused by insufficient cash;
- looser entry prices increased fills but weakened portfolio performance;
- the holding-period parameter is active but rarely dominant;
- RSI exit behavior is the dominant exit mechanism;
- RSI > 60 appears more robust than RSI > 50 in historical research;
- RSI > 60 improvement is explained mainly by larger winners and slightly longer rebound capture.

The missing question is whether those findings are stable across market regimes or concentrated in favorable conditions.

## Programme Boundary

Program B - Scientific Research is independent from Program A - Production & Data Integrity. It may consume corrected, validated datasets produced by Program A, but it must not modify production configuration, trading rules, order submission, runtime state, launchers, or scheduled tasks.

## Research Questions

1. Which observable market-state variables explain strategy performance?
2. Are drawdowns concentrated around specific market-state conditions?
3. Are BUY signals more frequent, more profitable, or more fillable in specific conditions?
4. Is idle capital caused by market-state conditions rather than parameter settings?
5. Does RSI > 60 improve the same conditions as RSI > 50, or does it merely shift exposure?
6. Can future regime definitions be developed from evidence rather than imposed upfront?
7. Could a future activation framework reduce risk without overfitting?

## Data Requirements

Minimum inputs:

- Corrected split-adjusted daily OHLCV for the current R1000 universe.
- Raw OHLCV preserved for audit.
- Dividend data if total-return analysis is performed.
- Daily market calendar.
- Daily portfolio and trade logs from existing corrected backtests.
- Security Master mapping current symbols, historical symbols, Massive symbols, and IBKR contract identity.

Preferred inputs:

- Point-in-time IWB holdings if available through an entitled source.
- Historical benchmark series for IWB, Russell 1000, SPY, QQQ, and possibly VIX.
- Sector and industry classifications with effective dates.
- Corporate-action event history.
- Delisted/renamed predecessor data where technically valid.

Do not assume missing membership, delisting, dividend, or corporate-action data. If unavailable, mark the analysis as limited.

## Market-State Feature Set

The first Program B deliverable is a comprehensive daily market-state dataset. Bull, bear, sideways, or other regime definitions must not be hardcoded before this dataset has been analysed.

### Trend Features

- Broad-market 50-day and 200-day moving-average state.
- Broad-market 20-day, 60-day, and 120-day returns.
- Percentage of universe symbols above their 50-day moving average.
- Percentage of universe symbols above their 200-day moving average.

### Volatility Features

- Broad-market realized volatility over 20 and 60 trading days.
- Universe median realized volatility.
- Cross-sectional volatility dispersion.
- VIX level and VIX percentile if a validated local history is available.

### Breadth Features

- Percentage of symbols with positive 20-day return.
- Percentage of symbols with positive 60-day return.
- Equal-weight universe return versus capitalization-weighted proxy if data permits.
- New-high/new-low proxy if enough history is available.

### Dispersion And Correlation Features

- Cross-sectional return dispersion.
- Average pairwise correlation sample if computationally practical.
- Sector dispersion if sector data is available.

### Momentum Features

- Broad-market 5-day, 20-day, 60-day, 120-day, and 252-day returns.
- Equal-weight universe momentum distribution.
- Median and percentile symbol momentum.

### Drawdown Features

- Broad-market drawdown from rolling peak.
- Equal-weight universe proxy drawdown.
- Count and percentage of symbols in 10%, 20%, and 30% drawdowns.

### Market Concentration Features

- IWB top-10 weight concentration when holdings weights are available.
- Sector concentration where sector data is available.
- Cross-sectional contribution concentration.

### Liquidity And Opportunity Features

- Average daily dollar volume.
- Count of symbols eligible for strategy calculation.
- Count of daily BUY signals.
- Count of daily missed BUY signals due to 97% limit not filled.
- Count of symbols excluded for stale, insufficient, or invalid data.
- Portfolio capital utilization.
- Unused capital.
- Available slots.
- Number of qualifying opportunities versus available slots.
- Any other market-state variable later justified by evidence.

## Regime Definition Policy

Do not immediately define bull/bear regimes.

The sequence must be:

1. Build the daily market-state dataset.
2. Validate feature quality and no-look-ahead construction.
3. Analyse distributions, correlations, clusters, and relationships with strategy outcomes.
4. Propose candidate regime definitions only after evidence has been reviewed.
5. Validate candidate regimes across chronological subperiods and rolling windows.

All rolling values must be computed using information available up to that date only. No future data can be used to label a trading day for an out-of-sample or activation-style test.

## Methodology

1. Build market-state features from local corrected data after the data-integrity phase.
2. Validate no look-ahead leakage in feature construction.
3. Join daily market-state observations to existing portfolio daily results for production baseline and RSI > 60 research baseline.
4. Analyse relationships between market-state features and:
   - daily return;
   - annualized return;
   - volatility;
   - Sharpe;
   - Sortino where available;
   - maximum drawdown;
   - win rate;
   - profit factor;
   - trade count;
   - average trade return;
   - capital utilization;
   - BUY signal count;
   - missed-entry count.
5. Develop candidate regime definitions only after feature analysis.
6. Compare RSI > 50 and RSI > 60 by candidate regime.
7. Run chronological subperiod checks for every regime conclusion.
8. Mark results unreliable when sample size is too small.

## Robustness Requirements

Each market-state or regime finding must report:

- number of trading days;
- number of completed trades;
- number of BUY fills;
- number of SELL fills;
- average exposure;
- whether results are dominated by top trades;
- whether the finding persists across first half, second half, and rolling windows where enough data exists.

## Activation Research Framework

This phase should not implement a live activation engine. It may evaluate a hypothetical framework with clearly labelled research-only states:

- Full operation.
- Reduced new BUY activity.
- No new BUY entries.
- Monitoring and SELL-only mode.

Any future production activation rule must require a separate approved Strategy Specification change.

## Expected Outputs

Create a timestamped run directory under:

`C:\TradingbotR1000\backtests\r1000_max_positions_corrected\strategy_analysis\market_regime_analysis`

Expected files:

- `market_state_features.csv`
- `market_state_feature_quality.csv`
- `market_state_strategy_join.csv`
- `market_state_relationships.csv`
- `candidate_regime_definitions.csv`, only after analysis supports them
- `regime_performance_summary.csv`
- `regime_trade_metrics.csv`
- `regime_exposure_metrics.csv`
- `regime_signal_quality.csv`
- `regime_robustness_checks.csv`
- `validation_summary.md`
- `experiment_report.md`

After completion, update:

- `Strategy_Research_Journal.md`
- `Research_Master_Plan.md`
- `Experiment_Registry.csv`
- `Strategy_Analysis_Report.md`

## Acceptance Criteria

The market-regime study is acceptable only if:

1. Data-adjustment policy has been documented.
2. No production files are modified.
3. No bull/bear or other regime definitions are imposed before feature analysis.
4. Regime labels, once proposed, are reproducible and use no future data.
5. Each conclusion includes sample size and limitation notes.
6. Production RSI > 50 and research RSI > 60 are both analysed.
7. Any activation concept remains research-only.

## Known Limitations To Carry Forward

- Current universe bias remains unless point-in-time historical membership is obtained.
- Delisting bias remains unless delisted constituents and terminal returns are added.
- Corporate-action bias remains until split and dividend data are integrated.
- Sector-regime analysis is limited unless dated classifications are available.
- Paper-trading fill behavior cannot prove live execution quality.
