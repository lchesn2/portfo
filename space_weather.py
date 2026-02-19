"""
space_weather.py
================
Fetches real-time space weather data from NOAA SWPC public JSON APIs
and caches the result to a local JSON file that space.html reads from.

NOAA endpoints used (all free, no API key required):
  - Solar wind plasma  : https://services.swpc.noaa.gov/products/solar-wind/plasma-2-hour.json
  - Solar wind mag     : https://services.swpc.noaa.gov/products/solar-wind/mag-2-hour.json
  - Kp index           : https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json
  - NOAA storm scales  : https://services.swpc.noaa.gov/products/noaa-scales.json
  - Alerts             : https://services.swpc.noaa.gov/products/alerts.json
  - 3-day forecast     : https://services.swpc.noaa.gov/text/3-day-forecast.txt

PythonAnywhere setup:
  - Add a Scheduled Task: python /path/to/space_weather.py
  - Run every hour (or every 10 min on paid plan)
  - The output file space_weather_cache.json is read by your Flask route
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Config ─────────────────────────────────────────────────────────────────

CACHE_FILE = Path(__file__).parent / "static" / "data" / "space_weather_cache.json"
REQUEST_TIMEOUT = 10  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── NOAA API endpoints ──────────────────────────────────────────────────────

ENDPOINTS = {
    "plasma":   "https://services.swpc.noaa.gov/products/solar-wind/plasma-2-hour.json",
    "mag":      "https://services.swpc.noaa.gov/products/solar-wind/mag-2-hour.json",
    "kp":       "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
    "scales":   "https://services.swpc.noaa.gov/products/noaa-scales.json",
    "alerts":   "https://services.swpc.noaa.gov/products/alerts.json",
}


# ── Fetch helpers ───────────────────────────────────────────────────────────

def fetch_json(url: str) -> list | dict | None:
    """Fetch a NOAA JSON endpoint. Returns parsed data or None on failure."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None


# ── Parsers ─────────────────────────────────────────────────────────────────

def parse_solar_wind(plasma_raw: list, mag_raw: list) -> dict:
    """
    Extract latest solar wind speed, density, and Bz from NOAA arrays.
    Row format (plasma): [time, density, speed, temperature]
    Row format (mag):    [time, bx, by, bz, bt, lat, lon]
    First row is always the header — skip it.
    Also builds a timeseries sampled every ~10 rows for the trend chart.
    """
    result = {
        "speed": None, "density": None, "bz": None, "bt": None,
        "timestamp": None, "timeseries": []
    }

    if plasma_raw:
        # Latest reading
        for row in reversed(plasma_raw[1:]):
            try:
                result["density"]   = round(float(row[1]), 1)
                result["speed"]     = round(float(row[2]), 0)
                result["timestamp"] = row[0]
                break
            except (TypeError, ValueError, IndexError):
                continue

        # Timeseries — take ALL valid rows (2-hour endpoint is small, ~24-100 rows)
        for row in plasma_raw[1:]:
            try:
                spd = float(row[2])
                if spd > 0:
                    result["timeseries"].append({
                        "time":  row[0],
                        "speed": round(spd, 0),
                    })
            except (TypeError, ValueError, IndexError):
                continue
        # Thin to max 60 pts if needed
        if len(result["timeseries"]) > 60:
            step = max(1, len(result["timeseries"]) // 60)
            result["timeseries"] = result["timeseries"][::step]

    if mag_raw:
        for row in reversed(mag_raw[1:]):
            try:
                result["bz"] = round(float(row[3]), 1)
                result["bt"] = round(float(row[4]), 1)
                break
            except (TypeError, ValueError, IndexError):
                continue

    return result


def parse_kp(kp_raw: list) -> dict:
    """
    Extract current and recent Kp values.
    Row format: [time, kp]
    Returns the latest Kp and the last 8 readings for the bar chart.
    """
    result = {"current": None, "history": []}

    if not kp_raw:
        return result

    rows = kp_raw[1:]  # skip header
    readings = []
    for row in rows:
        try:
            readings.append({
                "time": row[0],
                "kp":   float(row[1])
            })
        except (TypeError, ValueError, IndexError):
            continue

    if readings:
        result["current"] = readings[-1]["kp"]
        result["history"] = readings[-24:]  # last 24 for chart

    return result


def parse_scales(scales_raw: dict) -> dict:
    """
    Extract current G/S/R storm scale levels.
    The scales endpoint returns a dict keyed by scale name.
    Example: {"G": {"Scale": "G0", "Text": "None"}, ...}
    """
    result = {"G": {"scale": "G0", "label": "Quiet"},
              "S": {"scale": "S0", "label": "None"},
              "R": {"scale": "R0", "label": "None"}}

    if not scales_raw:
        return result

    # NOAA returns the current 24h max — key is "0" for current
    current = scales_raw.get("0", {})
    for key in ["G", "S", "R"]:
        entry = current.get(key, {})
        scale = entry.get("Scale", f"{key}0")
        text  = entry.get("Text", "None")
        result[key] = {"scale": scale, "label": text}

    return result


def parse_alerts(alerts_raw: list) -> list:
    """
    Extract the 5 most recent space weather alerts and parse the
    structured bulletin format into clean fields.

    NOAA alert messages look like:
        Space Weather Message Code: WARK04
        Serial Number: 5262
        Issue Time: 2026 Feb 19 0205 UTC

        WARNING: Geomagnetic K-index of 4 expected
        Valid From: 2026 Feb 19 0205 UTC
        Valid To: 2026 Feb 19 0900 UT
        ...
        NOAA Space Weather Scale descriptions can be found at
        www.swpc.noaa.gov/noaa-scales-explanation

        Potential Impacts: ...

    We extract: headline (the WARNING/ALERT/WATCH line) + impacts line.
    """
    if not alerts_raw:
        return []

    alerts = []
    for item in alerts_raw[:5]:
        raw = item.get("message", "")
        product_id = item.get("product_id", "")
        issue_time = item.get("issue_datetime", "")

        # Pull the headline — first line starting with WARNING/ALERT/WATCH/SUMMARY
        headline = ""
        impacts = ""
        for line in raw.splitlines():
            line = line.strip()
            if not headline and any(
                line.startswith(kw)
                for kw in ("WARNING:", "ALERT:", "WATCH:", "SUMMARY:", "CONTINUED")
            ):
                headline = line
            if line.startswith("Potential Impacts:"):
                impacts = line.replace("Potential Impacts:", "").strip()

        # Fallback: use first non-empty, non-header line
        if not headline:
            for line in raw.splitlines():
                line = line.strip()
                if line and not any(
                    line.startswith(kw)
                    for kw in ("Space Weather", "Serial", "Issue Time", "NOAA")
                ):
                    headline = line
                    break

        alerts.append({
            "product_id": product_id,
            "issue_time": issue_time,
            "headline":   headline,
            "impacts":    impacts,
        })

    return alerts


def aurora_visibility(kp: float | None) -> dict:
    """
    Map Kp index to aurora visibility description.
    Based on NOAA's own Kp → latitude table.
    """
    if kp is None:
        return {"label": "Unknown", "latitude": None}

    table = [
        (9, "Equatorial regions (< 40°)"),
        (8, "Mid-latitudes (< 45°)"),
        (7, "Mid-latitudes (< 50°)"),
        (6, "Mid-latitudes (< 55°)"),
        (5, "Mid-latitudes (< 60°)"),
        (4, "High latitudes (< 65°)"),
        (3, "High latitudes (< 65°)"),
        (2, "Sub-auroral zone (> 65°)"),
        (1, "Polar regions only (> 70°)"),
        (0, "Not visible"),
    ]
    for threshold, label in table:
        if kp >= threshold:
            return {"label": label, "latitude": threshold}
    return {"label": "Not visible", "latitude": None}


# ── Main fetch & cache ───────────────────────────────────────────────────────

def fetch_all() -> dict:
    """Fetch all NOAA endpoints and return a structured payload."""
    log.info("Fetching NOAA SWPC data...")

    plasma_raw  = fetch_json(ENDPOINTS["plasma"])
    mag_raw     = fetch_json(ENDPOINTS["mag"])
    kp_raw      = fetch_json(ENDPOINTS["kp"])
    scales_raw  = fetch_json(ENDPOINTS["scales"])
    alerts_raw  = fetch_json(ENDPOINTS["alerts"])

    solar_wind = parse_solar_wind(plasma_raw, mag_raw)
    kp         = parse_kp(kp_raw)
    scales     = parse_scales(scales_raw)
    alerts     = parse_alerts(alerts_raw)
    aurora     = aurora_visibility(kp["current"])

    payload = {
        "fetched_at":  datetime.now(timezone.utc).isoformat(),
        "solar_wind":  solar_wind,
        "kp":          kp,
        "scales":      scales,
        "aurora":      aurora,
        "alerts":      alerts,
    }

    log.info(
        "Done — wind: %s km/s  Bz: %s nT  Kp: %s  G-scale: %s",
        solar_wind["speed"],
        solar_wind["bz"],
        kp["current"],
        scales["G"]["scale"],
    )
    return payload


def write_cache(payload: dict) -> None:
    """Write payload to the static data cache file."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    log.info("Cache written → %s", CACHE_FILE)


def load_cache() -> dict | None:
    """Read cache file. Returns None if missing or malformed."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    payload = fetch_all()
    write_cache(payload)