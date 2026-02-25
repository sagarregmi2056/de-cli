"""
Standalone v3 dashboard for predicted Polymarket markets.

Goals:
- Keep existing Flask routes/code untouched.
- Use a clean v3 database namespace.
- Add search + analytics tab.
- Add URL prediction tab that saves to v3 DB.
- Auto-resolve markets against latest Gamma/Polymarket data.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import secrets
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from db_v3 import get_db_v3
from gamma_client import (
    extract_outcome_prices_from_event,
    extract_token_ids_from_event,
    get_markets,
)
from gemini_clients import OneVsOneGeminiClient, TeamsGeminiClient, EdgeCaseGeminiClient
from geo_enricher import enrich_structured_event
from market_processor import _build_prediction_payload
from markets_scanner import classify_event_type
from prediction_client import get_prediction
from web_app import _extract_event_info_from_url, _fetch_event_data, _infer_api_event_type


app = Flask(__name__)

RESOLVED_HIGH = 0.97
RESOLVED_LOW = 0.03
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

_clients: Dict[str, Any] = {}


def _strtobool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _is_password_hash(value: str) -> bool:
    return value.startswith(("pbkdf2:", "scrypt:", "argon2:"))


def _load_auth_users() -> Dict[str, str]:
    users: Dict[str, str] = {}

    users_json = (os.getenv("WEB_APP_V3_AUTH_USERS") or "").strip()
    if users_json:
        try:
            parsed = json.loads(users_json)
            if isinstance(parsed, dict):
                for email, pwd in parsed.items():
                    email_norm = str(email or "").strip().lower()
                    password = str(pwd or "")
                    if email_norm and password:
                        users[email_norm] = password
        except Exception:
            pass

    single_email = (os.getenv("WEB_APP_V3_AUTH_EMAIL") or "").strip().lower()
    single_password_hash = (os.getenv("WEB_APP_V3_AUTH_PASSWORD_HASH") or "").strip()
    single_password = os.getenv("WEB_APP_V3_AUTH_PASSWORD")
    if single_email:
        if single_password_hash:
            users[single_email] = single_password_hash
        elif single_password:
            users[single_email] = single_password

    return users


AUTH_ENABLED = _strtobool(os.getenv("WEB_APP_V3_AUTH_ENABLED"), default=True)
AUTH_USERS = _load_auth_users()

secret_key = os.getenv("WEB_APP_V3_SECRET_KEY")
if not secret_key:
    secret_key = secrets.token_hex(32)
    print(
        "WARNING: WEB_APP_V3_SECRET_KEY is not set. Using an ephemeral key; "
        "all sessions will reset when the server restarts."
    )

app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = _strtobool(os.getenv("WEB_APP_V3_COOKIE_SECURE"), default=False)
app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(
    hours=max(1, min(168, _env_int("WEB_APP_V3_SESSION_HOURS", 12)))
)

if AUTH_ENABLED and not AUTH_USERS:
    raise RuntimeError(
        "Auth is enabled but no users configured. Set WEB_APP_V3_AUTH_USERS or "
        "WEB_APP_V3_AUTH_EMAIL + WEB_APP_V3_AUTH_PASSWORD_HASH (or WEB_APP_V3_AUTH_PASSWORD)."
    )


def _get_clients() -> Tuple[OneVsOneGeminiClient, TeamsGeminiClient, EdgeCaseGeminiClient]:
    if not _clients:
        _clients["one_v_one"] = OneVsOneGeminiClient()
        _clients["teams"] = TeamsGeminiClient()
        _clients["edge_case"] = EdgeCaseGeminiClient()
    return _clients["one_v_one"], _clients["teams"], _clients["edge_case"]


def _parse_int(raw: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, value))


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    for ch in ",.'\"-_/()[]:;":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return decoded
        except Exception:
            return []
    return []


def _classify_event_type_with_fallback(raw_event: Dict[str, Any]) -> str:
    event_type = classify_event_type(raw_event)
    if event_type != "other":
        return event_type

    title = (raw_event.get("title") or "").lower()
    description = (raw_event.get("description") or "").lower()
    slug = (raw_event.get("slug") or "").lower()
    combined = " ".join([title, description, slug])

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
    ]

    if any(ind in combined for ind in one_v_one_indicators):
        return "1v1"
    if any(ind in combined for ind in team_indicators):
        return "teams"
    return "1v1"


def _extract_predicted_winner(doc: Dict[str, Any]) -> Dict[str, Any]:
    prediction = doc.get("prediction_result") or {}
    person_a = prediction.get("PersonA") or {}
    person_b = prediction.get("PersonB") or {}

    a_name = str(person_a.get("Name") or "").strip()
    b_name = str(person_b.get("Name") or "").strip()
    a_prob = _safe_float(person_a.get("WinPercentage")) or 0.0
    b_prob = _safe_float(person_b.get("WinPercentage")) or 0.0

    winner_name = ""
    winner_prob = 0.0
    winner_side = None

    if a_prob > b_prob:
        winner_name = a_name
        winner_prob = a_prob
        winner_side = "A"
    elif b_prob > a_prob:
        winner_name = b_name
        winner_prob = b_prob
        winner_side = "B"

    return {
        "person_a_name": a_name,
        "person_b_name": b_name,
        "person_a_prob": a_prob,
        "person_b_prob": b_prob,
        "winner_name": winner_name,
        "winner_prob": winner_prob,
        "winner_side": winner_side,
        "gap": abs(a_prob - b_prob),
    }


def _extract_team_names(doc: Dict[str, Any], predicted: Dict[str, Any]) -> Tuple[str, str]:
    structured = doc.get("structured_event") or {}
    candidates = structured.get("candidates") if isinstance(structured, dict) else []

    team_names: List[str] = []
    for item in candidates if isinstance(candidates, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("team_name") or "").strip()
        if name:
            team_names.append(name)

    if len(team_names) >= 2:
        return team_names[0], team_names[1]

    return (
        predicted.get("person_a_name") or "-",
        predicted.get("person_b_name") or "-",
    )


def _extract_outcomes(payload: Dict[str, Any]) -> List[str]:
    outcomes: List[str] = []

    raw_outcomes = _as_list(payload.get("outcomes"))
    for item in raw_outcomes:
        if isinstance(item, str):
            if item.strip():
                outcomes.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("outcome")
            if name:
                outcomes.append(str(name).strip())

    if not outcomes:
        prices = extract_outcome_prices_from_event(payload) or {}
        outcomes.extend([str(name).strip() for name in prices.keys() if str(name).strip()])

    deduped: List[str] = []
    seen = set()
    for outcome in outcomes:
        key = _norm(outcome)
        if key and key not in seen:
            seen.add(key)
            deduped.append(outcome)
    return deduped


def _infer_outcome_from_prices(payload: Dict[str, Any]) -> Tuple[str, Optional[str], str]:
    prices = extract_outcome_prices_from_event(payload) or {}
    clean_prices: Dict[str, float] = {}
    for name, value in prices.items():
        price = _safe_float(value)
        if price is None:
            continue
        clean_prices[str(name)] = price

    if not clean_prices:
        return "open", None, "no_prices"

    if all(abs(p - 0.5) <= 0.03 for p in clean_prices.values()):
        return "void", None, "flat_fifty_fifty"

    winner_name, winner_price = max(clean_prices.items(), key=lambda pair: pair[1])
    if winner_price >= RESOLVED_HIGH:
        others = [p for name, p in clean_prices.items() if name != winner_name]
        if all(p <= RESOLVED_LOW for p in others):
            return "resolved", winner_name, "price_extreme"
        if bool(payload.get("closed")):
            return "resolved", winner_name, "closed_high_probability"

    if bool(payload.get("closed")) and bool(payload.get("active")) is False:
        return "closed_unresolved", None, "closed_without_decisive_prices"

    return "open", None, "still_trading"


def _extract_resolution(payload: Dict[str, Any]) -> Tuple[str, Optional[str], str]:
    for key in ("winningOutcome", "resolvedOutcome", "winner", "winning_outcome"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return "resolved", value.strip(), f"field_{key}"

    resolution = payload.get("resolution")
    if isinstance(resolution, dict):
        for key in ("winner", "outcome", "resolved_outcome"):
            value = resolution.get(key)
            if isinstance(value, str) and value.strip():
                return "resolved", value.strip(), f"field_resolution_{key}"
        resolution_state = _norm(resolution.get("status"))
        if resolution_state in {"void", "cancelled", "canceled", "invalid", "n a", "na"}:
            return "void", None, "resolution_status_void"

    if isinstance(resolution, str) and resolution.strip():
        resolution_key = _norm(resolution)
        if resolution_key in {"void", "cancelled", "canceled", "invalid", "n a", "na"}:
            return "void", None, "resolution_void"
        return "resolved", resolution.strip(), "resolution_string"

    for key in ("isInvalid", "invalid", "voided"):
        if payload.get(key) is True:
            return "void", None, f"field_{key}"

    return _infer_outcome_from_prices(payload)


def _match_expected_outcome(
    predicted_name: str,
    predicted_side: Optional[str],
    outcomes: List[str],
) -> Optional[str]:
    if not outcomes:
        return None

    normalized = [(item, _norm(item)) for item in outcomes]
    predicted_norm = _norm(predicted_name)

    if predicted_norm:
        for original, key in normalized:
            if key == predicted_norm or predicted_norm in key or key in predicted_norm:
                return original

    simple_set = {key for _, key in normalized}
    if simple_set == {"yes", "no"} and predicted_side in {"A", "B"}:
        expected = "yes" if predicted_side == "A" else "no"
        for original, key in normalized:
            if key == expected:
                return original

    if predicted_side in {"A", "B"} and len(outcomes) >= 2:
        return outcomes[0] if predicted_side == "A" else outcomes[1]

    return None


def _find_price_for_outcome(prices: Dict[str, Any], outcome_name: Optional[str]) -> Optional[float]:
    if not outcome_name or not prices:
        return None

    target = _norm(outcome_name)
    if not target:
        return None

    for name, value in prices.items():
        if _norm(name) == target:
            return _safe_float(value)

    for name, value in prices.items():
        norm_name = _norm(name)
        if target in norm_name or norm_name in target:
            return _safe_float(value)

    return None


def _fetch_latest_payload(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    source_event_id = str(doc.get("source_event_id") or "").strip()
    slug = str(doc.get("slug") or doc.get("raw_event", {}).get("slug") or "").strip()

    if source_event_id:
        try:
            response = requests.get(f"{GAMMA_API_BASE}/events/{source_event_id}", timeout=8)
            response.raise_for_status()
            event = response.json()
            if isinstance(event, dict) and event:
                return event, "event_id"
        except Exception:
            pass

    if slug:
        markets = get_markets(slug=slug)
        if isinstance(markets, list) and markets:
            first = markets[0]
            if isinstance(first, dict):
                return first, "slug"

    raw_event = doc.get("raw_event")
    if isinstance(raw_event, dict):
        return raw_event, "snapshot"

    return {}, "none"


def _evaluate_market(doc: Dict[str, Any]) -> Dict[str, Any]:
    predicted = _extract_predicted_winner(doc)
    payload, source = _fetch_latest_payload(doc)

    outcomes = _extract_outcomes(payload)
    if not outcomes:
        outcomes = _extract_outcomes(doc.get("raw_event") or {})

    state, resolved_outcome, signal = _extract_resolution(payload)
    expected_outcome = _match_expected_outcome(
        predicted_name=str(predicted.get("winner_name") or ""),
        predicted_side=predicted.get("winner_side"),
        outcomes=outcomes,
    )

    if state == "void":
        prediction_status = "void"
    elif state == "resolved":
        if expected_outcome and resolved_outcome:
            prediction_status = "won" if _norm(expected_outcome) == _norm(resolved_outcome) else "lost"
        else:
            prediction_status = "unknown"
    else:
        prediction_status = "pending"

    now = dt.datetime.utcnow()
    resolved_at = now if state in {"resolved", "void"} else None

    return {
        "state": state,
        "resolved_outcome": resolved_outcome,
        "expected_outcome": expected_outcome,
        "prediction_status": prediction_status,
        "resolution_source": source,
        "resolution_signal": signal,
        "outcomes": outcomes,
        "checked_at": now,
        "resolved_at": resolved_at,
    }


def _update_resolution_status(coll: Any, doc_id: Any, resolution: Dict[str, Any]) -> None:
    status = resolution.get("prediction_status", "pending")
    set_doc: Dict[str, Any] = {
        "resolution_v3": resolution,
        "updated_at": dt.datetime.utcnow(),
    }

    if status == "won":
        set_doc["status"] = "resolved_won"
    elif status == "lost":
        set_doc["status"] = "resolved_lost"
    elif status == "void":
        set_doc["status"] = "void"
    elif status == "unknown":
        set_doc["status"] = "resolved_unknown"
    else:
        set_doc["status"] = "predicted"

    coll.update_one({"_id": doc_id}, {"$set": set_doc})


def _apply_auto_resolve(limit: int = 250) -> Dict[str, int]:
    db = get_db_v3()
    coll = db.markets

    counts = {
        "checked": 0,
        "updated": 0,
        "won": 0,
        "lost": 0,
        "pending": 0,
        "void": 0,
        "unknown": 0,
    }

    docs = list(
        coll.find({"prediction_result": {"$exists": True}})
        .sort("end_date", 1)
        .limit(max(1, min(limit, 2000)))
    )

    for doc in docs:
        counts["checked"] += 1
        resolution = _evaluate_market(doc)

        status = resolution.get("prediction_status", "unknown")
        if status not in counts:
            status = "unknown"
        counts[status] += 1

        before = doc.get("resolution_v3") or {}
        _update_resolution_status(coll, doc["_id"], resolution)

        if (
            before.get("prediction_status") != resolution.get("prediction_status")
            or before.get("resolved_outcome") != resolution.get("resolved_outcome")
        ):
            counts["updated"] += 1

    return counts


def _serialize_market(doc: Dict[str, Any]) -> Dict[str, Any]:
    raw_event = doc.get("raw_event") or {}
    resolution = doc.get("resolution_v3") or {}
    predicted = _extract_predicted_winner(doc)
    team_a, team_b = _extract_team_names(doc, predicted)

    slug = str(doc.get("slug") or raw_event.get("slug") or "").strip()
    market_url = f"https://polymarket.com/event/{slug}" if slug else None

    outcome_prices = doc.get("outcome_prices")
    if not isinstance(outcome_prices, dict) or not outcome_prices:
        outcome_prices = extract_outcome_prices_from_event(raw_event) or {}

    expected_outcome = resolution.get("expected_outcome")
    predicted_market_odds = _find_price_for_outcome(outcome_prices, expected_outcome)

    investment = doc.get("investment_result") or {}

    return {
        "id": str(doc.get("_id")),
        "source_event_id": str(doc.get("source_event_id") or raw_event.get("id") or ""),
        "title": str(doc.get("title") or raw_event.get("title") or "Untitled market"),
        "type": str(doc.get("type") or "unknown"),
        "team_a": team_a,
        "team_b": team_b,
        "slug": slug,
        "market_url": market_url,
        "end_date": doc.get("end_date") or raw_event.get("endDate"),
        "predicted_winner": predicted.get("winner_name") or "-",
        "predicted_prob": predicted.get("winner_prob") or 0.0,
        "prediction_gap": predicted.get("gap") or 0.0,
        "predicted_market_odds": predicted_market_odds,
        "api_event_type": doc.get("api_event_type"),
        "expected_outcome": expected_outcome,
        "resolved_outcome": resolution.get("resolved_outcome"),
        "prediction_status": resolution.get("prediction_status", "pending"),
        "resolution_state": resolution.get("state", "open"),
        "checked_at": resolution.get("checked_at"),
        "is_invested": bool(investment),
        "investment_amount": _safe_float(investment.get("amount")),
        "candidate_a_name": predicted.get("person_a_name"),
        "candidate_a_prob": predicted.get("person_a_prob"),
        "candidate_b_name": predicted.get("person_b_name"),
        "candidate_b_prob": predicted.get("person_b_prob"),
    }


def _build_summary(markets: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "total": len(markets),
        "won": 0,
        "lost": 0,
        "pending": 0,
        "void": 0,
        "unknown": 0,
        "resolved": 0,
        "win_rate": None,
        "invested": 0,
    }

    for market in markets:
        status = market.get("prediction_status", "pending")
        if status not in summary:
            status = "unknown"
        summary[status] += 1
        if market.get("is_invested"):
            summary["invested"] += 1

    summary["resolved"] = summary["won"] + summary["lost"]
    if summary["resolved"] > 0:
        summary["win_rate"] = round((summary["won"] / summary["resolved"]) * 100, 2)

    return summary


def _market_matches_search(market: Dict[str, Any], q: str) -> bool:
    qn = _norm(q)
    if not qn:
        return True

    haystack = " ".join(
        [
            str(market.get("title") or ""),
            str(market.get("team_a") or ""),
            str(market.get("team_b") or ""),
            str(market.get("predicted_winner") or ""),
            str(market.get("resolved_outcome") or ""),
            str(market.get("expected_outcome") or ""),
            str(market.get("type") or ""),
            str(market.get("slug") or ""),
            str(market.get("source_event_id") or ""),
        ]
    )
    return qn in _norm(haystack)


def _odds_bucket(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    if value < 0.2:
        return "0.00-0.19"
    if value < 0.4:
        return "0.20-0.39"
    if value < 0.6:
        return "0.40-0.59"
    if value < 0.8:
        return "0.60-0.79"
    return "0.80-1.00"


def _gap_bucket(value: float) -> str:
    if value < 5:
        return "0-4.99"
    if value < 10:
        return "5-9.99"
    if value < 20:
        return "10-19.99"
    return "20+"


def _build_analytics(markets: List[Dict[str, Any]]) -> Dict[str, Any]:
    analytics: Dict[str, Any] = {
        "invested_total": 0,
        "invested_by_type": {},
        "type_performance": {},
        "odds_buckets": {},
        "gap_buckets": {},
        "avg_gap_all": None,
        "avg_gap_won": None,
        "avg_gap_lost": None,
    }

    all_gaps: List[float] = []
    won_gaps: List[float] = []
    lost_gaps: List[float] = []

    for m in markets:
        m_type = m.get("type") or "unknown"
        status = m.get("prediction_status") or "pending"
        gap = _safe_float(m.get("prediction_gap")) or 0.0
        odds = _safe_float(m.get("predicted_market_odds"))

        all_gaps.append(gap)
        if status == "won":
            won_gaps.append(gap)
        elif status == "lost":
            lost_gaps.append(gap)

        if m.get("is_invested"):
            analytics["invested_total"] += 1
            analytics["invested_by_type"][m_type] = analytics["invested_by_type"].get(m_type, 0) + 1

        if m_type not in analytics["type_performance"]:
            analytics["type_performance"][m_type] = {
                "total": 0,
                "won": 0,
                "lost": 0,
                "pending": 0,
                "void": 0,
                "unknown": 0,
                "win_rate": None,
            }
        perf = analytics["type_performance"][m_type]
        perf["total"] += 1
        if status in perf:
            perf[status] += 1
        else:
            perf["unknown"] += 1

        ob = _odds_bucket(odds)
        if ob not in analytics["odds_buckets"]:
            analytics["odds_buckets"][ob] = {"count": 0, "won": 0, "lost": 0}
        analytics["odds_buckets"][ob]["count"] += 1
        if status == "won":
            analytics["odds_buckets"][ob]["won"] += 1
        elif status == "lost":
            analytics["odds_buckets"][ob]["lost"] += 1

        gb = _gap_bucket(gap)
        if gb not in analytics["gap_buckets"]:
            analytics["gap_buckets"][gb] = {"count": 0, "won": 0, "lost": 0}
        analytics["gap_buckets"][gb]["count"] += 1
        if status == "won":
            analytics["gap_buckets"][gb]["won"] += 1
        elif status == "lost":
            analytics["gap_buckets"][gb]["lost"] += 1

    for perf in analytics["type_performance"].values():
        resolved = perf["won"] + perf["lost"]
        if resolved > 0:
            perf["win_rate"] = round((perf["won"] / resolved) * 100, 2)

    if all_gaps:
        analytics["avg_gap_all"] = round(sum(all_gaps) / len(all_gaps), 2)
    if won_gaps:
        analytics["avg_gap_won"] = round(sum(won_gaps) / len(won_gaps), 2)
    if lost_gaps:
        analytics["avg_gap_lost"] = round(sum(lost_gaps) / len(lost_gaps), 2)

    analytics["invested_by_type"] = dict(sorted(analytics["invested_by_type"].items(), key=lambda x: x[0]))
    analytics["type_performance"] = dict(sorted(analytics["type_performance"].items(), key=lambda x: x[0]))
    analytics["odds_buckets"] = dict(
        sorted(
            analytics["odds_buckets"].items(),
            key=lambda x: ["0.00-0.19", "0.20-0.39", "0.40-0.59", "0.60-0.79", "0.80-1.00", "unknown"].index(x[0]),
        )
    )
    analytics["gap_buckets"] = dict(
        sorted(
            analytics["gap_buckets"].items(),
            key=lambda x: ["0-4.99", "5-9.99", "10-19.99", "20+"].index(x[0]),
        )
    )

    gap_max = 1
    if analytics["gap_buckets"]:
        gap_max = max(bucket["count"] for bucket in analytics["gap_buckets"].values())
    analytics["gap_max"] = gap_max or 1

    return analytics


def _load_market_data(limit: int, auto_resolve: bool) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], Optional[Dict[str, int]]]:
    resolve_counts = None
    if auto_resolve:
        resolve_counts = _apply_auto_resolve(limit=limit)

    coll = get_db_v3().markets
    docs = list(
        coll.find({"prediction_result": {"$exists": True}})
        .sort("end_date", 1)
        .limit(max(1, min(limit, 1000)))
    )

    markets = [_serialize_market(doc) for doc in docs]
    summary = _build_summary(markets)
    return docs, markets, summary, resolve_counts


def _predict_from_url(url: str) -> Dict[str, Any]:
    event_info = _extract_event_info_from_url(url)
    event_id = event_info.get("event_id")
    slug = event_info.get("slug")

    if not event_id and not slug:
        raise ValueError("Could not extract event ID or slug from URL.")

    raw_event = _fetch_event_data(event_id=event_id, slug=slug)
    if not raw_event:
        raise ValueError("Could not fetch market/event data from Polymarket Gamma API.")

    market_type = _classify_event_type_with_fallback(raw_event)

    one_v_one_client, teams_client, edge_case_client = _get_clients()

    event_json = json.dumps(raw_event)
    if market_type == "teams":
        structured = teams_client.generate_text(event_json)
    else:
        structured = one_v_one_client.generate_text(event_json)

    if not structured:
        raise ValueError("Failed to generate structured event data from Gemini.")

    structured_event_type = structured.get("event_type")
    if structured_event_type == "teams" and market_type != "teams":
        structured = teams_client.generate_text(event_json)
        market_type = "teams"

    edge_case = edge_case_client.generate_text(event_json) or {}
    structured = enrich_structured_event(structured)

    payload = _build_prediction_payload(structured)
    if not payload:
        raise ValueError("Could not build valid prediction payload.")

    payload.setdefault("event", {})
    inferred_event_type = _infer_api_event_type(raw_event, structured, market_type)
    payload["event"]["event_type"] = inferred_event_type

    prediction_result = get_prediction(payload)
    if not prediction_result:
        raise ValueError("Prediction API returned no result.")

    predicted = _extract_predicted_winner({"prediction_result": prediction_result})

    db = get_db_v3()
    coll = db.markets

    source_event_id = raw_event.get("id") or event_id
    slug_from_event = raw_event.get("slug") or slug

    token_ids = extract_token_ids_from_event(raw_event) or {}
    outcome_prices = extract_outcome_prices_from_event(raw_event) or {}

    outcomes = [str(k) for k in outcome_prices.keys()]
    expected_outcome = _match_expected_outcome(
        predicted_name=predicted.get("winner_name") or "",
        predicted_side=predicted.get("winner_side"),
        outcomes=outcomes,
    )
    predicted_market_odds = _find_price_for_outcome(outcome_prices, expected_outcome)

    now = dt.datetime.utcnow()
    has_edge_case = bool(edge_case.get("has_edge_case", False))
    risk_level = edge_case.get("risk_level", "None")

    set_doc: Dict[str, Any] = {
        "source": "polymarket",
        "title": raw_event.get("title"),
        "description": raw_event.get("description"),
        "slug": slug_from_event,
        "type": market_type,
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
        "token_ids": token_ids,
        "outcome_prices": outcome_prices,
        "api_event_type": inferred_event_type,
        "prediction_meta": {
            "source_url": url,
            "predicted_winner": predicted.get("winner_name"),
            "predicted_win_prob": predicted.get("winner_prob"),
            "prediction_gap": predicted.get("gap"),
            "expected_outcome": expected_outcome,
            "predicted_market_odds": predicted_market_odds,
            "created_via": "v3_predict_tab",
        },
        "status": "predicted",
        "updated_at": now,
    }
    if source_event_id:
        set_doc["source_event_id"] = source_event_id

    update_doc = {"$set": set_doc, "$setOnInsert": {"created_at": now}}

    if source_event_id:
        filter_doc = {"source": "polymarket", "source_event_id": source_event_id}
    elif slug_from_event:
        filter_doc = {"source": "polymarket", "slug": slug_from_event}
    else:
        filter_doc = {"source": "polymarket", "prediction_meta.source_url": url}

    coll.update_one(filter_doc, update_doc, upsert=True)

    saved = coll.find_one(filter_doc)
    saved_id = None
    if saved:
        saved_id = saved.get("_id")
        resolution = _evaluate_market(saved)
        _update_resolution_status(coll, saved_id, resolution)

    person_info = [
        {
            "label": "PersonA",
            "name": prediction_result.get("PersonA", {}).get("Name"),
            "win_pct": _safe_float(prediction_result.get("PersonA", {}).get("WinPercentage")) or 0.0,
            "details": prediction_result.get("PersonA", {}).get("Details"),
        },
        {
            "label": "PersonB",
            "name": prediction_result.get("PersonB", {}).get("Name"),
            "win_pct": _safe_float(prediction_result.get("PersonB", {}).get("WinPercentage")) or 0.0,
            "details": prediction_result.get("PersonB", {}).get("Details"),
        },
    ]

    teams_info = []
    structured_candidates = structured.get("candidates", [])
    if isinstance(structured_candidates, list):
        for idx, team in enumerate(structured_candidates):
            if not isinstance(team, dict):
                continue
            teams_info.append(
                {
                    "team_name": team.get("team_name") or f"Team {idx + 1}",
                    "captain": team.get("captain", {}).get("name")
                    if isinstance(team.get("captain"), dict)
                    else None,
                    "coach": team.get("coach", {}).get("name")
                    if isinstance(team.get("coach"), dict)
                    else None,
                }
            )

    return {
        "market_type": market_type,
        "market_title": raw_event.get("title"),
        "market_description": raw_event.get("description"),
        "slug": slug_from_event,
        "prediction_result": prediction_result,
        "predicted": predicted,
        "edge_case": edge_case,
        "saved_id": str(saved_id) if saved_id else None,
        "expected_outcome": expected_outcome,
        "predicted_market_odds": predicted_market_odds,
        "person_info": person_info,
        "teams_info": teams_info,
    }


def _is_safe_next_url(next_url: str) -> bool:
    return next_url.startswith("/") and not next_url.startswith("//")


def _verify_login(email: str, password: str) -> bool:
    expected = AUTH_USERS.get(email.strip().lower())
    if not expected:
        return False
    if _is_password_hash(expected):
        try:
            return check_password_hash(expected, password)
        except Exception:
            return False
    return hmac.compare_digest(expected, password)


@app.before_request
def _auth_guard() -> Optional[Any]:
    if not AUTH_ENABLED:
        return None

    endpoint = request.endpoint or ""
    if endpoint in {"login", "logout", "static"}:
        return None
    if session.get("auth_email"):
        return None

    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "authentication_required"}), 401

    next_url = request.full_path or request.path
    if next_url.endswith("?"):
        next_url = next_url[:-1]
    return redirect(url_for("login", next=next_url))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not AUTH_ENABLED:
        return redirect(url_for("markets_tab"))

    error = None
    next_url = (request.args.get("next") or request.form.get("next") or "/").strip() or "/"
    if not _is_safe_next_url(next_url):
        next_url = "/"

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if _verify_login(email, password):
            session.clear()
            session.permanent = True
            session["auth_email"] = email
            return redirect(next_url)
        error = "Invalid email or password."

    return render_template("login_v3.html", error=error, next_url=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


def _render_dashboard(
    active_tab: str,
    markets: List[Dict[str, Any]],
    summary: Dict[str, Any],
    resolve_counts: Optional[Dict[str, int]],
    *,
    limit: int,
    result_filter: str = "all",
    search: str = "",
    analytics: Optional[Dict[str, Any]] = None,
    prediction_view: Optional[Dict[str, Any]] = None,
    prediction_error: Optional[str] = None,
) -> Any:
    recent = sorted(markets, key=lambda m: str(m.get("end_date") or ""), reverse=True)[:25]
    return render_template(
        "dashboard_v3.html",
        active_tab=active_tab,
        markets=markets,
        summary=summary,
        resolve_counts=resolve_counts,
        limit=limit,
        result_filter=result_filter,
        search=search,
        analytics=analytics,
        prediction_view=prediction_view,
        prediction_error=prediction_error,
        recent_predictions=recent,
        auth_enabled=AUTH_ENABLED,
        auth_email=session.get("auth_email"),
    )


@app.route("/")
def markets_tab():
    auto_resolve = request.args.get("auto_resolve", "1") == "1"
    result_filter = request.args.get("result", "all")
    search = request.args.get("q", "").strip()
    limit = _parse_int(request.args.get("limit"), default=300, min_value=1, max_value=1000)

    _, all_markets, summary, resolve_counts = _load_market_data(limit=limit, auto_resolve=auto_resolve)

    markets = all_markets
    if result_filter != "all":
        markets = [m for m in markets if m.get("prediction_status") == result_filter]
    if search:
        markets = [m for m in markets if _market_matches_search(m, search)]

    return _render_dashboard(
        active_tab="markets",
        markets=markets,
        summary=summary,
        resolve_counts=resolve_counts,
        limit=limit,
        result_filter=result_filter,
        search=search,
    )


@app.route("/analytics")
def analytics_tab():
    auto_resolve = request.args.get("auto_resolve", "1") == "1"
    limit = _parse_int(request.args.get("limit"), default=500, min_value=1, max_value=1000)

    _, markets, summary, resolve_counts = _load_market_data(limit=limit, auto_resolve=auto_resolve)
    analytics = _build_analytics(markets)

    return _render_dashboard(
        active_tab="analytics",
        markets=markets,
        summary=summary,
        resolve_counts=resolve_counts,
        limit=limit,
        analytics=analytics,
    )


@app.route("/predict", methods=["GET", "POST"])
def predict_tab():
    auto_resolve = request.args.get("auto_resolve", "0") == "1"
    limit = _parse_int(request.args.get("limit"), default=300, min_value=1, max_value=1000)

    prediction_view = None
    prediction_error = None

    if request.method == "POST":
        url = (request.form.get("url") or request.values.get("url") or "").strip()
        if not url:
            prediction_error = "Please paste a Polymarket market URL."
        else:
            try:
                prediction_view = _predict_from_url(url)
            except Exception as e:
                prediction_error = str(e)

    _, markets, summary, resolve_counts = _load_market_data(limit=limit, auto_resolve=auto_resolve)

    return _render_dashboard(
        active_tab="predict",
        markets=markets,
        summary=summary,
        resolve_counts=resolve_counts,
        limit=limit,
        prediction_view=prediction_view,
        prediction_error=prediction_error,
    )


@app.route("/api/auto-resolve", methods=["POST"])
def api_auto_resolve():
    payload = request.get_json(silent=True) or {}
    limit = _parse_int(payload.get("limit"), default=300, min_value=1, max_value=2000)
    counts = _apply_auto_resolve(limit=limit)
    return jsonify({"ok": True, "counts": counts})


if __name__ == "__main__":
    # Dev-only entrypoint: `python3 cli-app/web_app_v3.py`
    debug_mode = _strtobool(os.getenv("WEB_APP_V3_DEBUG"), default=False)
    app.run(host="0.0.0.0", port=8001, debug=debug_mode)
