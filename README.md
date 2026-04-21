# portfo
https://larahrc.pythonanywhere.com
A personal portfolio site built with Flask, hosted on PythonAnywhere.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Home / landing page |
| `/projects` | Project showcase |
| `/education` | Education history |
| `/work` | Work experience |
| `/space` | Live space weather dashboard |

## Space Weather Dashboard

The `/space` page pulls real-time data from NOAA APIs:

- Solar wind speed, density, and Bz/Bt values
- Current and historical Kp index
- NOAA geomagnetic (G), solar radiation (S), and radio blackout (R) scales
- Aurora visibility estimate
- Active space weather alerts

Data is cached to `static/data/space_weather_cache.json` and refreshed automatically if stale (>2 hours). A manual refresh button on the page triggers `/space/refresh` to fetch fresh data on demand.

On PythonAnywhere's free tier, a scheduled task keeps the cache warm so live fetches are a fallback only.

## Setup

```bash
# Clone the repo
git clone <repo-url>
cd portfo

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run locally
flask run
```

## Project Structure

```
portfo/
├── app.py                  # Flask app and routes
├── space_weather.py        # NOAA data fetcher and cache logic
├── requirements.txt
├── static/
│   ├── css/styles.css
│   ├── data/
│   │   └── space_weather_cache.json
│   └── img/
└── templates/
    ├── base.html
    ├── home.html
    ├── projects.html
    ├── education.html
    ├── work.html
    └── space.html
```

## Tech Stack

- **Backend:** Python / Flask
- **Templating:** Jinja2
- **Data:** NOAA Space Weather APIs
- **Hosting:** PythonAnywhere
