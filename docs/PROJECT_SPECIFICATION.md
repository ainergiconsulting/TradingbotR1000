# TradingbotR1000 Project Specification

Date: 2026-07-21

## Authority

The only authoritative source for the TradingbotR1000 trading strategy is:

```text
docs/TradingbotR1000_Strategy_Specification_FINAL_v1.1.docx
```

The Tradingbot2607 architecture is the implementation reference. TradingbotR1000 should reuse that architecture as much as possible and adapt existing layers only where required to implement the approved Russell 1000 mean-reversion strategy.

This specification does not add, revise, or optimize trading rules.

## Strategy Scope

TradingbotR1000 implements a daily, long-only mean-reversion strategy on Russell 1000 stocks.

Source-defined strategy rules:

- Universe: Russell 1000 stocks.
- Timeframe: daily bars.
- Total account equity: IBKR Net Liquidation Value (NLV).
- Investable capital: 70% of NLV.
- Liquidity reserve: 30% of NLV, reserved only to support temporary position replacement operations and not to increase overall exposure.
- Position allocation: 20% of investable capital per position.
- Maximum positions: 5 simultaneous positions.
- Leverage: none.
- Entry trend filter: completed daily close above the 200-day moving average; the source example uses SMA(200).
- Entry pullback filter: completed daily close below the lower Bollinger Band.
- Bollinger settings: 20 trading days, 2.5 standard deviations.
- Entry order: BUY limit at `signal-day close * 0.97`, intended for the next trading day.
- Ranking: only when valid candidates exceed available slots; prioritize greatest 150-trading-day price appreciation.
- Exit: after fill, close at the next market opening when RSI(2) crosses above 50.
- Time exit: close after 10 trading days if RSI(2) has not crossed above 50.

Explicit non-strategy items from the approved document:

- No requirement for 10 consecutive days in the ranking.
- No source-defined requirement to use adjusted prices, IWB holdings, a specific data provider, a specific order time-in-force, or a specific broker order type.
- No additional entry, volatility, liquidity, or market-regime filters.

## Reused Architecture

TradingbotR1000 should keep the Tradingbot2607 architecture shape:

```text
Owner controls
  -> Local start/stop launchers
  -> Operational controller
  -> Health supervisor and runtime status
  -> Trading engine
  -> Strategy layer
  -> Order safety and IBKR integration
  -> IBKR account
  -> Reconciliation, reporting, analytics, and Telegram monitoring
```

The goal is architectural continuity, not a new platform design.

## Components To Reuse With Minimal Change

- Project governance: docs, changelog/status style, restore discipline, release evidence, and paper-validation workflow.
- Local operator controls: explicit owner start/stop, no automatic trading after reboot/logon, desktop launcher model.
- Operational controller: boot-session authorization, desired-running state, bounded restart, manual-intervention lockout.
- Health supervisor: heartbeat freshness, machine-readable health files, visible fail-closed status.
- Gateway/API readiness model: keep the layered readiness checks before trading is allowed.
- IBKR integration layer: reuse connection, account, position, contract, open-order, and request-timeout patterns.
- Order-safety layer: keep long-only, no-leverage, duplicate-order prevention, broker-evidence refresh, and rejection-reason patterns.
- Telegram monitoring: keep read-only operational status, health, portfolio, execution, and reconciliation visibility.
- Reconciliation and reporting architecture: keep broker-authoritative evidence, execution/fill reconciliation, and audit outputs.
- Standalone analytics separation: analytics must remain independent from trading runtime and must not affect orders.
- Secret handling: keep tokens, credentials, local runtime state, logs, and generated reports outside source control.
- Test discipline: preserve release-scoped tests for safety, controller, IBKR integration, Telegram, reconciliation, and strategy behavior.

## Components That Must Be Adapted

### Strategy Layer

Replace the Tradingbot2607 trailing-sell/rebuy strategy logic with the approved R1000 rules:

- daily Russell 1000 scan;
- SMA(200) trend condition;
- Bollinger pullback condition;
- BUY limit at 97% of signal-day close;
- 150-trading-day appreciation ranking only when slots are scarce;
- RSI(2) cross-above-50 exit;
- 10-trading-day maximum holding period.

No extra filters or ranking persistence may be added.

### Universe Handling

Adapt symbol management from a small active-position/watchlist model to a Russell 1000 universe model.

The strategy authority defines the universe as Russell 1000 stocks but does not define a specific constituent source. The project must therefore support a configurable Russell 1000 universe source without treating any provider choice as a trading rule.

Current implementation source: the repository-root `IWB_holdings.csv` file is the configured local Russell 1000 universe input. This is an implementation source choice, not a strategy rule.

### Market Data Layer

Adapt data loading to support daily bars across the Russell 1000 universe.

The strategy authority does not require adjusted prices or any specific provider. The data layer must supply the values needed for the approved daily-bar calculations without changing the strategy rules.

### Candidate Selection

Add a daily candidate-selection pipeline inside the existing strategy/engine boundary:

- evaluate completed daily-bar entry conditions;
- determine available portfolio slots;
- rank only when candidates exceed slots;
- select highest 150-day appreciation candidates.

Implementation detail: if two or more otherwise valid candidates have identical
150-trading-day price appreciation at the portfolio-slot cutoff, sort those tied
candidates by ticker symbol ascending. This tie-breaker is used only to keep
execution deterministic and auditable; it is not an additional trading filter or
strategy ranking factor.

### Order Planning

Adapt the order planner to support:

- next-trading-day BUY limit orders at 97% of signal-day close;
- position size equal to 20% of investable capital, where investable capital is 70% of NLV;
- 30% NLV liquidity reserve that must not increase total portfolio exposure;
- maximum five simultaneous positions;
- exit-at-next-open behavior after RSI signal;
- time exit after 10 trading days.

The broker-specific implementation must not reinterpret the approved strategy as requiring a specific order type or time-in-force where the approved document does not define one.

### Automated PAPER Execution Schedule

Automated PAPER execution is disabled by default and requires the explicit environment switch `TRADINGBOTR1000_ENABLE_AUTOMATED_PAPER_EXECUTION=1`.

The approved `run/start_trading_system.bat` launcher sets this switch for the
R1000 background runtime. Direct Python/module execution remains disabled unless
the same switch is supplied explicitly in that process environment.

The operational controller evaluates one automated strategy cycle per eligible US trading day at `09:35 America/New_York`. This time is an implementation scheduling choice for submitting next-trading-day entry orders and next-open exit orders after the US market has opened; it is not an additional strategy rule. Broker transmission remains gated by live IBKR market-hours and liquid-hours evidence and is refused outside liquid hours. The controller records the last completed cycle date to prevent repeated entry cycles for the same trading day.

Eligible sessions are weekdays excluding the standard US equity-market holidays
recognized by the local scheduler, including observed fixed-date holidays and
Good Friday.

### Investable Capital Control

Control Console option 13 manages the operational investable-capital mode.

- `AUTO`: effective investable capital is 70% of the current live IBKR NLV.
- `MANUAL`: effective investable capital is the operator-defined fixed USD amount.

The setting is persisted in `current_reference/PaperTradingR1000/state/investable_capital_control.json`.
At every strategy cycle, the runtime validates a manual amount against the latest
live NLV. If the manual amount exceeds live NLV, new BUY submissions are blocked
and logged as a compliance failure; valid SELL processing remains available
where the broker/account state allows it.

### First Three Automated Sessions Monitoring

When automated PAPER execution is enabled, the runtime records enhanced quality
evidence for the first three eligible US trading sessions that run a strategy
cycle. Evidence is written under
`current_reference/PaperTradingR1000/reports/quality_monitoring/` as per-cycle
JSON and readable per-session Markdown reports. The reports compare strategy
decision, planned order, submitted order, broker result, and reconciled portfolio
state without adding trading rules or changing order behavior.

### State Model

Extend state tracking to include:

- daily candidate evaluations;
- selected candidates;
- pending BUY orders;
- partially filled BUY orders, counted as one reserved position slot when the same symbol is both active and still pending;
- filled entry date;
- holding-day count;
- RSI exit state;
- time-exit state;
- active position count.

### Configuration

Adapt configuration to expose only implementation parameters needed to execute the approved strategy safely:

- universe source configuration;
- data source configuration;
- broker/environment settings;
- schedule/timing settings;
- account and paper/live safety settings;
- logging/reporting paths.

Strategy constants from the approved document should remain explicit and versioned.

### Reporting And Reconciliation

Extend existing reporting/reconciliation outputs to show:

- daily scan results;
- candidate ranking;
- selected and skipped candidates;
- entry order/fill outcomes;
- exit reason: RSI exit or time exit;
- holding period;
- slot usage;
- capital allocation;
- reconciliation status.

### Tests

Adapt tests to prove the approved strategy behavior without adding extra rules:

- completed daily-bar entry criteria;
- Bollinger settings;
- 97% BUY limit calculation;
- ranking only when candidates exceed slots;
- 70% investable-capital calculation from NLV;
- 30% liquidity reserve reporting;
- 20% of investable capital allocation;
- five-position maximum;
- RSI(2) crossing logic;
- next-open exit scheduling;
- 10-trading-day time exit;
- no leverage and no short orders.

## Implementation Boundaries

Do not copy Tradingbot2607 strategy behavior that conflicts with the approved R1000 strategy.

Do not add:

- 10-day ranking persistence;
- independent position sizing rules that bypass the 70% investable-capital and 20%-of-investable-capital sequence;
- use of the 30% liquidity reserve to increase overall exposure;
- IWB holdings as a strategy requirement;
- adjusted-price requirement;
- specific broker order type or time-in-force as a strategy rule;
- volatility, liquidity, regime, sector, stop-loss, or optimization filters.

Any future operational choice that is not strategy-defined must be documented as an implementation choice, not as a trading rule.

## Recommended Project Shape

Keep the Tradingbot2607 folder model:

```text
config/
docs/
run/
tests/
current_reference/
current_reference/PaperTradingR1000/
current_reference/PaperTradingR1000/config_files/
current_reference/PaperTradingR1000/state/
current_reference/PaperTradingR1000/logs/
current_reference/PaperTradingR1000/reports/
analytics/
```

The exact module names may differ, but the layer responsibilities should remain aligned with Tradingbot2607.
