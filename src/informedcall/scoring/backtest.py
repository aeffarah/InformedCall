"""Compare model probabilities with Kalshi's own prices and simulate trading the gap.

Decision time is 23:00 UTC the day before the event (6-7pm New York), using the last hourly
candle quotes at or before it. Buying Yes pays the ask, buying No pays 1 - bid, and the taker
fee follows Kalshi's quadratic schedule, assumed here as ceil(0.07 * P * (1 - P)) per
contract in cents. Verify the fee schedule before trusting any P&L number.

    uv run python -m informedcall.scoring.backtest --split 2025-07-01
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PREDICTIONS = Path("data/processed/nyc_high_predictions.parquet")
CANDLES = Path("data/raw/candles/KXHIGHNY.parquet")
CHART = Path("docs/img/calibration_nyc_high.png")

DECISION_HOUR_UTC = 23
FEE_RATE = 0.07
MIN_EDGE = 0.05
BINS = [0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0]

# Reference palette: categorical slots 1 and 2 on the light chart surface.
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def snapshot_quotes(candles: pd.DataFrame, days: pd.Series, tickers: pd.Series) -> pd.DataFrame:
    """Bid and ask per ticker at decision time, forward-filling quiet hours."""
    c = candles.copy()
    for col in ("bid_close", "ask_close"):
        c[col] = pd.to_numeric(c[col], errors="coerce")
    c = c.sort_values(["ticker", "end_ts"])
    c[["bid_close", "ask_close"]] = c.groupby("ticker")[["bid_close", "ask_close"]].ffill()
    decision = (
        pd.DataFrame({"ticker": tickers.values, "day": days.values})
        .drop_duplicates("ticker")
        .assign(ts=lambda d: d["day"] - pd.Timedelta(days=1) + pd.Timedelta(hours=DECISION_HOUR_UTC))
    )
    decision["ts"] = decision["ts"].dt.tz_localize("UTC")
    merged = c.merge(decision[["ticker", "ts"]], on="ticker")
    merged = merged[merged["end_ts"] <= merged["ts"]]
    last = merged.groupby("ticker").tail(1)
    return last[["ticker", "bid_close", "ask_close"]].rename(
        columns={"bid_close": "bid", "ask_close": "ask"}
    )


def fee(price: np.ndarray) -> np.ndarray:
    return np.ceil(FEE_RATE * price * (1 - price) * 100) / 100


def simulate(df: pd.DataFrame) -> pd.DataFrame:
    """One contract per market where the model sees at least MIN_EDGE after fees."""
    yes_cost = df["ask"]
    no_cost = 1 - df["bid"]
    edge_yes = df["p_model"] - yes_cost - fee(yes_cost)
    edge_no = (1 - df["p_model"]) - no_cost - fee(no_cost)
    buy_yes = (edge_yes >= MIN_EDGE) & (edge_yes >= edge_no) & (yes_cost < 1)
    buy_no = (edge_no >= MIN_EDGE) & (edge_no > edge_yes) & (df["bid"] > 0)
    bets = df[buy_yes | buy_no].copy()
    bets["side"] = np.where(buy_yes[bets.index], "yes", "no")
    cost = np.where(bets["side"] == "yes", yes_cost[bets.index], no_cost[bets.index])
    won = np.where(bets["side"] == "yes", bets["outcome"], 1 - bets["outcome"])
    bets["pnl"] = won - cost - fee(cost)
    return bets


def reliability(p: pd.Series, outcome: pd.Series) -> pd.DataFrame:
    bucket = pd.cut(p, BINS, include_lowest=True)
    out = pd.DataFrame({"p": p, "y": outcome}).groupby(bucket, observed=True).agg(
        predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size")
    )
    return out.reset_index(drop=True)


def draw_chart(rel_model: pd.DataFrame, rel_market: pd.DataFrame, brier: dict, n: int, start: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=200, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.plot([0, 0.6], [0, 0.6], color=AXIS, lw=1, ls=(0, (4, 4)), zorder=1)
    for rel, color, label in ((rel_market, ORANGE, "Kalshi price"), (rel_model, BLUE, "InformedCall model")):
        ax.plot(rel["predicted"], rel["observed"], color=color, lw=2, zorder=2)
        ax.scatter(rel["predicted"], rel["observed"], s=34, color=color, edgecolor=SURFACE, linewidth=1.5, zorder=3, label=label)
        end = rel.iloc[-1]
        ax.annotate(label, (end["predicted"], end["observed"]), xytext=(8, -4 if color == BLUE else 6),
                    textcoords="offset points", color=INK_2, fontsize=9)
    ax.text(0.57, 0.585, "perfectly calibrated", color=MUTED, fontsize=8, rotation=0, ha="right", va="top")
    ax.set_xlim(0, 0.62)
    ax.set_ylim(0, 0.62)
    ax.set_xlabel("Probability stated", color=INK_2, fontsize=10)
    ax.set_ylabel("How often it happened", color=INK_2, fontsize=10)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK_2)
    fig.text(0.06, 0.965, "NYC daily high: do the stated odds come true?", color=INK, fontsize=13, fontweight="bold", va="top")
    fig.text(
        0.06, 0.915,
        f"{n:,} bracket markets since {start}, priced 6-7pm the day before. "
        f"Brier score (lower is better): model {brier['model']:.4f}, market {brier['market']:.4f}.",
        color=INK_2, fontsize=9, va="top",
    )
    fig.subplots_adjust(left=0.1, right=0.95, top=0.86, bottom=0.12)
    CHART.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHART, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="2025-07-01", help="first day of the test period")
    args = parser.parse_args()

    pred = pd.read_parquet(PREDICTIONS)
    pred = pred[pred["day"] >= pd.Timestamp(args.split)]
    quotes = snapshot_quotes(pd.read_parquet(CANDLES), pred["day"], pred["ticker"])
    df = pred.merge(quotes, on="ticker").dropna(subset=["bid", "ask"]).copy()
    df["p_market"] = (df["bid"] + df["ask"]) / 2
    print(f"Test markets with quotes at decision time: {len(df)} of {len(pred)} ({df['day'].nunique()} days)")

    brier = {
        "model": float(((df["p_model"] - df["outcome"]) ** 2).mean()),
        "market": float(((df["p_market"] - df["outcome"]) ** 2).mean()),
    }
    print(f"Brier  model {brier['model']:.4f}   market {brier['market']:.4f}")

    rel_model = reliability(df["p_model"], df["outcome"])
    rel_market = reliability(df["p_market"], df["outcome"])
    print("\nReliability (model):\n", rel_model.round(3).to_string(index=False))
    print("\nReliability (market):\n", rel_market.round(3).to_string(index=False))

    bets = simulate(df)
    if len(bets):
        print(
            f"\nSimulated bets (edge >= {MIN_EDGE:.0%} after fees): {len(bets)}, "
            f"win rate {(bets['pnl'] > 0).mean():.0%}, avg P&L {bets['pnl'].mean():+.3f}/contract, "
            f"total {bets['pnl'].sum():+.1f} contracts-dollars"
        )
        print(bets.groupby("side")["pnl"].agg(["size", "mean", "sum"]).round(3).to_string())
    else:
        print("\nNo bets cleared the edge threshold.")

    draw_chart(rel_model, rel_market, brier, len(df), args.split)
    print(f"\nChart -> {CHART}")


if __name__ == "__main__":
    main()
