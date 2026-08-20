# TradingbotR1000 Data-Readiness Audit for Max-Positions Comparison

Audit date: 2026-07-23

Future analysis objective: compare the approved R1000 strategy using maximum
positions of 5, 8, 10, 15, and 20.

This audit does not implement a backtest.

## 1. Dataset Inventory

Configured runtime universe:

- `C:\TradingbotR1000\current_reference\PaperTradingR1000\config_files\universe_config.json`
- Universe source: `C:\TradingbotR1000\IWB_holdings.csv`
- Daily bars directory: `C:\TradingbotR1000\data\daily_bars`
- Symbol column: `Ticker`

Historical data files found:

| Location | Format | Role | Status |
| --- | --- | --- | --- |
| `C:\TradingbotR1000\data\daily_bars\<SYMBOL>.csv` | One CSV per normalized ticker | Active runtime historical-data source | Primary dataset for this audit |
| `C:\TradingbotR1000\ibkr_r1000_results\historical_bars.massive_checkpoint.csv` | Consolidated CSV | Massive full checkpoint | Complete-looking reference, 1,915,881 rows |
| `C:\TradingbotR1000\ibkr_r1000_results\historical_bars.csv` | Consolidated CSV | Original schema reference | Not a full history, 2,033 rows only |
| `C:\TradingbotR1000\ibkr_r1000_results\historical_bars.massive_checkpoint.csv.tmp` | Partial temp CSV | Interrupted checkpoint write artifact | Do not use for backtesting |
| `C:\TradingbotR1000\ibkr_r1000_results\symbol_compatibility_validation.csv` | CSV | Polygon/Massive to IBKR compatibility evidence | Valid mapping reference |
| `C:\TradingbotR1000\ibkr_r1000_results\massive_resume_progress.json` | JSON | Download progress evidence | Shows `adjusted: false` |

Active universe counts:

- Current IWB equity symbols after local normalization: 1,024.
- Active runtime tradable symbols after validated IBKR exclusions: 1,022.
- IBKR exclusions: `NSA`, `HOLX`.
- Per-symbol bar files in `data\daily_bars`: 1,025.
- Extra bar file not used by active runtime universe: `UHALB.csv`; active canonical file is `UHAL.B.csv`.
- Missing active-runtime bar files: 0.

## 2. Schema And Fields

Every active runtime per-symbol CSV has this schema:

```text
ticker,name,con_id,local_symbol,date,open,high,low,close,volume,bar_count,average
```

Field availability:

| Field | Available | Notes |
| --- | --- | --- |
| open | Yes | Required by next-open exit and execution modelling |
| high | Yes | Useful for daily limit-fill range checks |
| low | Yes | Useful for daily limit-fill range checks |
| close | Yes | Used by approved strategy signals |
| adjusted close | No | No adjusted-close column |
| volume | Yes | Can support approximate dollar-volume calculations |
| dividends | No | No dividend cash-flow data |
| split factors | No | No split-factor data |
| bar count | Yes | Massive aggregate field |
| volume-weighted average | Yes | Massive aggregate field `average` |

Downloader evidence:

- `massive_resume_progress.json` records `adjusted: false`.
- The downloader supports `--adjusted`, but the completed local resume progress
  indicates the current dataset was downloaded as unadjusted aggregates.
- No local file stores dividends, split factors, or adjusted close.

## 3. Coverage Statistics

Active runtime dataset date range:

- First available active-runtime bar date: `20160725`.
- Last available active-runtime bar date: `20260721`.
- All 1,022 active runtime symbols have latest date `20260721`.
- No active symbol is stale relative to the local latest date.

Coverage by completed daily observations:

| Requirement | Symbols | Percentage of 1,022 |
| --- | ---: | ---: |
| At least 200 observations | 1,013 | 99.12% |
| At least 1 year / 252 observations | 1,009 | 98.73% |
| At least 3 years / 756 observations | 955 | 93.44% |
| At least 5 years / 1,260 observations | 908 | 88.85% |
| At least 10 years / 2,520 observations | 0 | 0.00% |
| At least 2,500 observations, near full local range | 755 | 73.87% |

Row-count distribution:

| Percentile | Completed observations |
| --- | ---: |
| Minimum | 11 |
| 1% | 215 |
| 5% | 577 |
| 10% | 1,204 |
| 25% | 2,360 |
| Median | 2,511 |
| 75% | 2,511 |
| 90% | 2,511 |
| 95% | 2,511 |
| 99% | 2,511 |
| Maximum | 2,511 |

Common windows:

| Population | Symbols | Common raw data window | Observed market dates | First possible 200-bar signal date |
| --- | ---: | --- | ---: | --- |
| All active symbols with at least 200 rows | 1,013 | `20251001` to `20260721` | 201 | `20260720` |
| Near-full-history symbols with at least 2,500 rows | 755 | `20160804` to `20260721` | 2,503 | `20170519` |
| Broad current-universe run with per-symbol warmup | 1,022 | `20160725` to `20260721` | variable by symbol | `20170509` earliest |

Interpretation:

- A strict "all ready symbols are eligible from the first day" common period is
  not useful because it effectively begins near the end of the dataset.
- A comparative max-position study can use the same calendar dates for all five
  scenarios if symbols become eligible only after they have the strategy-required
  200 completed closes, matching the live runtime's `insufficient_history`
  behavior.
- A cleaner long-window comparison can be run on the 755 near-full-history
  symbols, but that changes the universe and must not be described as the full
  current R1000 strategy universe.

## 4. Data-Quality Problems By Symbol

Schema, duplicate, invalid-price, invalid-volume, and ordering checks:

- Duplicate rows: 0 active symbols affected.
- Invalid OHLC prices: 0 active symbols affected.
- Invalid volume values: 0 active symbols affected.
- Missing required OHLCV fields: 0 active symbols affected.
- Out-of-order rows: 0 active symbols affected.
- Active symbols stale versus local latest date: 0.

Symbols with fewer than 200 completed observations:

| Symbol | Rows | First date | Last date | Finding |
| --- | ---: | --- | --- | --- |
| MFP | 11 | 20260707 | 20260721 | Insufficient history |
| MBGL | 14 | 20260701 | 20260721 | Insufficient history |
| HONA | 16 | 20260629 | 20260721 | Insufficient history |
| FDXF | 35 | 20260601 | 20260721 | Insufficient history |
| SUNB | 98 | 20260302 | 20260721 | Insufficient history |
| MWH | 110 | 20260211 | 20260721 | Insufficient history |
| FPS | 114 | 20260205 | 20260721 | Insufficient history |
| VSNT | 136 | 20260105 | 20260721 | Insufficient history |
| MDLN | 147 | 20251217 | 20260721 | Insufficient history |

Symbols with observed-market-date gaps or discontinuous segments:

These are not duplicate/invalid-row errors, but they are material for a
long-window backtest because the local data has discontinuities that are not
explained by local ticker-change, merger, acquisition, spin-off, split, or
delisting metadata.

| Symbol | Rows | First | Last | Largest gap |
| --- | ---: | --- | --- | --- |
| XE | 235 | 20161230 | 20260721 | 2,162 observed market dates, 20170914 to 20260424 |
| SGI | 427 | 20160725 | 20260721 | 2,084 observed market dates, 20161031 to 20250218 |
| Q | 510 | 20160725 | 20260721 | 2,001 observed market dates, 20171114 to 20251103 |
| TLN | 603 | 20160725 | 20260721 | 1,908 observed market dates, 20161205 to 20240710 |
| P | 700 | 20160725 | 20260721 | 1,811 observed market dates, 20190131 to 20260417 |
| CCC | 1,149 | 20160725 | 20260721 | 1,194 observed market dates, 20210129 to 20251031 |
| ECHO | 1,363 | 20160725 | 20260721 | 1,148 observed market dates, 20211122 to 20260624 |
| IOT | 1,301 | 20160725 | 20260721 | 1,122 observed market dates, 20170630 to 20211215 |
| SN | 1,393 | 20160725 | 20260721 | 1,118 observed market dates, 20190219 to 20230731 |
| FIG | 1,362 | 20160725 | 20260721 | 1,104 observed market dates, 20171226 to 20220517 |
| CART | 1,466 | 20160725 | 20260721 | 934 observed market dates, 20191231 to 20230919 |
| CAI | 1,617 | 20160725 | 20260721 | 894 observed market dates, 20211122 to 20250618 |
| SNOW | 1,724 | 20160725 | 20260721 | 787 observed market dates, 20170731 to 20200916 |
| WTW | 1,824 | 20160725 | 20260721 | 687 observed market dates, 20190418 to 20220110 |
| SAIL | 1,551 | 20171117 | 20260721 | 626 observed market dates, 20220815 to 20250213 |
| FISV | 1,901 | 20160725 | 20260721 | 610 observed market dates, 20230606 to 20251111 |
| ESI | 1,906 | 20160725 | 20260721 | 605 observed market dates, 20160902 to 20190201 |
| RPRX | 1,915 | 20160725 | 20260721 | 596 observed market dates, 20180131 to 20200616 |
| NIQ | 1,991 | 20160725 | 20260721 | 520 observed market dates, 20230623 to 20250723 |
| AXON | 2,021 | 20160725 | 20260721 | 490 observed market dates, 20190213 to 20210126 |
| DD | 2,073 | 20160725 | 20260721 | 438 observed market dates, 20170831 to 20190603 |
| JAN | 1,300 | 20190911 | 20260721 | 422 observed market dates, 20240712 to 20260320 |
| COR | 2,091 | 20160725 | 20260721 | 420 observed market dates, 20211227 to 20230830 |
| GEN | 2,102 | 20160725 | 20260721 | 409 observed market dates, 20210325 to 20221108 |
| DOW | 2,115 | 20160725 | 20260721 | 396 observed market dates, 20170831 to 20190402 |
| SMCI | 2,162 | 20160725 | 20260721 | 349 observed market dates, 20180822 to 20200114 |
| S | 2,197 | 20160725 | 20260721 | 314 observed market dates, 20200331 to 20210630 |
| HHH | 920 | 20211020 | 20260721 | 270 observed market dates, 20220715 to 20230814 |
| RBC | 2,266 | 20160725 | 20260721 | 245 observed market dates, 20211004 to 20220926 |
| SOLS | 525 | 20211231 | 20260721 | 140 observed market dates, 20250409 to 20251030 |
| META | 1,179 | 20210630 | 20260721 | 90 observed market dates, 20220128 to 20220609 |
| BNY | 2,440 | 20160725 | 20260721 | 71 observed market dates, 20260206 to 20260521 |
| SPCX | 1,356 | 20201216 | 20260721 | 47 observed market dates, 20260406 to 20260612 |
| COHR | 2,464 | 20160725 | 20260721 | 47 observed market dates, 20220630 to 20220908 |
| BMNR | 843 | 20220303 | 20260721 | 13 observed market dates, 20250515 to 20250605 |
| CBC | 275 | 20250310 | 20260721 | 7 observed market dates, 20250312 to 20250324 |
| ALNY | 2,510 | 20160725 | 20260721 | 1 observed market date, 20230912 to 20230914 |
| BIIB | 2,509 | 20160725 | 20260721 | 1 observed market date, 20201105 to 20201109 |
| INSM | 2,510 | 20160725 | 20260721 | 1 observed market date, 20180806 to 20180808 |
| GH | 1,956 | 20181004 | 20260721 | 1 observed market date, 20240522 to 20240524 |
| DOC | 2,510 | 20160725 | 20260721 | 1 observed market date, 20240229 to 20240304 |
| IONS | 2,510 | 20160725 | 20260721 | 1 observed market date, 20180509 to 20180511 |
| SMMT | 2,504 | 20160727 | 20260721 | 1 observed market date, multiple early gaps |

## 5. Ticker Mapping, Corporate Actions, Mergers, And Delistings

Confirmed local ticker-format mappings:

| IWB symbol | Canonical historical symbol | IBKR request/local symbol |
| --- | --- | --- |
| BRKB | BRK.B | BRK B |
| HEIA | HEI.A | HEI A |
| UHALB | UHAL.B | UHAL B |
| BFB | BF.B | BF B |
| BFA | BF.A | BF A |
| LENB | LEN.B | LEN B |

Confirmed runtime exclusions:

| Symbol | Reason |
| --- | --- |
| NSA | `ibkr_value_only_no_smart_or_nyse_stock_contract` |
| HOLX | `ibkr_unresolved_no_market_universe_symbol` |

Corporate-action and history representation:

- The local data does not contain historical ticker-change tables.
- The local data does not contain merger, acquisition, or spin-off event data.
- The local data does not contain delisting records.
- Some files contain severe date discontinuities under the current ticker/name.
  These discontinuities may reflect ticker reuse, corporate events, SPAC history,
  renamed predecessors, downloader symbol semantics, or historical data defects.
  The local files alone do not identify which explanation applies.
- Predecessor histories must not be combined without external corporate-action
  evidence.

## 6. Strategy Fields Available And Missing

Supported directly by local data:

- SMA(200) from daily close.
- Bollinger Band 20-day, 2.5 standard deviation from daily close.
- 150-trading-day appreciation ranking from daily close.
- RSI(2) exit calculation from daily close.
- Next-open exit modelling from daily open.
- BUY limit level from signal-day close.
- Daily high/low range checks for possible next-day limit fills.
- Approximate Average Daily Dollar Volume from close times volume.

Missing:

- Adjusted close.
- Dividend amounts and ex-dividend dates.
- Split factors.
- Historical Russell 1000 membership by date.
- Historical sector/industry classifications.
- Delisting returns.
- Intraday order sequence, quote, spread, and queue data.
- Broker commissions, fees, and exchange fees.
- Executed fills from historical broker simulation.

## 7. Bias And Validity Review

| Bias | Assessment | Severity |
| --- | --- | --- |
| Survivorship bias | Dataset uses a current IWB/R1000 snapshot and does not include historical constituents that left the index. | Material |
| Look-ahead bias | Using today's Russell 1000 constituents across 2016-2026 would use future membership information. | Material |
| Corporate-action bias | Data was downloaded with `adjusted: false` and lacks dividends/splits, so long-horizon returns and signals may be distorted around corporate actions. | Material |
| Delisting bias | Delisted constituents and delisting returns are absent. | Material |
| Stale-price bias | No active symbol is stale versus local latest date, but 43 symbols have date discontinuities and 9 have insufficient history. | Material for affected symbols |
| Missing-data bias | No invalid rows were found, but discontinuous symbols can change candidate/ranking history. | Material |
| Universe-selection bias | IWB current holdings are an implementation source, not historical R1000 membership. | Material |

## 8. Supported And Unsupported Analyses

| Analysis | Classification | Reason |
| --- | --- | --- |
| Strategy signal reconstruction | SUPPORTED WITH LIMITATIONS | Required OHLCV fields exist, but prices are unadjusted and some symbols have discontinuous histories. |
| Comparison of 5/8/10/15/20 positions | SUPPORTED WITH LIMITATIONS | All scenarios can use the same dates and rules, but results are biased by current-universe membership and data gaps. |
| CAGR and annual returns | SUPPORTED WITH LIMITATIONS | Equity curves can be simulated, but total-return accuracy is limited by missing dividends, splits, delistings, commissions, and slippage. |
| Sharpe, Sortino, and volatility | SUPPORTED WITH LIMITATIONS | Daily returns can be computed from simulated equity curves, subject to the same return-quality caveats. |
| Maximum drawdown and Calmar | SUPPORTED WITH LIMITATIONS | Drawdowns can be computed, but corporate-action and survivorship bias remain. |
| Win rate and profit factor | SUPPORTED WITH LIMITATIONS | Trade-level outcomes can be simulated once a fill model is approved. |
| Turnover and transaction count | SUPPORTED WITH LIMITATIONS | Planned/simulated transactions can be counted, but fill assumptions affect results. |
| Next-day execution | SUPPORTED WITH LIMITATIONS | Daily open exists; cannot model opening auction, spread, or queue. |
| Limit-order execution | SUPPORTED WITH LIMITATIONS | Daily high/low can identify possible touches; cannot prove actual fill sequence or queue priority. |
| Commission modelling | NOT SUPPORTED | No local commission/fee schedule or historical commission records are present. |
| Slippage modelling | NOT SUPPORTED | No intraday quote/spread/order-book data is present. |
| Liquidity and Average Daily Dollar Volume | SUPPORTED WITH LIMITATIONS | Close times volume can approximate ADDV; split adjustment and intraday capacity are unavailable. |
| Sector concentration | SUPPORTED WITH LIMITATIONS | Current sector is available for 11 sectors; historical sector changes and industry classifications are absent. |
| Historical-universe reconstruction | NOT SUPPORTED | No historical Russell 1000 membership-by-date data is present. |
| Delisting handling | NOT SUPPORTED | No delisted constituent data or delisting returns are present. |
| Bear-market analysis | SUPPORTED WITH LIMITATIONS | The 2020 and 2022 bear-market periods are inside the range, but survivorship and current-universe bias remain. |

## 9. Realistic Execution Support

Next-day execution:

- Daily open is available.
- The approved strategy's exit-at-next-open can be approximated with next-day
  open.
- Opening-auction availability, gaps, halts, and order priority cannot be
  validated from daily bars.

Limit-order fills:

- Daily high and low allow a conservative "touched or not touched" check.
- Daily bars cannot prove whether a buy limit would have filled before a later
  same-day move, nor whether there was sufficient displayed liquidity at the
  limit.

Commissions and slippage:

- Not present in the local database.
- Any commission or slippage model would require explicit assumptions or
  additional broker/market data.

Liquidity:

- Average Daily Dollar Volume can be approximated using `close * volume`.
- This is not a complete capacity model because no bid/ask, spread, order-book,
  auction, or intraday-volume distribution is available.

## 10. Period Recommendations

Minimum defensible period for an exploratory current-universe comparison:

- `20170509` through `20260721`.
- Requirement: each symbol may only become eligible after it has at least 200
  completed daily closes available before the signal calculation.
- Limitation: current-universe survivorship and look-ahead bias are material.

Recommended common comparison period for the 5/8/10/15/20 analysis:

- `20170519` through `20260721`.
- Run all five max-position scenarios over exactly this same calendar period.
- Enforce the same symbol eligibility mask and the same data-quality exclusions
  across every scenario.
- Exclude or separately quarantine the 43 discontinuous-history symbols unless
  their history is externally validated.

Strict all-symbol common coverage:

- Not recommended.
- Among the 1,013 symbols with at least 200 observations, the common raw window
  starts only at `20251001`, and the first possible 200-bar signal date is
  `20260720`. This is too short for a meaningful comparison.

## 11. Assumptions Required

| Assumption | Acceptability | Comment |
| --- | --- | --- |
| Use current IWB holdings as the Russell 1000 universe for all historical dates | Material | Acceptable only for a current-universe sensitivity study, not an unbiased historical Russell 1000 backtest. |
| Symbols become eligible only after 200 completed closes | Acceptable | Matches the live runtime's insufficient-history behavior. |
| Exclude unresolved IBKR symbols `NSA` and `HOLX` | Acceptable | Matches validated runtime exclusions. |
| Exclude or quarantine the 43 discontinuous-history symbols | Material | Improves data validity but changes the active universe unless handled only until continuity is restored. |
| Use unadjusted OHLCV as downloaded | Material | Acceptable only if the report explicitly states that corporate-action and dividend effects are not handled. |
| Treat next-day open as executable for exits | Material | Reasonable for an approximation, but not a full execution model. |
| Treat buy limit as filled when next-day low is at or below the limit | Material | Common daily-bar approximation, but fill probability and intraday path are unknown. |
| Assume zero commissions | Material | Not acceptable for net-performance claims unless explicitly labelled gross of commissions. |
| Assume zero slippage | Material | Not acceptable for realistic execution claims. |
| Use current sector labels for historical concentration | Material | Acceptable only for approximate current-sector exposure, not historically dated sector analysis. |

## 12. Additional Data Required For Unsupported Analyses

To make unsupported analyses reliable, obtain:

- Historical Russell 1000 membership by effective date, including additions and
  deletions.
- Delisted constituent price history and delisting returns.
- Corporate-action master data: splits, dividends, spin-offs, mergers,
  acquisitions, ticker changes, and effective dates.
- Adjusted OHLCV or total-return price series with clear adjustment convention.
- Historical sector and industry classifications by date.
- Historical IBKR or broker commission and fee schedule.
- Intraday bars or quote/trade data for limit-order fill, slippage, spread, and
  liquidity modelling.
- Historical open/close auction data if opening execution realism is required.

## 13. Final Conclusion

DATA SUFFICIENT WITH MATERIAL LIMITATIONS

The local data is sufficient to reconstruct the approved R1000 signal logic and
to run a controlled comparative study of 5, 8, 10, 15, and 20 maximum positions
over the same calendar period. However, it is not sufficient for a fully
reliable, unbiased historical Russell 1000 backtest because it lacks historical
membership, delisting data, adjusted prices, dividends, split factors, and
historically dated sector/industry data. Execution realism is limited to
daily-bar approximations.
