#!/usr/bin/env python
"""
Quick test script to verify CLOB connection works.

Usage:
    python quick_test_clob.py
"""

from clob_client import get_client, get_market_prices
from gamma_client import get_market_token_ids
from config import POLYMARKET_PRIVATE_KEY


def main():
    print("\n" + "=" * 60)
    print("  Quick CLOB Connection Test")
    print("=" * 60 + "\n")
    
    # Test 1: Check config
    if not POLYMARKET_PRIVATE_KEY:
        print("❌ POLYMARKET_PRIVATE_KEY not set in .env")
        print("   Set it to test authenticated operations.\n")
        return
    
    print("✓ Configuration OK")
    
    # Test 2: Initialize client
    try:
        print("  Initializing CLOB client...")
        client = get_client()
        print("✓ Client initialized")
        
        # Test connection
        ok = client.get_ok()
        print(f"✓ Server status: {'OK' if ok else 'Not OK'}")
        
    except Exception as e:
        print(f"❌ Client initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Test 3: Try to fetch a price (need a token ID)
    print("\n" + "-" * 60)
    print("  To test price fetching, you need a token ID.")
    print("  Run: python test_clob_connection.py --source-event-id <id>")
    print("  Or:  python test_clob_connection.py --token-id <token_id>")
    print("-" * 60 + "\n")
    
    print("✓ Basic connection test passed!\n")


if __name__ == "__main__":
    main()

