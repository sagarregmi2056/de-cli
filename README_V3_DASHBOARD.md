# Destiny Engine Dashboard

Standalone dashboard that does not modify existing `web_app.py` routes.

## What it now includes

- `Markets` tab
  - Search by team/title/winner/slug/source ID
  - Result filter (`won`, `lost`, `pending`, `void`, `unknown`)
  - Table with predicted winner, prediction gap, market odds, expected outcome, resolved outcome, and investment flag
- `Analytics` tab
  - Right/wrong stats
  - Invested market types
  - Odds bucket performance
  - Prediction score-difference (gap) metrics and buckets
  - Market-type performance table
  - Visuals: pie chart, status bars, and gap curve for won/lost predictions
- `Predict URL` tab
  - Paste Polymarket URL
  - Run structured extraction + prediction
  - Save to v3 DB
  - Auto-attach to resolution tracking
  - Show recent saved predictions and current resolution status

## Run

```bash
cd cli-app
python3 web_app_v3.py
```

Open: `http://localhost:8001`

## Routes

- `GET /` -> Markets tab
- `GET /analytics` -> Analytics tab
- `GET|POST /predict` -> URL prediction tab
- `POST /api/auto-resolve` -> Re-check resolutions and update win/loss states

## DB setup for clean start

The v3 app reads from:

- `MONGO_URI` (default `mongodb://localhost:27017`)
- `MONGO_DB_NAME_V3` (default `debot_cli_v3`)

If you also want CLI scan/process output in the same clean DB:

```bash
MONGO_DB_NAME=debot_cli_v3 python3 main.py scan-markets
MONGO_DB_NAME=debot_cli_v3 python3 main.py process-markets
```
