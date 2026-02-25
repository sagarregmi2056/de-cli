#!/usr/bin/env python
"""
One-off script to run Gemini Teams + prediction for a single team event.

You can either:
  1) Pull a stored market from MongoDB by source_event_id / slug / mongo_id, or
  2) Point at a JSON file containing a single Polymarket-like event object.

Examples (from cli-app directory, with .venv active):

  # From Mongo by source_event_id
  python teams_directpredictions.py --source-id 184883

  # From Mongo by slug
  python teams_directpredictions.py --slug epl-lee-not-2026-02-06

  # From a raw event JSON file
  python teams_directpredictions.py --event-file path/to/event.json
"""

import argparse
import json
import sys
from typing import Any, Dict

from bson import ObjectId

from db import get_db
from gemini_clients import TeamsGeminiClient, EdgeCaseGeminiClient
from geo_enricher import enrich_structured_event
from prediction_client import get_prediction
from market_processor import _build_prediction_payload, _append_prediction_csv


def _load_event_from_mongo(
    mongo_id: str | None,
    source_id: str | None,
    slug: str | None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Fetch a single market document from MongoDB and return (raw_event, market_doc)."""
    db = get_db()
    coll = db.markets

    if mongo_id:
        try:
            query = {"_id": ObjectId(mongo_id)}
        except Exception:
            print("Invalid Mongo ObjectId.")
            sys.exit(1)
    elif source_id:
        query = {"source_event_id": source_id}
    elif slug:
        query = {"slug": slug}
    else:
        print("You must provide one of --mongo-id, --source-id, or --slug")
        sys.exit(1)

    doc = coll.find_one(query)
    if not doc:
        print("No market found for given identifier.")
        sys.exit(1)

    raw_event = doc.get("raw_event", {}) or {}
    if not raw_event:
        print("Market document has no raw_event field.")
        sys.exit(1)

    return raw_event, doc


def _load_event_from_file(path: str) -> Dict[str, Any]:
    """Load a single event JSON object from a file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to load event JSON from file: {e}")
        sys.exit(1)

    if not isinstance(data, dict):
        print("Event file must contain a single JSON object (not a list).")
        sys.exit(1)

    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Gemini Teams + prediction for a single team event."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mongo-id", help="MongoDB ObjectId of the market document.")
    group.add_argument("--source-id", help="Polymarket source_event_id.")
    group.add_argument("--slug", help="Polymarket event slug.")
    group.add_argument(
        "--event-file",
        help="Path to JSON file with a single Polymarket-like event object.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.event_file:
        raw_event = _load_event_from_file(args.event_file)
        # Build a minimal market dict for CSV logging when loading from file
        market = {
            "_id": None,
            "source_event_id": raw_event.get("id"),
            "slug": raw_event.get("slug"),
            "title": raw_event.get("title"),
            "raw_event": raw_event,
        }
    else:
        raw_event, market = _load_event_from_mongo(args.mongo_id, args.source_id, args.slug)

    event_str = json.dumps(raw_event)

    teams_client = TeamsGeminiClient()
    edge_case_client = EdgeCaseGeminiClient()

    print("=== Sending event to Gemini (Teams client) ===")
    structured = teams_client.generate_text(event_str)
    if not structured:
        print("No structured result from Teams Gemini client.")
        sys.exit(1)

    print("\n=== Sending event to Gemini (EdgeCase client) ===")
    edge_case = edge_case_client.generate_text(event_str) or {}
    has_edge_case = bool(edge_case.get("has_edge_case", False))
    risk_level = edge_case.get("risk_level", "None")

    print("\n=== Structured Event (raw from Gemini) ===")
    print(json.dumps(structured, indent=2))

    print("\n=== Edge Case Analysis ===")
    print(json.dumps(edge_case, indent=2))

    # Enrich with geo info (lat/lon/timezone) like in the main CLI
    structured = enrich_structured_event(structured)

    print("\n=== Structured Event (after geo enrichment) ===")
    print(json.dumps(structured, indent=2))

    if has_edge_case:
        print(f"\n[Warning] has_edge_case = {has_edge_case}, risk_level = {risk_level}")
        proceed = input(
            "Edge case detected. Still send to prediction API? [y/N]: "
        ).strip().lower()
        if proceed not in ("y", "yes"):
            print("Skipping prediction API call due to edge case.")
            sys.exit(0)

    # Build prediction payload using the same logic as the interactive CLI
    payload = _build_prediction_payload(structured)

    if payload is None:
        print("\n[Error] Cannot build valid prediction payload (missing required candidate data).")
        print("This usually means one or both teams don't have valid captain/coach data with all required fields.")
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

    # Display prediction summary (same style as direct 1v1 script)
    print("\n" + "=" * 70)
    print("PREDICTION SUMMARY")
    print("=" * 70)
    if prediction and "PersonA" in prediction and "PersonB" in prediction:
        person_a = prediction["PersonA"]
        person_b = prediction["PersonB"]
        print(f"{person_a.get('Name', 'PersonA')}: {person_a.get('WinPercentage', '0')}%")
        print(f"{person_b.get('Name', 'PersonB')}: {person_b.get('WinPercentage', '0')}%")

        try:
            a_prob = float(person_a.get("WinPercentage", "0"))
            b_prob = float(person_b.get("WinPercentage", "0"))
            if a_prob > b_prob:
                winner = person_a.get("Name", "PersonA")
                prob = a_prob
            else:
                winner = person_b.get("Name", "PersonB")
                prob = b_prob
            print(f"\nPredicted Winner: {winner} ({prob:.2f}% win probability)")
        except (ValueError, TypeError):
            print("\nCould not determine predicted winner from percentages")

    print("=" * 70)


if __name__ == "__main__":
    main()


