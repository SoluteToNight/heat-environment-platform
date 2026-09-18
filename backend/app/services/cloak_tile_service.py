"""CloakBrowser Tile Interception & Binary Memory Decoder Service.

Automates CloakBrowser to navigate QWeather map layers, intercepts raw weather tiles
without consuming API quota, decodes IEEE-754 headers and pixel values into physical fields
(temperature, relative humidity, wind speed, dew point, solar radiation).
"""

import io
import json
import logging
import math
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates

logger = logging.getLogger(__name__)

TILE_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "forecast_cache" / "tiles"


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


def capture_tiles_with_cloak(
    headless: bool = True,
    timeout_ms: int = 30000,
    force_refresh: bool = False
) -> dict[str, dict]:
    """Launch CloakBrowser, simulate layer switches, and intercept live tiles."""
    TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    meta_cache_file = TILE_CACHE_DIR / "tile_metadata_latest.json"

    # Check if cached tile exists from within last 1 hour
    if meta_cache_file.exists() and not force_refresh:
        try:
            with open(meta_cache_file, "r", encoding="utf-8") as f:
                cached_meta = json.load(f)
            cached_time = datetime.fromisoformat(cached_meta.get("captured_at", "2000-01-01T00:00:00+00:00"))
            age_sec = (datetime.now(timezone.utc) - cached_time).total_seconds()
            if age_sec < 3600:  # Fresh within 1h
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
                            "y": info["y"]
                        }
                if result:
                    return result
        except Exception as e:
            logger.warning("Failed to load cached tile metadata: %s", e)

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
        if "tiles.qweather.com/data" in url and url.endswith(".jpg"):
            layer_code = url.split("/")[-1].replace(".jpg", "")
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
                intercepted[layer_code] = {"url": url, "body": body}

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
            "y": y
        }

        # Cache binary to disk
        (TILE_CACHE_DIR / f"{key}.bin").write_bytes(data["body"])
        saved_meta["tiles"][key] = {
            "url": data["url"],
            "z": z, "x": x, "y": y,
            "size": len(data["body"])
        }

    with open(meta_cache_file, "w", encoding="utf-8") as f:
        json.dump(saved_meta, f, ensure_ascii=False, indent=2)

    logger.info("Intercepted and cached %d tile layers from CloakBrowser", len(output_tiles))
    return output_tiles
