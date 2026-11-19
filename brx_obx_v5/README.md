# BRX / OBX v5 — Options bias engine (proposed integration)

**Status:** standalone prototype, unvalidated trading performance, alerts only. It is intentionally isolated from the existing R Shiny `stock_analyzer_local_data/` app. Nothing here sends orders, fetches live quotes, or claims that a rule-score is a win probability.

## Scope

- Independent **Monthly, Weekly, Daily, 1m, 3m, 5m, 15m** signed-bias states. No cross-timeframe gating.
- Point-in-time **closed-bar** evidence, **confirmed pivots** (known only after right-hand bars), no future-looking features.
- Independent **reversal monitoring**; a reversal alert never flips the underlying bias.
- ITM / ATM / OTM classification, executable quote gates, Greek availability checks, expiration/settlement cutoffs, **0DTE disabled by default**.
- Contract ranking only when an **external validated pricer** supplies matching base/adverse exit bid scenarios; no invented option P&L.
- No EMA, SMA, MACD, VWAP, ML predictors, or implied backtest accuracy.

## Quick test

At repository root:

```bash
cd brx_obx_v5
python -m unittest discover -s tests -v
```

The module has no third-party Python requirements. Import via `PYTHONPATH=brx_obx_v5` or run tests from `brx_obx_v5`.

## Deployment boundary

These are pure rule evaluators, **not a production market-data integration**. Adapters still required for validated NYSE/Cboe session calendars, point-in-time OHLCV, indices and futures, historic breadth, options NBBO, per-series last trade timestamp/settlement, Greeks, and scenario repricing. Integrate ThetaData only after verifying the subscription endpoints and real quote availability. Do not store API keys in GitHub.

## Data contract

- `Evidence(sign, observed_at, reason)` is known at `observed_at`, and `observed_at <= as_of`. None = unavailable, 0 = valid/neutral.
- `BiasEngine.evaluate(symbol, timeframe, evidence, as_of, closed=...)` returns raw/confirmed bias, status, coverage, score and reasons; a confirmed state is never overwritten by an intrabar provisional result.
- `select_contracts(direction, contracts, scenarios, now, policy)` returns candidates or `NO_TRADE` with explicit reason codes; `Scenario.exit_bid` must come from validated market replay/pricing, not from the bias score.
- Relative price / volume / futures / breadth evidence are signed by a separate point-in-time feature pipeline. The provided `confirmed_pivots` and `volume_percentile` are helpers, not a complete connector.

## Required next engineering steps

1. Load daily, weekly, monthly bars and 1m data; implement a deterministic session calendar and corporate-action history.
2. Build feature adapters for market structure/BOS, volume, 52-week range, momentum, relative strength, breadth, opening range and futures signals. No lookahead or current constituents in historic tests.
3. Build pricing-service adapter with per-series settlement/cutoff, 0DTE conservative scenarios and fees/slippage; verify Greeks conventions.
4. Run walk-forward replay on SPX/SPY/QQQ and liquid stocks; compare net option P&L by ITM/ATM/OTM against liquid ATM benchmark.
5. Extend automated QA for missing feeds, calendar half-days/DST, splits, futures rolls, out-of-order ticks, hedging and risk budgets.

**Engineering heuristics**: score cutoffs, weights, 75% coverage, quote age, spread fraction and 0DTE cutoffs are initial design values from the BRX/OBX v4 specification. They have not been calibrated on held-out option-trade results.
