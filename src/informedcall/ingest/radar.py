"""Summarize NEXRAD radar composites around a point, without storing the images.

Iowa Mesonet archives a national base-reflectivity composite every 5 minutes as an 8-bit PNG
(pixel = 0.005 degrees, origin at 126W 50N, dBZ = 0.5 * value - 32). For each requested time this
downloads the image, measures how much of the area around the point shows rain in distance rings
and compass sectors, and keeps only those numbers.

    uv run python -m informedcall.ingest.radar nyc --lat 40.78 --lon -73.97 --start 2025-01-01
"""

import argparse
import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

URL = "https://mesonet.agron.iastate.edu/archive/data/{y}/{m}/{d}/GIS/uscomp/n0q_{stamp}.png"
OUT_DIR = Path("data/raw/radar")
ORIGIN_LON, ORIGIN_LAT, PIXEL = -126.0, 50.0, 0.005
RAIN_DBZ = 20.0
RINGS_KM = [0, 15, 50, 100, 200]
SECTORS = ["N", "E", "S", "W"]
HOURS_LST = [8, 11, 14]
LST_OFFSET = 5
WORKERS = 8
MAX_BACK_STEPS = 6  # composites are 5-minutely; fall back up to 30 minutes if one is missing


def _download(client: httpx.Client, ts: pd.Timestamp) -> bytes | None:
    for step in range(MAX_BACK_STEPS):
        t = ts - pd.Timedelta(minutes=5 * step)
        url = URL.format(y=t.year, m=f"{t.month:02d}", d=f"{t.day:02d}", stamp=t.strftime("%Y%m%d%H%M"))
        for attempt in range(3):
            try:
                resp = client.get(url)
            except httpx.HTTPError:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 200:
                return resp.content
            if resp.status_code == 404:
                break
            time.sleep(2 ** attempt)
    return None


def _grid(lat: float, lon: float, half_deg: float = 2.0):
    """Pixel window around the point, with each pixel's distance (km) and bearing sector."""
    x0, x1 = int((lon - half_deg - ORIGIN_LON) / PIXEL), int((lon + half_deg - ORIGIN_LON) / PIXEL)
    y0, y1 = int((ORIGIN_LAT - (lat + half_deg)) / PIXEL), int((ORIGIN_LAT - (lat - half_deg)) / PIXEL)
    xs = ORIGIN_LON + (np.arange(x0, x1) + 0.5) * PIXEL
    ys = ORIGIN_LAT - (np.arange(y0, y1) + 0.5) * PIXEL
    dx = (xs[None, :] - lon) * 111.32 * np.cos(np.radians(lat))
    dy = (ys[:, None] - lat) * 110.57
    dist = np.hypot(dx, dy)
    bearing = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
    sector = np.select(
        [(bearing >= 315) | (bearing < 45), (bearing >= 45) & (bearing < 135), (bearing >= 135) & (bearing < 225)],
        [0, 1, 2],
        default=3,
    )
    return (x0, x1, y0, y1), dist, sector


def summarize(png: bytes, window, dist, sector) -> dict:
    x0, x1, y0, y1 = window
    img = Image.open(io.BytesIO(png))
    values = np.asarray(img)[y0:y1, x0:x1]
    dbz = values.astype(np.float32) * 0.5 - 32.0
    wet = dbz >= RAIN_DBZ
    out = {}
    for lo, hi in zip(RINGS_KM[:-1], RINGS_KM[1:]):
        ring = (dist >= lo) & (dist < hi)
        out[f"wet_{lo}_{hi}"] = float(wet[ring].mean())
        out[f"max_{lo}_{hi}"] = float(dbz[ring].max())
        for i, name in enumerate(SECTORS):
            cell = ring & (sector == i)
            out[f"wet_{lo}_{hi}_{name}"] = float(wet[cell].mean()) if cell.any() else 0.0
    return out


def decision_times(start: date, end: date) -> list[pd.Timestamp]:
    days = pd.date_range(start, end, freq="D")
    return [pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=LST_OFFSET + h) for d in days for h in HOURS_LST]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--limit", type=int, default=0, help="cap images (for testing)")
    args = parser.parse_args()

    window, dist, sector = _grid(args.lat, args.lon)
    path = OUT_DIR / f"{args.name}_features.parquet"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    seen = set(done["ts"]) if len(done) else set()
    times = [t for t in decision_times(args.start, args.end) if t not in seen]
    if args.limit:
        times = times[: args.limit]
    print(f"{args.name}: {len(times)} images to fetch ({len(seen)} done)", flush=True)

    rows: list[dict] = []
    missing = 0

    def work(ts: pd.Timestamp) -> dict | None:
        png = _download(client, ts)
        return None if png is None else {"ts": ts, **summarize(png, window, dist, sector)}

    def save() -> None:
        frames = ([done] if len(done) else []) + ([pd.DataFrame(rows)] if rows else [])
        pd.concat(frames, ignore_index=True).to_parquet(path, index=False)

    limits = httpx.Limits(max_connections=WORKERS)
    with httpx.Client(timeout=60, limits=limits) as client, ThreadPoolExecutor(WORKERS) as pool:
        for i, result in enumerate(pool.map(work, times), 1):
            if result is None:
                missing += 1
            else:
                rows.append(result)
            if i % 200 == 0:
                save()
                print(f"  {i}/{len(times)} images, {missing} missing", flush=True)
    save()
    print(f"done: {len(rows)} fetched, {missing} missing -> {path}", flush=True)


if __name__ == "__main__":
    main()
