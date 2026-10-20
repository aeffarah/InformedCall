"""Pull settled Kalshi markets for a series from both the live and historical endpoints.

Kalshi splits data at a cutoff: markets settled after it are on /markets, older ones on
/historical/markets. Neither needs authentication for reads.

    uv run python -m informedcall.ingest.kalshi KXHIGHNY
    uv run python -m informedcall.ingest.kalshi KXRAIN --suffix=-NYC
"""

import argparse
import time
from pathlib import Path

import httpx
import pandas as pd

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
OUT_DIR = Path("data/raw/kalshi")
PAGE_LIMIT = 1000

KEEP = [
    "ticker",
    "event_ticker",
    "title",
    "yes_sub_title",
    "strike_type",
    "floor_strike",
    "cap_strike",
    "open_time",
    "close_time",
    "settlement_ts",
    "result",
    "settlement_value_dollars",
    "last_price_dollars",
    "volume_fp",
    "open_interest_fp",
    "rules_primary",
]


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    for attempt in range(5):
        resp = client.get(f"{BASE_URL}{path}", params=params)
        if resp.status_code == 429:
            time.sleep(2**attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Rate limited on {path}")


def _paged_markets(client: httpx.Client, path: str, params: dict) -> list[dict]:
    markets: list[dict] = []
    cursor = ""
    while True:
        page = _get(client, path, {**params, "limit": PAGE_LIMIT, "cursor": cursor})
        markets.extend(page["markets"])
        cursor = page.get("cursor") or ""
        if not cursor:
            return markets


def fetch_series(series: str, suffix: str = "") -> pd.DataFrame:
    """All settled markets for a series, live and historical, deduped by ticker."""
    with httpx.Client(timeout=30) as client:
        live = _paged_markets(
            client, "/markets", {"series_ticker": series, "status": "settled"}
        )
        historical = _paged_markets(
            client, "/historical/markets", {"series_ticker": series}
        )
    df = pd.DataFrame(live + historical)
    if df.empty:
        return df
    df = df.drop_duplicates("ticker", keep="first")
    if suffix:
        df = df[df["ticker"].str.endswith(suffix)]
    for col in KEEP:
        if col not in df:
            df[col] = None
    df = df[KEEP].copy()
    for col in ("open_time", "close_time", "settlement_ts"):
        df[col] = pd.to_datetime(df[col], utc=True, format="ISO8601")
    for col in (
        "floor_strike",
        "cap_strike",
        "settlement_value_dollars",
        "last_price_dollars",
        "volume_fp",
        "open_interest_fp",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("close_time").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("series")
    parser.add_argument("--suffix", default="", help="keep only tickers ending with this")
    args = parser.parse_args()

    df = fetch_series(args.series, args.suffix)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = args.series + args.suffix.replace("-", "_")
    path = OUT_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    if df.empty:
        print(f"{args.series}: no settled markets")
        return
    print(
        f"{args.series}: {len(df)} markets, "
        f"{df['close_time'].min():%Y-%m-%d} -> {df['close_time'].max():%Y-%m-%d}, "
        f"results {df['result'].value_counts().to_dict()} -> {path}"
    )


if __name__ == "__main__":
    main()
