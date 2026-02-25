#!/usr/bin/env python
"""
Quick test to verify read-only price fetching works.

This tests if we can fetch prices using the read-only client
(as per Polymarket docs) without authentication.
"""

from py_clob_client.client import ClobClient
from config import POLYMARKET_CLOB_HOST


def test_readonly_client():
    """Test read-only client connection."""
    print("\n" + "=" * 70)
    print("  Testing Read-Only CLOB Client (No Auth Required)")
    print("=" * 70 + "\n")
    
    # Create read-only client (as per Polymarket docs)
    client = ClobClient(POLYMARKET_CLOB_HOST)
    
    print("✓ Read-only client created successfully")
    
    # Test server connection
    try:
        ok = client.get_ok()
        time_result = client.get_server_time()
        print(f"✓ Server status: {'OK' if ok else 'Not OK'}")
        if time_result:
            print(f"✓ Server time: {time_result}")
    except Exception as e:
        print(f"✗ Server connection failed: {e}")
        return False
    
    print("\n" + "-" * 70)
    print("  To test price fetching, you need a token ID from an ACTIVE market.")
    print("  Active markets have orderbooks and prices available.")
    print("\n  Example:")
    print("    python test_readonly_prices.py --token-id <active_token_id>")
    print("-" * 70 + "\n")
    
    return True


def test_price_fetching(token_id: str):
    """Test fetching prices for a specific token ID."""
    print(f"\n{'='*70}")
    print(f"  Testing Price Fetching for Token ID")
    print(f"{'='*70}\n")
    print(f"Token ID: {token_id[:50]}...\n")
    
    client = ClobClient(POLYMARKET_CLOB_HOST)
    
    # Test 1: get_midpoint
    print("1. Testing get_midpoint()...")
    try:
        midpoint = client.get_midpoint(token_id)
        if midpoint is not None:
            print(f"   ✓ Midpoint: {midpoint:.4f} ({midpoint*100:.2f}%)")
        else:
            print("   ⚠️  No midpoint available")
    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "No orderbook exists" in error_str:
            print("   ✗ No orderbook exists (market not active)")
        else:
            print(f"   ✗ Error: {e}")
    
    # Test 2: get_price (BUY)
    print("\n2. Testing get_price(token_id, 'BUY')...")
    try:
        buy_price = client.get_price(token_id, "BUY")
        if buy_price is not None:
            print(f"   ✓ BUY price: {buy_price:.4f} ({buy_price*100:.2f}%)")
        else:
            print("   ⚠️  No BUY price available")
    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "No orderbook exists" in error_str:
            print("   ✗ No orderbook exists (market not active)")
        else:
            print(f"   ✗ Error: {e}")
    
    # Test 3: get_order_book
    print("\n3. Testing get_order_book()...")
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
            print("   ✗ No orderbook exists (market not active)")
            print("\n   → This means the market hasn't opened for trading on CLOB yet.")
            print("   → Token IDs are valid, but no one can trade until the orderbook is created.")
        else:
            print(f"   ✗ Error: {e}")
    
    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--token-id" and len(sys.argv) > 2:
        test_price_fetching(sys.argv[2])
    else:
        test_readonly_client()

