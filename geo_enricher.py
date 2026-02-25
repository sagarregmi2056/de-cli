"""
Geo enrichment utilities for structured Gemini events.

Adds lat/lon, directions, and timezone to candidates and event based on
birth_place/birth_country and event_location strings.
"""

import time
from functools import lru_cache
from typing import Any, Dict, Optional

from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

# Shared geocoder / timezone finder
_geolocator = Nominatim(user_agent="debot-cli/1.0", timeout=10)
_tf = TimezoneFinder()


@lru_cache(maxsize=512)
def _geocode(location_name: str) -> Optional[Dict[str, Any]]:
    try:
        loc = _geolocator.geocode(location_name, addressdetails=False)
        if not loc:
            return None
        tz = _tf.timezone_at(lng=loc.longitude, lat=loc.latitude)
        return {
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "lat_dir": "N" if loc.latitude >= 0 else "S",
            "lon_dir": "E" if loc.longitude >= 0 else "W",
            "timezone": tz,
        }
    except Exception:
        return None


def _geocode_event_location_with_fallbacks(location_name: str) -> Optional[Dict[str, Any]]:
    """
    Geocode an event_location string with a couple of graceful fallbacks.
    
    Many event locations are of the form "Venue, City, Country". Some
    venues are hard for Nominatim to resolve, but the "City, Country"
    tail is usually enough. This helper tries:
      1) Full string
      2) The last two comma‑separated components (e.g. "Colombo, Sri Lanka")
    """
    if not location_name:
        return None

    # 1) Try the full location string first
    geo = _geocode(location_name)
    if geo:
        return geo

    # 2) Try a simplified "city, country" tail if available
    parts = [p.strip() for p in location_name.split(",") if p.strip()]
    if len(parts) >= 2:
        fallback = ", ".join(parts[-2:])
        # Avoid a redundant call if the fallback is identical
        if fallback.lower() != location_name.lower():
            geo = _geocode(fallback)
            if geo:
                return geo

    return None


def enrich_structured_event(structured: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich structured_event (1v1 or teams) with lat/lon/timezone where possible.
    Mutates and returns the structured dict.
    """
    event_type = structured.get("event_type")
    event = structured.get("event", {})

    def geocode_and_apply(obj: Dict[str, Any], place: str, is_event: bool = False) -> None:
        if not place:
            return
        geo = _geocode(place)
        if not geo:
            return
        obj["lat"] = geo["latitude"]
        obj["lon"] = geo["longitude"]
        obj["lat_dir"] = geo["lat_dir"]
        obj["lon_dir"] = geo["lon_dir"]
        tz = geo.get("timezone")
        if is_event:
            obj["event_timezone"] = obj.get("event_timezone") or tz
        else:
            obj["birth_timezone"] = obj.get("birth_timezone") or tz

    def fallback_event_timezone(place: str) -> str:
        """Provide a best-effort timezone if geocoding did not return one."""
        place_l = place.lower()
        if "melbourne" in place_l:
            return "Australia/Melbourne"
        if "sydney" in place_l:
            return "Australia/Sydney"
        if "new york" in place_l:
            return "America/New_York"
        if "london" in place_l:
            return "Europe/London"
        if "paris" in place_l:
            return "Europe/Paris"
        # Generic fallback to avoid missing TZ in payloads
        return "UTC"

    # Enrich candidates
    candidates = structured.get("candidates", [])

    if event_type == "teams":
        # For team events, each candidate is actually a team object
        # with nested captain/coach persons. We need to enrich those
        # nested persons so the prediction payload has full geo data.
        for team in candidates:
            for role_key in ("captain", "coach"):
                person = team.get(role_key)
                if not isinstance(person, dict):
                    continue

                birth_place = person.get("birth_place")
                birth_country = person.get("birth_country")
                place_str = None
                if birth_place and birth_country:
                    place_str = f"{birth_place}, {birth_country}"
                elif birth_place:
                    place_str = birth_place
                elif birth_country:
                    place_str = birth_country

                if place_str:
                    geocode_and_apply(person, place_str, is_event=False)
                    # be polite to Nominatim
                    time.sleep(0.2)

                # Normalize birth_time: set None instead of "unknown"
                if person.get("birth_time") == "unknown":
                    person["birth_time"] = None
    else:
        # 1v1 and other event types: candidates are already persons
        for cand in candidates:
            birth_place = cand.get("birth_place")
            birth_country = cand.get("birth_country")
            place_str = None
            if birth_place and birth_country:
                place_str = f"{birth_place}, {birth_country}"
            elif birth_place:
                place_str = birth_place
            elif birth_country:
                place_str = birth_country
            if place_str:
                geocode_and_apply(cand, place_str, is_event=False)
                # be polite to Nominatim
                time.sleep(0.2)
            # Normalize birth_time: set None instead of "unknown"
            if cand.get("birth_time") == "unknown":
                cand["birth_time"] = None

    # Enrich event location
    event_location = event.get("event_location")
    if event_location:
        geo = _geocode_event_location_with_fallbacks(event_location)
        if geo:
            event["event_lat"] = geo["latitude"]
            event["event_lon"] = geo["longitude"]
            event["event_lat_dir"] = geo["lat_dir"]
            event["event_lon_dir"] = geo["lon_dir"]
            event["event_timezone"] = event.get("event_timezone") or geo.get("timezone")
        # Fallback timezone if still missing
        if not event.get("event_timezone"):
            event["event_timezone"] = fallback_event_timezone(event_location)

    structured["event"] = event
    structured["candidates"] = candidates
    return structured


