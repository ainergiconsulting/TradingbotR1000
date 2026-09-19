# TradingBotR1000 - Weekend Early Order Evaluation Plan

Status: IMPLEMENTED AND VERIFIED ON MINIMAL ACCEPTANCE BRANCH
Work window: Saturday 2026-09-19
Target: complete the requested early order evaluation/disclosure without changing the proven broker execution path.

## Scope correction

The original weekend draft proposed a broader PREPARE/EXECUTE redesign. During implementation review the operator clarified the actual requirement:

1. Strategy inputs are completed daily bars from the prior completed US session.
2. Therefore candidate/order evaluation does not need to wait until 09:28 ET.
3. As soon as the 08:30 ET daily-bar refresh completes successfully, the bot should evaluate the planned orders and disclose their details on Telegram.
4. The existing 09:28 strategy cycle and 09:30 broker transmission behavior should otherwise remain unchanged.

The broader execution-path refactor was therefore abandoned and was not promoted to production.

## Implemented minimal flow

08:30 ET daily-bar refresh
-> immediately after successful same-day refresh: early read-only order-plan evaluation
-> persist reports/preopen_preview_report.json
-> Telegram sends planned symbols, BUY/SELL side, planned quantity, order type and LIMIT price where applicable
-> no broker order is sent
-> 09:28 ET regular strategy cycle runs unchanged
-> 09:30 ET existing broker execution path runs unchanged

The early evaluation is informational/operational control evidence. It uses the same strategy engine and same completed bars as the later regular cycle. If account state changes between the early evaluation and 09:28, the regular cycle remains authoritative.

## Safety invariants

- No strategy parameter changed.
- SMA, Bollinger, RSI, ranking, 97% BUY limit, max positions, long-only, no-leverage and DAY TIF remain unchanged.
- strategy_scheduler.py is unchanged.
- automated_broker.py is unchanged.
- automated_order_store.py is unchanged.
- order_safety.py is unchanged.
- The existing execution block in trading_engine.py from the 09:30 wait through process_order_plan/reconciliation is byte-identical to main.
- Early evaluation forces the initial broker connection read-only and returns before wait_until_order_transmission_time() and process_order_plan().
- Canonical production scan/order/execution reports are not overwritten by the early preview.
- A failed early preview does not prevent or replace the existing regular 09:28 strategy cycle.
- The preview is generated once per eligible session after a successful same-day refresh; a mismatched preview/data session is regenerated.

## Operator disclosure

Telegram pre-open alert/status includes:
- signal session;
- selected candidate count;
- every planned BUY/SELL;
- planned quantity calculated from the early account snapshot;
- LIMIT/MARKET order type;
- LIMIT price where applicable;
- Broker submitted: 0;
- explicit statement that the normal 09:28/09:30 cycle remains authoritative.

The planned quantity is an advance estimate. The regular strategy cycle continues to use the then-current account/broker state, exactly as before.

## Verification completed

- Focused preview/controller/Telegram tests passed.
- Expanded operational/support regression suite passed 87/87.
- Full test discovery still reports only the four pre-existing optional backtest/short-strategy setup/import errors; no new runtime failure was introduced.
- Real-data equivalence replay using the Sep-18 completed-bar dataset:
  - baseline: HSIC 82.49, LAD 312.03, PNC 225.05, VZ 46.88;
  - early preview: exactly the same four symbols and LIMIT prices.
- Isolated preview test patched wait_until_order_transmission_time() and process_order_plan() to fail if reached; neither was called.
- Canonical daily_scan_report.json, order_plan.json and automated_execution_report.json hashes remained unchanged by the isolated preview.
- Live PAPER broker state was unchanged before/after preview validation.
- Git diff proves automated_broker.py, automated_order_store.py, order_safety.py and strategy_scheduler.py are identical to main.
- The normal trading_engine execution block is byte-identical to main.

## Acceptance conclusion

A new live order test is not required solely for this change because the broker execution path has not changed. Acceptance is based on proving:
1. the early evaluation produces the same strategy result from the same completed bars;
2. it cannot enter the broker execution path;
3. the existing live broker path is unchanged;
4. Telegram provides the requested advance disclosure.

## Friday 2026-09-18 instruction

No implementation or operational scheduling changes were made on Friday. Weekend work began Saturday 2026-09-19 as requested.
