"""
Configuration for the CLI app.

Loads environment variables (via python-dotenv) and exposes
constants for Gemini and the prediction API.
"""

import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set.")

DEFAULT_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")

PREDICTION_API_URL = os.getenv(
    "PREDICTION_API_URL", "https://de.ideapreneurnepal.com.np/prediction"
)
PREDICTION_API_TOKEN = os.getenv("PREDICTION_API_TOKEN", "VyUwnQK2EN")

# Simple keyword-based type detection (mirrors DEBot config)
ONE_V_ONE_KEYWORDS = [
    "tennis",
    "badminton",
    "table tennis",
    "golf",
    "Formula 1",
    "Boxing",
    "MMA",
    "UFC", 
    
]

TEAM_KEYWORDS = [
    "epl",
    "la liga",
    "laliga",
    "ucl",
    "mls",
    "serie b",
    "bundesliga",
    "efl",
    "efl cup",
    "nfl",
    "international",
    "world cup",
    "european championship",
    "asian championship",
    "africa championship",
    "north america championship",
    "south america championship",
    "oceania championship",
    "world championship",
    "cricket",
    "t20",
    "t20 world cup",
    "odi",
    "test match",
    "ipl",
    "bbl",
    "cpl",
    "psl",
    "basketball",
    "nba",
    "ncaab",
    "hockey",
    "nhl",
    "baseball",
    "mlb",
    # League/category slug keys used in Polymarket sports URLs
    "acn",
    "arg",
    "aus",
    "bl2",
    "bra",
    "bundesliga",
    "caf",
    "cbb",
    "cde",
    "chi1",
    "col1",
    "concacaf",
    "conmebol",
    "csl",
    "cze1",
    "den",
    "dfb",
    "egy1",
    "elc",
    "ere",
    "es2",
    "fa-cup",
    "fifa-friendlies",
    "fr2",
    "isp",
    "itc",
    "itsb",
    "kor",
    "laliga",
    "lib",
    "ligue-1",
    "mar1",
    "mex",
    "mls",
    "nor",
    "per1",
    "por",
    "rou1",
    "rus",
    "scop",
    "sea",
    "spl",
    "ssc",
    "sud",
    "tur",
    "ucl",
    "ucol",
    "uel",
    "ukr1",
    "uwcl",
    # Basketball league/category slug keys used in Polymarket sports URLs
    "bknbl",
    "bkfr1",
    "euroleague",
    "basketball-champions-league",
    "bkcl",
    "bkligend",
    "basketball-series-a",
    "bkseriea",
    "bkcba",
    "bkkbl",
    # Cricket and rugby category slug keys used in Polymarket sports URLs
    "wbc",
    "csa-t20",
    "crint",
    "cricbbl",
    "rusrp",
    "ruprem",
    "rusixnat",
    "rutopft",
    "ruurc",
]

# Earnings / finance-style markets we do NOT want to treat as sports teams.
# These will be classified as "other" so they don't show up under "Teams".
EARNINGS_KEYWORDS = [
    "quarterly earnings",
    "nongaap eps",
    "non-gaap eps",
    "earnings per share",
    "eps",
    "beat quarterly earnings",
    "closes",
    "microsoft",
    "above",
    "below",
    "over",
    "under",
    "over/under",
    "over/under 2.5",
    "over/under 3.5",
    "over/under 4.5",
    "over/under 5.5",
    "closes",
    "NVIDIA",
    "meta",
    "apple",
    "google",
    "amazon",
    "tesla",
    "microsoft",
    "facebook",
    "twitter",
    "instagram",
    "tiktok",
    "youtube",
    "reddit",
    "discord",
    "telegram",
    "snapchat",
    "pinterest",
    "linkedin",
    "netflix",
    "nflx",
]

# Election / politics markets we also do NOT want under sports teams.
ELECTION_KEYWORDS = [
    "election",
    "primary",
    "democratic primary",
    "republican primary",
    "runoff",
    "governor",
    "senate",
    "house seat",
    "mayor",
    "president",
]

# Entertainment / music / pop-culture markets we do NOT want as sports teams.
ENTERTAINMENT_KEYWORDS = [
    "spotify",
    "#1 song",
    "number 1 song",
    "top song",
    "billboard",
    "hot 100",
    "album of the year",
    "grammy",
    "tweet",
    "closes",
    "elon musk",
    "trump",
    # Treat Netflix / streaming content markets as entertainment
    "netflix",
    "nflx",
    "netflix show",
    "global netflix show",
]

# Polymarket API filtering (optional, with defaults)
POLYMARKET_VOLUME_MIN = int(os.getenv("POLYMARKET_VOLUME_MIN", "500"))
POLYMARKET_END_DATE_MIN_DAYS = int(os.getenv("POLYMARKET_END_DATE_MIN_DAYS", "1"))

# Investment settings
INVESTMENT_AMOUNT = float(os.getenv("INVESTMENT_AMOUNT", "1.0"))  # Default: $1 per market

# Polymarket CLOB API settings (optional - only needed for trading/fetching odds)
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY") or None
POLYMARKET_FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS") or None
# Handle empty string case for signature_type
_signature_type_str = os.getenv("POLYMARKET_SIGNATURE_TYPE", "2")
POLYMARKET_SIGNATURE_TYPE = int(_signature_type_str) if _signature_type_str and _signature_type_str.strip() else 2
POLYMARKET_CLOB_HOST = os.getenv("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com")
# Handle empty string case for chain_id
_chain_id_str = os.getenv("POLYMARKET_CHAIN_ID", "137")
POLYMARKET_CHAIN_ID = int(_chain_id_str) if _chain_id_str and _chain_id_str.strip() else 137
