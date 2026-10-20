# InformedCall

**Quant-grade forecasts from real-world signals.**

> Not investment advice. Forecasts are probabilistic and can be wrong. Nothing here is a recommendation to buy, sell, or bet on anything.

## What it is

InformedCall turns real-world data (weather models, station observations, and later satellite imagery and other physical-world signals) into calibrated probabilities for recurring prediction-market contracts, then scores those probabilities against what actually happened.

The core idea is a **calibration lab**: for each market, find the official settlement source, gather leading indicators, produce a probability, and publish an honest scorecard. A new market category is mostly a new data adapter.

## Status

Early MVP. Private.

## MVP

Focus on the most liquid weather markets only, in a handful of big cities (NYC, LA, SF, Miami). Smaller cities are too thin to matter.

- **Rain today** (yes/no): resolves yes if total precipitation is strictly greater than 0 inches.
- **Highest temperature today** (brackets).

Per market:

1. Pull historical market prices and outcomes.
2. Pull settled observations and the forecasts that existed the day before.
3. Show a calibration chart: when the model says 30%, does it happen about 30% of the time, and how does the market's own calibration compare? Backtests use bid/ask and fees, not midpoints.

Rules and quirks for each market are tracked in [docs/market-notes.md](docs/market-notes.md).

## Roadmap

- **Now:** NYC rain and high-temperature backtest, then the other big cities.
- **Next:** Intraday nowcasting (radar and satellite), lows, snow, and point-in-time temperature markets.
- **Later:** Gas prices, hurricanes and wildfires, economic data, other venues.

## Open questions

- Which station and report each market settles on, and how rounding and brackets work.
- Whether a trace of rain counts as "greater than 0 inches", and which source decides the outcome.
- Whether the market data endpoints need authentication.
- Whether calibrated forecasts beat the market's own prices. If they don't, that is a result worth publishing too.

## Setup

Secrets live in a local, git-ignored `.env` file. Copy `.env.example` to `.env` and fill it in. Never commit credentials.
