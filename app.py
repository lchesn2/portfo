"""
app.py — space weather route snippet
=====================================
Add this to your existing app.py.
The route reads from the cache file written by space_weather.py.
If the cache is missing or stale (> 2 hours), it triggers a live fetch.
"""

from flask import Flask, render_template
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import time

try:
    from space_weather import fetch_all, write_cache, load_cache
    _space_weather_ok = True
except Exception:
    _space_weather_ok = False

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(24).hex()

_last_refresh: float = 0.0
_REFRESH_COOLDOWN = 60  # seconds


@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


def cache_is_stale(payload: dict, max_age_minutes: int = 120) -> bool:
    """Return True if the cache is older than max_age_minutes."""
    try:
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        age = datetime.now(timezone.utc) - fetched_at
        return age.total_seconds() > max_age_minutes * 60
    except (KeyError, ValueError):
        return True


@app.route("/space")
def space():
    """
    Serve the space weather dashboard.
    Reads from cache. If cache is missing or stale, fetches fresh data.
    On PythonAnywhere free tier, the scheduled task keeps cache fresh so
    live fetches here are just a safety net.
    """
    _unavailable = {
        "fetched_at": None,
        "solar_wind": {"speed": None, "density": None, "bz": None, "bt": None},
        "kp":         {"current": None, "history": []},
        "scales":     {
            "G": {"scale": "—", "label": "Unavailable"},
            "S": {"scale": "—", "label": "Unavailable"},
            "R": {"scale": "—", "label": "Unavailable"},
        },
        "aurora":  {"label": "Unavailable", "latitude": None},
        "alerts":  [],
    }

    if not _space_weather_ok:
        return render_template("space.html", sw=_unavailable)

    data = load_cache()

    if data is None or cache_is_stale(data):
        try:
            data = fetch_all()
            write_cache(data)
        except Exception as e:
            app.logger.error("Live fetch failed: %s", e)
            data = _unavailable

    return render_template("space.html", sw=data)


# ── Example: other existing routes (keep yours as-is) ───────────────────────


@app.route("/space/refresh", methods=["POST"])
def space_refresh():
    """
    Manual refresh endpoint — triggered by the refresh button on the dashboard.
    Fetches fresh NOAA data, writes cache, returns JSON so the button can
    update the badge label before the page reloads.
    """
    global _last_refresh
    if time.time() - _last_refresh < _REFRESH_COOLDOWN:
        return {"ok": False, "error": "Please wait before refreshing again."}, 429
    _last_refresh = time.time()

    try:
        data = fetch_all()
        write_cache(data)
        return {
            "ok":               True,
            "fetched_at":       data["fetched_at"],
            "solar_wind_speed": data["solar_wind"].get("speed"),
            "bz":               data["solar_wind"].get("bz"),
            "kp":               data["kp"].get("current"),
            "g_scale":          data["scales"]["G"].get("scale"),
        }
    except Exception as e:
        app.logger.error("Manual refresh failed: %s", e)
        return {"ok": False, "error": "Data refresh failed. Please try again."}, 500

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/projects")
def projects():
    return render_template("projects.html")

@app.route("/education")
def education():
    return render_template("education.html")

@app.route("/work")
def work():
    return render_template("work.html")