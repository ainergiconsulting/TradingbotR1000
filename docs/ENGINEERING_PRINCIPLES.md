# TradingbotR1000 Engineering Principles

Date introduced: 2026-07-24

## Bulk Processing Principle

TradingbotR1000 is expected to grow to millions of historical records and repeated large-scale analyses. Codex reasoning must therefore be used primarily for:

- architecture;
- algorithm design;
- code review;
- implementation planning;
- interpretation of results;
- debugging;
- decision making.

Bulk data processing must not be performed directly through Codex reasoning whenever it can reasonably be automated.

Whenever an operation involves processing more than a small number of files, securities, historical records, simulations, reports, validation checks, or database updates, it must be implemented as reusable Python code.

Examples include:

- reading or validating hundreds or thousands of CSV files;
- historical data correction;
- corporate-action processing;
- indicator rebuilding;
- dataset generation;
- feature engineering;
- backtests;
- statistical analysis;
- report generation;
- consistency checks;
- database updates.

## Preferred Workflow

The preferred workflow is:

1. Design the algorithm.
2. Implement it as reusable Python modules or scripts.
3. Execute the Python code.
4. Validate the output.
5. Use Codex reasoning only to analyse the results and determine the next engineering step.

Codex must not be used as the large-scale data-processing engine.

## Project Organization

Reusable scripts must be organised consistently inside the project structure, documented, and accompanied by validation tests whenever appropriate.

For Program A and Program B work:

- production runtime code remains isolated from research and data-correction tooling;
- one-time or offline tooling belongs under `tools`, `analytics`, `backtests`, or a clearly named project subpackage;
- generated data-quality evidence belongs under `data/validation` or `ibkr_r1000_results` depending on whether it is data-validation output or operational output;
- permanent design and milestone reports belong under `docs`;
- bulk outputs must be machine-readable first, with human-readable summaries generated from those outputs.

## Runtime Boundary

Data-correction, research and analysis tooling must not change production runtime behavior unless a later phase explicitly authorizes a controlled production integration.
