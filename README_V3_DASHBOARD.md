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
export WEB_APP_V3_SECRET_KEY='<LONG_RANDOM_SECRET>'
export WEB_APP_V3_AUTH_EMAIL='you@example.com'
export WEB_APP_V3_AUTH_PASSWORD_HASH='<werkzeug_password_hash>'
# optional (defaults to false for local http):
# export WEB_APP_V3_COOKIE_SECURE=1
# VM stability options for /predict:
# export WEB_APP_V3_GEMINI_USE_SEARCH=0
# export WEB_APP_V3_GEMINI_MAX_RETRIES=1
# export WEB_APP_V3_EDGE_CASE_ENABLED=0
python3 web_app_v3.py
```

Open: `http://localhost:8001`

Generate a password hash:

```bash
python3 -c "from werkzeug.security import generate_password_hash as g; print(g('your_password_here'))"
```

You can also configure multiple users:

```bash
export WEB_APP_V3_AUTH_USERS='{"alice@example.com":"<hash1>","bob@example.com":"<hash2>"}'
```

## Routes

- `GET|POST /login` -> Login screen
- `POST /logout` -> End session
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
