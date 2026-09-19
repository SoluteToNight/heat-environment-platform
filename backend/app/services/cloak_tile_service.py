"""CloakBrowser Tile Interception & Binary Memory Decoder Service.

Automates CloakBrowser to navigate QWeather map layers, intercepts raw weather tiles
without consuming API quota, decodes IEEE-754 headers and pixel values into physical fields
(temperature, relative humidity, wind speed, dew point, solar radiation).
"""

import io
import json
import logging
import math
import re
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates

logger = logging.getLogger(__name__)

TILE_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "forecast_cache" / "tiles"

# QWeather tile URL structure (verified 2026-09-19 against captured metadata):
#   .../data/{product}/{version}/{run YYYYMMDDHH}/{YYYY}/{MM}/{DD}/{HH}/{z}/{x}/{y}/{layer}.jpg
# e.g. https://tiles.qweather.com/data/g/2.0/2026091812/2026/09/19/01/2/3/1/rh-2m.jpg
# where 2026091812 is the model run time and 2026/09/19/01 the tile valid time.
# NOTE: the hour segment appears to be written in different timezone conventions per
# layer family (tmp-2m in local Beijing hours, rh/wind/dpt in UTC hours); record raw
# values without conversion. See docs/瓦片背景场时效与分辨率调查记录.md.
TILE_URL_PATTERN = re.compile(
    r"/data/(?P<product>[^/]+)/(?P<version>[^/]+)/(?P<run>\d{10})"
    r"/(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/(?P<hour>\d{2})"
    r"/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)/(?P<layer>[a-z0-9-]+)\.jpg$"
)


def parse_tile_url(url: str) -> dict | None:
    """Parse model run time, tile valid time and z/x/y out of a QWeather tile URL."""
    match = TILE_URL_PATTERN.search(url)
    if not match:
        return None
    g = match.groupdict()
    return {
        "run_time": g["run"],
        "valid_time": f"{g['year']}-{g['month']}-{g['day']}T{g['hour']}:00",
        "z": int(g["z"]),
        "x": int(g["x"]),
        "y": int(g["y"]),
    }


def decode_qweather_tile(content: bytes, variable_name: str) -> tuple[np.ndarray, dict]:
    """Universal decoder for QWeather public map tiles in memory."""
    img = Image.open(io.BytesIO(content))
    pixels = np.asarray(img.convert("RGBA"))
    raw = pixels.ravel()

    # Decode 28 bytes header starting at offset 4128 with stride 32
    header = bytearray()
    for idx in range(28):
        offset = 4128 + idx * 32
        channels = raw[offset:offset + 3].astype(float)
        red, green, blue = np.rint(channels / [64, 16, 64]).astype(int)
        header.append((red << 6) | (green << 2) | blue)

    params = struct.unpack("<7f", header)
    min_val, max_val = params[:2]

    # Extract 257x257 data grid
    data_x, data_y = 0, 8
    w, h = 257, 257
    codes = pixels[data_y:data_y + h, data_x:data_x + w, 0]
    values = codes.astype(float) * ((max_val - min_val) / 255.0) + min_val

    # Variable-specific conversions
    if variable_name in ("tmp", "dpt", "temperature_2m", "dew_point"):
        # Kelvin to Celsius
        values = values - 273.15
        unit = "°C"
    elif variable_name in ("rh", "relative_humidity_2m"):
        unit = "%"
    elif variable_name in ("wind", "wind_speed_10m"):
        unit = "m/s"
    elif variable_name in ("asob", "solar_radiation"):
        unit = "W/m²"
    else:
        unit = "raw"

    return values, {
        "min": float(min_val),
        "max": float(max_val),
        "converted_min": float(np.nanmin(values)),
        "converted_max": float(np.nanmax(values)),
        "converted_mean": float(np.nanmean(values)),
        "unit": unit
    }


def sample_tile_at_coords(
    values: np.ndarray,
    z: int,
    x: int,
    y: int,
    coords: list[tuple[float, float]]
) -> np.ndarray:
    """Bilinear sample from tile matrix at given [(lon, lat), ...] coordinates."""
    tile_count = 2 ** z
    w = values.shape[1] - 1
    h = values.shape[0] - 1

    cols = []
    rows = []
    for lon, lat in coords:
        c = ((lon + 180.0) / 360.0 * tile_count - x) * w
        r = ((1.0 - np.arcsinh(np.tan(np.deg2rad(lat))) / np.pi) / 2.0 * tile_count - y) * h
        cols.append(c)
        rows.append(r)

    sampled = map_coordinates(values, [rows, cols], order=1, mode="nearest")
    return sampled


def load_cached_tiles(max_age_seconds: int = 3600) -> dict[str, dict] | None:
    """Read tiles from the disk cache only; never launch a browser.

    Returns the tile dict (url/body/z/x/y per layer) when a fresh capture exists,
    otherwise None. Safe to call inside request handlers.
    """
    meta_cache_file = TILE_CACHE_DIR / "tile_metadata_latest.json"
    if not meta_cache_file.exists():
        return None
    try:
        with open(meta_cache_file, "r", encoding="utf-8") as f:
            cached_meta = json.load(f)
        cached_time = datetime.fromisoformat(cached_meta.get("captured_at", "2000-01-01T00:00:00+00:00"))
        age_sec = (datetime.now(timezone.utc) - cached_time).total_seconds()
        if age_sec >= max_age_seconds:
            return None
        logger.info("Using cached CloakBrowser tiles (age: %.1f min)", age_sec / 60)
        result = {}
        for var, info in cached_meta.get("tiles", {}).items():
            tile_path = TILE_CACHE_DIR / f"{var}.bin"
            if tile_path.exists():
                result[var] = {
                    "url": info["url"],
                    "body": tile_path.read_bytes(),
                    "z": info["z"],
                    "x": info["x"],
                    "y": info["y"],
                    "run_time": info.get("run_time"),
                    "valid_time": info.get("valid_time"),
                }
        return result or None
    except Exception as e:
        logger.warning("Failed to load cached tile metadata: %s", e)
        return None


def capture_tiles_with_cloak(
    headless: bool = True,
    timeout_ms: int = 30000,
    force_refresh: bool = False
) -> dict[str, dict]:
    """Launch CloakBrowser, simulate layer switches, and intercept live tiles.

    Heavy operation (browser automation, up to tens of seconds): only call from
    background tasks or the explicit maintenance endpoint, never from map/adjustment
    query handlers — those must use :func:`load_cached_tiles` instead.
    """
    TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    meta_cache_file = TILE_CACHE_DIR / "tile_metadata_latest.json"

    if not force_refresh:
        cached = load_cached_tiles()
        if cached:
            return cached

    import cloakbrowser

    profile_dir = Path("cloakbrowser-profile")
    profile_dir.mkdir(exist_ok=True)

    logger.info("Launching CloakBrowser to intercept QWeather weather map tiles...")
    context = cloakbrowser.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1440, "height": 900}
    )
    page = context.pages[0] if context.pages else context.new_page()

    intercepted = {}

    def on_res(res):
        url = res.url
        if "tiles.qweather.com/data" not in url or not url.endswith(".jpg"):
            return
        layer_code = url.split("/")[-1].replace(".jpg", "")
        parsed = parse_tile_url(url)
        # The same layer is requested at several zoom levels (including low-zoom
        # ancestor tiles of the target tile). Keep the highest-zoom response per
        # layer; a later coarse ancestor must not overwrite a detailed city tile.
        existing = intercepted.get(layer_code)
        if parsed and existing and existing.get("parsed") and parsed["z"] < existing["parsed"]["z"]:
            return
        body = b""
        try:
            if res.ok:
                body = res.body()
        except Exception:
            pass
        if not body:
            import urllib.request
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ShanghaiHeatResearch/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    body = resp.read()
            except Exception:
                pass
        if body:
            intercepted[layer_code] = {"url": url, "body": body, "parsed": parsed}

    page.on("response", on_res)

    target_url = "https://map.qweather.com/?lat=31.23&lon=121.47&level=8&layer=tmp"
    page.goto(target_url, wait_until="networkidle", timeout=timeout_ms)
    time.sleep(2)

    # Switch layers to trigger tile requests
    layers = [("rh", "rh"), ("wind", "wind"), ("dpt", "dpt"), ("asob", "asob"), ("tmp", "tmp")]
    for lid, _ in layers:
        try:
            page.click(f"#{lid}")
            time.sleep(1.5)
        except Exception as e:
            logger.warning("Failed to click layer switch #%s: %s", lid, e)

    context.close()

    # Parse tiles and save to cache
    output_tiles = {}
    saved_meta = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "tiles": {}
    }

    for key, data in intercepted.items():
        parsed = data.get("parsed")
        if parsed:
            z, x, y = parsed["z"], parsed["x"], parsed["y"]
        else:
            # Parse z, x, y from URL
            parts = data["url"].split("/")
            filename = parts[-1]
            try:
                file_idx = parts.index(filename)
                y = int(parts[file_idx - 1])
                x = int(parts[file_idx - 2])
                z = int(parts[file_idx - 3])
            except Exception:
                z, x, y = 8, 214, 106  # Default Shanghai level 8 tile coordinates

        output_tiles[key] = {
            "url": data["url"],
            "body": data["body"],
            "z": z,
            "x": x,
            "y": y,
            "run_time": parsed["run_time"] if parsed else None,
            "valid_time": parsed["valid_time"] if parsed else None,
        }

        # Cache binary to disk
        (TILE_CACHE_DIR / f"{key}.bin").write_bytes(data["body"])
        saved_meta["tiles"][key] = {
            "url": data["url"],
            "z": z, "x": x, "y": y,
            "run_time": parsed["run_time"] if parsed else None,
            "valid_time": parsed["valid_time"] if parsed else None,
            "size": len(data["body"])
        }

    with open(meta_cache_file, "w", encoding="utf-8") as f:
        json.dump(saved_meta, f, ensure_ascii=False, indent=2)

    logger.info("Intercepted and cached %d tile layers from CloakBrowser", len(output_tiles))
    return output_tiles
