"""
Gamma Markets API client for Polymarket.

This module provides functions to interact with Polymarket's Gamma API
to fetch market data, outcomes, and token IDs.

API Base URL: https://gamma-api.polymarket.com
"""

import json
from typing import Any, Dict, List, Optional

import requests

# Base URL for Gamma API
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single event by ID from Gamma API.
    
    Args:
        event_id: The source_event_id (market ID)
    
    Returns:
        Event data dictionary or None if error
    """
    url = f"{GAMMA_API_BASE}/events/{event_id}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Debug: pretty-print the full event JSON (truncated) so we can
        # inspect where clobTokenIds / outcomePrices live for specific IDs
        try:
            preview = json.dumps(data, indent=2)
            if len(preview) > 4000:
                preview = preview[:4000] + "...(truncated)"
            print(f"[gamma_client] /events/{event_id} full JSON:\n{preview}")
        except Exception:
            pass

        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching event {event_id}: {e}")
        return None


def get_markets(event_id: Optional[str] = None, **params) -> Optional[List[Dict[str, Any]]]:
    """
    Get markets from Gamma API.
    
    Args:
        event_id: Optional event ID to filter markets
        **params: Additional query parameters
    
    Returns:
        List of market dictionaries or None if error
    """
    url = f"{GAMMA_API_BASE}/markets"
    request_params = params.copy()
    if event_id:
        request_params["event_id"] = event_id

    try:
        response = requests.get(url, params=request_params, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Handle both list and object responses
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "data" in data:
            return data["data"]
        elif isinstance(data, dict) and "markets" in data:
            return data["markets"]
        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching markets: {e}")
        return None


def get_market(market_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single market by ID from Gamma API.
    
    Args:
        market_id: The market ID
    
    Returns:
        Market data dictionary or None if error
    """
    url = f"{GAMMA_API_BASE}/markets/{market_id}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching market {market_id}: {e}")
        return None


def extract_token_ids_from_event(event_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract token IDs from event/market data structure.
    
    Based on actual Gamma API response structure:
    - Markets have `outcomes` as JSON string: "[\"Yes\", \"No\"]"
    - Markets have `clobTokenIds` as JSON string: "[\"token1\", \"token2\"]"
    - They correspond by index (first outcome = first token ID)
    
    Args:
        event_data: Event or market data from Gamma API
    
    Returns:
        Dictionary mapping outcome names to token IDs
        Example: {"Yes": "71321045679252212594626385532706912750332728571942532289631379312455583992563"}
    """
    import json as json_module
    
    token_map: Dict[str, str] = {}

    # Method 1: Check for clobTokenIds (most common in markets response)
    clob_token_ids_str = event_data.get("clobTokenIds") or event_data.get("clob_token_ids")
    outcomes_str = event_data.get("outcomes")
    
    if clob_token_ids_str and outcomes_str:
        try:
            # Parse JSON strings
            if isinstance(clob_token_ids_str, str):
                token_ids = json_module.loads(clob_token_ids_str)
            else:
                token_ids = clob_token_ids_str
            
            if isinstance(outcomes_str, str):
                outcomes = json_module.loads(outcomes_str)
            else:
                outcomes = outcomes_str
            
            # Map by index
            if isinstance(token_ids, list) and isinstance(outcomes, list):
                if len(token_ids) == len(outcomes):
                    for outcome_name, token_id in zip(outcomes, token_ids):
                        token_map[str(outcome_name)] = str(token_id)
        except (json_module.JSONDecodeError, TypeError) as e:
            print(f"Error parsing clobTokenIds/outcomes: {e}")
    
    # Method 2: Check markets array (if event has multiple markets)
    markets = event_data.get("markets", [])
    if markets and not token_map:  # Only if we didn't find tokens above
        for market in markets:
            market_token_map = extract_token_ids_from_event(market)
            if market_token_map:
                token_map.update(market_token_map)
                break  # Use first market with token IDs
    
    # Method 3: Check direct outcomes array (if structured differently)
    outcomes = event_data.get("outcomes", [])
    if outcomes and isinstance(outcomes, list) and not token_map:
        for outcome in outcomes:
            if isinstance(outcome, dict):
                name = outcome.get("name") or outcome.get("title") or outcome.get("outcome")
                token_id = outcome.get("token_id") or outcome.get("tokenId") or outcome.get("tokenID")
                if name and token_id:
                    token_map[name] = str(token_id)
    
    # Method 4: Check for tokenIds array (parallel to outcomes)
    token_ids = event_data.get("tokenIds", []) or event_data.get("token_ids", [])
    outcome_names = event_data.get("outcomeNames", []) or event_data.get("outcome_names", [])
    if token_ids and outcome_names and len(token_ids) == len(outcome_names) and not token_map:
        for name, token_id in zip(outcome_names, token_ids):
            token_map[str(name)] = str(token_id)
    
    return token_map


def extract_outcome_prices_from_event(event_data: Dict[str, Any]) -> Dict[str, float]:
    """
    Extract outcome prices from event/market data structure.
    
    Mirrors extract_token_ids_from_event but for `outcomePrices`, giving a
    snapshot mapping outcome name -> last seen price (0.0–1.0).
    """
    import json as json_module

    price_map: Dict[str, float] = {}

    # Method 1: Check for outcomePrices parallel to outcomes
    outcome_prices_str = event_data.get("outcomePrices") or event_data.get("outcome_prices")
    outcomes_str = event_data.get("outcomes")

    if outcome_prices_str and outcomes_str:
        try:
            if isinstance(outcome_prices_str, str):
                prices = json_module.loads(outcome_prices_str)
            else:
                prices = outcome_prices_str

            if isinstance(outcomes_str, str):
                outcomes = json_module.loads(outcomes_str)
            else:
                outcomes = outcomes_str

            if isinstance(prices, list) and isinstance(outcomes, list):
                if len(prices) == len(outcomes):
                    for outcome_name, price in zip(outcomes, prices):
                        try:
                            price_map[str(outcome_name)] = float(price)
                        except (TypeError, ValueError):
                            continue
        except (json_module.JSONDecodeError, TypeError) as e:
            print(f"Error parsing outcomePrices/outcomes: {e}")

    # Method 2: Check markets array if not found at top level
    markets = event_data.get("markets", [])
    if markets and not price_map:
        for market in markets:
            market_price_map = extract_outcome_prices_from_event(market)
            if market_price_map:
                price_map.update(market_price_map)
                break

    # Method 3: Some schemas embed prices per-outcome dict
    outcomes = event_data.get("outcomes", [])
    if outcomes and isinstance(outcomes, list) and not price_map:
        for outcome in outcomes:
            if isinstance(outcome, dict):
                name = outcome.get("name") or outcome.get("title") or outcome.get("outcome")
                price = (
                    outcome.get("price")
                    or outcome.get("lastPrice")
                    or outcome.get("last_price")
                    or outcome.get("probability")
                )
                if name is not None and price is not None:
                    try:
                        price_map[str(name)] = float(price)
                    except (TypeError, ValueError):
                        continue

    return price_map


def get_market_token_ids(source_event_id: str) -> Dict[str, str]:
    """
    Get token IDs for all outcomes in a market.
    
    This is the main function to use. It tries multiple methods, in this order:
    1. MongoDB snapshot (`token_ids` / `raw_event`)
    2. Get event by ID and extract token IDs (`/events/{id}.markets[*].clobTokenIds`)
    3. Get markets for event (`/markets?event_id=...`) and extract token IDs
    4. Try getting first market by ID if we have market IDs
    5. Fallback to CLOB API simplified markets (if available)
    
    Args:
        source_event_id: The market/event ID from Polymarket
    
    Returns:
        Dictionary mapping outcome names to token IDs
        Example: {"Yes": "44804726753601178293652604511461891232965799888489574021036312274240304608626"}
    """
    markets: Optional[List[Dict[str, Any]]] = None
    event_data: Optional[Dict[str, Any]] = None

    # Method 1: MongoDB snapshot (preferred; populated by markets_scanner)
    token_map = get_market_token_ids_from_mongodb(source_event_id)
    if token_map:
        # Validate snapshot against current /events/{id}. If the keys don't
        # match the outcomes from the event (e.g., legacy Damwon/Suning vs
        # current Yes/No market), prefer the live event data and overwrite
        # the snapshot so the CLI shows correct token IDs.
        try:
            event_data = get_event(source_event_id)
            if event_data:
                expected_map = extract_token_ids_from_event(event_data)
                if expected_map and set(token_map.keys()) != set(expected_map.keys()):
                    print(
                        "[gamma_client] Mongo token_ids keys "
                        f"{list(token_map.keys())} do not match event outcomes "
                        f"{list(expected_map.keys())}; overriding snapshot with "
                        "current event clobTokenIds."
                    )
                    token_map = expected_map
                    # Persist corrected mapping back to Mongo
                    try:
                        from db import get_db

                        db = get_db()
                        db.markets.update_one(
                            {"source_event_id": source_event_id},
                            {"$set": {"token_ids": token_map}},
                        )
                    except Exception:
                        pass
        except Exception:
            # If validation fails, still return the snapshot (best effort)
            pass
        return token_map

    # Method 2: Try getting event directly (/events/{id}) and reading markets[*].clobTokenIds
    event_data = get_event(source_event_id)
    if event_data:
        token_map = extract_token_ids_from_event(event_data)
        if token_map:
            # Persist to Mongo for future lookups
            try:
                from db import get_db

                db = get_db()
                db.markets.update_one(
                    {"source_event_id": source_event_id},
                    {"$set": {"token_ids": token_map}},
                )
            except Exception:
                pass
            return token_map

    # Method 3: Try Gamma /markets?event_id=<id> as a fallback. For some legacy
    # events this may point to older markets (e.g., Damwon/Suning), so we only
    # hit this after event + MongoDB have failed.
    markets = get_markets(event_id=source_event_id)
    if markets:
        # Prefer Moneyline-like markets where outcomes are teams / DRAW instead of Yes/No
        moneyline_market = None
        other_markets: List[Dict[str, Any]] = []

        for market in markets:
            # Extract outcomes to check
            outcomes_str = market.get("outcomes")
            if isinstance(outcomes_str, str):
                import json as _json

                try:
                    outcomes = _json.loads(outcomes_str)
                except Exception:
                    outcomes = []
            else:
                outcomes = outcomes_str if isinstance(outcomes_str, list) else []

            market_type = (market.get("type") or "").lower()
            market_name = (market.get("name") or "").lower()
            question = (market.get("question") or "").lower()

            # Check if this looks like a Moneyline market:
            # 1. Has "moneyline" in type/name/question
            # 2. Has 3 outcomes (Team1, DRAW, Team2)
            # 3. Has "DRAW" as one outcome
            # 4. Outcomes are short abbreviations (PES, CAT, etc.) not "Yes"/"No"
            is_moneyline = (
                "moneyline" in market_type
                or "moneyline" in market_name
                or "moneyline" in question
                or (len(outcomes) == 3 and any("draw" in str(o).lower() for o in outcomes))
                or (len(outcomes) >= 2 and not any(o in ["Yes", "No"] for o in outcomes))
            )

            if is_moneyline:
                moneyline_market = market
            else:
                other_markets.append(market)

        # Try Moneyline first if found
        if moneyline_market:
            token_map = extract_token_ids_from_event(moneyline_market)
            if token_map:
                return token_map

        # Then try other markets
        for market in other_markets:
            token_map = extract_token_ids_from_event(market)
            if token_map:
                return token_map

    # Method 4: Try getting first market by ID if we have market IDs
    if markets and len(markets) > 0:
        market_id = markets[0].get("id") or markets[0].get("_id")
        if market_id:
            market_data = get_market(str(market_id))
            if market_data:
                token_map = extract_token_ids_from_event(market_data)
                if token_map:
                    return token_map

    # Method 5: Try CLOB API as last resort (if we can get market slug/ID)
    try:
        from clob_client import get_token_ids_from_clob
        
        # Try to get slug from event data or markets
        slug = None
        if event_data:
            slug = event_data.get("slug")
        elif markets and len(markets) > 0:
            slug = markets[0].get("slug")
        
        if slug:
            clob_token_map = get_token_ids_from_clob(market_slug=slug)
            if clob_token_map:
                return clob_token_map
    except Exception as e:
        # Silently fail - CLOB API is optional
        pass


def get_market_token_ids_for_slug(slug: str) -> Dict[str, str]:
    """
    Get token IDs for a market by Polymarket slug (preferred for sports/teams).
    
    Per Polymarket docs, the recommended way is:
      GET https://gamma-api.polymarket.com/markets?slug=<slug>
    and then read `clobTokenIds` + `outcomes`.
    
    Args:
        slug: Polymarket market slug (e.g., \"itsb-reg-man-2026-02-10\")
    
    Returns:
        {outcome_name: token_id}
    """
    # 1) Try Gamma markets?slug=<slug> (doc‑recommended)
    markets = get_markets(slug=slug)
    if markets:
        print(f"[gamma_client] markets?slug={slug} returned {len(markets)} market(s)")
        # Prefer markets that actually have clobTokenIds / outcomes
        for idx, m in enumerate(markets, start=1):
            # Compact debug: only show essential identifiers and prices
            try:
                mid = m.get("id")
                mslug = m.get("slug")
                volume = m.get("volume")
                clob_token_ids = m.get("clobTokenIds")
                outcome_prices = m.get("outcomePrices")
                print(
                    f"[gamma_client] market #{idx}: id={mid}, slug={mslug}, "
                    f"volume={volume}, clobTokenIds={clob_token_ids}, "
                    f"outcomePrices={outcome_prices}"
                )
            except Exception:
                pass

            token_map = extract_token_ids_from_event(m)
            if token_map:
                print(
                    f"[gamma_client] Using market #{idx} from markets?slug={slug} "
                    f"with outcomes={list(token_map.keys())}"
                )
                return token_map
        print(f"[gamma_client] markets?slug={slug} had no clobTokenIds/outcomes we can use")
    else:
        print(f"[gamma_client] markets?slug={slug} returned no markets")

    # 2) Fallback: try CLOB simplified markets by slug
    try:
        from clob_client import get_token_ids_from_clob

        clob_token_map = get_token_ids_from_clob(market_slug=slug)
        if clob_token_map:
            return clob_token_map
    except Exception:
        # If CLOB lookup fails, return empty and let caller decide
        pass

    return {}


def get_market_token_ids_from_mongodb(source_event_id: str) -> Dict[str, str]:
    """
    Get token IDs from MongoDB raw_event (fallback method).
    
    Args:
        source_event_id: The market/event ID
    
    Returns:
        Dictionary mapping outcome names to token IDs
    """
    from db import get_db

    db = get_db()
    market = db.markets.find_one({"source_event_id": source_event_id})
    if not market:
        return {}

    # Prefer the flattened token_ids snapshot if present.
    token_ids = market.get("token_ids") or {}
    if isinstance(token_ids, dict) and token_ids:
        return {str(k): str(v) for k, v in token_ids.items()}

    # Fallback: derive token IDs from the raw_event blob.
    raw_event = market.get("raw_event", {})
    if not raw_event:
        return {}

    return extract_token_ids_from_event(raw_event)


def find_token_id_for_candidate(
    source_event_id: str, candidate_name: str
) -> Optional[str]:
    """
    Find token ID for a specific candidate/outcome name.
    
    Args:
        source_event_id: The market/event ID
        candidate_name: Name of the candidate (e.g., "Frances Tiafoe")
    
    Returns:
        Token ID string or None if not found
    """
    token_map = get_market_token_ids(source_event_id)
    
    # Try exact match first
    if candidate_name in token_map:
        return token_map[candidate_name]
    
    # Try case-insensitive match
    candidate_lower = candidate_name.lower()
    for name, token_id in token_map.items():
        if name.lower() == candidate_lower:
            return token_id
    
    # Try partial match (if name contains candidate name)
    for name, token_id in token_map.items():
        if candidate_lower in name.lower() or name.lower() in candidate_lower:
            return token_id
    
    return None


def get_outcome_prices(
    source_event_id: Optional[str] = None,
    slug: Optional[str] = None,
) -> Dict[str, float]:
    """
    Get outcome prices (odds) for a market.
    
    This mirrors get_market_token_ids and prefers stable, current data:
      1) MongoDB snapshot (`outcome_prices` / `raw_event`)
      2) /events/{id}.markets[*].outcomePrices
      3) /markets?slug=<slug>  (for some sports/teams markets)
      4) /markets?event_id=<id> (last resort; can point to legacy markets)
    """
    # 1) MongoDB snapshot (preferred; populated by markets_scanner)
    if source_event_id:
        try:
            from db import get_db

            db = get_db()
            m = db.markets.find_one({"source_event_id": source_event_id})
            if m:
                snapshot = m.get("outcome_prices")
                if isinstance(snapshot, dict) and snapshot:
                    prices_from_mongo = {str(k): float(v) for k, v in snapshot.items()}
                    # Validate against /events/{id}; if keys don't match, override.
                    try:
                        event_data = get_event(source_event_id)
                        if event_data:
                            expected = extract_outcome_prices_from_event(event_data)
                            if expected and set(prices_from_mongo.keys()) != set(expected.keys()):
                                print(
                                    "[gamma_client] Mongo outcome_prices keys "
                                    f"{list(prices_from_mongo.keys())} do not match event outcomes "
                                    f"{list(expected.keys())}; overriding snapshot with "
                                    "current event outcomePrices."
                                )
                                prices_from_mongo = expected
                                db.markets.update_one(
                                    {"source_event_id": source_event_id},
                                    {"$set": {"outcome_prices": prices_from_mongo}},
                                )
                    except Exception:
                        # If validation fails, still use the snapshot
                        pass
                    return prices_from_mongo
        except Exception:
            pass

    # 2) Try getting event directly (/events/{id}) and reading markets[*].outcomePrices
    if source_event_id:
        try:
            event_data = get_event(source_event_id)
            if event_data:
                prices_from_event = extract_outcome_prices_from_event(event_data)
                if prices_from_event:
                    # Persist to Mongo for future lookups
                    try:
                        from db import get_db

                        db = get_db()
                        db.markets.update_one(
                            {"source_event_id": source_event_id},
                            {"$set": {"outcome_prices": prices_from_event}},
                        )
                    except Exception:
                        pass
                    return prices_from_event
        except Exception:
            pass

    # 3) Try Gamma /markets with slug (best-effort for some sports markets)
    markets: Optional[List[Dict[str, Any]]] = None
    if slug:
        markets = get_markets(slug=slug)
        if markets is not None:
            print(
                f"[gamma_client] get_outcome_prices: /markets?slug={slug} "
                f"returned {len(markets) if isinstance(markets, list) else 'non-list'} entries"
            )
            if isinstance(markets, list) and markets:
                try:
                    preview = json.dumps(markets[0], indent=2)
                    if len(preview) > 4000:
                        preview = preview[:4000] + "...(truncated)"
                    print(f"[gamma_client] First /markets?slug={slug} market JSON:\n{preview}")
                except Exception:
                    pass

    # 4) Fallback: /markets?event_id=<id> (may point to legacy markets)
    if (not markets) and source_event_id:
        markets = get_markets(event_id=source_event_id)
        if markets is not None:
            print(
                f"[gamma_client] get_outcome_prices: /markets?event_id={source_event_id} "
                f"returned {len(markets) if isinstance(markets, list) else 'non-list'} entries"
            )
            if isinstance(markets, list) and markets:
                try:
                    preview = json.dumps(markets[0], indent=2)
                    if len(preview) > 4000:
                        preview = preview[:4000] + "...(truncated)"
                    print(
                        f"[gamma_client] First /markets?event_id={source_event_id} "
                        f"market JSON:\n{preview}"
                    )
                except Exception:
                    pass

    if markets:
        # Reuse the moneyline heuristic used in get_market_token_ids
        moneyline_market = None
        other_markets: List[Dict[str, Any]] = []

        for market in markets:
            outcomes_str = market.get("outcomes")
            if isinstance(outcomes_str, str):
                try:
                    import json as _json

                    outcomes = _json.loads(outcomes_str)
                except Exception:
                    outcomes = []
            else:
                outcomes = outcomes_str if isinstance(outcomes_str, list) else []

            market_type = market.get("type", "").lower()
            market_name = market.get("name", "").lower()
            question = market.get("question", "").lower()

            is_moneyline = (
                "moneyline" in market_type
                or "moneyline" in market_name
                or "moneyline" in question
                or (len(outcomes) == 3 and any("draw" in str(o).lower() for o in outcomes))
                or (len(outcomes) >= 2 and not any(o in ["Yes", "No"] for o in outcomes))
            )

            if is_moneyline:
                moneyline_market = market
            else:
                other_markets.append(market)

        if moneyline_market:
            prices = extract_outcome_prices_from_event(moneyline_market)
            if prices:
                return prices

        for market in other_markets:
            prices = extract_outcome_prices_from_event(market)
            if prices:
                return prices

    # 2) MongoDB fallback (cached snapshot or raw_event)
    if source_event_id:
        try:
            from db import get_db

            db = get_db()
            m = db.markets.find_one({"source_event_id": source_event_id})
            if m:
                outcome_prices = m.get("outcome_prices")
                if isinstance(outcome_prices, dict) and outcome_prices:
                    return {str(k): float(v) for k, v in outcome_prices.items()}

                raw_event = m.get("raw_event", {})
                if raw_event:
                    prices = extract_outcome_prices_from_event(raw_event)
                    if prices:
                        return prices
        except Exception:
            pass

    return {}

