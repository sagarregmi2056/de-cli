#!/usr/bin/env python
"""
One-off script to run Gemini + prediction for:
    ATP: Alexander Bublik vs Tomas Etcheverry
    Match date: Jan 23, 2026

It reuses the cli-app clients, config, geo enrichment, and prediction client.
Run from project root (or from cli-app with PYTHONPATH set appropriately):

    cd cli-app
    source .venv/bin/activate
    python directpredictions.py
"""

import json
import sys

# Make sure cli-app is on sys.path if you run from project root
# import os, pathlib
# sys.path.append(str(pathlib.Path(__file__).resolve().parent))

from gemini_clients import OneVsOneGeminiClient, EdgeCaseGeminiClient
from geo_enricher import enrich_structured_event
from prediction_client import get_prediction
from market_processor import _append_prediction_csv
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder


# Helper for retry geocoding
_geolocator_retry = Nominatim(user_agent="debot-cli-retry/1.0", timeout=10)
_tf_retry = TimezoneFinder()


def _retry_geocode(location_name: str):
    """Retry geocoding with a fresh geocoder instance."""
    try:
        loc = _geolocator_retry.geocode(location_name, addressdetails=False)
        if not loc:
            return None
        tz = _tf_retry.timezone_at(lng=loc.longitude, lat=loc.latitude)
        return {
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "lat_dir": "N" if loc.latitude >= 0 else "S",
            "lon_dir": "E" if loc.longitude >= 0 else "W",
            "timezone": tz,
        }
    except Exception:
        return None


def build_event() -> dict:
    """
    Minimal Polymarket-like event payload for the Bublik vs Etcheverry match.
    Gemini only needs a good title + location/time context.
    
    Match: Alexander Bublik vs Tomas Etcheverry
    Date: Jan 23, 2026
    Source: https://polymarket.com/sports/atp/games/date/2026-01-22/atp-bublik-etcheve-2026-01-23
    """
    return {
        "id": "manual-bublik-etcheverry",
        "title": "ATP: Alexander Bublik vs Tomas Etcheverry",
        "description": (
            "Prediction market for the ATP men's singles match between "
            "Alexander Bublik and Tomas Etcheverry on January 23, 2026."
        ),
        "slug": "atp-bublik-etcheve-2026-01-23",
        "startDate": "2026-01-23T00:00:00Z",
        "endDate": "2026-01-24T00:00:00Z",
        "eventLocation": "ATP Tour match venue",
    }


def main() -> None:
    raw_event = build_event()
    event_str = json.dumps(raw_event)

    one_v_one_client = OneVsOneGeminiClient()
    edge_case_client = EdgeCaseGeminiClient()

    print("=== Sending event to Gemini (1v1 client) ===")
    structured = one_v_one_client.generate_text(event_str)
    if not structured:
        print("No structured result from Gemini 1v1 client.")
        sys.exit(1)

    print("\n=== Sending event to Gemini (EdgeCase client) ===")
    edge_case = edge_case_client.generate_text(event_str) or {}
    has_edge_case = bool(edge_case.get("has_edge_case", False))
    risk_level = edge_case.get("risk_level", "None")

    print("\n=== Structured Event (raw from Gemini) ===")
    print(json.dumps(structured, indent=2))

    print("\n=== Edge Case Analysis ===")
    print(json.dumps(edge_case, indent=2))

    # Enrich with geo info (lat/lon/timezone) like in the CLI
    structured = enrich_structured_event(structured)

    print("\n=== Structured Event (after geo enrichment) ===")
    print(json.dumps(structured, indent=2))

    if has_edge_case:
        print(f"\n[Warning] has_edge_case = {has_edge_case}, risk_level = {risk_level}")
        proceed = input("Edge case detected. Still send to prediction API? [y/N]: ").strip().lower()
        if proceed not in ("y", "yes"):
            print("Skipping prediction API call due to edge case.")
            sys.exit(0)

    # Ensure all required event fields are present (API requires event_lat, event_lon, etc.)
    event = structured.get("event", {})
    
    # If geo enrichment failed to add event lat/lon, add defaults for Melbourne
    if "event_lat" not in event or event.get("event_lat") is None:
        event["event_lat"] = -37.8213608  # Melbourne Park default
        event["event_lon"] = 144.9790884
        event["event_lat_dir"] = "S"
        event["event_lon_dir"] = "E"
        print("\n[Note] Using default Melbourne coordinates for event location")
    
    # Ensure event_timezone is present (should be set by geo_enricher, but fallback if missing)
    if "event_timezone" not in event or not event.get("event_timezone"):
        event["event_timezone"] = "Australia/Melbourne"
        print("[Note] Using default timezone: Australia/Melbourne")

    # Ensure all candidates have required fields (lat, lon, lat_dir, lon_dir, birth_timezone)
    candidates = structured.get("candidates", [])
    
    # Country fallback coordinates (capital cities as fallback)
    country_fallbacks = {
        "Russia": {"lat": 55.7558, "lon": 37.6173, "lat_dir": "N", "lon_dir": "E", "timezone": "Europe/Moscow"},
        "Germany": {"lat": 52.5200, "lon": 13.4050, "lat_dir": "N", "lon_dir": "E", "timezone": "Europe/Berlin"},
        "USA": {"lat": 38.9072, "lon": -77.0369, "lat_dir": "N", "lon_dir": "W", "timezone": "America/New_York"},
        "Spain": {"lat": 40.4168, "lon": -3.7038, "lat_dir": "N", "lon_dir": "W", "timezone": "Europe/Madrid"},
        "France": {"lat": 48.8566, "lon": 2.3522, "lat_dir": "N", "lon_dir": "E", "timezone": "Europe/Paris"},
        "UK": {"lat": 51.5074, "lon": -0.1278, "lat_dir": "N", "lon_dir": "W", "timezone": "Europe/London"},
        "Australia": {"lat": -35.2809, "lon": 149.1300, "lat_dir": "S", "lon_dir": "E", "timezone": "Australia/Sydney"},
        "Kazakhstan": {"lat": 51.1694, "lon": 71.4491, "lat_dir": "N", "lon_dir": "E", "timezone": "Asia/Almaty"},
        "Argentina": {"lat": -34.6037, "lon": -58.3816, "lat_dir": "S", "lon_dir": "W", "timezone": "America/Argentina/Buenos_Aires"},
    }
    
    for cand in candidates:
        # Ensure birth_time is None (not "unknown")
        if cand.get("birth_time") == "unknown":
            cand["birth_time"] = None
        
        # If missing geo fields, try to geocode again with simpler location string
        if "lat" not in cand or cand.get("lat") is None:
            birth_place = cand.get("birth_place", "")
            birth_country = cand.get("birth_country", "")
            
            print(f"\n[Warning] Candidate {cand.get('name')} missing geo fields. Attempting retry...")
            
            # Try different location formats
            location_attempts = []
            if birth_place and birth_country:
                location_attempts.append(f"{birth_place}, {birth_country}")
                location_attempts.append(birth_country)  # Try just country
            elif birth_country:
                location_attempts.append(birth_country)
            elif birth_place:
                location_attempts.append(birth_place)
            
            geo_success = False
            for loc_str in location_attempts:
                geo = _retry_geocode(loc_str)
                if geo:
                    cand["lat"] = geo["latitude"]
                    cand["lon"] = geo["longitude"]
                    cand["lat_dir"] = geo["lat_dir"]
                    cand["lon_dir"] = geo["lon_dir"]
                    cand["birth_timezone"] = geo.get("timezone")
                    geo_success = True
                    print(f"[Success] Geocoded {cand.get('name')} using: {loc_str}")
                    break
            
            # If still no geo data, use country fallback
            if not geo_success and birth_country in country_fallbacks:
                fallback = country_fallbacks[birth_country]
                cand["lat"] = fallback["lat"]
                cand["lon"] = fallback["lon"]
                cand["lat_dir"] = fallback["lat_dir"]
                cand["lon_dir"] = fallback["lon_dir"]
                cand["birth_timezone"] = fallback["timezone"]
                print(f"[Note] Using country fallback coordinates for {cand.get('name')} ({birth_country})")
            elif not geo_success:
                print(f"[Error] Cannot geocode {cand.get('name')} and no fallback available for {birth_country}")
                print("This will cause API errors. Please check the birth_place/birth_country fields.")

    # Build prediction payload (for 1v1 we can just send structured event)
    payload = {
        "event_type": structured.get("event_type", "1v1"),
        "candidates": candidates,
        "event": event,
    }

    # Final validation: ensure all required fields are present
    required_event_fields = ["event_name", "event_date", "event_time", "event_location", 
                            "event_timezone", "event_lat", "event_lon", "event_lat_dir", "event_lon_dir"]
    missing_event_fields = [f for f in required_event_fields if f not in event or event.get(f) is None]
    if missing_event_fields:
        print(f"\n[Error] Event missing required fields: {missing_event_fields}")
        print("Cannot send to prediction API without these fields.")
        sys.exit(1)
    
    # Validate all candidates have required fields
    required_candidate_fields = ["name", "birth_date", "birth_place", "birth_country", "gender",
                                "lat", "lon", "lat_dir", "lon_dir", "birth_timezone"]
    for cand in candidates:
        missing = [f for f in required_candidate_fields if f not in cand or cand.get(f) is None]
        if missing:
            print(f"\n[Error] Candidate {cand.get('name')} missing required fields: {missing}")
            print("Cannot send to prediction API without these fields.")
            sys.exit(1)

    print("\n=== Sending payload to prediction API ===")
    print("Payload preview:")
    print(json.dumps(payload, indent=2))

    prediction = get_prediction(payload)
    if prediction is None:
        print("\n[Error] No prediction received from API.")
        sys.exit(1)

    print("\n=== Prediction API Response ===")
    print(json.dumps(prediction, indent=2))
    
    # Save to CSV (same as interactive mode)
    # Build a minimal market dict for CSV logging
    market = {
        "_id": None,
        "source_event_id": raw_event.get("id"),
        "slug": raw_event.get("slug"),
        "title": raw_event.get("title"),
        "raw_event": raw_event,
    }
    try:
        _append_prediction_csv(
            market=market,
            structured_event=structured,
            payload=payload,
            prediction_result=prediction,
            edge_case=edge_case,
            risk_level=risk_level,
        )
        print("\n[Info] Prediction saved to predictedmarket/predictions.csv")
    except Exception as e:
        print(f"\n[Warning] Failed to save prediction to CSV: {e}")
    
    # Display prediction summary
    print("\n" + "=" * 70)
    print("PREDICTION SUMMARY")
    print("=" * 70)
    if prediction and "PersonA" in prediction and "PersonB" in prediction:
        person_a = prediction["PersonA"]
        person_b = prediction["PersonB"]
        print(f"{person_a.get('Name', 'PersonA')}: {person_a.get('WinPercentage', '0')}%")
        print(f"{person_b.get('Name', 'PersonB')}: {person_b.get('WinPercentage', '0')}%")
        
        # Determine predicted winner
        try:
            a_prob = float(person_a.get('WinPercentage', '0'))
            b_prob = float(person_b.get('WinPercentage', '0'))
            if a_prob > b_prob:
                winner = person_a.get('Name', 'PersonA')
                prob = a_prob
            else:
                winner = person_b.get('Name', 'PersonB')
                prob = b_prob
            print(f"\nPredicted Winner: {winner} ({prob:.2f}% win probability)")
        except (ValueError, TypeError):
            print("\nCould not determine predicted winner from percentages")
    print("=" * 70)
    print("\nNote: Check the actual match result on Polymarket to compare:")
    print("https://polymarket.com/sports/atp/games/date/2026-01-22/atp-bublik-etcheve-2026-01-23")


if __name__ == "__main__":
    main()