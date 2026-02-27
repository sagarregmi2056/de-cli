"""
Minimal Flask web UI to inspect predicted and invested Polymarket markets.

This reuses the same MongoDB `markets` collection populated by the CLI
pipelines and renders a simple HTML page with:

- Predicted markets (have `prediction_result`)
- Whether we invested, and basic investment details
- Predictions endpoint: paste URL and get predictions
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from flask import Flask, render_template, request, jsonify

from db import get_db
from gamma_client import get_event, get_markets
from gemini_clients import OneVsOneGeminiClient, TeamsGeminiClient, EdgeCaseGeminiClient
from geo_enricher import enrich_structured_event
from prediction_client import get_prediction
from market_processor import _build_prediction_payload
from markets_scanner import classify_event_type


app = Flask(__name__)


def _serialize_market(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare a market document for safe rendering in templates."""
    raw_event = doc.get("raw_event", {}) or {}

    prediction: Dict[str, Any] = doc.get("prediction_result") or {}
    person_a = prediction.get("PersonA") or {}
    person_b = prediction.get("PersonB") or {}

    investment: Dict[str, Any] = doc.get("investment_result") or {}

    def _safe(v: Any, default: str = "") -> Any:
        return default if v is None else v

    # Determine predicted winner + prob (if available)
    winner_name = None
    winner_prob = None
    try:
        pa_name = _safe(person_a.get("Name"))
        pb_name = _safe(person_b.get("Name"))
        pa_win = float(person_a.get("WinPercentage", "0") or 0)
        pb_win = float(person_b.get("WinPercentage", "0") or 0)
        if pa_win > pb_win:
            winner_name = pa_name
            winner_prob = pa_win
        elif pb_win > pa_win:
            winner_name = pb_name
            winner_prob = pb_win
    except Exception:
        # If anything goes wrong, we just omit the winner summary.
        winner_name = None
        winner_prob = None

    return {
        "id": str(doc.get("_id")),
        "source_event_id": str(doc.get("source_event_id") or raw_event.get("id") or ""),
        "slug": _safe(doc.get("slug") or raw_event.get("slug"), ""),
        "title": _safe(doc.get("title") or raw_event.get("title"), ""),
        "type": _safe(doc.get("type"), "unknown"),
        "end_date": _safe(doc.get("end_date") or raw_event.get("endDate"), ""),
        "status": _safe(doc.get("status"), "unknown"),
        "edge_case_risk_level": _safe(doc.get("edge_case_risk_level"), "None"),
        "has_edge_case": bool(doc.get("has_edge_case", False)),
        "winner_name": winner_name,
        "winner_prob": winner_prob,
        "investment": {
            "winner_name": investment.get("winner_name"),
            "winner_prob": investment.get("winner_prob"),
            "amount": investment.get("amount"),
            "token_id": investment.get("token_id"),
        }
        if investment
        else None,
    }


@app.route("/")
def index():
    """
    List predicted markets, optionally filtered by status.

    Query params:
      - status: "all" (default), "predicted", or "invested"
    """
    db = get_db()
    coll = db.markets

    status_filter = request.args.get("status", "all")

    query: Dict[str, Any] = {
        # Only show markets where we have a prediction_result
        "prediction_result": {"$exists": True},
    }
    if status_filter == "invested":
        query["status"] = "invested"
    elif status_filter == "predicted":
        # Explicitly exclude invested, keep "predicted"/"analyzed" etc.
        query["status"] = {"$ne": "invested"}

    docs: List[Dict[str, Any]] = list(
        coll.find(query).sort("end_date", 1).limit(500)
    )

    markets = [_serialize_market(doc) for doc in docs]

    return render_template(
        "markets.html",
        markets=markets,
        status_filter=status_filter,
    )


def _extract_event_info_from_url(url: str) -> Dict[str, Optional[str]]:
    """Extract event ID or slug from a Polymarket URL."""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    
    event_id = None
    slug = None
    
    # Check query parameters
    query_params = parse_qs(parsed.query)
    if "slug" in query_params:
        slug = query_params["slug"][0]
    if "event_id" in query_params or "id" in query_params:
        event_id = query_params.get("event_id", query_params.get("id", [None]))[0]
    
    # Extract from path
    if not event_id and not slug:
        # Look for numeric ID
        for part in path_parts:
            if part.isdigit():
                event_id = part
                break
        
        # Last segment might be slug (common pattern: /sports/ufc/ufc-sea2-ant-2026-02-21)
        if not event_id and path_parts:
            potential_slug = path_parts[-1]
            # Skip common non-slug segments
            if potential_slug not in ["event", "events", "markets", "market", "sports", "ufc", "atp", "epl"]:
                slug = potential_slug
    
    return {"event_id": event_id, "slug": slug}


def _fetch_event_data(event_id: Optional[str] = None, slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch event data from Polymarket with multiple fallback strategies."""
    # Strategy: Try slug first (more reliable for sports URLs), then event_id as fallback
    # This is because many sports events aren't accessible via /events/{id} but work via slug
    
    # Try slug-based lookup first (most reliable for URLs like /sports/ufc/...)
    if slug:
        # Strategy 1: Direct /markets?slug=<slug> lookup
        markets = get_markets(slug=slug)
        if markets and len(markets) > 0:
            market = markets[0]
            
            # If market has a title, use it directly - don't try to fetch event
            # Many sports markets are self-contained and event lookup often fails with 404
            if market.get("title"):
                # Market has title, use it directly (even if it doesn't have outcomes yet)
                # This avoids 404 errors when trying to fetch events that don't exist
                return market
        

        try:
            # Try without prefix (e.g., "sea2-ant-2026-02-21" instead of "ufc-sea2-ant-2026-02-21")
            slug_parts = slug.split("-")
            if len(slug_parts) > 3:
                # Try last few parts as alternative slug
                alt_slug = "-".join(slug_parts[-4:])  # e.g., "sea2-ant-2026-02-21"
                alt_markets = get_markets(slug=alt_slug)
                if alt_markets and len(alt_markets) > 0:
                    market = alt_markets[0]
                    # Use market directly if it has title (avoid event lookup that might 404)
                    if market.get("title"):
                        return market
        except Exception:
            pass
        
        # Strategy 3: Try fetching events and search for matching slug in event data
        # This is a last resort as it's more expensive
        try:
            from gamma_client import GAMMA_API_BASE
            import requests
            
          
            events_url = f"{GAMMA_API_BASE}/events"
            
            response = requests.get(events_url, params={"slug": slug}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                elif isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                        return data["data"][0]
                    elif "events" in data and isinstance(data["events"], list) and len(data["events"]) > 0:
                        return data["events"][0]
        except Exception:
            pass
    
    if event_id and not slug:
        event = get_event(event_id)
        if event:
            return event
    
    return None


def _infer_api_event_type(raw_event: Dict[str, Any], structured: Dict[str, Any], event_type: str) -> str:
    """
    Map market/sport metadata to the prediction API's allowed enum values:
    football, cricket, basketball, boxing, ufc, tennis.
    """
    text = " ".join(
        [
            str(raw_event.get("title") or ""),
            str(raw_event.get("description") or ""),
            str(raw_event.get("slug") or ""),
            str(raw_event.get("category") or ""),
            str(raw_event.get("sportsMarketType") or ""),
            str(raw_event.get("sport") or ""),
            str((structured or {}).get("event", {}).get("event_name") or ""),
        ]
    ).lower()

    # Direct mappings first when source provides a clean sport string
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
    # All major team football/soccer leagues should map to football.
    if any(k in text for k in ("football", "soccer", "epl", "la liga", "serie a", "bundesliga", "nfl")):
        return "football"

    # Safe defaults by pipeline type.
    return "football" if event_type == "teams" else "tennis"


@app.route("/predictions", methods=["GET", "POST"])
def predictions():
    """
    Predictions page: paste a Polymarket URL and get win predictions.
    
    GET: Show form to paste URL
    POST: Process URL and return predictions
    """
    if request.method == "GET":
        return render_template("predictions.html")
    
    # POST: Process the URL
    # Try to get URL from form data first, then JSON
    url = None
    if request.form:
        url = request.form.get("url")
    if not url and request.is_json:
        url = request.json.get("url")
    if not url:
        # Also try getting from request.values (handles both form and args)
        url = request.values.get("url")
    
    # Strip whitespace if URL exists
    if url:
        url = url.strip()
    
    if not url:
        # Debug: log what we received (in production, you might want to remove this)
        import sys
        print(f"[DEBUG] Form data: {dict(request.form)}", file=sys.stderr)
        print(f"[DEBUG] Request values: {dict(request.values)}", file=sys.stderr)
        print(f"[DEBUG] Is JSON: {request.is_json}", file=sys.stderr)
        
        return render_template(
            "predictions.html",
            error="Please provide a Polymarket URL. Make sure the URL field is filled in and try again."
        ), 400
    
    try:
        # Extract event info from URL
        event_info = _extract_event_info_from_url(url)
        event_id = event_info.get("event_id")
        slug = event_info.get("slug")
        
        if not event_id and not slug:
            return render_template(
                "predictions.html",
                error="Could not extract event ID or slug from URL. Please check the URL format. Expected format: https://polymarket.com/sports/.../slug-name",
                url=url
            ), 400
        
        # Fetch event data
        raw_event = _fetch_event_data(event_id=event_id, slug=slug)
        if not raw_event:
            error_msg = f"Could not fetch event data from Polymarket."
            if slug:
                error_msg += f" Tried slug: {slug}"
            if event_id:
                error_msg += f" Tried event_id: {event_id}"
            error_msg += " The event may not exist, the URL may be invalid, or the API may be temporarily unavailable."
            
            return render_template(
                "predictions.html",
                error=error_msg,
                url=url,
                debug_info={"event_id": event_id, "slug": slug}
            ), 404
        
        # Classify event type
        event_type = classify_event_type(raw_event)
        
        # Additional fallback check when base classifier returns "other".
        # Important: do NOT treat "vs" alone as teams, because tennis/boxing/UFC
        # are also head-to-head formats that use "vs".
        if event_type == "other":
            title = (raw_event.get("title") or "").lower()
            description = (raw_event.get("description") or "").lower()
            slug = (raw_event.get("slug") or "").lower()
            combined_text = " ".join([title, description, slug])

            one_v_one_indicators = [
                "tennis",
                "atp",
                "wta",
                "ufc",
                "mma",
                "boxing",
                "boxer",
                "formula 1",
                "f1",
                "golf",
                "badminton",
                "table tennis",
                "wtt",
                "wtt-mens-singles"
                
            ]
            team_indicators = [
                "cricket",
                "t20",
                "odi",
                "test match",
                "basketball",
                "nba",
                "ncaab",
                "ncaawb",
                "hockey",
                "nhl",
                "baseball",
                "mlb",
                "football",
                "soccer",
                "futbol",
                "epl",
                "la liga",
                "bundesliga",
                "serie a",
                "serie b",
                "nfl",
                "sea"
            ]

            if any(indicator in combined_text for indicator in one_v_one_indicators):
                event_type = "1v1"
            elif any(indicator in combined_text for indicator in team_indicators):
                event_type = "teams"
        
        # Initialize Gemini clients
        if event_type == "teams":
            gemini_client = TeamsGeminiClient()
        else:
            gemini_client = OneVsOneGeminiClient()
        
        edge_case_client = EdgeCaseGeminiClient()
        
        # Process with Gemini
        event_json = json.dumps(raw_event)
        structured = gemini_client.generate_text(event_json)
        
        # Check if Gemini's structured output indicates a different event type
        # If it says "teams" but we used 1v1 client, reprocess with TeamsGeminiClient
        structured_event_type = structured.get("event_type") if structured else None
        if structured_event_type == "teams" and event_type != "teams":
            import sys
            print(f"[PREDICTIONS] Reclassifying: Initial classification was '{event_type}' but "
                  f"Gemini returned 'teams'. Reprocessing with TeamsGeminiClient. URL: {url}", 
                  file=sys.stderr)
            # Reprocess with TeamsGeminiClient
            teams_client = TeamsGeminiClient()
            structured = teams_client.generate_text(event_json)
            event_type = "teams"  # Update event_type for consistency
        
        if not structured:
            return render_template(
                "predictions.html",
                error="Failed to get structured data from Gemini. Please try again.",
                url=url
            ), 500
        
        # Get edge case analysis
        edge_case = edge_case_client.generate_text(event_json) or {}
        
        # Enrich with geo info
        structured = enrich_structured_event(structured)
        
        # Build prediction payload
        payload = _build_prediction_payload(structured)
        
        if not payload:
            return render_template(
                "predictions.html",
                error="Could not build valid prediction payload. Missing required candidate data.",
                url=url,
                structured_event=structured
            ), 400
        
        # Ensure nested event.event_type is present for prediction API schema.
        payload.setdefault("event", {})
        payload["event"]["event_type"] = _infer_api_event_type(raw_event, structured, event_type)

        # Single prediction API call.
        prediction_result = get_prediction(payload)
        
        if not prediction_result:
            # Log compact context once; prediction_client already logged request + API error body.
            import sys

            print("[PREDICTIONS] Prediction API returned no result.", file=sys.stderr)
            print("[PREDICTIONS] URL:", url, file=sys.stderr)
            print("[PREDICTIONS] Event type:", event_type, file=sys.stderr)

            return render_template(
                "predictions.html",
                error="Failed to get prediction from API. Please try again.",
                url=url
            ), 500
        
        # Prepare response data
        person_a = prediction_result.get("PersonA", {})
        person_b = prediction_result.get("PersonB", {})
        
        # Determine winner
        winner_name = None
        winner_prob = None
        try:
            pa_win = float(person_a.get("WinPercentage", "0") or 0)
            pb_win = float(person_b.get("WinPercentage", "0") or 0)
            if pa_win > pb_win:
                winner_name = person_a.get("Name", "PersonA")
                winner_prob = pa_win
            elif pb_win > pa_win:
                winner_name = person_b.get("Name", "PersonB")
                winner_prob = pb_win
        except Exception:
            pass
        
        # Save to database (upsert - update if exists, insert if new)
        saved_to_db = False
        try:
            import datetime as dt
            from bson import ObjectId
            
            db = get_db()
            coll = db.markets
            
            # Extract event info for upsert
            source_event_id = raw_event.get("id") or event_id
            slug_from_event = raw_event.get("slug") or slug
            
            # Prepare document for upsert
            now = dt.datetime.utcnow()
            has_edge_case = bool(edge_case.get("has_edge_case", False))
            risk_level = edge_case.get("risk_level", "None")
            
            # Build the update document
            update_doc = {
                "$set": {
                    "source": "polymarket",
                    "title": raw_event.get("title"),
                    "description": raw_event.get("description"),
                    "slug": slug_from_event,
                    "type": event_type,
                    "start_date": raw_event.get("startDate") or raw_event.get("start_date"),
                    "end_date": raw_event.get("endDate") or raw_event.get("end_date"),
                    "volume": raw_event.get("volume"),
                    "raw_event": raw_event,
                    "structured_event": structured,
                    "edge_case": edge_case,
                    "has_edge_case": has_edge_case,
                    "edge_case_risk_level": risk_level,
                    "prediction_payload": payload,
                    "prediction_result": prediction_result,
                    "status": "predicted" if prediction_result else "analyzed",
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                }
            }
            
            # Ensure source_event_id is in the update doc
            if source_event_id:
                update_doc["$set"]["source_event_id"] = source_event_id
            
            # Upsert by source_event_id (if available) or slug
            if source_event_id:
                result = coll.update_one(
                    {"source": "polymarket", "source_event_id": source_event_id},
                    update_doc,
                    upsert=True
                )
            elif slug_from_event:
                result = coll.update_one(
                    {"source": "polymarket", "slug": slug_from_event},
                    update_doc,
                    upsert=True
                )
            else:
                # Fallback: use URL as identifier
                update_doc["$set"]["url"] = url
                result = coll.update_one(
                    {"source": "polymarket", "url": url},
                    update_doc,
                    upsert=True
                )
            
            saved_to_db = result.upserted_id is not None or result.modified_count > 0
            if saved_to_db:
                import sys
                print(f"[PREDICTIONS] Saved prediction to DB. "
                      f"Upserted: {result.upserted_id is not None}, "
                      f"Modified: {result.modified_count > 0}, "
                      f"Event ID: {source_event_id}, Slug: {slug_from_event}", file=sys.stderr)
        except Exception as e:
            # Don't fail the request if DB save fails, just log it
            import sys
            import traceback
            print(f"[PREDICTIONS] Warning: Failed to save to DB: {e}", file=sys.stderr)
            print(f"[PREDICTIONS] Traceback: {traceback.format_exc()}", file=sys.stderr)
            saved_to_db = False
        
        # Prepare teams/candidates info
        teams_info = None
        candidates_info = None
        if event_type == "teams":
            teams_data = structured.get("candidates", [])
            teams_info = [
                {
                    "team_name": team.get("team_name"),
                    "captain": team.get("captain", {}).get("name") if isinstance(team.get("captain"), dict) else None,
                    "coach": team.get("coach", {}).get("name") if isinstance(team.get("coach"), dict) else None,
                }
                for team in teams_data
            ]
        elif event_type == "1v1":
            candidates = structured.get("candidates", [])
            candidates_info = [
                {
                    "name": cand.get("name"),
                    "birth_date": cand.get("birth_date"),
                    "birth_country": cand.get("birth_country"),
                }
                for cand in candidates
            ]
        
        return render_template(
            "predictions.html",
            success=True,
            url=url,
            payload=payload,
            prediction_result=prediction_result,
            event_type=event_type,
            detected_market_type=event_type,
            api_event_type=payload.get("event", {}).get("event_type"),
            fallback_used=False,
            market_title=raw_event.get("title"),
            market_description=raw_event.get("description"),
            person_a=person_a,
            person_b=person_b,
            winner_name=winner_name,
            winner_prob=winner_prob,
            teams_info=teams_info,
            candidates_info=candidates_info,
            edge_case=edge_case,
            has_edge_case=edge_case.get("has_edge_case", False),
            risk_level=edge_case.get("risk_level", "None"),
            saved_to_db=saved_to_db,
        )
        
    except Exception as e:
        return render_template(
            "predictions.html",
            error=f"Error processing prediction: {str(e)}",
            url=url
        ), 500


if __name__ == "__main__":
    # Dev-only entrypoint: `python cli-app/web_app.py`
    app.run(host="0.0.0.0", port=8000, debug=True)
