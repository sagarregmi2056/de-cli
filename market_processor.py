"""
Market processing pipeline for the CLI app.

Takes markets stored in MongoDB (from scan-markets), runs Gemini 1v1 + EdgeCase
on each, calls the prediction API, and updates the market document with all
structured data and prediction results.
"""

import datetime as dt
import json
import sys
from typing import Any, Dict, Optional
import csv
import os

from db import get_db
from gemini_clients import (
    OneVsOneGeminiClient,
    TeamsGeminiClient,
    EdgeCaseGeminiClient,
)
from geo_enricher import enrich_structured_event
from prediction_client import get_prediction
from gamma_client import (
    get_market_token_ids,
    get_market_token_ids_for_slug,
    find_token_id_for_candidate,
    get_outcome_prices,
)
from clob_client import (
    get_market_prices,
    get_market_spreads,
    is_market_resolved,
    place_buy_order,
)
from config import (
    INVESTMENT_AMOUNT,
    POLYMARKET_PRIVATE_KEY,
    EARNINGS_KEYWORDS,
    ELECTION_KEYWORDS,
    ENTERTAINMENT_KEYWORDS,
)
from ui_helpers import (
    print_market_card,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_structured_summary,
    prompt_yes_no,
)


def _append_prediction_csv(
    market: Dict[str, Any],
    structured_event: Dict[str, Any],
    payload: Dict[str, Any],
    prediction_result: Dict[str, Any],
    edge_case: Dict[str, Any],
    risk_level: str,
) -> None:
    """
    Append a single prediction result to a CSV file for later analysis.
    
    Stores event metadata, the two candidates we sent, and their prediction scores.
    """
    try:
        # Resolve CSV path under cli-app/predictedmarket/predictions.csv
        base_dir = os.path.dirname(__file__)
        csv_dir = os.path.join(base_dir, "predictedmarket")
        os.makedirs(csv_dir, exist_ok=True)
        csv_path = os.path.join(csv_dir, "predictions.csv")

        file_exists = os.path.exists(csv_path)

        structured_event_type = structured_event.get("event_type")
        payload_event_type = payload.get("event_type")

        event = structured_event.get("event", {}) or {}
        candidates = payload.get("candidates", []) or []

        # We only log if we have at least 2 candidates
        if len(candidates) < 2:
            return

        def _safe(v: Any) -> str:
            return "" if v is None else str(v)

        cand1 = candidates[0]
        cand2 = candidates[1]

        person_a = prediction_result.get("PersonA", {}) or {}
        person_b = prediction_result.get("PersonB", {}) or {}

        row = {
            # Meta
            "logged_at_utc": dt.datetime.utcnow().isoformat(),
            "mongo_id": str(market.get("_id", "")),
            "source_event_id": _safe(market.get("source_event_id") or market.get("raw_event", {}).get("id")),
            "market_slug": _safe(market.get("slug") or market.get("raw_event", {}).get("slug")),
            "market_title": _safe(market.get("title") or market.get("raw_event", {}).get("title")),
            # Event info
            "structured_event_type": _safe(structured_event_type),
            "payload_event_type": _safe(payload_event_type),
            "event_name": _safe(event.get("event_name")),
            "event_date": _safe(event.get("event_date")),
            "event_time": _safe(event.get("event_time")),
            "event_location": _safe(event.get("event_location")),
            "event_timezone": _safe(event.get("event_timezone")),
            "event_lat": _safe(event.get("event_lat")),
            "event_lon": _safe(event.get("event_lon")),
            "event_lat_dir": _safe(event.get("event_lat_dir")),
            "event_lon_dir": _safe(event.get("event_lon_dir")),
            # Candidate 1
            "cand1_name": _safe(cand1.get("name")),
            "cand1_role": _safe(cand1.get("role")),
            "cand1_team_name": _safe(cand1.get("team_name")),
            "cand1_gender": _safe(cand1.get("gender")),
            "cand1_birth_date": _safe(cand1.get("birth_date")),
            "cand1_birth_place": _safe(cand1.get("birth_place")),
            "cand1_birth_country": _safe(cand1.get("birth_country")),
            "cand1_birth_timezone": _safe(cand1.get("birth_timezone")),
            "cand1_lat": _safe(cand1.get("lat")),
            "cand1_lon": _safe(cand1.get("lon")),
            "cand1_lat_dir": _safe(cand1.get("lat_dir")),
            "cand1_lon_dir": _safe(cand1.get("lon_dir")),
            # Candidate 2
            "cand2_name": _safe(cand2.get("name")),
            "cand2_role": _safe(cand2.get("role")),
            "cand2_team_name": _safe(cand2.get("team_name")),
            "cand2_gender": _safe(cand2.get("gender")),
            "cand2_birth_date": _safe(cand2.get("birth_date")),
            "cand2_birth_place": _safe(cand2.get("birth_place")),
            "cand2_birth_country": _safe(cand2.get("birth_country")),
            "cand2_birth_timezone": _safe(cand2.get("birth_timezone")),
            "cand2_lat": _safe(cand2.get("lat")),
            "cand2_lon": _safe(cand2.get("lon")),
            "cand2_lat_dir": _safe(cand2.get("lat_dir")),
            "cand2_lon_dir": _safe(cand2.get("lon_dir")),
            # Prediction result
            "personA_name": _safe(person_a.get("Name")),
            "personA_win_pct": _safe(person_a.get("WinPercentage")),
            "personB_name": _safe(person_b.get("Name")),
            "personB_win_pct": _safe(person_b.get("WinPercentage")),
            # Edge case info
            "has_edge_case": _safe(edge_case.get("has_edge_case", False)),
            "edge_case_risk_level": _safe(risk_level),
        }

        fieldnames = list(row.keys())

        with open(csv_path, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        # Don't break the main pipeline if logging fails
        print_warning(f"Failed to append prediction CSV: {e}")


def _sanitize_prediction_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip out any extra fields the prediction API doesn't expect, especially
    for team events where we attach role/team_name, etc.
    """
    allowed_candidate_keys = {
        "name",
        "birth_date",
        "birth_time",
        "birth_place",
        "birth_country",
        "birth_timezone",
        "lat",
        "lon",
        "lat_dir",
        "lon_dir",
        "gender",
    }

    event = payload.get("event") or {}
    candidates = payload.get("candidates") or []

    clean_candidates: list[Dict[str, Any]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        clean = {k: v for k, v in cand.items() if k in allowed_candidate_keys}
        clean_candidates.append(clean)

    return {
        "event_type": payload.get("event_type"),
        "candidates": clean_candidates,
        "event": event,
    }


def _has_required_candidate_fields(candidates: list[Dict[str, Any]]) -> bool:
    """
    Validate that every candidate has the full set of fields the prediction API expects.
    
    This mirrors the 'required_fields' used for teams in _build_prediction_payload:
    name, birth_date, birth_place, birth_country, birth_timezone, lat, lon, lat_dir, lon_dir.
    We reject None, empty strings, and the literal string 'unknown'.
    """
    required_fields = [
        "name",
        "birth_date",
        "birth_place",
        "birth_country",
        "birth_timezone",
        "lat",
        "lon",
        "lat_dir",
        "lon_dir",
    ]

    for cand in candidates:
        if not isinstance(cand, dict):
            return False
        for field in required_fields:
            value = cand.get(field)
            if value is None or value == "" or (isinstance(value, str) and value.lower() == "unknown"):
                return False
    return True


def _handle_investment_flow(
    market: Dict[str, Any],
    prediction_result: Dict[str, Any],
    interactive: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Simple investment flow: Buy the outcome with highest win percentage.
    
    1. Get token IDs from source_event_id
    2. Find candidate with highest win percentage
    3. Get token ID for that candidate
    4. Check if market is resolved (skip if so)
    5. Prompt user to invest
    6. Place order if confirmed
    """
    source_event_id = market.get("source_event_id")
    market_type = market.get("type", "1v1")
    slug = market.get("slug")
    if not source_event_id:
        print_warning("No source_event_id found. Cannot fetch token IDs.")
        return None
    
    try:
        # Step 1: Get token IDs (needed later when we know which side to back)
        print_info("Fetching token IDs from Polymarket...")
        if market_type == "teams" and slug:
            token_ids = get_market_token_ids_for_slug(slug)
            if not token_ids:
                print_info(
                    "Slug-based token ID lookup returned no results; "
                    "falling back to event_id-based lookup."
                )
                token_ids = get_market_token_ids(source_event_id)
        else:
            token_ids = get_market_token_ids(source_event_id)

        if not token_ids:
            print_warning("Could not find token IDs for this market.")
            return None

        # Step 2: Get current market prices (to check if resolved)
        print_info("Checking market status...")
        market_prices = get_market_prices(token_ids)
        
        # Only check if resolved if we have prices (prices dict should be {str: float})
        if market_prices:
            try:
                # Ensure market_prices is a simple dict of {str: float}
                if isinstance(market_prices, dict):
                    # Filter out any non-float values
                    clean_prices = {k: float(v) for k, v in market_prices.items() if isinstance(v, (int, float))}
                    if clean_prices and is_market_resolved(clean_prices):
                        print_warning(
                            "Market is already resolved (odds at 0% or 100%). Skipping investment."
                        )
                        return None
            except Exception as e:
                print_warning(f"Could not check market resolution: {e}")
                # Continue anyway - might be able to invest
        
        # Step 3: Find candidate with highest win percentage
        person_a = prediction_result.get("PersonA", {})
        person_b = prediction_result.get("PersonB", {})
        
        person_a_name = person_a.get("Name", "PersonA")
        person_a_win = person_a.get("WinPercentage", "0")
        
        person_b_name = person_b.get("Name", "PersonB")
        person_b_win = person_b.get("WinPercentage", "0")
        
        try:
            person_a_prob = float(person_a_win)
            person_b_prob = float(person_b_win)
        except (ValueError, TypeError):
            print_warning("Could not parse win percentages from prediction.")
            return None
        
        # Find winner (highest win percentage)
        if person_a_prob > person_b_prob:
            winner_name = person_a_name
            winner_prob = person_a_prob
            winner_side = "A"
        else:
            winner_name = person_b_name
            winner_prob = person_b_prob
            winner_side = "B"

        # Step 4: Get token ID for winner
        # For teams markets like Serie B where outcomes are ["Yes","No"]
        # on "Will Team X win?", we map:
        #   - PersonA (home team) -> "Yes"
        #   - PersonB (away team) -> "No"
        if market_type == "teams" and set(token_ids.keys()) == {"Yes", "No"}:
            chosen_outcome = "Yes" if winner_side == "A" else "No"
            outcome_token_id = token_ids.get(chosen_outcome)
        else:
            # Fallback: try to resolve by candidate name
            outcome_token_id = find_token_id_for_candidate(source_event_id, winner_name)
        
        if not outcome_token_id:
            print_warning(
                f"Could not find token ID for '{winner_name}'. Skipping investment."
            )
            return None
        
        # Step 5: Display and (optionally) prompt
        if interactive:
            print("\n" + "=" * 70)
            print_success("Investment Opportunity")
            print("=" * 70)
            print(f"Higher Predicted Winner: {winner_name}")
            print(f"Win Probability: {winner_prob:.2f}%")
            print(f"Investment Amount: ${INVESTMENT_AMOUNT:.2f}")
            print("=" * 70)

            invest = prompt_yes_no(
                f"Do you want to invest on higher predicted '{winner_name}' market ({winner_prob:.2f}% win probability) for ${INVESTMENT_AMOUNT:.2f}?",
                default=False,
                allow_back=True,
            )
            
            if invest is None:
                print_info("Exiting investment flow.")
                return None
            elif invest == "b":
                print_info("Going back.")
                return None
            elif invest != "y":
                print_info("Investment skipped.")
                return None
        # In non-interactive mode we always attempt the investment once a winner is chosen.
        # Step 6: Place order
        if interactive:
            print_info(f"Placing order for ${INVESTMENT_AMOUNT:.2f}...")
        try:
            order_response = place_buy_order(
                token_id=outcome_token_id,
                amount_usd=INVESTMENT_AMOUNT,
                price=None,  # Use market price
                order_type=None,  # Use default (GTC)
            )
            if interactive:
                print_success("Order placed successfully!")
                print_info("Order response:")
                print(json.dumps(order_response, indent=2))
            
            return {
                "order_response": order_response,
                "winner_name": winner_name,
                "winner_prob": winner_prob,
                "token_id": outcome_token_id,
                "amount": INVESTMENT_AMOUNT,
                "invested_at": dt.datetime.utcnow().isoformat(),
            }
        except Exception as e:
            print_error(f"Failed to place order: {e}")
            return None
    
    except Exception as e:
        print_error(f"Error in investment flow: {e}")
        return None


def _build_prediction_payload(structured_event: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Build prediction API payload from Gemini structured output.
    
    For 1v1: payload is same as structured_event (candidates array).
    For teams: transform teams array into candidates array (captain + coach for each team).
    """
    event_type = structured_event.get("event_type")
    
    if event_type == "1v1":
        # 1v1 format is already correct: {event_type: "1v1", candidates: [...], event: {...}}
        return _sanitize_prediction_payload(structured_event)
    
    elif event_type == "teams":
        # Teams format from Gemini: {event_type: "teams", candidates: [{team_name, captain, coach}, ...], event: {...}}
        # For prediction API we want a 1v1 between one person from each team:
        # - Prefer captain vs captain
        # - If a team has no captain, fall back to coach for that team
        teams_data = structured_event.get("candidates", [])  # Gemini uses "candidates" for teams
        prediction_candidates = []
        
        def _pick_best_person(team: Dict[str, Any]) -> tuple[Dict[str, Any] | None, str | None]:
            """Prefer a valid captain; if not, fall back to a valid coach.
            
            'Valid' means: has the full set of fields required by the prediction API,
            including geo + timezone. This avoids sending under-specified captains
            when the coach has complete data.
            """

            def is_valid(person: Any) -> bool:
                if not isinstance(person, dict):
                    return False
                required_fields = [
                    "name",
                    "birth_date",
                    "birth_place",
                    "birth_country",
                    "birth_timezone",
                    "lat",
                    "lon",
                    "lat_dir",
                    "lon_dir",
                ]
                # Reject None, empty strings, and the literal string "unknown"
                for field in required_fields:
                    value = person.get(field)
                    if value is None or value == "" or (isinstance(value, str) and value.lower() == "unknown"):
                        return False
                return True

            captain = team.get("captain") if isinstance(team.get("captain"), dict) else None
            coach = team.get("coach") if isinstance(team.get("coach"), dict) else None

            if is_valid(captain):
                return captain, "captain"
            if is_valid(coach):
                return coach, "coach"
            return None, None
        
        for team_data in teams_data:
            team_name = team_data.get("team_name", "Unknown Team")

            person, role = _pick_best_person(team_data)
            if not person or not role:
                # Skip teams where we don't have enough data for either captain or coach
                continue

            candidate: Dict[str, Any] = {
                "name": person.get("name"),
                "birth_date": person.get("birth_date"),
                "birth_time": person.get("birth_time"),
                "birth_place": person.get("birth_place"),
                "birth_country": person.get("birth_country"),
                "gender": person.get("gender", "unknown"),
            }

            # Include all geo fields if present (added by geo_enricher)
            if "lat" in person:
                candidate["lat"] = person.get("lat")
            if "lon" in person:
                candidate["lon"] = person.get("lon")
            if "lat_dir" in person:
                candidate["lat_dir"] = person.get("lat_dir")
            if "lon_dir" in person:
                candidate["lon_dir"] = person.get("lon_dir")
            if "birth_timezone" in person:
                candidate["birth_timezone"] = person.get("birth_timezone")

            prediction_candidates.append(candidate)
        
        # For teams, we need exactly 2 candidates (one from each team) for a 1v1 prediction
        if len(prediction_candidates) != 2:
            print_warning(
                f"Expected 2 candidates for teams event, but got {len(prediction_candidates)}. "
                f"Cannot build valid 1v1 prediction payload."
            )
            return None
        
        # Treat this as a 1v1 match for the prediction engine
        payload = {
            "event_type": "1v1",
            "candidates": prediction_candidates,
            "event": structured_event.get("event", {}),
        }
        return _sanitize_prediction_payload(payload)
    
    else:
        # Unknown type, return as-is (but sanitize keys)
        return _sanitize_prediction_payload(structured_event)


def _infer_api_event_type_for_payload(
    market: Dict[str, Any],
    structured_event: Dict[str, Any],
    market_type: str,
) -> str:
    """
    Map event/sport metadata to prediction API enum:
    football, cricket, basketball, boxing, ufc, tennis.
    """
    raw_event = market.get("raw_event", {}) or {}
    text = " ".join(
        [
            str(raw_event.get("title") or ""),
            str(raw_event.get("description") or ""),
            str(raw_event.get("slug") or ""),
            str(raw_event.get("category") or ""),
            str(raw_event.get("sportsMarketType") or ""),
            str(raw_event.get("sport") or ""),
            str((structured_event or {}).get("event", {}).get("event_name") or ""),
        ]
    ).lower()

    direct = str(
        raw_event.get("sport")
        or raw_event.get("category")
        or raw_event.get("event_type")
        or ""
    ).strip().lower()
    if direct in {"football", "cricket", "basketball", "boxing", "ufc", "tennis"}:
        return direct

    if any(k in text for k in ("ufc", "mma")):
        return "ufc"
    if any(k in text for k in ("boxing", "boxer")):
        return "boxing"
    if any(k in text for k in ("tennis", "atp", "wta", "grand slam")):
        return "tennis"
    if any(k in text for k in ("cricket", "t20", "odi", "ipl")):
        return "cricket"
    if any(k in text for k in ("nba", "wnba", "ncaab", "ncaawb", "basketball")):
        return "basketball"
    if any(k in text for k in ("football", "soccer", "epl", "la liga", "serie a", "bundesliga", "nfl")):
        return "football"

    return "football" if market_type == "teams" else "tennis"


def process_markets(
    max_count: Optional[int] = None,
    interactive: bool = True,
    event_type: Optional[str] = None,
    sport_keywords: Optional[list[str]] = None,
) -> None:
    """
    Process markets with status='new':
      - Run Gemini OneVsOne client to get structured event data.
      - Run EdgeCase client to get risk analysis.
      - Call prediction API and attach prediction result.
      - Update the market document in MongoDB.

    If interactive=True, ask before processing each market.
    """
    db = get_db()
    coll = db.markets

    one_v_one_client = OneVsOneGeminiClient()
    teams_client = TeamsGeminiClient()
    edge_case_client = EdgeCaseGeminiClient()

    # Only process markets whose end_date is today or in the future.
    # end_date is stored as an ISO8601 string (e.g. "2026-01-21T19:45:00Z"),
    # so we compare using an ISO string at today's UTC midnight.
    today_iso = (
        dt.datetime.utcnow()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    # Base query: only markets whose end_date is today or in the future.
    query: Dict[str, Any] = {
        "end_date": {"$gte": today_iso, "$exists": True},
    }

    # Type-specific status logic:
    # - For 1v1: allow re-running already processed markets (no status filter).
    # - For teams/others: keep status='new' so we don't reprocess everything.
    if event_type:
        query["type"] = event_type
        if event_type != "1v1":
            query["status"] = "new"
    else:
        query["status"] = "new"

    cursor = coll.find(query).sort("end_date", 1)
    if max_count is not None:
        cursor = cursor.limit(max_count)

    processed = 0
    # For non-interactive (auto) runs, collect a brief summary of invested markets.
    auto_invested_markets: list[Dict[str, Any]] = []

    for market in cursor:
        market_id = market.get("_id")
        raw_event = market.get("raw_event", {}) or {}
        title = market.get("title") or raw_event.get("title")
        end_date = market.get("end_date") or raw_event.get("endDate")
        market_type = market.get("type", "1v1")  # Default to 1v1 if not set
        slug = market.get("slug") or raw_event.get("slug")
        source_event_id = market.get("source_event_id") or raw_event.get("id")

        # Extra safety: skip obvious non-sports markets (earnings/elections/etc.)
        # for teams / mixed flows. For 1v1 runs, we do NOT skip based on these
        # keywords so tennis/1v1 markets behave as before.
        if event_type != "1v1":
            text = " ".join(
                [
                    str(title or ""),
                    str(raw_event.get("description") or ""),
                    str(slug or ""),
                ]
            ).lower()
            # Optional sport / league filter: if provided, only keep markets whose
            # text contains at least one of the keywords (e.g. "cricket", "epl").
            if sport_keywords:
                lowered_keywords = [kw.lower() for kw in sport_keywords]
                if not any(kw in text for kw in lowered_keywords):
                    continue
            # Skip "More Markets" / props-style events (O/U, totals, etc.) for teams,
            # since our strategy is about predicting the match winner, not totals.
            if "more markets" in text:
                print_info("Skipping 'More Markets' / totals event for teams pipeline.")
                continue
            if (
                any(kw in text for kw in EARNINGS_KEYWORDS)
                or any(kw in text for kw in ELECTION_KEYWORDS)
                or any(kw in text for kw in ENTERTAINMENT_KEYWORDS)
            ):
                print_info("Skipping non-sports market (earnings/election/entertainment).")
                continue

        # Odds to show in CLI: resolve via Gamma helpers (which also validate
        # and update the Mongo snapshot) so we don't keep stale mappings
        # (e.g., Damwon/Suning from legacy markets).
        current_odds = None
        # Token IDs to show in CLI: resolve via Gamma helpers (which also
        # validate and update the Mongo snapshot) so we don't get stale
        # mappings like old Damwon/Suning markets.
        current_token_ids = None
        # Resolve odds once at the start for this market
        if source_event_id or slug:
            try:
                print_info("Resolving outcome prices (odds)...")
                prices = get_outcome_prices(source_event_id=source_event_id, slug=slug)
                if prices:
                    current_odds = prices
                    print_info(f"Using resolved outcome prices as odds: {current_odds}")

                    # If odds are already effectively 0 or 1 on any side, treat as
                    # resolved and skip this market (no point predicting/investing).
                    try:
                        numeric_odds = [
                            float(v) for v in current_odds.values() if v is not None
                        ]
                        # 1) If any side is effectively 0 or 1, treat as resolved.
                        if any(p <= 0.01 or p >= 0.99 for p in numeric_odds):
                            print_warning(
                                "Market appears resolved from outcome prices (0 or 1 odds). "
                                "Skipping this market."
                            )
                            coll.update_one(
                                {"_id": market_id},
                                {
                                    "$set": {
                                        "status": "resolved",
                                        "updated_at": dt.datetime.utcnow(),
                                    }
                                },
                            )
                            # Move to next market in cursor.
                            continue
                        # 2) If both sides are ~50/50, this often indicates a void/
                        # cancelled market with frozen prices. Skip these as well.
                        if numeric_odds and all(
                            abs(p - 0.5) <= 0.01 for p in numeric_odds
                        ):
                            print_warning(
                                "Market appears to be 50/50 on all outcomes "
                                "(likely void/cancelled). Skipping this market."
                            )
                            coll.update_one(
                                {"_id": market_id},
                                {
                                    "$set": {
                                        "status": "void",
                                        "updated_at": dt.datetime.utcnow(),
                                    }
                                },
                            )
                            continue
                    except Exception:
                        # If parsing fails, just ignore and continue normally.
                        pass
                else:
                    print_warning("Could not resolve outcome prices for this market.")
            except Exception as e:
                print_warning(f"Could not resolve outcome prices: {e}")

        try:
            if source_event_id:
                print_info("Resolving token IDs for display...")
                if market_type == "teams" and slug:
                    token_ids_fresh = get_market_token_ids_for_slug(slug)
                    if not token_ids_fresh:
                        print_info(
                            "Slug-based token ID lookup returned no results; "
                            "falling back to event_id-based lookup."
                        )
                        token_ids_fresh = get_market_token_ids(source_event_id)
                else:
                    token_ids_fresh = get_market_token_ids(source_event_id)

                if token_ids_fresh:
                    current_token_ids = {str(k): str(v) for k, v in token_ids_fresh.items()}
                    print_info(f"Using resolved token IDs: {current_token_ids}")
                    # Persist (or correct) snapshot back to Mongo for future runs.
                    coll.update_one(
                        {"_id": market_id},
                        {
                            "$set": {
                                "token_ids": current_token_ids,
                                "updated_at": dt.datetime.utcnow(),
                            }
                        },
                    )
        except Exception as e:
            print_warning(f"Could not resolve token IDs for display: {e}")

        # Loop on the same market until success/skip/back/exit
        while True:
            if interactive:
                print_market_card(
                    title=title,
                    market_type=market_type,
                    end_date=str(end_date),
                    market_id=str(market_id),
                    slug=slug,
                    source_event_id=str(source_event_id) if source_event_id else None,
                    odds=current_odds,
                    token_ids=current_token_ids,
                )

            if interactive:
                ans = prompt_yes_no("Process this market?", default=True, allow_back=True)
                if ans is None:
                    print_success("Exiting. Goodbye!")
                    sys.exit(0)
                elif ans == "b":
                    print_info("Going back to market type selection.")
                    return
                elif ans == "n":
                    print_info("Skipping market.")
                    break  # move to next market

            raw_event = market.get("raw_event")
            if not raw_event:
                print("No raw_event found on market, marking as error.")
                coll.update_one(
                    {"_id": market_id},
                    {
                        "$set": {
                            "status": "error",
                            "last_error_message": "Missing raw_event on market document.",
                            "updated_at": dt.datetime.utcnow(),
                        }
                    },
                )
                break

            event_json = json.dumps(raw_event)

            try:
                # Choose Gemini client based on market type
                if market_type == "teams":
                    print("Using TeamsGeminiClient for team event...")
                    structured = teams_client.generate_text(event_json)
                    client_name = "Teams"
                else:
                    # Default to 1v1 (tennis, boxing, etc.)
                    print("Using OneVsOneGeminiClient for 1v1 event...")
                    structured = one_v_one_client.generate_text(event_json)
                    client_name = "1v1"
                
                if not structured:
                    raise Exception(f"No structured result from Gemini {client_name} client.")

                edge_case = edge_case_client.generate_text(event_json) or {}

                has_edge_case = bool(edge_case.get("has_edge_case", False))
                risk_level = edge_case.get("risk_level", "None")

                # Enrich structured data with geo info and show summary
                structured = enrich_structured_event(structured)
                print_structured_summary(structured)

                # Build payload for prediction API
                payload = _build_prediction_payload(structured)
                prediction_result = None

                # If payload is None, we can't send to prediction API (e.g., missing required data)
                if payload is None:
                    print_warning(
                        "Cannot build valid prediction payload (missing required candidate data). "
                        "Skipping prediction API call for this market."
                    )
                    # Still save the structured event to MongoDB
                    now = dt.datetime.utcnow()
                    coll.update_one(
                        {"_id": market_id},
                        {
                            "$set": {
                                "structured_event": structured,
                                "edge_case": edge_case,
                                "updated_at": now.isoformat(),
                            }
                        },
                    )
                    print_success(f"Market {market_id} updated (structured event saved, no prediction).")
                    continue

                # Validate candidate fields for both 1v1 and teams before calling prediction API.
                payload_candidates = payload.get("candidates") or []
                if not _has_required_candidate_fields(payload_candidates):
                    print_warning(
                        "Cannot build valid prediction payload (missing candidate geo/birth fields). "
                        "Skipping prediction API call for this market."
                    )
                    now = dt.datetime.utcnow()
                    coll.update_one(
                        {"_id": market_id},
                        {
                            "$set": {
                                "structured_event": structured,
                                "edge_case": edge_case,
                                "prediction_payload": payload,
                                "updated_at": now.isoformat(),
                            }
                        },
                    )
                    print_success(
                        f"Market {market_id} updated (structured event + payload saved, no prediction)."
                    )
                    continue

                # Ensure event-level geo is present; the prediction API expects event_lat / event_lon.
                event_payload = (payload.get("event") or {})
                if event_payload.get("event_lat") is None or event_payload.get("event_lon") is None:
                    print_warning(
                        "Cannot build valid prediction payload (missing event geo fields). "
                        "Skipping prediction API call for this market."
                    )
                    # Save structured event and payload for debugging/analysis, but skip prediction.
                    now = dt.datetime.utcnow()
                    coll.update_one(
                        {"_id": market_id},
                        {
                            "$set": {
                                "structured_event": structured,
                                "edge_case": edge_case,
                                "prediction_payload": payload,
                                "updated_at": now.isoformat(),
                            }
                        },
                    )
                    print_success(
                        f"Market {market_id} updated (structured event + payload saved, no prediction)."
                    )
                    continue

                # Prediction API requires nested event.event_type enum.
                payload.setdefault("event", {})
                payload["event"]["event_type"] = _infer_api_event_type_for_payload(
                    market=market,
                    structured_event=structured,
                    market_type=market_type,
                )

                # In interactive mode, ask whether to send to prediction engine
                # Default send = True when no edge case; False when edge case found.
                default_send = not has_edge_case
                sent_to_prediction = False
                if interactive:
                    send = prompt_yes_no(
                        "Send this market to prediction engine now?",
                        default=default_send,
                        allow_back=True,
                    )
                    if send is None:
                        print_success("Exiting. Goodbye!")
                        sys.exit(0)
                    elif send == "b":
                        print_info("Going back to market selection.")
                        break  # move back to type selection
                    elif send == "y":
                        sent_to_prediction = True
                        print_info("Prediction API payload:")
                        print(json.dumps(payload, indent=2))
                        prediction_result = get_prediction(payload)
                    else:
                        print_info("Skipping prediction API call for this market.")
                else:
                    sent_to_prediction = True
                    # In non-interactive/auto mode, avoid dumping large JSON payloads.
                    prediction_result = get_prediction(payload)

                now = dt.datetime.utcnow()
                coll.update_one(
                    {"_id": market_id},
                    {
                        "$set": {
                            "structured_event": structured,
                            "edge_case": edge_case,
                            "has_edge_case": has_edge_case,
                            "edge_case_risk_level": risk_level,
                            "prediction_payload": payload,
                            "prediction_result": prediction_result,
                            "status": "predicted" if prediction_result else "analyzed",
                            "updated_at": now,
                        }
                    },
                )

                processed += 1
                if prediction_result:
                    if interactive:
                        print_success(
                            f"Market processed and predicted. Edge case: {has_edge_case}, "
                            f"Risk: {risk_level}"
                        )
                        print_info("Prediction API response:")
                        print(json.dumps(prediction_result, indent=2))
                        if edge_case:
                            print_info("Edge case analysis:")
                            print(json.dumps(edge_case, indent=2))
                    
                    # Append a CSV row for offline analysis
                    _append_prediction_csv(
                        market=market,
                        structured_event=structured,
                        payload=payload,
                        prediction_result=prediction_result,
                        edge_case=edge_case,
                        risk_level=risk_level,
                    )
                    
                    # Investment flow after successful prediction
                    investment_result = _handle_investment_flow(
                        market, prediction_result, interactive=interactive
                    )
                    
                    # Save investment result to MongoDB if investment was made
                    if investment_result:
                        now = dt.datetime.utcnow()
                        coll.update_one(
                            {"_id": market_id},
                            {
                                "$set": {
                                    "investment_result": investment_result,
                                    "status": "invested",
                                    "updated_at": now,
                                }
                            },
                        )
                        # For auto runs, keep a lightweight summary for final logging.
                        if not interactive:
                            auto_invested_markets.append(
                                {
                                    "title": str(title),
                                    "slug": str(slug) if slug else None,
                                    "source_event_id": str(source_event_id)
                                    if source_event_id
                                    else None,
                                    "winner_name": investment_result.get("winner_name"),
                                    "winner_prob": investment_result.get("winner_prob"),
                                }
                            )
                    
                    break  # success, move to next market
                else:
                    if sent_to_prediction:
                        print_warning(
                            f"Prediction failed. Edge case: {has_edge_case}, Risk: {risk_level}"
                        )
                        retry = prompt_yes_no(
                            "Retry this market (prediction failed)?",
                            default=False,
                            allow_back=True,
                        )
                        if retry is None:
                            print_success("Exiting. Goodbye!")
                            sys.exit(0)
                        elif retry == "b":
                            print_info("Going back to market type selection.")
                            break
                        elif retry == "y":
                            continue  # retry same market
                        else:
                            print_info("Skipping this market after prediction failure.")
                            break
                    else:
                        print_warning(
                            f"Market analyzed but prediction skipped. Edge case: {has_edge_case}, "
                            f"Risk: {risk_level}"
                        )
                        if edge_case:
                            print_info("Edge case analysis:")
                            print(json.dumps(edge_case, indent=2))
                        break

            except Exception as e:
                print_error(f"Error processing market: {e}")
                if interactive:
                    retry = prompt_yes_no(
                        "Retry this market after error?",
                        default=False,
                        allow_back=True,
                    )
                    if retry is None:
                        print_success("Exiting. Goodbye!")
                        sys.exit(0)
                    elif retry == "b":
                        print_info("Going back to market type selection.")
                        break
                    elif retry == "y":
                        continue  # retry same market
                # Non-interactive (or user chose not to retry): mark error and move on
                coll.update_one(
                    {"_id": market_id},
                    {
                        "$set": {
                            "status": "error",
                            "last_error_message": str(e),
                            "updated_at": dt.datetime.utcnow(),
                        }
                    },
                )
                break

    if not interactive and auto_invested_markets:
        print("\nAuto-invest run complete. Invested in the following markets:")
        for inv in auto_invested_markets:
            slug = inv.get("slug")
            url = f"https://polymarket.com/event/{slug}" if slug and slug != "None" else None
            line = f"- {inv.get('title')} (winner: {inv.get('winner_name')}, prob={inv.get('winner_prob'):.2f}%)"
            if url:
                line += f" | URL: {url}"
            print(line)

    print(f"\nProcessing complete. Markets processed: {processed}")
