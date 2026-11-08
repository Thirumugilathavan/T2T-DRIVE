"""
LLM Adapter for T2T DRIVE Agent.
Provides an interface for external LLM inference (e.g. Evon / Gemini / OpenAI)
with automatic fallback to deterministic NLU when offline or unconfigured.
"""

import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("t2t_drive.llm_adapter")


class LLMAdapter:
    """
    Adapter interfacing between LangGraph and conversational LLMs.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: str = "evon-copilot-v1"):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.model_name = model_name or os.getenv("LLM_MODEL", "evon-copilot-v1")
        self.is_configured = bool(self.api_key)

    def extract_intent_and_entities(self, text: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Calls external LLM to parse natural language if configured.
        Returns parsed dict or None if LLM is not configured / fails.
        """
        if not self.is_configured:
            return None

        try:
            # Here we would call the actual LLM API (e.g. Evon or Gemini)
            # In Phase 3 tests and offline dev, returns None to allow deterministic NLU fallback
            logger.info("LLM adapter invoked for model: %s", self.model_name)
            return None
        except Exception as e:
            logger.warning("LLM extraction failed, falling back to rule-based NLU: %s", e)
            return None
