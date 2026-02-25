#!/usr/bin/env python
"""Test script to explore CLOB client methods and their signatures."""

import inspect
from py_clob_client.client import ClobClient

# Methods we're interested in
methods_to_check = [
    "get_order_book",
    "get_price",
    "get_prices",
    "calculate_market_price",
    "get_midpoint",
    "create_and_post_order",
    "post_order",
    "get_open_orders",
    "get_trades",
    "get_orders",
]

print("=" * 80)
print("CLOB CLIENT METHODS ANALYSIS")
print("=" * 80)

for method_name in methods_to_check:
    method = getattr(ClobClient, method_name, None)
    if method:
        sig = inspect.signature(method)
        is_async = inspect.iscoroutinefunction(method)
        print(f"\n{method_name}:")
        print(f"  Signature: {sig}")
        print(f"  Is async: {is_async}")








