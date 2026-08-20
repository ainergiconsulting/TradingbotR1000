# TradingbotR1000 Implementation Roadmap

Date: 2026-07-24

Scope: executable plan for approval. This roadmap does not authorize production behavior changes by itself.

## Guiding Rules

1. The Strategy Specification v1.1 remains the single source of truth for live strategy behavior.
2. Production trading must remain operational while data and research work proceeds.
3. Tradingbot2607-derived architecture should be reused; do not create duplicate controllers, consoles, state stores, or trading engines.
4. Data changes must preserve raw source files and use atomic promotion.
5. Runtime changes must be introduced in shadow mode before becoming authoritative.
6. Any live-trading behavior change requires explicit approval.

## Programmes

### Program A - Production & Data Integrity

Objective: build a robust, autonomous, production-ready trading system.

Scope:

- daily IWB holdings acquisition and dated snapshots;
- additions/removals detection;
- central Security Master;
- IBKR contract resolution;
- IBKR daily OHLCV updates after migration;
- minimum warm-up history for genuinely new IWB constituents only;
- broker snapshot, runtime state, reconciliation, reporting, Control Console, and Telegram continuity;
- data-quality validation and rejection of corrupted data.

Massive is not a permanent production dependency. The existing approximately ten-year historical database has already been downloaded and must not be replaced or re-downloaded. Massive may be used only during the initial historical correction phase for corporate actions, historical-dataset validation, split adjustments, and dividend-adjustment evaluation.

### Program B - Scientific Research

Objective: determine under which market conditions the strategy generates alpha and when it should reduce exposure or remain inactive.

Scope:

- corrected historical research datasets;
- comprehensive daily market-state dataset;
- conditional performance analysis;
- robustness validation;
- research-only activation framework;
- future strategy-change proposals only after explicit approval.

Program B must not modify production trading behavior.

### Deferred Historical Membership

Point-in-time historical Russell 1000 membership remains deferred. The architecture must preserve room for dated membership records later, but the next implementation phase should not attempt to reconstruct historical index membership.

## Phase Roadmap

### Phase 0 - Baseline Audit And Planning

Status: planned by this document.

Objective:

Document current architecture, data flow, research state, risks, and next-phase decisions.

Deliverables:

- `docs/Current_State_Audit.md`
- `docs/Data_Integrity_and_Universe_Plan.md`
- `docs/Market_Regime_Research_Plan.md`
- `docs/Implementation_Roadmap.md`
- `docs/Planning_Decisions_Required.md`

Acceptance:

- Planning documents exist.
- Research journal and registry reference this phase.
- No production behavior changed.

### Phase A1 - Backup, Baseline Hashes, And Progress Tracker

Objective:

Create reproducible pre-change evidence before modifying runtime or data pipelines.

Likely actions after approval:

- Record hashes for key strategy, runtime, config, and research files.
- Snapshot current runtime reports and state metadata.
- Record current data row counts and validation summaries.
- Add a continuously updated progress tracker covering both programmes.

Validation:

- Hash report generated.
- Working tree changes limited to approved planning/evidence files.
- Production launchers unchanged.

Rollback:

- No runtime rollback should be needed; evidence-only phase.

### Phase A2 - One-Time Massive Historical Correction Inputs

Objective:

Add a separate one-time corporate-action and reference-data collection workflow for historical correction only.

Current status:

Paused before full current-universe collection. Phase A2.5 must be completed and accepted before the full collection continues.

Likely files:

- New tool under `C:\TradingbotR1000\tools`
- Raw output under `C:\TradingbotR1000\data\source\massive`
- Validation report under `C:\TradingbotR1000\ibkr_r1000_results` or `C:\TradingbotR1000\data\validation`

Dependencies:

- Massive API key available.
- Subscription entitlement confirmed for required endpoints.
- Existing ten-year historical dataset already present.

Validation:

- Run on a small sample first.
- Confirm pagination, retries, rate-limit handling, checkpointing, and no overwrite of valid raw data.
- Validate known split examples against local price discontinuities.
- Confirm the workflow does not re-download the complete OHLCV history.

Rollback:

- Disable the one-time tool; raw historical bars remain untouched. No recurring Massive job is created.

### Phase A2.5 - Historical Data Correction Design

Objective:

Define the correction design before full corporate-action collection and historical adjustment work proceeds.

Design document:

`C:\TradingbotR1000\docs\Phase_A2_5_Historical_Data_Correction_Design.md`

Scope:

- corporate-action storage;
- versioning strategy;
- raw historical data preservation;
- corrected dataset generation;
- prevention of double adjustment;
- volume adjustment policy;
- indicator rebuild process;
- validation methodology;
- rollback strategy;
- exact meaning and algorithm for validating historical bars against corporate actions.

Dependencies:

- Phase A2 collector sample validation complete.
- Full A2 collection paused.

Validation:

- Design document exists and covers all required topics.
- Progress tracker separates planning completion from implementation completion.
- No production runtime files changed.

Rollback:

- Documentation-only phase; no runtime rollback required.

### Phase A3 - Security Master

Objective:

Create a central Security Master with a permanent internal Canonical Security ID and make existing symbol normalization a facade over it.

Likely files:

- `data/security_master/security_master.sqlite3`
- `data/security_master/security_master_export.csv`
- `current_reference/PaperTradingR1000/symbol_mapping.py`
- `tools/validate_symbol_compatibility.py`

Dependencies:

- Current IWB universe.
- Initial Massive ticker/reference data where available.
- Existing IBKR validation output.

Validation:

- Every current IWB symbol resolves to exactly one Security Master row.
- Every tradable symbol has a verified IBKR stock contract or explicit exclusion.
- All external identifiers are attributes of the Canonical Security ID, not primary identifiers.
- Existing six share-class mappings remain represented.
- `HOLX` and `NSA` remain safely excluded unless confirmed resolved.

Rollback:

- Runtime continues using existing static `symbol_mapping.py` until shadow mode passes.

### Phase A4 - Daily IWB Universe Update

Objective:

Create an automated but safe daily holdings update workflow.

Likely files:

- New tool under `tools`
- Versioned holdings snapshots under `data/source/iwb_holdings`
- Universe delta report under `reports` or `data/validation`
- Runtime universe view generated from the Security Master

Dependencies:

- Approved holdings provider and access method.
- Security Master phase complete.

Validation:

- Schema checks.
- Date checks.
- Row-count sanity checks.
- Added/removed/security-change report.
- No promotion if unresolved symbols exist without approved exclusions.

Rollback:

- Keep last validated universe snapshot active.

### Phase A5 - IBKR Daily OHLCV Update Workflow

Objective:

Create the post-migration daily OHLCV update path using IBKR only.

Likely files:

- New or adapted data-update tool under `tools` or `current_reference\PaperTradingR1000`
- Daily update logs under existing report/log locations
- Validation reports under `data\validation`

Dependencies:

- Security Master complete.
- Daily IWB update complete.

Validation:

- Updates only missing recent bars for active securities.
- Requests minimum warm-up history only for genuinely new IWB constituents not already present locally.
- Does not re-download the existing ten-year database from IBKR.
- Rejects corrupted bars automatically.
- Preserves existing valid historical data.

Rollback:

- Continue using last validated local bar files.

### Phase A6 - Adjusted Historical Dataset Builder

Objective:

Build derived split-adjusted and dividend-aware research datasets without altering raw data or creating a recurring Massive dependency.

Likely files:

- New tool under `backtests/r1000_max_positions_corrected` or `tools`
- Processed datasets under `data\processed`
- Validation reports under `data\validation`

Dependencies:

- Corporate-action ingestion complete.
- Historical correction design accepted.
- Security Master complete.

Validation:

- Raw files unchanged.
- Adjusted files reproducible from raw bars plus corporate actions.
- Split examples validate against Massive adjusted factors.
- Indicators and returns use the intended dataset explicitly.
- The historical OHLCV database is corrected in place only through controlled derived outputs, not replaced or broadly re-downloaded.

Rollback:

- Research runners can continue using current `data/daily_bars` until the adjusted dataset is approved.

### Phase A7 - Production Shadow Integration

Objective:

Run production scan logic against the new Security Master and validated data layer in shadow mode.

Likely files:

- `trading_engine.py`
- `automated_broker.py`
- `reconciliation.py`
- `config_loader.py`
- `symbol_mapping.py`
- runtime reports

Dependencies:

- Phases 3 to 5 complete.

Validation:

- Compare old and new universe membership.
- Compare signal eligibility.
- Compare order-plan identities.
- Confirm automated broker uses validated IBKR contract identity.
- Confirm Control Console and Telegram show the same security identity and exclusions.

Rollback:

- Keep current production path active until explicitly switched.

### Phase A8 - Controlled Production Data Switch

Objective:

Switch production from ticker-only mapping to the Security Master-backed runtime view after successful shadow validation.

Approval required:

Yes. This phase changes production runtime behavior.

Validation:

- Dry-run cycle with broker transmission blocked.
- Duplicate-prevention check.
- Reconciliation check.
- Console and Telegram status check.

Rollback:

- Revert runtime configuration to previous universe source and ticker mapping facade.

### Phase B1 - Market-State Dataset Build

Objective:

Build a comprehensive daily market-state dataset from corrected research data. Do not define bull/bear or other regimes yet.

Likely files:

- New research script under `backtests/r1000_max_positions_corrected`
- Outputs under `strategy_analysis\market_regime_analysis`

Dependencies:

- Adjusted historical dataset approved for research.

Validation:

- No look-ahead leakage.
- Market-state variables use only information available as of each date.
- Missing benchmark or VIX data is reported rather than filled silently.
- No regime definitions are hardcoded in this phase.

Rollback:

- Research-only phase; no production impact.

### Phase B2 - Market-State Analysis And Regime Discovery

Objective:

Analyse the market-state dataset and develop candidate regime definitions only after the state variables have been inspected.

Dependencies:

- Phase B1 complete.
- Existing corrected backtest outputs available.

Validation:

- Every candidate regime definition includes sample size and construction logic.
- Full-period totals reconcile to validated backtest outputs.
- Small-sample regimes are flagged.

Rollback:

- Research-only phase.

### Phase B3 - Conditional Performance Analysis

Objective:

Analyse strategy performance by discovered market regime for production RSI > 50 and research RSI > 60.

Dependencies:

- Phase B2 complete.

Validation:

- Every regime result includes sample size.
- Full-period totals reconcile to validated backtest outputs.
- Small-sample regimes are flagged.

Rollback:

- Research-only phase.

### Phase B4 - Robustness And Out-of-Sample Checks

Objective:

Validate regime findings across chronological subperiods, rolling windows, and sensitivity checks.

Dependencies:

- Phase B3 complete.

Validation:

- No production changes.
- Regime findings remain marked as research evidence, not trading rules.

Rollback:

- Research-only phase.

### Phase B5 - Research Activation Framework

Objective:

Evaluate research-only activation modes such as full operation, reduced new BUY activity, no new BUY entries, and monitoring/SELL-only mode.

Approval required:

Yes before any production implementation.

Validation:

- Activation logic is simulated only.
- Strategy Specification remains unchanged.
- No live trading behavior changes.

Rollback:

- Research-only phase until separately approved.

### Phase B6 - Production Change Proposal

Objective:

If evidence justifies it, prepare a formal change proposal for strategy specification and production runtime updates.

Approval required:

Yes. This is the only phase that can authorize production strategy changes.

Validation:

- Side-by-side current production vs proposed behavior.
- Risk impact.
- Operational impact.
- Paper-account test plan.
- Rollback plan.

## Progress-Control System For Future Execution

For approved implementation phases, maintain a machine-readable progress file such as:

`C:\TradingbotR1000\docs\PROJECT_PROGRESS.json`

Recommended fields:

- programme;
- phase;
- tasks;
- testing status;
- completed work;
- pending work;
- blockers;
- decisions pending;
- fixed task weight;
- objective weighted completion percentage.

Codex can then resume after interruption without repeating completed steps unnecessarily.

Completion percentage must be computed from registered task weights and task status, not from subjective estimates.

## Stop Conditions For Future Autonomous Work

Future implementation should stop and ask for approval only when:

- a production trading behavior change would occur;
- live order routing behavior would change;
- a destructive or irreversible data operation is required;
- external credentials or paid data entitlements are missing;
- corporate-action evidence conflicts with existing historical data;
- a Security Master mapping is ambiguous;
- a proposed change differs from the Strategy Specification;
- validation fails in a way that risks production safety.

## Recommended Immediate Roadmap

1. Execute Phase A1 safety baseline and progress tracker.
2. Execute Phase A2 one-time Massive historical correction inputs.
3. Execute Phase A3 Security Master.
4. Execute Phase A4 daily IWB universe update.
5. Execute Phase A5 IBKR daily OHLCV update workflow.
6. Execute Phase A6 adjusted research dataset builder.
7. Review shadow validation before any production runtime switch.
8. Begin Program B market-state dataset build only after corrected research data is available.
