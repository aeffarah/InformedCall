"""Same-day rain nowcast for the NYC rain-today market, compared with Kalshi's price at the same hour.

At 8, 11, and 14 local standard time, a logistic regression estimates whether any more rain will
count today, from the day-ahead forecast and (in the radar variant) how much of the area around
Central Park shows rain on radar, by distance ring and for the western, upstream sector. Days where
measurable rain has already been recorded are decided and are not modelled. The question under
test: does radar tell us something the price has not absorbed?

Kalshi's two NYC rain series differ on trace amounts (old counts a trace, new does not), so each
market is scored with the target its own series uses.

    uv run python -m informedcall.model.rain_intraday --split 2025-07-01
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from informedcall.ingest.radar import HOURS_LST, LST_OFFSET
from informedcall.model.rain_baseline import daily_table, test_markets
from informedcall.scoring.backtest import MIN_EDGE, quotes_at, simulate

RAW = Path("data/raw")
OUT = Path("data/processed")
TRACE = 0.0001
FORECAST = ["log_mm", "wet_share"]
RADAR = ["wet_0_15", "wet_15_50", "wet_50_100", "wet_100_200", "wet_15_50_W", "wet_50_100_W", "wet_100_200_W"]
HOUR_DUMMIES = [f"h{h}" for h in HOURS_LST]


def rain_so_far(precip: pd.DataFrame, days: pd.Series, hour: int) -> pd.DataFrame:
    """Measurable and trace rain recorded so far on each climate day, from hourly METAR."""
    p = precip.assign(lst_day=(precip["valid"] - pd.Timedelta(hours=LST_OFFSET)).dt.tz_localize(None).dt.normalize())
    by_day = {d: g for d, g in p.groupby("lst_day")}
    rows = []
    for day in days:
        g = by_day.get(day)
        if g is None:
            continue
        ts = pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=LST_OFFSET + hour)
        so_far = g[g["valid"] <= ts]["p01i"]
        if len(so_far) < max(hour // 2, 1):
            continue
        rows.append({"day": day, "ts": ts, "hour": hour,
                     "measurable": float(so_far[so_far >= 0.01].sum()), "trace": bool((so_far == TRACE).any())})
    return pd.DataFrame(rows)


def build_rows(days: pd.DataFrame, precip: pd.DataFrame, radar: pd.DataFrame) -> pd.DataFrame:
    parts = [rain_so_far(precip, days["day"], h) for h in HOURS_LST]
    rows = pd.concat(parts, ignore_index=True).merge(days, on="day")
    rows = rows.merge(radar, on="ts", how="inner")
    rows["log_mm"] = np.log1p(rows["blend_mm"])
    for h in HOURS_LST:
        rows[f"h{h}"] = (rows["hour"] == h).astype(float)
    return rows


def fit(train: pd.DataFrame, target: str, cols: list[str]):
    model = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))
    return model.fit(train[cols], train[target])


def decided(df: pd.DataFrame, rule: str) -> pd.Series:
    """Rain already settled the market as Yes at decision time."""
    if rule == "any":
        return (df["measurable"] > 0) | df["trace"]
    return df["measurable"] > 0


def score_variant(rows: pd.DataFrame, cutoff: pd.Timestamp, cols: list[str]) -> pd.DataFrame:
    out = rows.copy()
    out["p_model"] = np.nan
    for rule, target in (("any", "rain_any"), ("meas", "rain_meas")):
        pending = ~decided(out, rule)
        train = out[(out["day"] < cutoff) & pending]
        model = fit(train, target, cols)
        mask = pending & (out["day"] >= cutoff)
        out.loc[mask, f"p_{rule}"] = model.predict_proba(out.loc[mask, cols])[:, 1]
        out[f"p_{rule}"] = np.where(decided(out, rule), 1.0, out.get(f"p_{rule}"))
    out["p_model"] = np.where(out["series"] == "old", out["p_any"], out["p_meas"]) if "series" in out else np.nan
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="2025-07-01", help="first day of the test period")
    args = parser.parse_args()
    cutoff = pd.Timestamp(args.split)

    days = daily_table()
    precip = pd.read_parquet(RAW / "obs/nyc_p01i.parquet")
    radar = pd.read_parquet(RAW / "radar/nyc_features.parquet")
    rows = build_rows(days, precip, radar)
    print(f"Rows with radar, forecast, and observations: {len(rows)} ({rows['day'].nunique()} days)")

    markets = test_markets()
    candles = pd.concat([pd.read_parquet(RAW / f"candles/{f}.parquet") for f in ("KXRAINNYC", "KXRAIN_NYC")])
    results, frames = [], []

    for name, cols in (("no radar", FORECAST + HOUR_DUMMIES), ("radar", FORECAST + RADAR + HOUR_DUMMIES)):
        scored = score_variant(rows.merge(markets[["day", "series"]].drop_duplicates("day"), on="day"), cutoff, cols)
        test = scored[scored["day"] >= cutoff].merge(markets[["ticker", "day", "outcome"]], on="day")
        for hour in HOURS_LST:
            h = test[test["hour"] == hour].copy()
            quotes = quotes_at(candles, h.drop_duplicates("ticker")[["ticker", "ts"]])
            h = h.merge(quotes, on="ticker").dropna(subset=["bid", "ask", "p_model"])
            h["p_market"] = (h["bid"] + h["ask"]) / 2
            bets = simulate(h)
            results.append({
                "variant": name, "hour_lst": hour, "markets": len(h),
                "brier_model": ((h["p_model"] - h["outcome"]) ** 2).mean(),
                "brier_market": ((h["p_market"] - h["outcome"]) ** 2).mean(),
                "bets": len(bets), "avg_pnl": bets["pnl"].mean() if len(bets) else np.nan,
                "total_pnl": bets["pnl"].sum() if len(bets) else 0.0,
            })
            frames.append(h.assign(variant=name))

    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(frames).to_parquet(OUT / "nyc_rain_intraday_predictions.parquet", index=False)
    print(f"\nTest period from {args.split}; bets need {MIN_EDGE:.0%} edge after fees\n")
    print(pd.DataFrame(results).round(4).to_string(index=False))


if __name__ == "__main__":
    main()
