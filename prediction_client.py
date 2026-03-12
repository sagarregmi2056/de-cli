"""
Client for the external prediction API used by the CLI app.
"""

import json
import os
import time
from typing import Any, Dict, Optional

import requests

from config import PREDICTION_API_URL, PREDICTION_API_TOKEN, TEAM_COMPARISON_API_URL

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


PREDICTION_API_TIMEOUT_SECS = max(5, _env_int("PREDICTION_API_TIMEOUT_SECS", 20))
# Number of retry attempts after the first request (default: 2 retries, 3 total attempts)
PREDICTION_API_RETRIES = max(0, _env_int("PREDICTION_API_RETRIES", 2))
PREDICTION_API_RETRY_BACKOFF_SECS = max(0.2, _env_float("PREDICTION_API_RETRY_BACKOFF_SECS", 1.5))


def get_prediction(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

    max_attempts = PREDICTION_API_RETRIES + 1
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                PREDICTION_API_URL,
                json=payload,
                headers=headers,
                timeout=PREDICTION_API_TIMEOUT_SECS,
            )

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                wait_secs = PREDICTION_API_RETRY_BACKOFF_SECS * attempt
                print(
                    f"[PREDICTIONS] Attempt {attempt}/{max_attempts} got HTTP {response.status_code}. "
                    f"Retrying in {wait_secs:.1f}s..."
                )
                time.sleep(wait_secs)
                continue

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            last_error = e
            status_code = e.response.status_code if e.response is not None else None
            if status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                wait_secs = PREDICTION_API_RETRY_BACKOFF_SECS * attempt
                print(
                    f"[PREDICTIONS] Attempt {attempt}/{max_attempts} failed with HTTP {status_code}. "
                    f"Retrying in {wait_secs:.1f}s..."
                )
                time.sleep(wait_secs)
                continue
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = e
            if attempt < max_attempts:
                wait_secs = PREDICTION_API_RETRY_BACKOFF_SECS * attempt
                print(
                    f"[PREDICTIONS] Attempt {attempt}/{max_attempts} failed ({type(e).__name__}: {e}). "
                    f"Retrying in {wait_secs:.1f}s..."
                )
                time.sleep(wait_secs)
                continue
            break
        except requests.exceptions.RequestException as e:
            last_error = e
            break
        except Exception as e:
            last_error = e
            break

    print(f"Error in get_prediction after {max_attempts} attempt(s): {last_error}")
    if isinstance(last_error, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        print(
            "[PREDICTIONS] Network issue detected. You can tune retries with "
            "PREDICTION_API_RETRIES, PREDICTION_API_RETRY_BACKOFF_SECS, "
            "and PREDICTION_API_TIMEOUT_SECS."
        )
    resp = getattr(last_error, "response", None)
    if resp is not None:
        try:
            print(f"Prediction API error body: {resp.text}")
        except Exception:
            pass
    return None


def get_team_comparison(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    print("[TEAM-COMPARISON] Sending request to team comparison API")
    print(f"[TEAM-COMPARISON] URL: {TEAM_COMPARISON_API_URL}")
    print("[TEAM-COMPARISON] Payload:")
    print(json.dumps(payload, indent=2, ensure_ascii=True))

    headers = {
        "Content-Type": "application/json",
        "De-Token": PREDICTION_API_TOKEN,
    }

    max_attempts = PREDICTION_API_RETRIES + 1
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                TEAM_COMPARISON_API_URL,
                json=payload,
                headers=headers,
                timeout=PREDICTION_API_TIMEOUT_SECS,
            )

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                wait_secs = PREDICTION_API_RETRY_BACKOFF_SECS * attempt
                print(
                    f"[TEAM-COMPARISON] Attempt {attempt}/{max_attempts} got HTTP {response.status_code}. "
                    f"Retrying in {wait_secs:.1f}s..."
                )
                time.sleep(wait_secs)
                continue

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            last_error = e
            status_code = e.response.status_code if e.response is not None else None
            if status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                wait_secs = PREDICTION_API_RETRY_BACKOFF_SECS * attempt
                print(
                    f"[TEAM-COMPARISON] Attempt {attempt}/{max_attempts} failed with HTTP {status_code}. "
                    f"Retrying in {wait_secs:.1f}s..."
                )
                time.sleep(wait_secs)
                continue
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = e
            if attempt < max_attempts:
                wait_secs = PREDICTION_API_RETRY_BACKOFF_SECS * attempt
                print(
                    f"[TEAM-COMPARISON] Attempt {attempt}/{max_attempts} failed ({type(e).__name__}: {e}). "
                    f"Retrying in {wait_secs:.1f}s..."
                )
                time.sleep(wait_secs)
                continue
            break
        except requests.exceptions.RequestException as e:
            last_error = e
            break
        except Exception as e:
            last_error = e
            break

    print(f"Error in get_team_comparison after {max_attempts} attempt(s): {last_error}")
    resp = getattr(last_error, "response", None)
    if resp is not None:
        try:
            print(f"Team comparison API error body: {resp.text}")
        except Exception:
            pass
    return None
