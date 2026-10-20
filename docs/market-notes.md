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

## Validation of the ingest (2026-10-20)

Pulled NYC markets and NWS daily climate reports (Iowa Mesonet, station KNYC = CLINYC) and checked whether our reading of the rules reproduces Kalshi's recorded results (`informedcall.scoring.labels`).

| Check | Result |
|---|---|
| NYC high temp (9,757 markets, 2021-08 to now) | 2 disagreements (0.02%) |
| NYC rain, new `KXRAIN` series (92 markets) | 0 disagreements |
| NYC rain, old `KXRAINNYC` "greater than 0" markets (526) | 2 disagreements, both days missing from the Mesonet feed |

### Rain rules differ by series
- Old `KXRAINNYC` ("precipitation recorded at Central Park"): a **trace counts as rain**. About 100% of trace days since 2025 resolved Yes.
- New `KXRAIN` (CLINYC): a **trace counts as 0**. Every trace day resolved No.
- Labels must follow each series' own rule. Mixing them would corrupt training data.
- The old series was a ladder of thresholds per day (>0, >0.05, >0.1 ... >9). Only the `floor_strike == 0` market is rain-today. Threshold wording also varies slightly ("according to the NWS Daily Climate Report", "0.00").
- Old rain data comes in two chunks: 2021-09 to 2022 and 2025 to 2026-07. There is nothing in between.

### High temp quirks
- Subtitles vary: "87° or higher/above", "80° or below/lower", "81° to 82°", and legacy half-degree thresholds ("51.5° or higher"). Plain numeric comparisons work because the reported high is a whole number.
- About 14.5% of markets are legacy (`HIGHNY-...` tickers) with no strike fields, so thresholds come from the subtitle.
- 3 legacy subtitles are unparseable ("56°", "<94°", "96°"). 2 legacy markets mislabel the threshold ("42° or higher" resolved No at a high of 42). Both are negligible.
- The Mesonet feed has gaps (for example 2025-06-02 and 06-03 have no precip value). Missing days should be dropped, not guessed.

## Forecast archive (Open-Meteo previous runs, NYC Central Park, 2026-10-20)

Day-ahead hourly forecasts (`*_previous_day1`), collapsed to a daily high over the NWS climate day (midnight to midnight local standard time, so 1am to 1am in summer).

| Model | Archive starts | Days scored | Bias | MAE | RMSE |
|---|---|---|---|---|---|
| GFS (`gfs_seamless`) | 2024-01-19 | 1,002 | -0.6°F | 2.7°F | 3.5°F |
| ECMWF IFS (`ecmwf_ifs025`) | 2024-02-04 | 987 | -1.0°F | 2.8°F | 3.6°F |
| NBM (`ncep_nbm_conus`) | 2024-10-09 | 739 | -0.6°F | 2.5°F | 3.9°F |
| 3-model mean (days all three exist) | 2024-10-09 | 739 | -0.7°F | 2.2°F | 2.9°F |

- A 2°F-wide bracket against a typical error of about 3°F means no bracket is ever likely above roughly 25-30%. Edge will come from calibrated widths and bias, not confident calls.
- Cold bias is expected: hourly values understate a true daily maximum. NBM bias varies by season (about -1.4°F in winter, +0.5°F in fall), so calibrate by season.
- NBM has the lowest MAE but a higher RMSE than the mean, which suggests a few large misses. Worth inspecting before trusting it.
- Backtest window is roughly 2024-10 onward for NBM, 2024-02 onward for GFS and ECMWF.

## Fees (2026-10-20)

- `KXHIGHNY`, `KXRAIN`, `KXRAINNYC`, and `KXHIGHMIA` all report `fee_type=quadratic`, `fee_multiplier=1` via the API.
- Taker fee per third-party sources: `ceil(0.07 * C * P * (1 - P))` cents for C contracts at price P. It peaks at 50 cents (about 1.75 cents per contract) and falls toward the extremes.
- Maker fees: sources disagree (25% of taker, or none on most markets). Not modeled; the backtest assumes taker-only.
- Kalshi's own fee schedule PDF returned HTTP 429 and was not read. Confirm against it before any real trading.
- The backtest rounds the fee up per single contract, which slightly overstates cost compared with one larger order.

## First backtest: NYC high temp vs Kalshi price (2026-10-20)

Test period 2025-07-01 onward, 2,484 bracket markets with quotes (414 days), decision time 23:00 UTC the day before. Model trained only on earlier days.

| | Brier (lower is better) |
|---|---|
| Baseline model (blended forecasts, seasonal bias, normal error) | 0.1278 |
| Kalshi price (bid/ask midpoint) | 0.1076 |

- Both are well calibrated through about 35%, but **the market is sharper**: it separates likely from unlikely brackets better than our model does.
- The model's top bin is overconfident: 42 markets it priced near 67% happened only 36% of the time.
- Simulated bets (edge of at least 5 cents after taker fees): 1,198 bets, 37% win rate, **-2.5 cents per contract on average**, roughly -30 contract-dollars in total. Both sides lose (yes -2.3c, no -2.7c). No edge from this model.
- Chart: [docs/img/calibration_nyc_high.png](img/calibration_nyc_high.png).

### Why the baseline is not enough
- It uses a fixed error width per season, so it cannot tell a confident day from an uncertain one.
- Its point forecast is built from hourly model output, which understates the daily high, and it uses day-ahead runs only.
- The market also sees the latest model runs, official NWS forecasts, and local knowledge.

### Ideas to close the gap (not yet tried)
- Use the most recent model run available at decision time instead of only the day-ahead run.
- Use model disagreement (spread) to widen or narrow each day's distribution.
- Weight models by recent skill, and add an official NWS or NBM point forecast.
- Re-test on a longer window when the archive grows.

## Intraday test: does the price lag the observations? (2026-10-20)

Hypothesis: as the event day unfolds, Kalshi prices react slowly to the temperature already recorded. Test: at 12, 14, 16, and 18 local standard time (1pm to 7pm in summer), predict the final high from the day-ahead blend, the highest reading so far, and the latest reading (per-hour regression, truncated at the running max), then compare with the market price at that hour. Test period 2025-07-01 onward, bets need 5 cents of edge after fees.

Hourly METAR readings (2024-01 onward):

| Hour (LST) | Brier model | Brier market | Bets | Avg P&L per contract |
|---|---|---|---|---|
| 12 | 0.1015 | 0.0751 | 1,026 | -3.2c |
| 14 | 0.0740 | 0.0422 | 805 | -4.9c |
| 16 | 0.0587 | 0.0164 | 745 | -2.3c |
| 18 | 0.0558 | 0.0110 | 756 | -1.1c |

**The market beats the model at every hour, and the gap widens as the day goes on. No lag found.** But this test cannot settle the question, because our observations are too coarse:

- Hourly readings understate the official high (on average the final high is 0.8F above the highest hourly reading at 7pm). A trader watching live station data sees the running maximum more precisely than we do.
- One-minute data (Mesonet `asos1min`, starts about 2025-01, about 78% of minutes present) did not fix this. It contains spikes of up to 19F around 06:00 UTC (likely a nightly sensor routine), and even after removing them the official high is below the one-minute maximum 31% of the time. The official daily high is not simply the highest one-minute reading.
- Faithfully rebuilding the running maximum probably needs the 5-minute or 6-hour maximum groups that NWS uses, which we have not found a backtestable source for.

### What this implies
- The most-watched market (NYC daily high) looks efficient for anyone using public data at this granularity. The late-day Brier of 0.011 says the market is nearly certain once the day is mostly over.
- Any edge more likely sits where traders have a harder time getting the data, not in re-deriving what a weather app already shows.
- Candidates to test next: same-day radar nowcasting for rain, and satellite fog and cloud for marine-layer cities (LA, SF).
