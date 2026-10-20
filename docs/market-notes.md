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
