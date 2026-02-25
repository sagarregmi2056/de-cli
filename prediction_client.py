"""
Client for the external prediction API used by the CLI app.
"""

import json
from typing import Any, Dict, Optional

import requests

from config import PREDICTION_API_URL, PREDICTION_API_TOKEN


def get_prediction(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        top_level_event_type = payload.get("event_type")
        nested_event_type = event.get("event_type")
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []

        print("[PREDICTIONS] Sending request to prediction API")
        print(f"[PREDICTIONS] URL: {PREDICTION_API_URL}")
        print(f"[PREDICTIONS] Top-level event_type: {top_level_event_type}")
        print(f"[PREDICTIONS] Nested event.event_type: {nested_event_type}")
        print(f"[PREDICTIONS] Candidates count: {len(candidates)}")
        print("[PREDICTIONS] Payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=True))

        headers = {
            "Content-Type": "application/json",
            "De-Token": PREDICTION_API_TOKEN,
        }
        response = requests.post(PREDICTION_API_URL, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error in get_prediction: {e}")
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                print(f"Prediction API error body: {resp.text}")
            except Exception:
                pass
        return None
