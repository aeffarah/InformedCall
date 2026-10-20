"""Pull archived day-ahead forecasts from Open-Meteo's Previous Runs API.

`*_previous_day1` is what a model predicted one day earlier, i.e. what a trader could have
known the day before. Archive coverage starts around 2024-01 and varies by model.

    uv run python -m informedcall.ingest.forecasts nyc --lat 40.7794 --lon -73.9692
"""

import argparse
import time
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
OUT_DIR = Path("data/raw/forecasts")
MODELS = ["gfs_seamless", "ecmwf_ifs025", "ncep_nbm_conus"]
VARIABLES = ["temperature_2m_previous_day1", "precipitation_previous_day1"]
START = date(2024, 1, 1)

# NWS climate days run midnight to midnight local *standard* time, so in summer the
# window is 1am to 1am daylight time. Offsets are hours behind UTC.
STANDARD_UTC_OFFSET = {"nyc": -5, "miami": -5, "la": -8, "sf": -8}


def _get(client: httpx.Client, params: dict) -> dict:
    for attempt in range(5):
        resp = client.get(URL, params=params)
        if resp.status_code == 429:
            time.sleep(2 ** (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Rate limited by Open-Meteo")


def fetch_hourly(lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    """Hourly UTC forecasts, one column per variable and model."""
    frames = []
    with httpx.Client(timeout=120) as client:
        for year in range(start.year, end.year + 1):
            lo = max(start, date(year, 1, 1))
            hi = min(end, date(year, 12, 31))
            data = _get(
                client,
                {
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": ",".join(VARIABLES),
                    "models": ",".join(MODELS),
                    "start_date": lo.isoformat(),
                    "end_date": hi.isoformat(),
                    "timezone": "UTC",
                },
            )
            frames.append(pd.DataFrame(data["hourly"]))
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def daily_highs_f(hourly: pd.DataFrame, utc_offset: int) -> pd.DataFrame:
    """Forecast daily high in °F per model, over the NWS climate day.

    Hourly values understate a true daily maximum, so expect a small cold bias that
    calibration against the observed highs should absorb.
    """
    shifted = hourly.assign(day=(hourly["time"] + pd.Timedelta(hours=utc_offset)).dt.date)
    cols = [c for c in hourly if c.startswith("temperature_2m_previous_day1")]
    daily = shifted.groupby("day")[cols].agg(["max", "count"])
    out = pd.DataFrame(index=daily.index)
    for col in cols:
        full_day = daily[(col, "count")] >= 24
        celsius = daily[(col, "max")].where(full_day)
        model = col.removeprefix("temperature_2m_previous_day1_")
        out[f"high_f_{model}"] = celsius * 9 / 5 + 32
    return out.rename_axis("day").reset_index()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="short location name, e.g. nyc")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    hourly = fetch_hourly(args.lat, args.lon, args.start, args.end)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{args.name}_hourly.parquet"
    hourly.to_parquet(path, index=False)
    print(f"{args.name}: {len(hourly)} hourly rows, {hourly['time'].min()} -> {hourly['time'].max()} -> {path}")
    for col in hourly.columns.drop("time"):
        valid = hourly[col].dropna()
        first = hourly.loc[valid.index[0], "time"] if len(valid) else None
        print(f"  {col}: {len(valid)} non-null, first {first}")


if __name__ == "__main__":
    main()
