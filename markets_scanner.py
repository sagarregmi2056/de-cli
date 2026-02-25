"""
Market scanning logic for the CLI app.

This module is intentionally self-contained and does NOT depend on the DEBot
package so that the CLI can keep working even if DEBot is removed.
It re-implements the same Polymarket fetching mechanism DEBot uses.
"""

import datetime as dt
from typing import Any, Dict, List, Optional

import requests
from pymongo import UpdateOne

from config import POLYMARKET_VOLUME_MIN, POLYMARKET_END_DATE_MIN_DAYS
from db import get_db
from config import (
    ONE_V_ONE_KEYWORDS,
    TEAM_KEYWORDS,
    EARNINGS_KEYWORDS,
    ELECTION_KEYWORDS,
    ENTERTAINMENT_KEYWORDS,
)
from gamma_client import (
    extract_token_ids_from_event,
    extract_outcome_prices_from_event,
)

def fetch_events(limit: int, offset: int) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch markets from the Polymarket API.

    Mirrors DEBot.DEBoT.utils.fetch_events, but is local to the CLI app so it
    doesn't depend on the DEBot package.
    """
    try:
        url = "https://gamma-api.polymarket.com/events"

        params = {
            "limit": limit,
            "offset": offset,
            "active": True,
            "archived": False,
            "closed": False,
            # Only future events (configurable days ahead) to avoid already-resolved ones
            "end_date_min": (
                dt.date.today() + dt.timedelta(days=POLYMARKET_END_DATE_MIN_DAYS)
            ).isoformat(),
            "volume_min": POLYMARKET_VOLUME_MIN,
            "ascending": True,
            "order": "endDate",
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Debug: log Gamma /events response (first event full JSON for inspection)
        try:
            if isinstance(data, list):
                print(
                    f"[markets_scanner] /events returned {len(data)} item(s) "
                    f"for offset={offset}, limit={limit}"
                )
                if data:
                    first = data[0]
                    from json import dumps as _dumps

                    print("[markets_scanner] First event full JSON:")
                    full_first = _dumps(first, indent=2)
                    # Avoid flooding the terminal for very large events
                    if len(full_first) > 4000:
                        full_first = full_first[:4000] + "...(truncated)"
                    print(full_first)
            else:
                print(
                    f"[markets_scanner] /events returned non-list payload "
                    f"for offset={offset}, limit={limit}: type={type(data).__name__}"
                )
        except Exception:
            # Logging should never break scanning
            pass

        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Polymarket: {e}")
        return None


def classify_event_type(event: Dict[str, Any]) -> str:
    """Roughly classify a market as 1v1, teams, or other based on text."""
    title = (event.get("title") or "").lower()
    description = (event.get("description") or "").lower()
    slug = (event.get("slug") or "").lower()
    text = " ".join([title, description, slug])

    # Skip 'More Markets' / props-style events from teams pipeline. These
    # typically contain multiple totals/O-U markets (Over/Under, O/U 1.5, etc.)
    # and are not the main win/moneyline markets we want to trade on.
    if "more markets" in text:
        return "other"

    # First, explicitly treat non-sports markets as "other", not teams
    if any(kw in text for kw in EARNINGS_KEYWORDS):
        return "other"

    
    if any(kw in text for kw in ELECTION_KEYWORDS):
        return "other"

  
    if any(kw in text for kw in ENTERTAINMENT_KEYWORDS):
        return "other"

    if any(kw in text for kw in ONE_V_ONE_KEYWORDS):
        return "1v1"
    if any(kw in text for kw in TEAM_KEYWORDS):
        return "teams"
    return "other"


def normalize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Polymarket event into our markets document shape."""
    end_date = event.get("endDate") or event.get("end_date")
    start_date = event.get("startDate") or event.get("start_date")

    # Best-effort extraction of outcome -> token_id mapping
    # so the CLI and debug tools can rely on MongoDB without
    # always having to hit Gamma/CLOB again.
    token_ids: Dict[str, str] = {}
    outcome_prices: Dict[str, float] = {}
    try:
        token_ids = extract_token_ids_from_event(event) or {}
        # Also snapshot outcome prices (if present in the event/markets payload).
        outcome_prices = extract_outcome_prices_from_event(event) or {}
    except Exception:
        # Never let token ID extraction break market scanning
        token_ids = {}
        outcome_prices = {}

    doc: Dict[str, Any] = {
        "source": "polymarket",
        "source_event_id": event.get("id"),
        "title": event.get("title"),
        "description": event.get("description"),
        "slug": event.get("slug"),
        "type": classify_event_type(event),
        "start_date": start_date,
        "end_date": end_date,
        "status": "new",
        "volume": event.get("volume"),
        "raw_event": event,
        # Store flattened token/price snapshots for easy access.
        # These are snapshots from Gamma at scan time; live prices
        # and spreads are still fetched from CLOB when needed.
        "token_ids": token_ids,
        "outcome_prices": outcome_prices,
        "has_edge_case": False,
        "edge_case_risk_level": "None",
        "created_at": dt.datetime.utcnow(),
        "updated_at": dt.datetime.utcnow(),
    }
    return doc


def upsert_markets(events: List[Dict[str, Any]]) -> None:
    """Bulk upsert a list of events into the markets collection."""
    if not events:
        return

    db = get_db()
    coll = db.markets
    ops = []
    now = dt.datetime.utcnow()

    for ev in events:
        source_event_id = ev.get("id")
        if not source_event_id:
            continue

        base_doc = normalize_event(ev)
        base_doc["updated_at"] = now

        ops.append(
            UpdateOne(
                {"source": "polymarket", "source_event_id": source_event_id},
                {
                    "$setOnInsert": {
                        "created_at": now,
                        "status": "new",
                        "has_edge_case": False,
                        "edge_case_risk_level": "None",
                    },
                    "$set": {
                        "title": base_doc["title"],
                        "description": base_doc["description"],
                        "slug": base_doc["slug"],
                        "type": base_doc["type"],
                        "start_date": base_doc["start_date"],
                        "end_date": base_doc["end_date"],
                        "volume": base_doc["volume"],
                        "raw_event": base_doc["raw_event"],
                        "updated_at": now,
                    },
                },
                upsert=True,
            )
        )

    if ops:
        result = coll.bulk_write(ops, ordered=False)
        inserted = result.upserted_count
        modified = result.modified_count
        print(f"Upserted markets: inserted={inserted}, updated={modified}")


def scan_markets(limit: int, max_batches: int | None) -> None:
    """
    Fetch upcoming markets from Polymarket in batches and save to MongoDB.

    This reuses DEBot.DEBoT.utils.fetch_events, which already applies
    filters like active/closed/end_date_min/volume_min.
    """
    offset = 0
    batch = 0
    total_events = 0

    while True:
        if max_batches is not None and batch >= max_batches:
            print(f"Reached max_batches={max_batches}, stopping scan.")
            break

        print(f"Fetching events: limit={limit}, offset={offset}")
        events = fetch_events(limit=limit, offset=offset)
        if not events:
            print("No more events returned from API, stopping.")
            break

        print(f"Fetched {len(events)} events, upserting into MongoDB...")
        upsert_markets(events)
        total_events += len(events)

        batch += 1
        offset += limit

    print(f"Scan complete. Total events fetched: {total_events}")


