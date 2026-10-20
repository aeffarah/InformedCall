# Market notes

Working notes on the Kalshi weather markets we model. Volumes were observed by hand on 2026-10-20 and are unverified. Anything marked TODO still needs checking.

## Scope decision

Only the large, liquid markets are worth modeling: NYC, LA, SF, and Miami. Everything else is low liquidity, so any edge there is too small to matter. Add a city only if its volume justifies it.

## Rain today (yes/no)

- **Rule (NYC, as read 2026-10-20):** resolves yes if total precipitation at CLINYC for the day is strictly greater than 0 inches. Outcome verified from weather.com.
- **Volume seen:** about $426k on the NYC market.
- **Open questions:**
  - A trace of rain is reported as "T" in NWS climate reports and is not a measurable amount. Does "strictly greater than 0" count a trace? Check how past markets resolved on trace days.
  - The rule names CLINYC (the NWS climate report) but says outcome is verified from weather.com. Which one wins if they differ? Compare both on past dates.
  - Does the day end at local midnight, and what happens with late revisions?

## Highest temperature today (brackets)

- **Volume seen:** about $124k on the NYC market.
- **Open questions:**
  - Settlement source and station per city (TODO: confirm each).
  - Bracket edges and rounding.
  - Preliminary vs. final climate report, and any revisions.

## Other market types seen

- **Temperature at 2pm (Chicago):** point-in-time, good for intraday nowcasting. Low priority until the main markets work.

## Backtest rules

- Use bid/ask and Kalshi fees, never midpoints.
- Paper trade before any real money.
- Do not tune on the same days used to report results.

## Findings from the Kalshi API (2026-10-20)

### Access
- Public market data needs no API key: `GET https://api.elections.kalshi.com/trade-api/v2/series`, `/markets`, and `/historical/markets` all answered unauthenticated.
- Live `/markets` only covers markets settled after the cutoff from `GET /historical/cutoff` (2026-08-21 at time of writing). Anything older is under `/historical/markets`, which accepts `series_ticker` and cursor pagination (limit 1000).
- Candlesticks and trades not yet tested. Trade history cutoff is also 2026-08-21.

### Settlement rules (rain)
- "Trace" amounts (T) and missing daily precipitation values count as 0 inches. So Yes needs measurable rain.
- Official source is the Weather Company's Daily Climate Report (weather.com/kalshi), "latest version of the data". Settlement lands about 15:25 UTC the day after.
- Fee type is quadratic.

### Series are messy
Several ticker generations exist per city. Do not assume one series per market:

| Market | Series | History seen |
|---|---|---|
| NYC rain | `KXRAINNYC` | 2021-09 to 2026-07 (895 markets) |
| Multi-city rain (about 35 cities, incl. NYC) | `KXRAIN`, tickers like `KXRAIN-26AUG19-SFO` | 2026-07 onward |
| NYC rain, new daily | `KXRAINDNYC` | only 1 settled market so far |
| NYC high temp | `KXHIGHNY` | 2021-08 to now (9,406 markets) |
| Miami high temp | `KXHIGHMIA` | 2023-05 to now |
| LA high temp | `KXHIGHLAX` | 2025-01 to now |
| SF high temp | `KXHIGHTSFO` | 2026-01 to now |

LA, SF, and Miami rain look monthly (`KXRAINLAXM`, `KXRAINSFOM`, `KXRAINMIAM`), not daily. Daily rain for those cities is only inside the multi-city `KXRAIN` series.

### What this means for the backtest
- Forecast archives (Open-Meteo previous runs) start 2024-01, so the backtestable window is the overlap with market history.
- NYC is the deepest (about 2.8 years of overlap), then Miami (about 2.4), LA (about 1.7), SF (about 9 months).
- Start with NYC, then Miami. LA and SF are thin for now.
- Rain history needs stitching across `KXRAINNYC` and `KXRAIN`. Check whether the rule text changed between them.
