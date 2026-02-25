"""
Gemini clients for the CLI app.

These mirror DEBot's Gemini clients (same prompts and behaviour) but are
implemented locally so the CLI does not depend on the DEBot package.
"""

from typing import Optional, Dict, Any, List

from google import genai
from google.genai.types import (
    GenerateContentConfig,
    GoogleSearch,
    HttpOptions,
    Tool,
    Content,
    Part,
)

from config import GEMINI_API_KEY, DEFAULT_MODEL_NAME


def _extract_json(text: str) -> Dict[str, Any]:
    """
    Minimal JSON extractor similar to DEBot.utils.extract_json.
    Assumes the model returns plain JSON (as instructed in prompts).
    """
    import json

    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            json_str = text[start:end]
            return json.loads(json_str)
        else:
            raise ValueError("No JSON found in response")
    except Exception as e:
        raise Exception(f"Failed to parse JSON response: {str(e)}\nResponse: {text}")


class BaseGeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = DEFAULT_MODEL_NAME,
        use_search: bool = True,
        max_retries: int = 3,
    ):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY not found. Set it in environment or pass as parameter."
            )

        self.client = genai.Client(
            http_options=HttpOptions(api_version="v1beta"), api_key=self.api_key
        )

        self.tools: Optional[List[Tool]] = (
            [Tool(google_search=GoogleSearch())] if use_search else None
        )
        self.model_name = model_name
        self.system_prompt = self._system_prompt()
        self.use_search = use_search
        self.max_retries = max_retries

    def generate_text(self, event_data: str, max_retries: int = 3) -> Dict[str, Any]:
        try:
            for attempt in range(max_retries):
                prompt = self._build_contents(event_data)
                config = GenerateContentConfig(tools=self.tools) if self.tools else None

                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                candidate = response.candidates[0] if response.candidates else None
                metadata = getattr(candidate, "grounding_metadata", None)
                web_queries_raw = (
                    getattr(metadata, "web_search_queries", None) if metadata else None
                )
                web_queries = list(web_queries_raw) if web_queries_raw else []

                if len(web_queries) > 0 or not self.use_search:
                    print("Web Search Queries Used")
                    return _extract_json(response.text)
                else:
                    print(f"No web search on attempt {attempt + 1}, retrying...")

            return None
        except Exception as e:
            raise Exception(f"Error generating text: {e}") from e

    def _build_contents(self, user_prompt: str) -> list[Content]:
        contents: list[Content] = []
        if self.system_prompt:
            contents.append(Content(role="model", parts=[Part(text=self.system_prompt)]))
        contents.append(Content(role="user", parts=[Part(text=user_prompt)]))
        return contents

    def _system_prompt(self) -> str:
        raise NotImplementedError("Subclasses must implement _system_prompt")


class OneVsOneGeminiClient(BaseGeminiClient):
    def _system_prompt(self) -> str:
        # Copied from DEBot.DEBoT.gemini.OneVsOneGeminiClient
        return """You are a rigorous Biographical Research and Verification Engine. Your goal is to extract hyper-accurate data about individuals in sporting events by cross-referencing real-time information.

        ### OPERATIONAL MANDATE:
        1. **ALWAYS SEARCH:** You must use the Google Search tool for EVERY request to verify dates, times, locations, and spellings. Do not rely on your internal training data, as event schedules change.
        2. **VERIFY FIRST, JSON SECOND:** Before generating the JSON, verify every field. If a piece of data (like a Birth Time) is not public, you must attempt to search for it specifically (e.g., "Person Name birth chart" or "Person Name bio") before marking it "unknown".
        3. **ISO 8601 COMPLIANCE:** All dates must be YYYY-MM-DD. All times must be HH:MM in 24-hour format.

        ### DATA EXTRACTION RULES:
        - **Candidates:**
        - Name: Common stage/sporting name.
        - Birth Name: Full legal name. If seemingly identical to common name, confirm via search.
        - Birth Location: Must include City, State/Province, and Country.
        - **Event:**
        - Location: Must be the specific venue name + city/country. Do not output "TBD" unless a search confirms no venue is currently scheduled.

        ### OUTPUT FORMAT:
        Return ONLY valid JSON. No markdown formatting (```json), no conversational filler.

        {
            "event_type": "1v1",
            "candidates": [
                {
                    "name": "string - full legal name", // or "unknown" (Search to verify)
                    "birth_date": "YYYY-MM-DD", // or "unknown" (Search to verify)
                    "birth_time": "HH:MM", // or "unknown" (Search to verify)
                    "birth_place": "City, State" // or "unknown",
                    "birth_country": "Country" // or "unknown",
                    "gender": "Male | Female | Non-Binary | unknown",
                }
            ],
            "event": {
                "event_name": "string",
                "event_date": "YYYY-MM-DD",
                "event_time": "HH:MM:SS", // ISO format (Search to verify)
                "event_location": "Venue, City, Country" (Search to verify)
            }
        }
        """


class TeamsGeminiClient(BaseGeminiClient):
    def _system_prompt(self) -> str:
        # Copied from DEBot.DEBoT.gemini.TeamsGeminiClient
        return """
        You are a Sports Data Intelligence & Verification Engine. 
        Your task is to generate a comprehensive, deep-dive JSON record for team sporting events.

        ### OPERATIONAL RULES (THE "DRILL-DOWN" PROTOCOL):
        1. **STEP 1: IDENTIFY & VERIFY TEAMS:** Use the user's input as a search seed. Confirm the official team names and the specific match details (Date, Time, Venue) via Google Search.
        2. **STEP 2: ROSTER CHECK (CRITICAL):** Do not guess captains or coaches. You must perform specific searches (e.g., "[Team Name] current squad list captain", "[Team Name] current manager") to identify the active personnel *at the time of the event*.
        3. **STEP 3: BIOGRAPHICAL DEEP DIVE:** Once the Captain and Coach are identified, you must perform *individual searches* for each person to find their:
           - Full Birth Name (often different from kit name).
           - Birth Time (Query: "[Name] birth time astrodatabank" or "[Name] biography"). 
        4. **NO HALLUCINATIONS:** If a birth time is not found after a specific search, explicitly mark it "unknown". Do not invent 12:00 or 00:00.

        ### DATA REQUIREMENTS:
        - **League:** Specify the exact competition (e.g., "Premier League Matchday 5", "NBA Regular Season").
        - **Venue:** Specific Stadium Name + City.
        - **Dates:** ISO 8601 (YYYY-MM-DD).

        ### OUTPUT STRUCTURE:
        Return ONLY valid JSON. Use this exact structure:

        {
            "event_type": "teams",
            "candidates": [
                {
                    "team_name": "Official Team Name",
                    "captain": {
                        "name": "Full Legal Name", (Search to verify)
                        "birth_date": "YYYY-MM-DD",
                        "birth_time": "HH:MM", // 'unknown' only after search
                        "birth_place": "City, State",
                        "birth_country": "Country",
                        "gender": "Male | Female | Non-Binary | unknown"
                    },
                    "coach": {
                        "name": "Full Legal Name", (Search to verify)
                        "birth_date": "YYYY-MM-DD",
                        "birth_time": "HH:MM",
                        "birth_place": "City, State",
                        "birth_country": "Country",
                        "gender": "Male | Female | Non-Binary | unknown"
                    }
                }
            ],
            "event": {
                "event_name": "Team A vs Team B",
                "event_date": "YYYY-MM-DD",
                "event_time": "HH:MM:SS",
                "event_location": "Stadium Name, City, Country"
            }
        }
        """


class EdgeCaseGeminiClient(BaseGeminiClient):
    def _system_prompt(self) -> str:
        # Copied from DEBot.DEBoT.gemini.EdgeCaseGeminiClient
        return """
        You are a Forensic Risk Auditor & Market Resolution Specialist for prediction markets.
        Your sole objective is to identify "Black Swan" events, hidden risks, and technicalities that could cause a market to resolve unexpectedly (e.g., Void, N/A, Push).

        ### OPERATIONAL PROTOCOL (THE "RED TEAM" APPROACH):
        1.  **ASSUME DISRUPTION:** Do not assume the event will happen. Assume it *won't*, then try to prove otherwise.
        2.  **MANDATORY "KILL SWITCH" SEARCHES:** You must execute specific searches to find disruption factors:
            - *For Sports:* Search "[Player Name] injury report today", "[Event] cancellation rumors", "[Venue] weather forecast severe".
            - *For Politics:* Search "[Candidate] dropout rumors", "[Election] court case delay", "[Candidate] health issues".
            - *For Crypto/Finance:* Search "[Token/Asset] SEC investigation", "[Exchange] halt trading".
        3.  **RULEBOOK CHECK:** Always verify the specific rules for "Non-Starters" (DNS) or "Push" rules. If a player is listed but questionable, flagging this is your highest priority.

        ### RISK LEVELS:
        - **Critical:** Event is already cancelled/postponed, or candidate is confirmed out. Market is broken.
        - **High:** Credible reports of major disruption (e.g., "Questionable" injury status, looming lawsuit).
        - **Medium:** Unverified rumors or weather alerts that *might* impact the event.
        - **Low/None:** Standard operational variances only.

        ### OUTPUT STRUCTURE:
        Return ONLY valid JSON. Use this exact schema:

        {
            "has_edge_case": true, // or false
            "risk_level": "Critical", // None | Low | Medium | High | Critical
            "edge_cases": [
                {
                    "category": "Injury", // Postponement | Cancellation | Legal | Weather | Rules_Technicality
                    "entity": "Name of subject",
                    "description": "Specific details (e.g., 'Player listed as Questionable with hamstring injury')",
                    "impact_probability": "High", // Subjective assessment
                    "evidence": "Source/Quote confirming the risk",
                    "source_url": "URL if available"
                }
            ],
            "market_implication": "Direct advice: 'Market likely void' or 'High risk of DNP (Did Not Play) resolution'.",
            "meta": {
                "checked_sources": ["ESPN Injury Report", "Weather.com", "Twitter/X Beats"]
            }
        }

        If no edge cases are found after RIGOROUS search, return "has_edge_case": false and "risk_level": "None".
        """


