#!/usr/bin/env python
"""
Test script to inspect Gamma API responses and MongoDB data structure.

This helps us understand:
1. What's in raw_event from MongoDB
2. How to get token IDs from source_event_id
3. API endpoint structure
"""

import json
import sys
from typing import Any, Dict, Optional

import requests

from db import get_db


def inspect_mongodb_market(source_event_id: Optional[str] = None) -> None:
    """Inspect a market document from MongoDB to see raw_event structure."""
    try:
        db = get_db()
        coll = db.markets

        if source_event_id:
            market = coll.find_one({"source_event_id": source_event_id})
        else:
            # Get first market with raw_event
            market = coll.find_one({"raw_event": {"$exists": True}})

        if not market:
            print("No market found in MongoDB.")
            return
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        print("Skipping MongoDB inspection. Continuing with API tests only.")
        return

    print("=" * 80)
    print("MONGODB MARKET DOCUMENT")
    print("=" * 80)
    print(f"Market ID: {market.get('_id')}")
    print(f"Source Event ID: {market.get('source_event_id')}")
    print(f"Title: {market.get('title')}")
    print(f"Status: {market.get('status')}")
    print()

    raw_event = market.get("raw_event", {})
    if raw_event:
        print("=" * 80)
        print("RAW_EVENT STRUCTURE")
        print("=" * 80)
        print(json.dumps(raw_event, indent=2))
        print()

        # Look for key fields
        print("=" * 80)
        print("KEY FIELDS IN RAW_EVENT")
        print("=" * 80)
        print(f"ID: {raw_event.get('id')}")
        print(f"Title: {raw_event.get('title')}")
        print(f"Markets: {raw_event.get('markets')}")
        print(f"Outcomes: {raw_event.get('outcomes')}")
        print(f"Token IDs: {raw_event.get('tokenIds')}")
        print(f"Token ID: {raw_event.get('token_id')}")
        print(f"Conditional Tokens: {raw_event.get('conditionalTokens')}")
        print()

        # Check if there's a markets array
        markets = raw_event.get("markets", [])
        if markets:
            print(f"Found {len(markets)} markets in event")
            for i, mkt in enumerate(markets[:2]):  # Show first 2
                print(f"\nMarket {i+1}:")
                print(json.dumps(mkt, indent=2))
    else:
        print("No raw_event found in market document.")


def test_gamma_api_event(source_event_id: str) -> None:
    """Test Gamma API endpoint to get event by ID."""
    print("=" * 80)
    print(f"TESTING GAMMA API: GET /events/{source_event_id}")
    print("=" * 80)

    url = f"https://gamma-api.polymarket.com/events/{source_event_id}"
    print(f"URL: {url}")

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        print("\nResponse:")
        print(json.dumps(data, indent=2))
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


def test_gamma_api_markets(source_event_id: str) -> None:
    """Test Gamma API endpoint to get markets for an event."""
    print("=" * 80)
    print(f"TESTING GAMMA API: GET /markets (with event_id={source_event_id})")
    print("=" * 80)

    url = "https://gamma-api.polymarket.com/markets"
    params = {"event_id": source_event_id}
    print(f"URL: {url}")
    print(f"Params: {params}")

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        print("\nResponse:")
        print(json.dumps(data, indent=2))
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


def test_gamma_api_market_by_id(market_id: str) -> None:
    """Test Gamma API endpoint to get market by ID."""
    print("=" * 80)
    print(f"TESTING GAMMA API: GET /markets/{market_id}")
    print("=" * 80)

    url = f"https://gamma-api.polymarket.com/markets/{market_id}"
    print(f"URL: {url}")

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        print("\nResponse:")
        print(json.dumps(data, indent=2))
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


def main() -> None:
    """Main test function."""
    if len(sys.argv) > 1:
        source_event_id = sys.argv[1]
    else:
        # Try to get first market from MongoDB
        try:
            db = get_db()
            market = db.markets.find_one({"raw_event": {"$exists": True}})
            if market:
                source_event_id = market.get("source_event_id")
                print(f"Using source_event_id from MongoDB: {source_event_id}")
            else:
                print("No markets found in MongoDB.")
                print("Please provide source_event_id as argument.")
                print("Usage: python test_gamma_api.py [source_event_id]")
                print("\nExample: python test_gamma_api.py 176693")
                sys.exit(1)
        except Exception as e:
            print(f"MongoDB connection error: {e}")
            print("Please provide source_event_id as argument.")
            print("Usage: python test_gamma_api.py [source_event_id]")
            print("\nExample: python test_gamma_api.py 176693")
            sys.exit(1)

    print("\n" + "=" * 80)
    print("GAMMA API RESEARCH & DEBUGGING")
    print("=" * 80)
    print(f"Source Event ID: {source_event_id}")
    print()

    # Step 1: Inspect MongoDB data
    print("\n" + "=" * 80)
    print("STEP 1: INSPECTING MONGODB DATA")
    print("=" * 80)
    inspect_mongodb_market(source_event_id)

    # Step 2: Test API endpoints
    print("\n" + "=" * 80)
    print("STEP 2: TESTING GAMMA API ENDPOINTS")
    print("=" * 80)

    # Test 1: Get event by ID
    test_gamma_api_event(source_event_id)

    # Test 2: Get markets for event
    test_gamma_api_markets(source_event_id)

    # Test 3: Try to get market by ID (if we find a market ID in raw_event)
    try:
        db = get_db()
        market = db.markets.find_one({"source_event_id": source_event_id})
        if market:
            raw_event = market.get("raw_event", {})
            markets = raw_event.get("markets", [])
            if markets and len(markets) > 0:
                market_id = markets[0].get("id") or markets[0].get("_id")
                if market_id:
                    print("\n")
                    test_gamma_api_market_by_id(str(market_id))
    except Exception as e:
        print(f"MongoDB connection error (skipping market ID lookup): {e}")

    print("\n" + "=" * 80)
    print("TESTING COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Review the API responses above")
    print("2. Look for 'outcomes', 'markets', 'token_id', or 'tokenId' fields")
    print("3. Update gamma_client.py extraction logic if needed")
    print("4. Test token ID extraction:")
    print(f"   from gamma_client import get_market_token_ids")
    print(f"   token_map = get_market_token_ids('{source_event_id}')")
    print(f"   print(token_map)")


if __name__ == "__main__":
    main()

