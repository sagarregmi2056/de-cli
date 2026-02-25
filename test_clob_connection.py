#!/usr/bin/env python
"""
Test script to verify CLOB connection and fetch odds without placing orders.

Usage:
    python test_clob_connection.py
    python test_clob_connection.py --token-id <token_id>
    python test_clob_connection.py --source-event-id <event_id>
"""

import argparse
import sys
from typing import Dict, Optional

from clob_client import (
    get_client,
    get_market_prices,
    get_token_ids_from_clob,
)
from gamma_client import get_market_token_ids
from config import (
    POLYMARKET_PRIVATE_KEY,
    POLYMARKET_FUNDER_ADDRESS,
    POLYMARKET_SIGNATURE_TYPE,
    POLYMARKET_CLOB_HOST,
    POLYMARKET_CHAIN_ID,
)


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_info(label: str, value: any):
    """Print a key-value pair."""
    print(f"  {label:30s}: {value}")


def test_config():
    """Test if configuration is set up correctly."""
    print_section("Configuration Check")
    
    print_info("CLOB Host", POLYMARKET_CLOB_HOST)
    print_info("Chain ID", POLYMARKET_CHAIN_ID)
    print_info("Signature Type", POLYMARKET_SIGNATURE_TYPE)
    print_info("Private Key Set", "✓ Yes" if POLYMARKET_PRIVATE_KEY else "✗ No")
    print_info("Funder Address Set", "✓ Yes" if POLYMARKET_FUNDER_ADDRESS else "✗ No")
    
    if not POLYMARKET_PRIVATE_KEY:
        print("\n⚠️  WARNING: POLYMARKET_PRIVATE_KEY not set!")
        print("   You can still test read-only operations, but authenticated")
        print("   operations (fetching prices, placing orders) will fail.")
        return False
    
    return True


def test_client_initialization():
    """Test CLOB client initialization."""
    print_section("CLOB Client Initialization")
    
    try:
        print("  Initializing CLOB client...")
        client = get_client()
        print("  ✓ Client initialized successfully!")
        
        # Test basic connection
        print("\n  Testing connection...")
        try:
            ok = client.get_ok()
            time_result = client.get_server_time()
            print_info("  Server Status", "✓ OK" if ok else "✗ Not OK")
            print_info("  Server Time", time_result if time_result else "N/A")
        except Exception as e:
            print(f"  ⚠️  Could not fetch server status: {e}")
        
        return client
    except Exception as e:
        print(f"  ✗ Failed to initialize client: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_readonly_client():
    """Test read-only client (no auth required)."""
    print_section("Read-Only Client Test (No Auth)")
    
    try:
        from py_clob_client.client import ClobClient
        
        print("  Creating read-only client...")
        read_client = ClobClient(POLYMARKET_CLOB_HOST)
        
        print("  Testing read-only operations...")
        ok = read_client.get_ok()
        time_result = read_client.get_server_time()
        
        print_info("  Server Status", "✓ OK" if ok else "✗ Not OK")
        print_info("  Server Time", time_result if time_result else "N/A")
        
        print("\n  ✓ Read-only client works!")
        return read_client
    except Exception as e:
        print(f"  ✗ Read-only client failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_fetch_prices(token_id: str):
    """Test fetching prices for a token ID."""
    print_section(f"Fetch Prices Test (Token ID: {token_id[:20]}...)")
    
    try:
        client = get_client()
        
        print("  Testing price fetching methods...")
        
        # Method 1: get_midpoint
        try:
            midpoint = client.get_midpoint(token_id)
            print_info("  Midpoint Price", f"{midpoint:.4f}" if midpoint else "N/A")
        except Exception as e:
            print(f"  ⚠️  get_midpoint failed: {e}")
        
        # Method 2: get_price (BUY)
        try:
            buy_price = client.get_price(token_id, "BUY")
            print_info("  BUY Price", f"{buy_price:.4f}" if buy_price else "N/A")
        except Exception as e:
            print(f"  ⚠️  get_price(BUY) failed: {e}")
        
        # Method 3: get_price (SELL)
        try:
            sell_price = client.get_price(token_id, "SELL")
            print_info("  SELL Price", f"{sell_price:.4f}" if sell_price else "N/A")
        except Exception as e:
            print(f"  ⚠️  get_price(SELL) failed: {e}")
        
        # Method 4: get_order_book
        try:
            order_book = client.get_order_book(token_id)
            if order_book:
                print("  ✓ Order book fetched successfully")
                # Try to extract some info
                if hasattr(order_book, "bids") and order_book.bids:
                    best_bid = order_book.bids[0]
                    bid_price = best_bid.price if hasattr(best_bid, "price") else best_bid.get("price", "N/A")
                    print_info("  Best Bid", f"{bid_price}")
                if hasattr(order_book, "asks") and order_book.asks:
                    best_ask = order_book.asks[0]
                    ask_price = best_ask.price if hasattr(best_ask, "price") else best_ask.get("price", "N/A")
                    print_info("  Best Ask", f"{ask_price}")
            else:
                print("  ⚠️  Order book is empty")
        except Exception as e:
            print(f"  ⚠️  get_order_book failed: {e}")
        
        print("\n  ✓ Price fetching test completed!")
        return True
    except Exception as e:
        print(f"  ✗ Price fetching test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_market_prices(token_ids: Dict[str, str]):
    """Test the get_market_prices wrapper function."""
    print_section("Market Prices Wrapper Test")
    
    try:
        print(f"  Fetching prices for {len(token_ids)} outcomes...")
        prices = get_market_prices(token_ids)
        
        if prices:
            print("\n  ✓ Prices fetched successfully:")
            for outcome_name, price in prices.items():
                percentage = price * 100 if price else 0
                print_info(f"    {outcome_name}", f"{price:.4f} ({percentage:.2f}%)")
        else:
            print("  ⚠️  No prices returned (market may be resolved or illiquid)")
        
        return prices
    except Exception as e:
        print(f"  ✗ Market prices test failed: {e}")
        import traceback
        traceback.print_exc()
        return {}


def test_token_id_fetching(source_event_id: str):
    """Test fetching token IDs from Gamma API."""
    print_section(f"Token ID Fetching Test (Event ID: {source_event_id})")
    
    try:
        print("  Fetching token IDs from Gamma API...")
        token_ids = get_market_token_ids(source_event_id)
        
        if token_ids:
            print(f"\n  ✓ Found {len(token_ids)} token IDs:")
            for outcome_name, token_id in token_ids.items():
                print_info(f"    {outcome_name}", token_id[:50] + "..." if len(token_id) > 50 else token_id)
            return token_ids
        else:
            print("  ⚠️  No token IDs found")
            return {}
    except Exception as e:
        print(f"  ✗ Token ID fetching failed: {e}")
        import traceback
        traceback.print_exc()
        return {}


def test_clob_simplified_markets():
    """Test fetching simplified markets from CLOB."""
    print_section("CLOB Simplified Markets Test")
    
    try:
        print("  Fetching simplified markets from CLOB API...")
        markets = get_token_ids_from_clob()
        
        if markets:
            print(f"\n  ✓ Found {len(markets)} markets with token IDs")
            # Show first few
            count = 0
            for outcome_name, token_id in markets.items():
                if count < 3:
                    print_info(f"    {outcome_name}", token_id[:50] + "..." if len(token_id) > 50 else token_id)
                    count += 1
            if len(markets) > 3:
                print(f"    ... and {len(markets) - 3} more")
        else:
            print("  ⚠️  No markets found (this is normal if no market_slug/market_id provided)")
        
        return markets
    except Exception as e:
        print(f"  ⚠️  Simplified markets test: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(
        description="Test CLOB connection and fetch odds without placing orders"
    )
    parser.add_argument(
        "--token-id",
        help="Token ID to test price fetching (optional)",
    )
    parser.add_argument(
        "--source-event-id",
        help="Source event ID to test token ID fetching (optional)",
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("  CLOB Connection & Odds Fetching Test")
    print("=" * 70)
    
    # Test 1: Configuration
    config_ok = test_config()
    
    # Test 2: Read-only client (works without auth)
    read_client = test_readonly_client()
    
    # Test 3: Authenticated client (if config is OK)
    client = None
    if config_ok:
        client = test_client_initialization()
    else:
        print("\n⚠️  Skipping authenticated client test (no private key)")
    
    # Test 4: Token ID fetching (if source_event_id provided)
    token_ids = {}
    if args.source_event_id:
        token_ids = test_token_id_fetching(args.source_event_id)
        
        # If we got token IDs, test fetching prices for them
        if token_ids:
            test_get_market_prices(token_ids)
    
    # Test 5: Price fetching for specific token ID
    if args.token_id:
        test_fetch_prices(args.token_id)
    elif token_ids:
        # Use first token ID from fetched token IDs
        first_token_id = list(token_ids.values())[0]
        print(f"\n  Using first token ID from fetched token IDs...")
        test_fetch_prices(first_token_id)
    
    # Test 6: CLOB simplified markets (optional)
    if not args.source_event_id and not args.token_id:
        test_clob_simplified_markets()
    
    # Summary
    print_section("Test Summary")
    
    print("  Configuration:", "✓ OK" if config_ok else "✗ Missing private key")
    print("  Read-only client:", "✓ OK" if read_client else "✗ Failed")
    print("  Authenticated client:", "✓ OK" if client else "✗ Failed or skipped")
    
    if token_ids:
        print(f"  Token IDs fetched: ✓ {len(token_ids)} found")
    else:
        print("  Token IDs fetched: ⚠️  None (provide --source-event-id to test)")
    
    if args.token_id or token_ids:
        print("  Price fetching: ✓ Tested")
    else:
        print("  Price fetching: ⚠️  Not tested (provide --token-id or --source-event-id)")
    
    print("\n" + "=" * 70)
    print("  Test Complete!")
    print("=" * 70 + "\n")
    
    # Exit code
    if not config_ok:
        print("⚠️  Note: Some tests were skipped due to missing configuration.")
        print("   Set POLYMARKET_PRIVATE_KEY in .env to test authenticated operations.\n")
        sys.exit(0)
    elif not client:
        print("✗ Some tests failed. Check the errors above.\n")
        sys.exit(1)
    else:
        print("✓ All tests passed!\n")
        sys.exit(0)


if __name__ == "__main__":
    main()

