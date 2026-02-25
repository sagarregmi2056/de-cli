"""
CLOB (Central Limit Order Book) API client for Polymarket trading.

This module provides functions to interact with Polymarket's CLOB API
for placing orders, fetching prices, and managing positions.

API Base URL: https://clob.polymarket.com
"""

import asyncio
from typing import Any, Dict, Optional

import requests

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from config import (
    POLYMARKET_PRIVATE_KEY,
    POLYMARKET_FUNDER_ADDRESS,
    POLYMARKET_SIGNATURE_TYPE,
    POLYMARKET_CLOB_HOST,
    POLYMARKET_CHAIN_ID,
)


# Global client instance (initialized on first use)
_clob_client: Optional[ClobClient] = None


def _initialize_client() -> ClobClient:
    """
    Initialize and authenticate CLOB client.
    
    This performs L1 → L2 authentication following the official documentation:
    1. Create ClobClient with key, chain_id, signature_type, and funder
    2. Create or derive API credentials (async operation)
    3. Set API credentials on the client
    
    Returns:
        Authenticated ClobClient instance
    """
    global _clob_client
    
    if _clob_client is not None:
        return _clob_client
    
    if not POLYMARKET_PRIVATE_KEY:
        raise ValueError(
            "POLYMARKET_PRIVATE_KEY not set. Add it to .env file."
        )
    
    # Step 1: Initialize client with basic parameters
    client_kwargs = {
        "host": POLYMARKET_CLOB_HOST,
        "key": POLYMARKET_PRIVATE_KEY,
        "chain_id": POLYMARKET_CHAIN_ID,
        "signature_type": POLYMARKET_SIGNATURE_TYPE,
    }
    
    # Add funder address if provided (required for signature_type 1 or 2)
    if POLYMARKET_FUNDER_ADDRESS:
        client_kwargs["funder"] = POLYMARKET_FUNDER_ADDRESS
    
    _clob_client = ClobClient(**client_kwargs)
    
    # Step 2: Create or derive API credentials (L2 authentication)
    # NOTE: In current py-clob-client versions these methods are SYNC,
    # so we must NOT wrap them in asyncio.run().
    try:
        if hasattr(_clob_client, "create_or_derive_api_creds"):
            api_creds = _clob_client.create_or_derive_api_creds()
        elif hasattr(_clob_client, "create_or_derive_api_key"):
            # Fallback to old method name if it exists
            api_creds = _clob_client.create_or_derive_api_key()
        else:
            raise AttributeError(
                "Neither create_or_derive_api_creds nor create_or_derive_api_key found"
            )
    except Exception as e:
        raise ValueError(f"Failed to create API credentials: {e}")
    
    # Step 3: Set API credentials on the client (required for authenticated operations)
    try:
        _clob_client.set_api_creds(api_creds)
    except Exception as e:
        raise ValueError(f"Failed to set API credentials: {e}")
    
    return _clob_client


def get_client() -> ClobClient:
    """
    Get or initialize CLOB client.
    
    Returns:
        Authenticated ClobClient instance
    """
    return _initialize_client()


def _get_prices_from_gamma_api(token_ids: Dict[str, str]) -> Dict[str, float]:
    """
    Fallback: Try to get prices from Gamma API markets endpoint.
    Note: Gamma API outcomePrices are often not real-time, so this is a last resort.
    """
    # Gamma API doesn't provide reliable real-time prices
    # CLOB API requires authentication for price data
    # Without POLYMARKET_PRIVATE_KEY, we cannot fetch real-time odds
    return {}


def get_market_prices(token_ids: Dict[str, str]) -> Dict[str, float]:
    """
    Get current *prices* for each token ID (midpoint / best buy).
    
    NOTE: For your workflow you care more about **spreads** than prices.
    This function is still kept for:
      - Resolution checks (is_market_resolved)
      - Any legacy odds‑based logic
    
    For spreads, use get_market_spreads().
    """
    prices: Dict[str, float] = {}
    
    # Try read-only client first (no auth needed for basic price fetching)
    read_client = ClobClient(POLYMARKET_CLOB_HOST)
    
    # Prepare authenticated client as fallback (if available)
    auth_client = None
    if POLYMARKET_PRIVATE_KEY:
        try:
            auth_client = get_client()
        except Exception:
            pass
    
    def _try_get_price(client, token_id: str) -> Optional[float]:
        try:
            midpoint = client.get_midpoint(token_id)
            if midpoint is not None:
                return float(midpoint)
            buy_price = client.get_price(token_id, "BUY")
            if buy_price is not None:
                return float(buy_price)
        except Exception as e:
            return e
        return None
    
    for outcome_name, token_id in token_ids.items():
        result = _try_get_price(read_client, token_id)
        if isinstance(result, float):
            prices[outcome_name] = result
            continue
        if isinstance(result, Exception) and auth_client:
            auth_result = _try_get_price(auth_client, token_id)
            if isinstance(auth_result, float):
                prices[outcome_name] = auth_result
                continue
    return prices


def get_market_spreads(token_ids: Dict[str, str]) -> Dict[str, float]:
    """
    Get bid‑ask spreads for each token ID, using the /spreads REST endpoint.
    
    This is what you'll use as your "odds" / liquidity signal in the CLI.
    
    Args:
        token_ids: {outcome_name: token_id}
    
    Returns:
        {outcome_name: spread} where spread is a float (e.g., 0.05 for a 5¢ spread)
    """
    if not token_ids:
        return {}
    
    # Build payload for /spreads
    payload = [{"token_id": tid} for tid in token_ids.values()]
    try:
        resp = requests.post(
            f"{POLYMARKET_CLOB_HOST}/spreads",
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()  # {token_id: "0.05"}
    except Exception as e:
        print(f"Error fetching spreads from CLOB: {e}")
        return {}
    
    spreads: Dict[str, float] = {}
    for outcome_name, token_id in token_ids.items():
        spread_str = data.get(token_id)
        if spread_str is None:
            continue
        try:
            spreads[outcome_name] = float(spread_str)
        except (TypeError, ValueError):
            continue
    
    return spreads


def is_market_resolved(prices: Dict[str, float]) -> bool:
    """
    Check if market is resolved (any outcome at 0.00 or 1.00).
    
    Args:
        prices: Dictionary of outcome prices
    
    Returns:
        True if market is resolved, False otherwise
    """
    for price in prices.values():
        if price is not None:
            # Market is resolved if price is exactly 0.00 or 1.00
            # Or very close (within 0.01) to account for rounding
            if price <= 0.01 or price >= 0.99:
                return True
    return False


def place_buy_order(
    token_id: str,
    amount_usd: float,
    price: Optional[float] = None,
    order_type: Optional[OrderType] = None,
) -> Dict[str, Any]:
    """
    Place a buy order for outcome tokens.
    
    For market orders (FOK, FAK), uses MarketOrderArgs.
    For limit orders (GTC, GTD), uses OrderArgs with price.
    
    Args:
        token_id: ERC1155 token ID for the outcome
        amount_usd: Amount to invest in USD (e.g., 1.0 for $1)
        price: Limit price (0.00-1.00). If None and order_type is FOK/FAK, uses market order.
               If None and order_type is GTC/GTD, uses current market price as limit.
        order_type: Order type (GTC, GTD, FOK, FAK). Defaults to GTC if None
    
    Returns:
        Order response dictionary with orderID, status, etc.
    """
    client = get_client()
    
    if order_type is None:
        order_type = OrderType.GTC
    
    # Market orders (FOK, FAK) don't need a price - they execute at market
    is_market_order = order_type in (OrderType.FOK, OrderType.FAK)
    
    if is_market_order:
        # Use MarketOrderArgs for market orders
        market_order = MarketOrderArgs(
            token_id=token_id,
            amount=amount_usd,
            side=BUY,
            order_type=order_type,
        )
        
        # Create and sign market order
        signed_order = client.create_market_order(market_order)
        
        # Post market order
        response = client.post_order(signed_order, order_type)
    else:
        # Limit orders (GTC, GTD) need a price
        if price is None:
            # Get current market price for BUY side
            try:
                raw_price = client.get_price(token_id, "BUY")
                if raw_price is None:
                    # Fallback to midpoint
                    raw_price = client.get_midpoint(token_id)
                if raw_price is None:
                    raise ValueError(f"Could not get price for token {token_id}")

                # Some py-clob-client versions may return a dict or Decimal-like
                # object. Coerce to float defensively.
                if isinstance(raw_price, dict):
                    # Common patterns: {"price": "..."} or {"buy": "..."}
                    raw_price = (
                        raw_price.get("price")
                        or raw_price.get("buy")
                        or raw_price.get("midpoint")
                    )
                price = float(raw_price)
            except Exception as e:
                print(f"Error getting market price: {e}")
                raise
        else:
            # Coerce user-provided price to float
            try:
                price = float(price)
            except Exception as e:
                raise ValueError(f"Invalid price value {price!r}: {e}")
        
        # For limit orders, size is in shares (calculated from amount_usd / price)
        # According to docs, for limit orders, size is in shares
        shares = amount_usd / price if price > 0 else 0
        
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=shares,  # For limit orders, size is in shares
            side=BUY,
        )
        
        # Create and sign order
        signed_order = client.create_order(order_args)
        
        # Post order to CLOB API
        response = client.post_order(signed_order, order_type)
    
    return response


def get_orders() -> list:
    """
    Get all orders for the authenticated account.
    
    Returns:
        List of order dictionaries
    """
    client = get_client()
    return client.get_orders()


def get_trades() -> list:
    """
    Get trade history for the authenticated account.
    
    Returns:
        List of trade dictionaries
    """
    client = get_client()
    return client.get_trades()


def cancel_order(order_id: str) -> Dict[str, Any]:
    """
    Cancel an open order.
    
    Args:
        order_id: Order ID to cancel
    
    Returns:
        Cancellation response
    """
    client = get_client()
    try:
        return client.cancel(order_id)
    except Exception as e:
        print(f"Error canceling order: {e}")
        raise


def get_token_ids_from_clob(market_slug: Optional[str] = None, market_id: Optional[str] = None) -> Dict[str, str]:
    """
    Get token IDs from CLOB API's simplified markets endpoint.
    
    This can be used as a fallback when Gamma API doesn't have token IDs.
    
    Args:
        market_slug: Market slug to search for (optional)
        market_id: Market ID to search for (optional)
    
    Returns:
        Dictionary mapping outcome names to token IDs
        Example: {"Yes": "token_id_1", "No": "token_id_2"}
    """
    try:
        # Create a read-only client (no auth needed for this endpoint)
        read_client = ClobClient(POLYMARKET_CLOB_HOST)
        
        # Get simplified markets
        markets_response = read_client.get_simplified_markets()
        
        if not markets_response or "data" not in markets_response:
            return {}
        
        markets = markets_response.get("data", [])
        
        # Search for matching market
        for market in markets:
            # Check if this market matches our criteria
            if market_slug and market.get("slug") == market_slug:
                return _extract_token_ids_from_clob_market(market)
            if market_id and market.get("id") == market_id:
                return _extract_token_ids_from_clob_market(market)
        
        # If no specific market requested, return empty (we need a way to identify the market)
        return {}
    except Exception as e:
        print(f"Error fetching token IDs from CLOB: {e}")
        return {}


def _extract_token_ids_from_clob_market(market: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract token IDs from a CLOB simplified market response.
    
    Args:
        market: Market dictionary from get_simplified_markets()
    
    Returns:
        Dictionary mapping outcome names to token IDs
    """
    token_map: Dict[str, str] = {}
    
    # CLOB markets have outcomes with token_id fields
    outcomes = market.get("outcomes", [])
    if isinstance(outcomes, list):
        for outcome in outcomes:
            if isinstance(outcome, dict):
                name = outcome.get("name") or outcome.get("title")
                token_id = outcome.get("token_id") or outcome.get("tokenId")
                if name and token_id:
                    token_map[str(name)] = str(token_id)
    
    return token_map

