"""Intraday probabilities for NYC daily-high markets, compared with Kalshi's price at the same hour.

At each decision time on the event day, a per-hour linear regression predicts the final climate
high from the day-ahead blend, the highest reading so far, and the latest reading. Its residual
spread gives a normal distribution, truncated because the high cannot finish below what has
already been recorded. The hypothesis under test: does the price lag the observations?

Decision hours are in local standard time (the NWS climate day), so 12 means 1pm in summer.

    uv run python -m informedcall.model.intraday --split 2025-07-01
"""

import argparse
from math import erf, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from informedcall.model.baseline import bracket_bounds, daily_table
from informedcall.scoring.backtest import CANDLES, MIN_EDGE, quotes_at, simulate
from informedcall.scoring.labels import bracket_yes, event_date, parse_bracket

RAW = Path("data/raw")
OUT = Path("data/processed")
HOURS_LST = [12, 14, 16, 18]
LST_OFFSET = 5  # hours behind UTC


def _cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(erf)(x / sqrt(2.0)))


def obs_features(obs: pd.DataFrame, days: pd.DataFrame, hour: int, min_readings: int) -> pd.DataFrame:
    """Highest and latest reading so far on each climate day, at `hour` local standard time.

    Days with fewer than `min_readings` observations by then are skipped, since gaps could hide
    the true running maximum.
    """
    o = obs.assign(lst_day=(obs["valid"] - pd.Timedelta(hours=LST_OFFSET)).dt.tz_localize(None).dt.normalize())
    by_day = {d: g for d, g in o.groupby("lst_day")}
    rows = []
    for day in days["day"]:
        g = by_day.get(day)
        if g is None:
            continue
        ts = pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=LST_OFFSET + hour)
        so_far = g[g["valid"] <= ts]
        if len(so_far) < min_readings:
            continue
        rows.append({"day": day, "ts": ts, "max_so_far": so_far["tmpf"].max(), "latest": so_far["tmpf"].iloc[-1]})
    return pd.DataFrame(rows).merge(days[["day", "blend", "high"]], on="day")


def design(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(df)), df["blend"], df["max_so_far"], df["latest"]])


def fit_hour(train: pd.DataFrame) -> tuple[np.ndarray, float]:
    X, y = design(train), train["high"].to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, float(resid.std(ddof=X.shape[1]))


def market_table() -> pd.DataFrame:
    mk = pd.read_parquet(RAW / "kalshi/KXHIGHNY.parquet")
    mk["day"] = mk["event_ticker"].map(event_date)
    parsed = mk["yes_sub_title"].map(parse_bracket)
    mk["kind"] = [p[0] for p in parsed]
    mk["low"] = [p[1] for p in parsed]
    mk["top"] = [p[2] for p in parsed]
    return mk.dropna(subset=["kind"])[["ticker", "day", "kind", "low", "top"]]


def probabilities(df: pd.DataFrame, beta: np.ndarray, sigma: float) -> np.ndarray:
    mu = design(df) @ beta
    floor = df["max_so_far"].to_numpy() - 0.5
    bounds = [bracket_bounds(k, lo, tp) for k, lo, tp in zip(df["kind"], df["low"], df["top"])]
    lower = np.maximum([b[0] for b in bounds], floor)
    upper = np.array([b[1] for b in bounds])
    z = lambda edge: np.where(np.isinf(edge), np.sign(edge) * 40, (edge - mu) / sigma)
    mass_above_floor = 1.0 - _cdf(z(floor))
    inside = np.clip(_cdf(z(upper)) - _cdf(z(lower)), 0, None)
    return np.where(mass_above_floor > 1e-9, inside / np.maximum(mass_above_floor, 1e-9), 0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="2025-07-01", help="first day of the test period")
    parser.add_argument("--source", choices=["hourly", "1min"], default="1min")
    args = parser.parse_args()
    cutoff = pd.Timestamp(args.split)

    days = daily_table()
    obs = pd.read_parquet(RAW / ("obs/nyc_asos.parquet" if args.source == "hourly" else "obs/nyc_1min.parquet"))
    minutes_wanted = lambda hour: int(0.7 * hour * 60) if args.source == "1min" else hour // 2
    candles = pd.read_parquet(CANDLES)
    markets = market_table()
    results, all_rows = [], []

    for hour in HOURS_LST:
        feats = obs_features(obs, days, hour, minutes_wanted(hour))
        train = feats[feats["day"] < cutoff]
        beta, sigma = fit_hour(train)
        test = feats[feats["day"] >= cutoff]
        df = markets.merge(test, on="day")
        df["p_model"] = probabilities(df, beta, sigma)
        df["outcome"] = [
            bracket_yes(h, k, lo, tp) for h, k, lo, tp in zip(df["high"], df["kind"], df["low"], df["top"])
        ]
        df = df.dropna(subset=["outcome"]).assign(outcome=lambda d: d["outcome"].astype(float))
        quotes = quotes_at(candles, df.drop_duplicates("ticker")[["ticker", "ts"]])
        df = df.merge(quotes, on="ticker").dropna(subset=["bid", "ask"])
        df["p_market"] = (df["bid"] + df["ask"]) / 2
        df["hour_lst"] = hour
        bets = simulate(df)
        results.append(
            {
                "hour_lst": hour,
                "train_days": len(train),
                "sigma_f": round(sigma, 2),
                "markets": len(df),
                "brier_model": ((df["p_model"] - df["outcome"]) ** 2).mean(),
                "brier_market": ((df["p_market"] - df["outcome"]) ** 2).mean(),
                "bets": len(bets),
                "avg_pnl": bets["pnl"].mean() if len(bets) else np.nan,
                "total_pnl": bets["pnl"].sum() if len(bets) else 0.0,
            }
        )
        all_rows.append(df)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(all_rows).to_parquet(OUT / "nyc_intraday_predictions.parquet", index=False)
    print(f"Observations: {args.source}. Test period from {args.split}; bets need {MIN_EDGE:.0%} edge after fees\n")
    print(pd.DataFrame(results).round(4).to_string(index=False))


if __name__ == "__main__":
    main()
