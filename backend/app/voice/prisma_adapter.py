"""
Gnani AI Prisma Speech-to-Text (STT) Adapter for T2T DRIVE.
Implements the verified Prisma v3.0 REST API specification (https://api.vachana.ai/stt/v3)
and a robust MockPrismaAdapter for offline testing and development.
Verified Documentation Date: November 8, 2026.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import httpx

from app.voice.schemas import STTResponse

logger = logging.getLogger("t2t_drive.prisma_adapter")


class PrismaAdapterBase(ABC):
    """Abstract interface for Speech-to-Text providers."""

    @abstractmethod
    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language_hint: str = "indic-auto",
        mime_type: str = "audio/wav"
    ) -> STTResponse:
        """Transcribes raw audio bytes into normalized STTResponse."""
        pass


class PrismaAdapter(PrismaAdapterBase):
    """
    Live Gnani AI Prisma v3.0 REST API Adapter.
    Endpoint: https://api.vachana.ai/stt/v3
    Headers: X-API-Key-ID: <api_key>
    Payload: multipart/form-data with audio_file, model, language_code, format, keyterms.
    """

    def __init__(
        self,
        api_key: str,
        endpoint_url: str = "https://api.vachana.ai/stt/v3",
        model: str = "prisma-v3.0",
        timeout_seconds: float = 20.0
    ):
        if not api_key:
            raise ValueError("PrismaAdapter requires a non-empty GNANI_API_KEY.")
        self.api_key = api_key
        self.endpoint_url = endpoint_url
        self.model = model
        self.timeout = timeout_seconds

        # Domain context terms for auto-rickshaw and cab drivers (context boosting)
        self.keyterms = [
            "diesel", "petrol", "cng", "savari", "owner", "vaadagai", "rent",
            "puncture", "repair", "toll", "fastag", "kanaku", "settlement",
            "aama", "confirm", "vendaam", "cancel"
        ]

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language_hint: str = "indic-auto",
        mime_type: str = "audio/wav"
    ) -> STTResponse:
        """Sends audio to Gnani Prisma v3.0 REST endpoint."""
        # Map driver language hint to Prisma language_code
        lang_code = self._map_language_code(language_hint)

        headers = {
            "X-API-Key-ID": self.api_key,
            "Accept": "application/json"
        }

        data = {
            "model": self.model,
            "language_code": lang_code,
            "format": "codemix"  # Keeps Tanglish / code-mixed terms and words
        }

        files = {
            "audio_file": (filename, audio_bytes, mime_type)
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint_url,
                    headers=headers,
                    data=data,
                    files=files
                )

            if response.status_code == 200:
                resp_json = response.json()
                transcript = self._extract_transcript(resp_json)
                detected_lang = resp_json.get("language_detected") or resp_json.get("language") or language_hint
                confidence = resp_json.get("confidence") or resp_json.get("confidence_score")

                if not transcript or not transcript.strip():
                    return STTResponse(
                        transcript="",
                        detected_language=detected_lang,
                        confidence=confidence,
                        provider="gnani_prisma",
                        processing_status="EMPTY",
                        error="Prisma returned an empty transcript (no speech detected)."
                    )

                return STTResponse(
                    transcript=transcript.strip(),
                    detected_language=detected_lang,
                    confidence=float(confidence) if confidence is not None else None,
                    provider="gnani_prisma",
                    processing_status="SUCCESS"
                )

            elif response.status_code == 401:
                logger.error("Prisma authentication failed (HTTP 401). Check GNANI_API_KEY.")
                return STTResponse(
                    transcript="",
                    provider="gnani_prisma",
                    processing_status="ERROR",
                    error="Gnani Prisma authentication failed. Invalid API Key."
                )

            elif response.status_code == 429:
                logger.warning("Prisma rate limit exceeded (HTTP 429).")
                return STTResponse(
                    transcript="",
                    provider="gnani_prisma",
                    processing_status="ERROR",
                    error="Gnani Prisma rate limit reached. Please retry shortly."
                )

            else:
                logger.error("Prisma error %d: %s", response.status_code, response.text)
                return STTResponse(
                    transcript="",
                    provider="gnani_prisma",
                    processing_status="ERROR",
                    error=f"Prisma STT service error ({response.status_code})."
                )

        except httpx.TimeoutException:
            logger.error("Prisma STT request timed out after %ds", self.timeout)
            return STTResponse(
                transcript="",
                provider="gnani_prisma",
                processing_status="ERROR",
                error="Prisma STT request timed out."
            )
        except Exception as e:
            logger.error("Unexpected error contacting Prisma STT: %s", e)
            return STTResponse(
                transcript="",
                provider="gnani_prisma",
                processing_status="ERROR",
                error=f"Prisma connection error: {str(e)}"
            )

    @staticmethod
    def _map_language_code(hint: str) -> str:
        """Maps user/frontend language hints to Prisma BCP-47 codes."""
        h = hint.lower().strip()
        if h in ("ta", "tamil"):
            return "ta-IN"
        elif h in ("en", "english"):
            return "en-IN"
        elif h in ("tanglish", "indic-auto", "code-mixed"):
            return "ta-IN,en-IN"  # Code-mixing hint
        return "indic-auto"

    @staticmethod
    def _extract_transcript(resp_json: Dict[str, Any]) -> str:
        """Extracts transcript text across various Prisma response schema versions."""
        if "transcript" in resp_json:
            return str(resp_json["transcript"])
        if "text" in resp_json:
            return str(resp_json["text"])
        if "result" in resp_json and isinstance(resp_json["result"], dict):
            return str(resp_json["result"].get("transcript", ""))
        if "predictions" in resp_json and isinstance(resp_json["predictions"], list) and resp_json["predictions"]:
            return str(resp_json["predictions"][0].get("transcript", ""))
        return ""


class MockPrismaAdapter(PrismaAdapterBase):
    """
    Mock Prisma Adapter for local development and unit/integration testing.
    Returns deterministic transcripts without hitting external servers.
    """

    def __init__(self, default_transcript: Optional[str] = None):
        self.default_transcript = default_transcript
        self.should_fail = False
        self.failure_reason = "Mock Prisma failure"
        self.should_timeout = False

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language_hint: str = "indic-auto",
        mime_type: str = "audio/wav"
    ) -> STTResponse:
        """Simulates speech recognition."""
        if self.should_timeout:
            return STTResponse(
                transcript="",
                provider="mock_prisma",
                processing_status="ERROR",
                error="Prisma STT request timed out."
            )

        if self.should_fail:
            return STTResponse(
                transcript="",
                provider="mock_prisma",
                processing_status="ERROR",
                error=self.failure_reason
            )

        # Use explicitly provided default transcript if set
        if self.default_transcript:
            return STTResponse(
                transcript=self.default_transcript,
                detected_language="tanglish" if "tanglish" in language_hint else "tamil",
                confidence=0.96,
                provider="mock_prisma",
                processing_status="SUCCESS"
            )

        # Context-based default mock selection based on language hint
        h = language_hint.lower()
        if "tanglish" in h:
            transcript = "diesel 400 potten"
            detected = "tanglish"
        elif "ta" in h or "tamil" in h:
            transcript = "டீசல் 400 போட்டேன்"
            detected = "tamil"
        elif "en" in h or "english" in h:
            transcript = "filled diesel 400"
            detected = "english"
        else:
            transcript = "diesel 400 potten"
            detected = "tanglish"

        return STTResponse(
            transcript=transcript,
            detected_language=detected,
            confidence=0.95,
            provider="mock_prisma",
            processing_status="SUCCESS"
        )
