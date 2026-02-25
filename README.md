# DEBot CLI - Market Scanner & Investment Tool

A command-line tool for scanning Polymarket markets, processing them with Gemini AI, getting predictions, and automatically investing in the highest win probability outcome.

## Features

-  **Market Scanning**: Fetch upcoming markets from Polymarket API
-  **AI Processing**: Use Gemini to extract structured data (1v1 or Teams)
-  **Predictions**: Get win probability predictions from external API
-  **Auto-Investment**: Automatically buy the outcome with highest win % (configurable amount)
-  **Real-time Odds**: Display current market odds when viewing/processing markets
- **MongoDB Storage**: All data saved to MongoDB for later inspection

## Setup

### 1. Install Dependencies

```bash
cd cli-app
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**Required Variables:**
- `GEMINI_API_KEY` - Get from https://aistudio.google.com/app/apikey
- `MONGO_URI` - MongoDB connection string
- `MONGO_DB_NAME` - Database name

**Optional (for investment feature):**
- `POLYMARKET_PRIVATE_KEY` - Your wallet private key
- `POLYMARKET_FUNDER_ADDRESS` - Polymarket proxy address
- `POLYMARKET_SIGNATURE_TYPE` - 0=EOA, 1=Magic, 2=Browser Wallet
- `INVESTMENT_AMOUNT` - Amount to invest per market (default: 1.0)

## Usage

### Interactive Mode (Recommended)

```bash
python main.py interactive
```

This will:
1. Ask you to choose market type (1v1, Teams, or All)
2. Optionally scan for new markets
3. Process markets one by one with prompts
4. Show real-time odds for each market
5. After prediction, ask if you want to invest

### Scan Markets

```bash
python main.py scan-markets --limit 100 --max-batches 5
```

Fetches markets from Polymarket and saves to MongoDB.

### Process Markets

```bash
python main.py process-markets --max 10
```

Process stored markets (Gemini + Prediction API).

### Show Market Details

```bash
python main.py show-market --source-id <polymarket_id>
# or
python main.py show-market --mongo-id <mongodb_id>
```

Shows saved data and **real-time odds** for a market.

## How It Works

### Market Flow

1. **Scan**: Fetch markets from Polymarket API → Save to MongoDB
2. **Process**: 
   - Extract structured data with Gemini (1v1 or Teams)
   - Run edge case analysis
   - Get predictions from API
   - **Display real-time odds** from CLOB API
3. **Invest**: 
   - Find outcome with highest win %
   - Check if market is resolved (skip if 0% or 100%)
   - Prompt user: "Do you want to buy [Winner] for $X?"
   - If yes → Place order via CLOB API
   - Save investment result to MongoDB

### Real-time Odds

Odds are **always fetched in real-time** from the CLOB API when:
- Displaying markets in interactive mode
- Showing market details with `show-market` command
- Processing markets for investment

Odds are **not stored** in MongoDB because they change constantly.

## File Structure

```
cli-app/
├── main.py                 # CLI entry point
├── markets_scanner.py      # Market fetching from Polymarket
├── market_processor.py     # Gemini + Prediction + Investment flow
├── clob_client.py          # CLOB API client (trading)
├── gamma_client.py         # Gamma API client (token IDs)
├── gemini_clients.py       # Gemini AI clients
├── prediction_client.py    # Prediction API client
├── geo_enricher.py         # Geo-enrichment
├── db.py                   # MongoDB connection
├── config.py               # Configuration
├── ui_helpers.py           # UI utilities
├── test/                   # Test scripts
└── docs/                   # Documentation
```

## Environment Variables

See `.env.example` for all available options.

### Required
- `GEMINI_API_KEY`
- `MONGO_URI`
- `MONGO_DB_NAME`

### Optional
- `INVESTMENT_AMOUNT` - Default: 1.0
- `POLYMARKET_VOLUME_MIN` - Default: 500
- `POLYMARKET_END_DATE_MIN_DAYS` - Default: 1
- `POLYMARKET_PRIVATE_KEY` - For trading
- `POLYMARKET_FUNDER_ADDRESS` - For trading
- `POLYMARKET_SIGNATURE_TYPE` - Default: 2

## Investment Feature

The investment feature:
1. Finds the outcome with **highest predicted win percentage**
2. Fetches **real-time odds** from CLOB API
3. Checks if market is resolved (skips if so)
4. Prompts user to confirm
5. Places buy order for configured amount
6. Saves result to MongoDB

**Note**: Requires CLOB API credentials (`POLYMARKET_PRIVATE_KEY`, etc.)

## Commands

```bash
# Interactive mode
python main.py interactive

# Scan markets
python main.py scan-markets --limit 100

# Process markets
python main.py process-markets --max 10

# Show market
python main.py show-market --source-id <id>

# Help
python main.py help
```

## Notes

- **Real-time Odds**: Always fetched fresh from CLOB API, never from DB
- **Market Data**: Stored in MongoDB (title, description, structured data, predictions)
- **Investment Results**: Saved to MongoDB after each investment
- **Error Handling**: All errors are caught and displayed gracefully

