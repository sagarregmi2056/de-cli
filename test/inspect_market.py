"""
Quick inspection script for a single Polymarket event.

Usage:
    python -m test.inspect_market <source_event_id>

Example:
    python -m test.inspect_market 192219
"""

import sys
from typing import Dict, Any

from gamma_client import (
    get_event,
    extract_token_ids_from_event,
    extract_outcome_prices_from_event,
)
from clob_client import get_market_spreads


def _print_header(title: str) -> None:
    border = "=" * len(title)
    print(f"\n{border}\n{title}\n{border}")


def inspect_event(event_id: str) -> None:
    event = get_event(event_id)
    if not event:
        print(f"Could not fetch event {event_id} from Gamma.")
        return

    _print_header(f"Gamma /events/{event_id}")
    print(f"slug:        {event.get('slug')}")
    print(f"title:       {event.get('title')}")
    print(f"volume:      {event.get('volume')}")
    print(f"liquidity:   {event.get('liquidity')}")
    print(f"endDate:     {event.get('endDate')}")

    markets = event.get("markets") or []
    print(f"\nmarkets count: {len(markets)}")
    if markets:
        first_market: Dict[str, Any] = markets[0]
        print("\nFirst market summary:")
        print(f"  id:           {first_market.get('id')}")
        print(f"  slug:         {first_market.get('slug')}")
        print(f"  question:     {first_market.get('question')}")
        print(f"  outcomes:     {first_market.get('outcomes')}")
        print(f"  outcomePrices:{first_market.get('outcomePrices')}")
        print(f"  clobTokenIds: {first_market.get('clobTokenIds')}")

    # Flatten outcome -> token_id and outcome -> outcome_price
    token_ids = extract_token_ids_from_event(event)
    outcome_prices = extract_outcome_prices_from_event(event)

    _print_header("Flattened outcomes from Gamma (event/markets)")
    if not token_ids and not outcome_prices:
        print("No token_ids or outcome_prices could be extracted.")
    else:
        for outcome_name in sorted(set(list(token_ids.keys()) + list(outcome_prices.keys()))):
            tid = token_ids.get(outcome_name)
            price = outcome_prices.get(outcome_name)
            print(f"  {outcome_name}:")
            if tid:
                print(f"    clobTokenId:   {tid}")
            if price is not None:
                print(f"    outcomePrice:  {price:.4f} ({price * 100:.1f}¢)")

    # Query CLOB spreads for these token IDs
    if token_ids:
        _print_header("CLOB /spreads for these token IDs")
        spreads = get_market_spreads(token_ids)
        if not spreads:
            print("No spreads returned (market may be inactive or illiquid).")
        else:
            for outcome_name, spread in spreads.items():
                print(f"  {outcome_name}: spread={spread:.4f}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m test.inspect_market <source_event_id>")
        sys.exit(1)

    event_id = sys.argv[1]
    inspect_event(event_id)


if __name__ == "__main__":
    main()


