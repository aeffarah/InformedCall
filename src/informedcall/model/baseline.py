"""Baseline probabilities for NYC daily-high bracket markets.

Blend the available day-ahead model forecasts, correct a per-season bias, and model the error
as a normal distribution with a per-season width, all learned on days before a cutoff. Each
bracket's probability is the mass of that distribution inside the bracket. Observed highs are
whole degrees, so brackets use half-degree continuity edges.

    uv run python -m informedcall.model.baseline --split 2025-07-01
"""

import argparse
from math import erf, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from informedcall.ingest.forecasts import STANDARD_UTC_OFFSET, daily_highs_f
from informedcall.scoring.labels import bracket_yes, event_date, parse_bracket

RAW = Path("data/raw")
OUT = Path("data/processed")
SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
           6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(erf)(x / sqrt(2.0)))


def daily_table() -> pd.DataFrame:
    """One row per day: observed high and the blended day-ahead forecast."""
    hourly = pd.read_parquet(RAW / "forecasts/nyc_hourly.parquet")
    fc = daily_highs_f(hourly, STANDARD_UTC_OFFSET["nyc"])
    fc["day"] = pd.to_datetime(fc["day"])
    model_cols = [c for c in fc if c.startswith("high_f_")]
    fc["blend"] = fc[model_cols].mean(axis=1)
    fc["n_models"] = fc[model_cols].notna().sum(axis=1)
    act = pd.read_parquet(RAW / "actuals/cli_KNYC.parquet")
    act["day"] = pd.to_datetime(act["valid"])
    df = fc.merge(act[["day", "high"]], on="day").dropna(subset=["blend", "high"])
    df["season"] = df["day"].dt.month.map(SEASONS)
    return df.reset_index(drop=True)


def fit(train: pd.DataFrame) -> pd.DataFrame:
    """Per-season bias (observed minus blend) and residual standard deviation."""
    resid = train["high"] - train["blend"]
    return resid.groupby(train["season"]).agg(bias="mean", sigma="std")


def bracket_bounds(kind: str, low: float, top: float | None) -> tuple[float, float]:
    """Continuity-corrected (lower, upper) edges for a whole-degree outcome."""
    edge = lambda v: v - 0.5 if float(v).is_integer() else v
    if kind == "ge":
        return edge(low), np.inf
    if kind == "le":
        return -np.inf, (low + 0.5 if float(low).is_integer() else low)
    return edge(low), (top + 0.5 if float(top).is_integer() else top)


def predict(markets: pd.DataFrame, days: pd.DataFrame, params: pd.DataFrame) -> pd.DataFrame:
    df = markets.copy()
    df["day"] = df["event_ticker"].map(event_date)
    parsed = df["yes_sub_title"].map(parse_bracket)
    df["kind"] = [p[0] for p in parsed]
    df["low"] = [p[1] for p in parsed]
    df["top"] = [p[2] for p in parsed]
    df = df.dropna(subset=["kind"]).merge(days[["day", "blend", "high", "season"]], on="day")
    df = df.join(params, on="season")
    mu = df["blend"] + df["bias"]
    bounds = [bracket_bounds(k, lo, tp) for k, lo, tp in zip(df["kind"], df["low"], df["top"])]
    lower = np.array([b[0] for b in bounds])
    upper = np.array([b[1] for b in bounds])
    z = lambda edge: np.where(np.isinf(edge), np.sign(edge) * 40, (edge - mu) / df["sigma"])
    df["p_model"] = _norm_cdf(z(upper)) - _norm_cdf(z(lower))
    df["outcome"] = [
        bracket_yes(h, k, lo, tp) for h, k, lo, tp in zip(df["high"], df["kind"], df["low"], df["top"])
    ]
    df["outcome"] = df["outcome"].astype(float)
    return df.dropna(subset=["outcome"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="2025-07-01", help="first day of the test period")
    args = parser.parse_args()

    days = daily_table()
    cutoff = pd.Timestamp(args.split)
    params = fit(days[days["day"] < cutoff])
    print("Fitted on days before", args.split)
    print(params.round(2).to_string())

    markets = pd.read_parquet(RAW / "kalshi/KXHIGHNY.parquet")
    pred = predict(markets, days, params)
    pred = pred[pred["day"] >= pd.Timestamp("2024-02-01")]
    test = pred[pred["day"] >= cutoff]
    OUT.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(OUT / "nyc_high_predictions.parquet", index=False)

    brier = ((test["p_model"] - test["outcome"]) ** 2).mean()
    base = ((test["outcome"].mean() - test["outcome"]) ** 2).mean()
    print(f"\nTest markets: {len(test)} over {test['day'].nunique()} days")
    print(f"Brier score: {brier:.4f}  (climatology baseline {base:.4f}, lower is better)")


if __name__ == "__main__":
    main()
