"""Baseline probabilities for the NYC rain-today market.

A logistic regression on how much rain the day-ahead models forecast and how many of them
forecast any. It is trained on every day before the cutoff against the observed climate
report, then scored against Kalshi's recorded results after the cutoff.

Kalshi's two NYC rain series differ on trace amounts: the old KXRAINNYC counted a trace as
rain, the new KXRAIN (CLINYC) counts it as 0. So two targets are fitted, "any rain incl. trace"
and "measurable rain only", and each test market is scored with the one its series uses.

    uv run python -m informedcall.model.rain_baseline --split 2025-07-01
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from informedcall.ingest.forecasts import STANDARD_UTC_OFFSET, daily_precip_mm
from informedcall.scoring.labels import event_date

RAW = Path("data/raw")
OUT = Path("data/processed")
WET_MM = 0.1


def daily_table() -> pd.DataFrame:
    hourly = pd.read_parquet(RAW / "forecasts/nyc_hourly.parquet")
    fc = daily_precip_mm(hourly, STANDARD_UTC_OFFSET["nyc"])
    fc["day"] = pd.to_datetime(fc["day"])
    cols = [c for c in fc if c.startswith("precip_mm_")]
    fc = fc.dropna(subset=cols, how="all")
    fc["blend_mm"] = fc[cols].mean(axis=1)
    fc["wet_share"] = (fc[cols] > WET_MM).sum(axis=1) / fc[cols].notna().sum(axis=1)

    act = pd.read_parquet(RAW / "actuals/cli_KNYC.parquet")
    act["day"] = pd.to_datetime(act["valid"])
    act = act[act["precip"].notna() | act["precip_trace"]]
    act["rain_meas"] = act["precip"].fillna(0) > 0
    act["rain_any"] = act["rain_meas"] | act["precip_trace"]
    return fc.merge(act[["day", "rain_meas", "rain_any"]], on="day").reset_index(drop=True)


def features(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.log1p(df["blend_mm"]), df["wet_share"]])


def test_markets() -> pd.DataFrame:
    old = pd.read_parquet(RAW / "kalshi/KXRAINNYC.parquet")
    old = old[old["floor_strike"].eq(0)].assign(series="old")
    new = pd.read_parquet(RAW / "kalshi/KXRAIN_NYC.parquet").assign(series="new")
    mk = pd.concat([old, new], ignore_index=True)
    mk["day"] = mk["event_ticker"].map(event_date)
    mk["outcome"] = mk["result"].eq("yes").astype(float)
    return mk[["ticker", "series", "day", "outcome"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="2025-07-01", help="first day of the test period")
    args = parser.parse_args()

    days = daily_table()
    cutoff = pd.Timestamp(args.split)
    train = days[days["day"] < cutoff]
    print(f"Train days {len(train)}, rain rate any {train['rain_any'].mean():.0%}, measurable {train['rain_meas'].mean():.0%}")

    models = {
        target: LogisticRegression(C=1.0).fit(features(train), train[target])
        for target in ("rain_any", "rain_meas")
    }
    mk = test_markets().merge(days, on="day")
    mk = mk[mk["day"] >= cutoff].copy()
    mk["p_any"] = models["rain_any"].predict_proba(features(mk))[:, 1]
    mk["p_meas"] = models["rain_meas"].predict_proba(features(mk))[:, 1]
    mk["p_model"] = np.where(mk["series"] == "old", mk["p_any"], mk["p_meas"])
    OUT.mkdir(parents=True, exist_ok=True)
    mk.to_parquet(OUT / "nyc_rain_predictions.parquet", index=False)

    brier = ((mk["p_model"] - mk["outcome"]) ** 2).mean()
    rate = mk["outcome"].mean()
    base = ((rate - mk["outcome"]) ** 2).mean()
    print(f"Test markets {len(mk)} ({mk['series'].value_counts().to_dict()}), rain rate {rate:.0%}")
    print(f"Brier {brier:.4f}  vs always-{rate:.0%} baseline {base:.4f}")
    print(f"Accuracy at 50%: {((mk['p_model'] > 0.5) == (mk['outcome'] > 0.5)).mean():.0%}")
    bins = pd.cut(mk["p_model"], [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0], include_lowest=True)
    print(mk.groupby(bins, observed=True).agg(n=("outcome", "size"), predicted=("p_model", "mean"), observed=("outcome", "mean")).round(2).to_string())


if __name__ == "__main__":
    main()
