"""
LLM provider abstraction and challenge parser.
Supports Ollama (default) with architecture for future providers.
Includes deterministic fallback parser.
"""
from __future__ import annotations
from typing import Optional

import json
import re
from abc import ABC, abstractmethod

# pyrefly: ignore [missing-import]
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.constraints import (
    ConstraintProfile,
)

logger = get_logger("llm")

SYSTEM_PROMPT = """You are the RouteEase constraint extraction engine.
Your ONLY task is to convert the user's natural-language description into the predefined routing constraint JSON schema.

Return ONLY valid JSON.
Do NOT return markdown.
Do NOT return explanations.
Do NOT return tables.
Do NOT return prose.
Do NOT invent information.
Do NOT generate routes.
Do NOT generate coordinates.
Do NOT generate traffic information.
Do NOT generate places.

Only populate fields supported by the schema.
If the user's statement does not provide enough information for a field, use its default/unknown value.
Never infer sensitive or unsupported user characteristics.
Your output will be validated by a strict Pydantic schema.

JSON Schema (output exactly this structure):
{
  "avoid_highways": false,
  "avoid_tolls": false,
  "avoid_ferries": false,
  "avoid_unpaved": false,
  "avoid_potholes": false,
  "avoid_roadblocks": false,
  "avoid_complex_intersections": false,
  "avoid_roundabouts": false,
  "avoid_heavy_merges": false,
  "avoid_high_traffic": false,
  "avoid_unlit_roads": false,
  "needs_rest_stops": false,
  "needs_accessible_restrooms": false,
  "needs_pharmacy": false,
  "needs_hospital": false,
  "needs_fuel": false,
  "needs_ev_charging": false,
  "mobility_level": "full",
  "driving_experience": "experienced",
  "vision_sensitivity": false,
  "priority": "balanced",
  "confidence": 0.5,
  "reasoning_summary": ""
}

Valid enum values:
- mobility_level: full, moderate, limited, wheelchair
- driving_experience: learner, beginner, intermediate, experienced
- priority: safety, accessibility, comfort, speed, balanced
"""


# ────────────────────────────────────────────────────────────────
# Provider interface
# ────────────────────────────────────────────────────────────────
class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a completion. Returns raw text."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": 1024,
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")

    def provider_name(self) -> str:
        return "ollama"


class LMStudioProvider(LLMProvider):
    """LM Studio local LLM provider (OpenAI-compatible API)."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.lm_studio_base_url).rstrip("/")
        self.model = model or settings.lm_studio_model

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        model_name = self.model or "meta-llama-3-8b-instruct"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 400,
            "stream": False
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "")

    def provider_name(self) -> str:
        return "lmstudio"


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible LLM provider."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.model = model or settings.openai_model
        self.api_key = api_key or settings.openai_api_key

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 400,
            "stream": False
        }
        headers = {
            "Content-Type": "application/json", 
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "CareGPS"
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "")

    def provider_name(self) -> str:
        return "openai"


class GeminiProvider(LLMProvider):
    """Gemini API provider."""

    def __init__(self, api_key: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": system_prompt + "\n\n" + user_prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                return ""

    def provider_name(self) -> str:
        return "gemini"


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider (uses OpenAI compatible API)."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.base_url = "https://openrouter.ai/api/v1"

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.0,
            "stream": False,
            "reasoning": {"enabled": True}
        }
        headers = {
            "Content-Type": "application/json", 
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "CareGPS"
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "")

    def provider_name(self) -> str:
        return "openrouter"


# ────────────────────────────────────────────────────────────────
# Deterministic fallback parser
# ────────────────────────────────────────────────────────────────
# Keyword → constraint field mappings
_KEYWORD_MAP: list[tuple[list[str], dict]] = [
    # Mobility
    (["walker", "walking frame", "walking aid"], {"mobility_level": "limited", "avoid_unpaved": True, "avoid_potholes": True, "priority": "accessibility"}),
    (["wheelchair", "disabled", "accessible", "wheel chair", "ramp"], {"mobility_level": "wheelchair", "avoid_unpaved": True, "avoid_potholes": True, "needs_accessible_restrooms": True, "priority": "accessibility"}),
    (["crutch", "crutches", "cane", "walking stick"], {"mobility_level": "limited", "avoid_unpaved": True, "avoid_potholes": True, "priority": "accessibility"}),
    (["mobility", "limited mobility", "hard to walk"], {"mobility_level": "limited", "avoid_potholes": True, "priority": "accessibility"}),
    (["curb", "high curb", "bad road", "rough road", "bumpy", "potholes", "pothole", "uneven", "unpaved", "dirt road", "gravel"], {"avoid_unpaved": True, "avoid_potholes": True}),

    # Driving experience
    (["new driver", "learner", "just started driving", "learning to drive", "beginner driver", "new to driving", "novice", "anxious driver", "scared to drive", "nervous", "first time driving"], {"driving_experience": "learner", "avoid_highways": True, "avoid_heavy_merges": True, "avoid_complex_intersections": True, "priority": "safety"}),
    (["highway", "highways", "motorway", "freeway", "expressway", "interstate", "fast traffic", "scared of trucks"], {"avoid_highways": True, "avoid_heavy_merges": True}),
    (["merge", "merging", "heavy merge", "changing lanes"], {"avoid_heavy_merges": True}),
    (["roundabout", "roundabouts", "traffic circle", "rotary"], {"avoid_roundabouts": True}),
    (["complex intersection", "complicated intersection", "busy junction", "hard turns", "difficult intersection"], {"avoid_complex_intersections": True}),

    # Vision / Environment
    (["night", "dark", "can't see", "poor vision", "vision", "night vision", "night driving", "unlit", "astigmatism", "harsh lighting", "headlights", "glare", "blind", "glasses"], {"vision_sensitivity": True, "avoid_unlit_roads": True, "avoid_high_traffic": True}),
    
    # Safety
    (["woman", "women", "girl", "safety", "safe", "scared", "alone", "solo"], {"avoid_unlit_roads": True, "priority": "safety"}),

    # Elderly
    (["elderly", "senior", "old age", "aging", "old", "grandma", "grandpa", "slow driver"], {"priority": "comfort", "avoid_high_traffic": True, "avoid_heavy_merges": True}),

    # Needs
    (["rest", "rest stop", "break", "stop and rest", "take a break", "tiring", "tired", "long drive", "sleepy", "fatigue"], {"needs_rest_stops": True, "priority": "comfort"}),
    (["pharmacy", "medicine", "medication", "pill", "chemist", "drugstore"], {"needs_pharmacy": True}),
    (["hospital", "emergency", "medical", "clinic", "doctor", "pregnant", "pregnancy"], {"needs_hospital": True, "priority": "safety"}),
    (["fuel", "gas", "petrol", "gas station", "fuel station", "diesel"], {"needs_fuel": True}),
    (["ev", "electric", "charging", "ev charging", "charge", "tesla", "battery"], {"needs_ev_charging": True}),
    (["restroom", "toilet", "bathroom", "accessible restroom", "washroom", "pee", "loo", "urinal"], {"needs_accessible_restrooms": True}),
    (["food", "eat", "hungry", "snack", "cafe", "restaurant", "coffee", "drink"], {"needs_rest_stops": True}),

    # Traffic
    (["traffic", "busy road", "congestion", "calm road", "calmer", "quiet road", "jam", "rush hour", "peaceful", "scenic", "relaxing", "trees", "nature"], {"avoid_high_traffic": True, "priority": "comfort"}),

    # Routing exclusions
    (["roadblock", "road block", "blocked", "closure", "closed"], {"avoid_roadblocks": True}),
    (["toll", "toll road", "tolls", "pay"], {"avoid_tolls": True}),
    (["ferry", "ferries", "boat"], {"avoid_ferries": True}),

    # Speed priority
    (["fast", "fastest", "quickly", "hurry", "rush", "quick", "asap", "as quickly as possible", "late", "urgent"], {"priority": "speed"}),
]


def fallback_parse(text: str) -> ConstraintProfile:
    """
    Deterministic keyword-based fallback parser.
    Scans text for known concepts and builds a ConstraintProfile.
    Does NOT overinterpret.
    """
    text_lower = text.lower()
    fields: dict = {}

    for keywords, mappings in _KEYWORD_MAP:
        for kw in keywords:
            if kw in text_lower:
                for key, val in mappings.items():
                    # For booleans, OR them (if any match sets True, keep True)
                    if isinstance(val, bool):
                        fields[key] = fields.get(key, False) or val
                    # For enums/strings, last match wins (but priority order matters)
                    elif key == "priority":
                        # Don't override a more specific priority with a generic one
                        if key not in fields or val != "balanced":
                            fields[key] = val
                    else:
                        fields[key] = val
                break  # Only match first keyword in each group

    fields["confidence"] = 0.6 if fields else 0.3
    fields["reasoning_summary"] = f"Fallback parser extracted from: '{text[:100]}'"

    return ConstraintProfile(**fields)


# ────────────────────────────────────────────────────────────────
# Challenge parser service
# ────────────────────────────────────────────────────────────────
class ChallengeParserService:
    """
    Parses natural-language challenges into structured constraints.
    Uses LLM if available, falls back to deterministic parser.
    """

    def __init__(self, provider: Optional[LLMProvider] = None):
        self._provider = provider

    async def parse(self, challenge_text: str) -> tuple[ConstraintProfile, str]:
        """
        Parse challenge text into constraints.
        Returns: (ConstraintProfile, parser_source_name)
        """
        if not challenge_text.strip():
            return ConstraintProfile(), "default"

        # Try LLM first
        if self._provider is not None:
            try:
                result = await self._try_llm(challenge_text)
                if result is not None:
                    return result, self._provider.provider_name()
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM parsing failed, using fallback: %s", e)

        # Fallback
        logger.info("Using fallback parser for challenge text")
        return fallback_parse(challenge_text), "fallback"

    async def _try_llm(self, text: str) -> Optional[ConstraintProfile]:
        """Attempt LLM parsing with retry."""
        assert self._provider is not None

        for attempt in range(2):
            try:
                user_prompt = f"Extract constraints from this user challenge:\n\n\"{text}\""
                if attempt == 1:
                    user_prompt += "\n\nPrevious response was invalid JSON. Please output ONLY valid JSON matching the schema."

                raw = await self._provider.generate(SYSTEM_PROMPT, user_prompt)
                logger.debug("LLM raw response (attempt %d): %s", attempt + 1, raw[:500])

                # Try to extract JSON from response
                parsed = self._extract_json(raw)
                if parsed is None:
                    logger.warning("Could not extract JSON from LLM response (attempt %d)", attempt + 1)
                    continue

                # Validate with Pydantic
                profile = ConstraintProfile(**parsed)
                logger.info("LLM parsed constraints successfully (attempt %d)", attempt + 1)
                return profile

            except Exception as e:  # noqa: BLE001
                logger.warning("LLM parse attempt %d failed: %s", attempt + 1, e)
                if attempt == 1:
                    return None

        return None

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extract JSON object from LLM response text."""
        # Try direct parse
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON in code fences
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find first { ... } block
        brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None


def create_llm_provider() -> Optional[LLMProvider]:
    """Factory: create the configured LLM provider, or None if unavailable."""
    settings = get_settings()
    if settings.llm_provider == "ollama":
        return OllamaProvider()
    if settings.llm_provider == "lmstudio":
        return LMStudioProvider()
    if settings.llm_provider == "openai":
        return OpenAIProvider()
    if settings.llm_provider == "gemini":
        return GeminiProvider()
    if settings.llm_provider == "openrouter":
        return OpenRouterProvider()
    # Future: anthropic
    logger.warning("Unknown LLM provider: %s", settings.llm_provider)
    return None
