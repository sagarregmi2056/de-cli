#!/usr/bin/env python
"""
Debug script to check token IDs and orderbook availability.

Usage:
    python debug_token_ids.py --source-event-id <event_id>
    python debug_token_ids.py --token-id <token_id>
"""

import argparse
import sys

from clob_client import get_client, get_market_prices
from gamma_client import get_market_token_ids


def debug_token_id(token_id: str):
    """Debug a single token ID."""
    print(f"\n{'='*70}")
    print(f"  Debugging Token ID: {token_id}")
    print(f"{'='*70}\n")
    
    client = get_client()
    
    # Test 1: Check if orderbook exists
    print("1. Checking orderbook...")
    try:
        order_book = client.get_order_book(token_id)
        if order_book:
            print("   ✓ Orderbook exists")
            if hasattr(order_book, "bids") and order_book.bids:
                print(f"   ✓ Has {len(order_book.bids)} bid(s)")
            if hasattr(order_book, "asks") and order_book.asks:
                print(f"   ✓ Has {len(order_book.asks)} ask(s)")
        else:
            print("   ⚠️  Orderbook is empty")
    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "No orderbook exists" in error_str:
            print("   ✗ No orderbook exists for this token ID")
            print("   → This means the market is not active on CLOB yet")
        else:
            print(f"   ✗ Error: {e}")
    
    # Test 2: Try to get midpoint
    print("\n2. Getting midpoint price...")
    try:
        midpoint = client.get_midpoint(token_id)
        if midpoint is not None:
            print(f"   ✓ Midpoint: {midpoint:.4f} ({midpoint*100:.2f}%)")
        else:
            print("   ⚠️  No midpoint available")
    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "No orderbook exists" in error_str:
            print("   ✗ No orderbook (expected)")
        else:
            print(f"   ✗ Error: {e}")
    
    # Test 3: Try to get BUY price
    print("\n3. Getting BUY price...")
    try:
        buy_price = client.get_price(token_id, "BUY")
        if buy_price is not None:
            print(f"   ✓ BUY price: {buy_price:.4f} ({buy_price*100:.2f}%)")
        else:
            print("   ⚠️  No BUY price available")
    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "No orderbook exists" in error_str:
            print("   ✗ No orderbook (expected)")
        else:
            print(f"   ✗ Error: {e}")
    
    print(f"\n{'='*70}\n")


def debug_event_id(source_event_id: str):
    """Debug token IDs for an event."""
    print(f"\n{'='*70}")
    print(f"  Debugging Event ID: {source_event_id}")
    print(f"{'='*70}\n")
    
    # First, try to find the event in MongoDB by slug to get correct event ID
    print("0. Checking MongoDB for event with this ID or slug...")
    from db import get_db
    db = get_db()
    market_doc = db.markets.find_one({"source_event_id": source_event_id})
    
    if market_doc:
        title = market_doc.get("title", "Unknown")
        slug = market_doc.get("slug", "Unknown")
        print(f"   ✓ Found in MongoDB:")
        print(f"      Title: {title}")
        print(f"      Slug: {slug}")
        print(f"      Source Event ID: {source_event_id}")
        
        # Check if this matches what we're looking for
        if "pescara" in title.lower() or "catanzaro" in title.lower() or "pes-cat" in slug.lower():
            print(f"   ✓ This looks like the correct soccer match!")
        else:
            print(f"   ⚠️  This doesn't look like the soccer match (Pescara vs Catanzaro)")
            print(f"   → The event ID might be wrong or pointing to a different event")
    else:
        print(f"   ⚠️  Not found in MongoDB")
        print(f"   → Try searching by slug: itsb-pes-cat-2026-02-10")
    
    print()
    
    # Step 0: List all markets for this event
    print("0. Listing all markets for this event...")
    from gamma_client import get_markets
    all_markets = get_markets(event_id=source_event_id)
    
    if all_markets:
        print(f"   ✓ Found {len(all_markets)} market(s) for this event:")
        for i, market in enumerate(all_markets, 1):
            market_type = market.get("type", "unknown")
            market_name = market.get("name", "unnamed")
            question = market.get("question", "")
            outcomes = market.get("outcomes", [])
            if isinstance(outcomes, str):
                import json
                try:
                    outcomes = json.loads(outcomes)
                except:
                    outcomes = []
            
            print(f"\n   Market {i}:")
            print(f"      Type: {market_type}")
            print(f"      Name: {market_name}")
            print(f"      Question: {question[:80]}..." if len(question) > 80 else f"      Question: {question}")
            print(f"      Outcomes: {outcomes}")
            
            # Check if this has token IDs
            from gamma_client import extract_token_ids_from_event
            token_map = extract_token_ids_from_event(market)
            if token_map:
                print(f"      ✓ Has token IDs: {list(token_map.keys())}")
            else:
                print(f"      ✗ No token IDs found")
    else:
        print("   ⚠️  Could not fetch markets list")
    
    # Step 1: Get token IDs
    print(f"\n1. Fetching token IDs from Gamma API...")
    token_ids = get_market_token_ids(source_event_id)
    
    if not token_ids:
        print("   ✗ No token IDs found")
        print("\n   Possible reasons:")
        print("   - Event ID is invalid")
        print("   - Market doesn't have token IDs yet")
        print("   - Market is not a CLOB market")
        return
    
    print(f"   ✓ Found {len(token_ids)} token ID(s):")
    for outcome_name, token_id in token_ids.items():
        print(f"      {outcome_name}: {token_id[:50]}...")
    
    # Show which market type we got
    print(f"\n   Market outcomes: {list(token_ids.keys())}")
    if "Yes" in token_ids and "No" in token_ids:
        print("   ⚠️  Note: Got Yes/No outcomes (might be 'Both Teams to Score' market)")
        print("   → For Moneyline markets, we need PES/DRAW/CAT outcomes")
    elif len(token_ids) == 2 and "DRAW" not in token_ids:
        print("   ⚠️  Note: Got 2 outcomes without DRAW (might not be Moneyline)")
        print("   → Moneyline markets usually have 3 outcomes: Team1, DRAW, Team2")
    
    # Step 2: Test each token ID
    print("\n2. Testing token IDs on CLOB...")
    
    # Try read-only client first
    from py_clob_client.client import ClobClient
    from config import POLYMARKET_CLOB_HOST, POLYMARKET_PRIVATE_KEY
    
    read_client = ClobClient(POLYMARKET_CLOB_HOST)
    print("   Using read-only client (no auth)...")
    
    # Also prepare authenticated client if available
    auth_client = None
    if POLYMARKET_PRIVATE_KEY:
        try:
            auth_client = get_client()
            print("   Authenticated client available (will use as fallback)...")
        except Exception as e:
            print(f"   ⚠️  Could not initialize authenticated client: {e}")
    
    active_count = 0
    for outcome_name, token_id in token_ids.items():
        print(f"\n   Testing '{outcome_name}'...")
        
        # Try read-only first
        try:
            order_book = read_client.get_order_book(token_id)
            if order_book:
                print(f"      ✓ Orderbook exists (read-only client)")
                active_count += 1
                
                # Try to get price
                try:
                    midpoint = read_client.get_midpoint(token_id)
                    if midpoint is not None:
                        print(f"      ✓ Price: {midpoint:.4f} ({midpoint*100:.2f}%)")
                except:
                    pass
            else:
                print(f"      ⚠️  Orderbook is empty (read-only)")
        except Exception as e:
            error_str = str(e)
            is_404 = "404" in error_str or "No orderbook exists" in error_str
            
            if is_404 and auth_client:
                # Try authenticated client as fallback
                print(f"      → Read-only failed (404), trying authenticated client...")
                try:
                    order_book = auth_client.get_order_book(token_id)
                    if order_book:
                        print(f"      ✓ Orderbook exists (authenticated client)")
                        active_count += 1
                        
                        # Try to get price
                        try:
                            midpoint = auth_client.get_midpoint(token_id)
                            if midpoint is not None:
                                print(f"      ✓ Price: {midpoint:.4f} ({midpoint*100:.2f}%)")
                        except:
                            pass
                    else:
                        print(f"      ⚠️  Orderbook is empty (authenticated)")
                except Exception as auth_e:
                    auth_error_str = str(auth_e)
                    if "404" in auth_error_str or "No orderbook exists" in auth_error_str:
                        print(f"      ✗ No orderbook exists (market not active on CLOB)")
                    else:
                        print(f"      ✗ Authenticated client error: {auth_e}")
            elif is_404:
                print(f"      ✗ No orderbook exists (market not active on CLOB)")
            else:
                print(f"      ✗ Error: {e}")
    
    # Summary
    print(f"\n{'='*70}")
    print(f"  Summary")
    print(f"{'='*70}")
    print(f"  Token IDs found: {len(token_ids)}")
    print(f"  Active on CLOB: {active_count}/{len(token_ids)}")
    
    if active_count == 0:
        print("\n  ⚠️  None of the token IDs have active orderbooks.")
        print("  This means the market is not yet active on CLOB.")
        print("  You cannot place orders or fetch odds until the market is active.")
    elif active_count < len(token_ids):
        print(f"\n  ⚠️  Only {active_count} of {len(token_ids)} outcomes are active.")
    else:
        print("\n  ✓ All outcomes are active on CLOB!")
    
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Debug token IDs and orderbook availability"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--source-event-id",
        help="Source event ID to debug",
    )
    group.add_argument(
        "--token-id",
        help="Token ID to debug",
    )
    group.add_argument(
        "--slug",
        help="Market slug to debug (e.g., itsb-pes-cat-2026-02-10)",
    )
    
    args = parser.parse_args()
    
    if args.slug:
        # Find event by slug from MongoDB
        from db import get_db
        db = get_db()
        market_doc = db.markets.find_one({"slug": args.slug})
        
        if market_doc:
            source_event_id = market_doc.get("source_event_id")
            if source_event_id:
                print(f"Found event with slug '{args.slug}':")
                print(f"  Title: {market_doc.get('title', 'Unknown')}")
                print(f"  Source Event ID: {source_event_id}\n")
                debug_event_id(str(source_event_id))
            else:
                print(f"Market found but no source_event_id")
        else:
            print(f"Market not found with slug: {args.slug}")
            print(f"Try running: python main.py scan-markets")
    elif args.source_event_id:
        debug_event_id(args.source_event_id)
    elif args.token_id:
        debug_token_id(args.token_id)


if __name__ == "__main__":
    main()

