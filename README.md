# InformedCall

**Quant-grade forecasts from real-world signals.**

> Not investment advice. Nothing here is a recommendation to buy, sell, or bet on anything, and no real money was traded.

**Status: exploration concluded (October 2026).** The hypothesis did not hold up, and the write-up below is the product.

## The question

Can public real-world data (weather models, station observations, radar) produce probabilities that beat the prices on Kalshi's recurring weather markets, after fees?

## Product framing

| | |
|---|---|
| **User** | Retail prediction-market traders, who have no easy way to tell whether a posted price is fair |
| **Problem** | Prices on recurring markets look like guesses. Is there a repeatable, public-data signal that a trader could use? |
| **Hypothesis** | A calibrated model on free weather data can beat the market's price on Kalshi's liquid weather markets |
| **Success criteria** | Better Brier score than the market's own price, and positive simulated profit after fees, both on days the model never saw. Win rate alone was rejected as a metric because cheap contracts can win rarely and still pay |
| **Stop rule** | If two independent tests show no edge, stop and write it up rather than keep tuning |

### Decisions and trade-offs

| Decision | Why |
|---|---|
| Scope to the most liquid markets (NYC first) | Thin markets cannot absorb a real edge, and NYC had the deepest price and forecast history |
| Validate labels against Kalshi's settlements before modelling | A wrong reading of the rules would have quietly corrupted every result |
| Test in order of cost: day-ahead, then intraday, then radar | Each step was cheap to run and would have shown an edge early if one existed |
| Backtest at the bid/ask with fees | Midpoint prices flatter any strategy |
| Cut: smaller cities, a consumer dashboard, brand and landing page, real-money trading | None of it matters until the model beats the price |
| Stop after the radar test | Two independent tests agreed. More tuning would have been hope, not evidence |

### Guardrails

No real money was traded. Everything is described as analytics, not advice. No credentials are stored in the repo, and raw data stays out of version control.

Built solo with Claude Code as a pair programmer. I set the questions, the success criteria, and the stop rule, and reviewed every result.

## What I built

- **Ingest:** Kalshi markets and hourly bid/ask history (stitching the live and historical endpoints), NWS daily climate reports, archived day-ahead forecasts from three weather models, station observations, and NEXRAD radar composites reduced to rain-coverage features.
- **Label validation:** before modelling, I checked that my reading of each market's rules reproduces Kalshi's recorded settlements.
- **Models:** a calibrated day-ahead baseline for daily-high brackets, plus intraday nowcasts that add the temperature so far (temperature) or radar (rain).
- **Backtest:** trained on earlier days, tested on later ones, priced at the bid/ask a trader would have faced, with taker fees.

## Results

| Test | Finding |
|---|---|
| Labels vs Kalshi settlements | 99.98% agreement on 9,757 NYC high-temp markets; 100% on the current rain series |
| Day-ahead NYC daily high | Brier 0.128 (model) vs 0.108 (market). Simulated trading: about -2.5 cents per contract |
| Intraday temperature, 1pm to 7pm | Market better at every hour, and the gap widens as the day goes on |
| Same-day rain with radar | Radar adds about 0.004 AUC over the forecast alone; the market ranks days better than either |

![Calibration of the model and Kalshi's price for NYC daily highs](docs/img/calibration_nyc_high.png)

Both are well calibrated, but the market is sharper. Two independent tests found no lag between public weather data and prices in NYC, which suggests those markets are efficient for anyone using public data at this level.

## What I learned

- **Market data is messy.** Several ticker generations exist per city, and rules changed between them (the older rain series counted a trace of rain as rain; the newer one counts it as zero). Labels have to follow each series' own rule.
- **Check the target before the model.** Reproducing the settlements first caught a trace-rain rule change and a legacy schema that would have silently corrupted training data.
- **A fair test needs the trader's information.** My observation data understated the running high, so the intraday temperature test could not settle the question on its own. One-minute station data had spikes and still did not match the official high.
- **Signal is not edge.** Radar features predicted rain well on their own, but the forecast already contained that information.

## What I would do differently

- **Check market efficiency first.** The cheapest test was always "is the price already calibrated?" It was. I would run that one-chart check before building any model, and only continue where the market looks weak.
- **Get the trader's data before the intraday test.** I could not see what a live station display shows, so that test could not settle the question. I would confirm data parity first.
- **Pick the market by how hard its data is to get**, not by how visible it is. NYC weather is the most-watched market, which is the worst place to look for an edge.

If I picked this up again, I would test a less-watched market (for example Miami) or a different category before touching the model.

## Limitations

- Baseline models only: fixed error widths, a simple blend, and coarse radar features with no storm motion.
- NYC only for backtests; other cities have less history.
- Maker fees are not modelled, and fees follow third-party descriptions of Kalshi's schedule.
- Roughly 2.5 years of archived forecasts limits the test window.

Details, tables, and data quirks are in [docs/market-notes.md](docs/market-notes.md).

## Reproduce

Requires [uv](https://docs.astral.sh/uv/). Kalshi market data needs no API key.

```
uv sync
uv run python -m informedcall.ingest.kalshi KXHIGHNY
uv run python -m informedcall.ingest.kalshi KXRAINNYC
uv run python -m informedcall.ingest.kalshi KXRAIN --suffix=-NYC
uv run python -m informedcall.ingest.actuals KNYC --start 2021
uv run python -m informedcall.ingest.forecasts nyc --lat 40.7794 --lon=-73.9692
uv run python -m informedcall.ingest.candles KXHIGHNY --since 2024-02-01
uv run python -m informedcall.model.baseline
uv run python -m informedcall.scoring.backtest
```

Raw data lands in `data/` and is git-ignored. Secrets, if ever needed, belong in a local `.env` (see `.env.example`).

## Layout

```
src/informedcall/
  ingest/    Kalshi, climate reports, forecasts, observations, radar, candlesticks
  model/     day-ahead and intraday baselines for temperature and rain
  scoring/   label checks and the fee-aware backtest
docs/        market notes and the calibration chart
```
