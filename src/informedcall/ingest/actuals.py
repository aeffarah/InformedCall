"""Pull NWS daily climate report (CLI) values from the Iowa Environmental Mesonet.

These are the same reports Kalshi's weather markets cite (e.g. CLINYC for station KNYC).
Precipitation is kept raw plus a trace flag, since Kalshi counts a trace as 0 inches.

    uv run python -m informedcall.ingest.actuals KNYC --start 2021
"""

import argparse
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

URL = "https://mesonet.agron.iastate.edu/json/cli.py"
OUT_DIR = Path("data/raw/actuals")

COLUMNS = ["station", "valid", "product", "high", "low", "precip", "snow"]


def _to_number(value) -> float | None:
    """CLI fields come back as numbers, or 'M' (missing) / 'T' (trace) strings."""
    if isinstance(value, (int, float)):
        return float(value)
    return None


def fetch_station(station: str, start_year: int, end_year: int) -> pd.DataFrame:
    rows: list[dict] = []
    with httpx.Client(timeout=60) as client:
        for year in range(start_year, end_year + 1):
            resp = client.get(URL, params={"station": station, "year": year})
            resp.raise_for_status()
            rows.extend(resp.json()["results"])
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["precip_raw"] = df["precip"].astype(str)
    df["precip_trace"] = df["precip_raw"].str.upper().eq("T")
    for col in ("high", "low", "precip", "snow"):
        df[col] = df[col].map(_to_number)
    df["valid"] = pd.to_datetime(df["valid"]).dt.date
    keep = [c for c in COLUMNS + ["precip_raw", "precip_trace"] if c in df]
    return df[keep].sort_values("valid").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("station")
    parser.add_argument("--start", type=int, default=2021)
    parser.add_argument("--end", type=int, default=date.today().year)
    args = parser.parse_args()

    df = fetch_station(args.station, args.start, args.end)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"cli_{args.station}.parquet"
    df.to_parquet(path, index=False)
    print(
        f"{args.station}: {len(df)} days, {df['valid'].min()} -> {df['valid'].max()}, "
        f"{int(df['precip_trace'].sum())} trace days, "
        f"{int((df['precip'].isna() & ~df['precip_trace']).sum())} missing precip -> {path}"
    )


if __name__ == "__main__":
    main()
