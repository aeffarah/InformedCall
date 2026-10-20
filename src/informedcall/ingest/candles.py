"""Pull hourly bid/ask candlesticks for already-ingested Kalshi markets.

Markets settled before the historical cutoff are served from /historical/markets/{ticker}/candlesticks,
newer ones from /series/{series}/markets/{ticker}/candlesticks. Progress is checkpointed so an
interrupted run resumes where it left off.

    uv run python -m informedcall.ingest.candles KXHIGHNY --since 2024-02-01
    uv run python -m informedcall.ingest.candles KXRAINNYC --floor-strike 0
    uv run python -m informedcall.ingest.candles KXRAIN_NYC --series-ticker KXRAIN

The positional name is the parquet file stem written by the market ingest.
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
MARKETS_DIR = Path("data/raw/kalshi")
OUT_DIR = Path("data/raw/candles")
PERIOD_MINUTES = 60
WORKERS = 6
CHECKPOINT_EVERY = 500


def _get(client: httpx.Client, path: str, params: dict) -> httpx.Response:
    for attempt in range(6):
        resp = client.get(f"{BASE_URL}{path}", params=params)
        if resp.status_code == 429:
            time.sleep(2 ** (attempt + 1))
            continue
        return resp
    raise RuntimeError(f"Rate limited on {path}")


def fetch_candles(client: httpx.Client, series: str, market: pd.Series) -> list[dict]:
    params = {
        "start_ts": int(market["open_time"].timestamp()),
        "end_ts": int(market["close_time"].timestamp()),
        "period_interval": PERIOD_MINUTES,
    }
    ticker = market["ticker"]
    resp = _get(client, f"/historical/markets/{ticker}/candlesticks", params)
    if resp.status_code == 404:
        resp = _get(client, f"/series/{series}/markets/{ticker}/candlesticks", params)
    resp.raise_for_status()
    rows = []
    for c in resp.json().get("candlesticks", []):
        rows.append(
            {
                "ticker": ticker,
                "end_ts": pd.to_datetime(c["end_period_ts"], unit="s", utc=True),
                "bid_close": _field(c, "yes_bid", "close"),
                "ask_close": _field(c, "yes_ask", "close"),
                "bid_high": _field(c, "yes_bid", "high"),
                "ask_low": _field(c, "yes_ask", "low"),
                "price_close": _field(c, "price", "close"),
                "volume": c.get("volume"),
                "open_interest": c.get("open_interest"),
            }
        )
    return rows


def _field(candle: dict, group: str, key: str):
    """Quote sides are empty (or missing keys) in periods with no activity."""
    return (candle.get(group) or {}).get(key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("series")
    parser.add_argument("--since", default="2024-01-01", help="only markets closing on/after")
    parser.add_argument("--limit", type=int, default=0, help="cap markets (for testing)")
    parser.add_argument("--series-ticker", default="", help="Kalshi series if different from the file stem")
    parser.add_argument("--floor-strike", type=float, default=None, help="keep only markets with this floor strike")
    args = parser.parse_args()

    markets = pd.read_parquet(MARKETS_DIR / f"{args.series}.parquet")
    markets = markets[markets["close_time"] >= pd.Timestamp(args.since, tz="UTC")]
    markets = markets.dropna(subset=["open_time", "close_time"])
    if args.floor_strike is not None:
        markets = markets[markets["floor_strike"].eq(args.floor_strike)]
    series_ticker = args.series_ticker or args.series
    if args.limit:
        markets = markets.head(args.limit)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{args.series}.parquet"
    done = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    seen = set(done["ticker"]) if len(done) else set()
    todo = markets[~markets["ticker"].isin(seen)]
    print(f"{args.series}: {len(markets)} markets, {len(seen)} already done, {len(todo)} to fetch", flush=True)

    frames = [done] if len(done) else []
    buffer: list[dict] = []
    empty = 0

    def save() -> None:
        pd.concat(frames + [pd.DataFrame(buffer)], ignore_index=True).to_parquet(path, index=False)

    with httpx.Client(timeout=30) as client, ThreadPoolExecutor(WORKERS) as pool:
        futures = [pool.submit(fetch_candles, client, series_ticker, row) for _, row in todo.iterrows()]
        for i, fut in enumerate(futures, 1):
            rows = fut.result()
            buffer.extend(rows)
            empty += not rows
            if i % CHECKPOINT_EVERY == 0:
                save()
                print(f"  {i}/{len(todo)} markets, {len(buffer)} candles", flush=True)
    save()
    print(f"done: {len(todo)} markets fetched, {empty} with no candles -> {path}", flush=True)


if __name__ == "__main__":
    main()
