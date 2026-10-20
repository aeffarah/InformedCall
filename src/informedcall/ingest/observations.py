"""Pull hourly surface temperature observations from the Iowa Environmental Mesonet.

Routine and special METAR reports for an ASOS station, in UTC. The intraday backtest uses them
for the temperature so far on the event day. Readings are whole degrees F.

    uv run python -m informedcall.ingest.observations NYC --start 2024-01-01
    uv run python -m informedcall.ingest.observations NYC --start 2025-01-01 --one-minute

One-minute data (the archive starts around 2025-01, with gaps) shows the running maximum the way
a trader watching the station would, which hourly readings miss.
"""

import argparse
import io
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
ONE_MINUTE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py"
OUT_DIR = Path("data/raw/obs")


def fetch_station(station: str, start: date, end: date, variable: str = "tmpf") -> pd.DataFrame:
    """Hourly METAR values of one variable (tmpf, or p01i for last-hour precipitation in inches)."""
    frames = []
    with httpx.Client(timeout=180) as client:
        for year in range(start.year, end.year + 1):
            lo = max(start, date(year, 1, 1))
            hi = min(end, date(year, 12, 31))
            params = [
                ("station", station), ("data", variable), ("tz", "UTC"), ("format", "onlycomma"),
                ("latlon", "no"), ("missing", "empty"), ("trace", "0.0001"), ("direct", "no"),
                ("year1", lo.year), ("month1", lo.month), ("day1", lo.day),
                ("year2", hi.year), ("month2", hi.month), ("day2", hi.day),
                ("report_type", 3), ("report_type", 4),
            ]
            resp = client.get(URL, params=params)
            resp.raise_for_status()
            frames.append(pd.read_csv(io.StringIO(resp.text)))
    df = pd.concat(frames, ignore_index=True)
    df["valid"] = pd.to_datetime(df["valid"], utc=True)
    df[variable] = pd.to_numeric(df[variable], errors="coerce")
    return df.dropna(subset=[variable]).drop_duplicates(["valid"]).sort_values("valid").reset_index(drop=True)


def fetch_one_minute(station: str, start: date, end: date) -> pd.DataFrame:
    """One-minute temperatures, fetched a month at a time."""
    frames = []
    months = pd.period_range(start, end, freq="M")
    with httpx.Client(timeout=300) as client:
        for month in months:
            lo = max(pd.Timestamp(start), month.start_time)
            hi = min(pd.Timestamp(end) + pd.Timedelta(days=1), month.end_time.ceil("D"))
            params = {
                "station": station, "vars": "tmpf", "sample": "1min", "what": "download",
                "delim": "comma", "gis": "no",
                "sts": lo.strftime("%Y-%m-%dT%H:%MZ"), "ets": hi.strftime("%Y-%m-%dT%H:%MZ"),
            }
            resp = client.get(ONE_MINUTE_URL, params=params)
            resp.raise_for_status()
            if len(resp.text.splitlines()) > 1:
                frames.append(pd.read_csv(io.StringIO(resp.text)))
    df = pd.concat(frames, ignore_index=True).rename(columns={"valid(UTC)": "valid"})
    df["valid"] = pd.to_datetime(df["valid"], utc=True)
    df["tmpf"] = pd.to_numeric(df["tmpf"], errors="coerce")
    return df[["station", "valid", "tmpf"]].dropna(subset=["tmpf"]).drop_duplicates("valid").sort_values("valid").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("station")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--one-minute", action="store_true", help="pull one-minute data instead of hourly")
    parser.add_argument("--variable", default="tmpf", help="hourly variable, e.g. tmpf or p01i")
    args = parser.parse_args()

    if args.one_minute:
        df = fetch_one_minute(args.station, args.start, args.end)
    else:
        df = fetch_station(args.station, args.start, args.end, args.variable)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "1min" if args.one_minute else ("asos" if args.variable == "tmpf" else args.variable)
    path = OUT_DIR / f"{args.station.lower()}_{suffix}.parquet"
    df.to_parquet(path, index=False)
    print(f"{args.station}: {len(df)} readings, {df['valid'].min()} -> {df['valid'].max()} -> {path}")


if __name__ == "__main__":
    main()
