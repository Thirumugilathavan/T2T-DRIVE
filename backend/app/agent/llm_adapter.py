"""
LLM / AI Extraction Adapter for T2T DRIVE Agent.
Provides an interface for external LLM inference (e.g. Gnani Evon / OpenAI-compatible / Gemini)
with strict Bearer authentication, clean token parsing, and deterministic NLU fallback.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger("t2t_drive.llm_adapter")


def clean_bearer_token(token: Optional[str]) -> str:
    """
    Cleans and validates an API bearer token:
    - Strips leading and trailing whitespace.
    - Strips surrounding quotes (' or \").
    - Raises ValueError if the resulting token is missing or empty.
    """
    if token is None:
        raise ValueError("AI extraction token is missing (None provided).")

    cleaned = str(token).strip().strip("'\"").strip()
    if not cleaned:
        raise ValueError("AI extraction token is missing or malformed (empty after trimming quotes and whitespace).")
    return cleaned


def build_bearer_header(token: Optional[str]) -> Dict[str, str]:
    """
    Constructs an Authorization header enforcing standard RFC 6750 'Bearer <token>' format.
    Ensures no extra quotes or whitespace are included.
    """
    clean_token = clean_bearer_token(token)
    return {"Authorization": f"Bearer {clean_token}"}


class LLMAdapter:
    """
    Adapter interfacing between LangGraph conversational agent and external LLM inference endpoints.
    Enforces server-side Bearer authentication, strict error handling, and zero silent mock fallback in live mode.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        inference_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 15.0
    ):
        raw_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("AI_EXTRACTION_API_KEY") or os.getenv("GNANI_EVON_API_KEY")
        self.raw_api_key = raw_key
        try:
            self.api_key = clean_bearer_token(raw_key) if raw_key else None
        except ValueError:
            self.api_key = None

        self.inference_url = inference_url or os.getenv("LLM_INFERENCE_URL") or os.getenv("GNANI_EVON_INFERENCE_URL") or "http://localhost:8000/v1/chat/completions"
        self.model_name = model_name or os.getenv("LLM_MODEL") or os.getenv("GNANI_EVON_MODEL_NAME") or "gnani-evon"
        self.timeout = timeout
        self.is_configured = bool(self.api_key and self.inference_url)

    def get_auth_headers(self) -> Dict[str, str]:
        """Returns Authorization header with Bearer token for server-side HTTP requests."""
        if not self.api_key:
            raise ValueError("Cannot construct Bearer header: LLM_API_KEY is not configured.")
        return build_bearer_header(self.api_key)

    def extract_intent_and_entities(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        require_live: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Calls external LLM inference endpoint to parse natural language intent and entities.

        Parameters:
        - text: User speech transcript or typed message.
        - context: Optional session context.
        - require_live: If True, strictly raises on missing token or provider failure
                        (prevents silent mock fallback in production).

        Returns:
        - Parsed dict with intent, entities, slots, and confidence,
          or None if LLM is unconfigured and require_live is False (allowing deterministic NLU fallback).
        """
        if not self.is_configured:
            if require_live:
                raise ValueError(
                    "AI Extraction is in LIVE mode but LLM_API_KEY is missing or invalid. "
                    "Configure LLM_API_KEY in environment variables."
                )
            return None

        headers = self.get_auth_headers()
        headers["Content-Type"] = "application/json"

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a multilingual AI assistant for auto and taxi drivers. "
                               "Extract intent (e.g. RECORD_EXPENSE, RECORD_INCOME), amount, category, and language."
                },
                {"role": "user", "content": text}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.inference_url,
                    headers=headers,
                    json=payload
                )

            if response.status_code == 401:
                logger.error("AI extraction provider rejected credentials (HTTP 401). Check LLM_API_KEY.")
                raise PermissionError("AI extraction provider authentication failed (HTTP 401 Unauthorized). Check LLM_API_KEY.")

            if response.status_code != 200:
                logger.warning("AI extraction provider error (%d): %s", response.status_code, response.text)
                if require_live:
                    raise RuntimeError(f"AI extraction provider failed with HTTP {response.status_code}: {response.text}")
                return None

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            parsed = json.loads(content) if isinstance(content, str) else content
            return parsed

        except httpx.TimeoutException:
            logger.error("AI extraction request timed out after %.1fs", self.timeout)
            if require_live:
                raise TimeoutError("AI extraction provider timed out.")
            return None
        except PermissionError:
            raise
        except Exception as e:
            logger.warning("LLM extraction call failed: %s", e)
            if require_live:
                raise
            return None
