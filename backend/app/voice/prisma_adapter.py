"""
Gnani AI Prisma Speech-to-Text (STT) Adapter for T2T DRIVE.
Implements the verified Prisma v3.0 REST API specification (https://api.vachana.ai/stt/v3)
and a robust MockPrismaAdapter for offline testing and development.
Verified Documentation Date: November 8, 2026.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import requests

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
        mime_type: str = "audio/wav",
        output_format: str = "transcribe",
        preferred_language: Optional[str] = None,
        itn_native_numerals: bool = False
    ) -> STTResponse:
        """Transcribes raw audio bytes into normalized STTResponse."""
        pass


class PrismaAdapter(PrismaAdapterBase):
    """
    Live Gnani AI Prisma v3.0 REST API Adapter.
    Endpoint: https://api.vachana.ai/stt/v3
    Headers: X-API-Key-ID: <api_key>
    Payload: multipart/form-data with audio_file, model, language_code, format,
             preferred_language, itn_native_numerals, multi_lang_codes.
    """

    def __init__(
        self,
        api_key: str,
        endpoint_url: str = "https://api.vachana.ai/stt/v3",
        model: str = "prisma-v3.0",
        timeout_seconds: float = 60.0
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
        mime_type: str = "audio/wav",
        output_format: str = "transcribe",
        preferred_language: Optional[str] = None,
        itn_native_numerals: bool = False
    ) -> STTResponse:
        """
        Sends audio to Gnani Prisma v3.0 REST endpoint using requests.
        Enforces strict standard TLS verification and single-call execution (zero retries).
        """
        # Map language parameters according to Gnani Prisma v3.0 specification
        lang_params = self._map_language_params(language_hint, preferred_language)

        headers = {
            "X-API-Key-ID": self.api_key,
            "Accept": "application/json",
            "Connection": "close"
        }

        data = {
            "model": self.model,
            **lang_params
        }
        if output_format:
            data["format"] = output_format
        if itn_native_numerals is not None:
            data["itn_native_numerals"] = "true" if itn_native_numerals else "false"

        # Ensure audio has a valid RIFF/WAVE header; auto-convert via FFmpeg if non-WAV container is passed
        if not (len(audio_bytes) >= 12 and audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE"):
            from app.voice.audio_preprocessor import AudioPreprocessor
            try:
                audio_bytes = AudioPreprocessor.convert_to_16k_mono_wav(audio_bytes)
                filename = "audio.wav"
                mime_type = "audio/wav"
            except Exception as conv_err:
                logger.warning("Defense-in-depth audio conversion to WAV failed in PrismaAdapter: %s", conv_err)

        files = {
            "audio_file": (filename, audio_bytes, mime_type)
        }

        # Initialize session with HTTPAdapter configured for 0 retries and clean socket termination
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        try:
            response = session.post(
                self.endpoint_url,
                headers=headers,
                data=data,
                files=files,
                timeout=self.timeout,
                verify=True
            )

            if response.status_code == 200:
                try:
                    resp_json = response.json()
                except Exception as json_err:
                    logger.error("Prisma returned malformed JSON: %s", json_err)
                    return STTResponse(
                        transcript="",
                        provider="gnani_prisma",
                        processing_status="ERROR",
                        error="Prisma returned a malformed non-JSON response."
                    )

                transcript = self._extract_transcript(resp_json)
                detected_lang = (
                    resp_json.get("detected_language_code") or
                    resp_json.get("language_detected") or
                    resp_json.get("language") or
                    lang_params.get("language_code") or
                    language_hint
                )
                confidence = resp_json.get("confidence") or resp_json.get("confidence_score")

                if not transcript or not transcript.strip():
                    return STTResponse(
                        transcript="",
                        detected_language=detected_lang,
                        confidence=confidence,
                        provider="gnani_prisma",
                        processing_status="EMPTY",
                        error="Prisma returned an empty transcript (no speech detected).",
                        analysis_report={"raw_response": resp_json, "http_status": response.status_code}
                    )

                return STTResponse(
                    transcript=transcript.strip(),
                    detected_language=detected_lang,
                    confidence=float(confidence) if confidence is not None else None,
                    provider="gnani_prisma",
                    processing_status="SUCCESS",
                    analysis_report={"raw_response": resp_json, "http_status": response.status_code}
                )

            elif response.status_code == 401:
                logger.error("Prisma authentication failed (HTTP 401). Check GNANI_API_KEY.")
                return STTResponse(
                    transcript="",
                    provider="gnani_prisma",
                    processing_status="ERROR",
                    error="Gnani Prisma authentication failed. Invalid API Key.",
                    analysis_report={"http_status": response.status_code}
                )

            elif response.status_code == 429:
                logger.warning("Prisma rate limit exceeded (HTTP 429).")
                return STTResponse(
                    transcript="",
                    provider="gnani_prisma",
                    processing_status="ERROR",
                    error="Gnani Prisma rate limit reached. Please retry shortly.",
                    analysis_report={"http_status": response.status_code}
                )

            else:
                err_msg = self._extract_error_message(response)
                logger.error("Prisma error %d: %s", response.status_code, err_msg)
                return STTResponse(
                    transcript="",
                    provider="gnani_prisma",
                    processing_status="ERROR",
                    error=f"Prisma STT error ({response.status_code}): {err_msg}",
                    analysis_report={"http_status": response.status_code}
                )

        except requests.exceptions.Timeout:
            logger.error("Prisma STT client request timed out after %ds", self.timeout)
            return STTResponse(
                transcript="",
                provider="gnani_prisma",
                processing_status="ERROR",
                error=f"Prisma STT request timed out after {self.timeout}s."
            )
        except requests.exceptions.SSLError as ssl_err:
            logger.error("Prisma SSL protocol error: %s", ssl_err)
            return STTResponse(
                transcript="",
                provider="gnani_prisma",
                processing_status="ERROR",
                error=f"Prisma SSL error: {str(ssl_err)}"
            )
        except requests.exceptions.ConnectionError as conn_err:
            logger.error("Prisma connection terminated or unreachable: %s", conn_err)
            return STTResponse(
                transcript="",
                provider="gnani_prisma",
                processing_status="ERROR",
                error=f"Prisma connection error: {str(conn_err)}"
            )
        except Exception as e:
            logger.error("Unexpected error contacting Prisma STT: %s", e)
            return STTResponse(
                transcript="",
                provider="gnani_prisma",
                processing_status="ERROR",
                error=f"Prisma error: {str(e)}"
            )
        finally:
            session.close()

    @staticmethod
    def _map_language_params(hint: str, preferred: Optional[str] = None) -> Dict[str, str]:
        """
        Maps driver language hint to verified Prisma v3.0 REST parameters.
        language_code must be a single locale (e.g. 'ta-IN', 'en-IN', 'indic-auto').
        multi_lang_codes is used only with language_code='indic-auto'.
        preferred_language biases the model toward the primary language.
        """
        h = (hint or "").lower().strip()
        params: Dict[str, str] = {}

        if h in ("ta", "tamil", "ta-in"):
            params["language_code"] = "ta-IN"
            params["preferred_language"] = preferred or "ta-IN"
        elif h in ("en", "english", "en-in"):
            params["language_code"] = "en-IN"
            params["preferred_language"] = preferred or "en-IN"
        elif h in ("tanglish", "code-mixed", "codemix", "indic-auto", "auto"):
            params["language_code"] = "indic-auto"
            params["preferred_language"] = preferred or "ta-IN"
            params["multi_lang_codes"] = "ta-IN,en-IN"
        else:
            params["language_code"] = "indic-auto"
            if preferred:
                params["preferred_language"] = preferred

        return params

    @staticmethod
    def _map_language_code(hint: str) -> str:
        """Backward-compatible helper returning single locale code."""
        h = (hint or "").lower().strip()
        if h in ("ta", "tamil", "ta-in"):
            return "ta-IN"
        elif h in ("en", "english", "en-in"):
            return "en-IN"
        return "indic-auto"

    @staticmethod
    def _extract_transcript(resp_json: Dict[str, Any]) -> str:
        """Extracts transcript text across various Prisma response schema versions."""
        if "transcript" in resp_json and resp_json["transcript"] is not None:
            return str(resp_json["transcript"])
        if "text" in resp_json and resp_json["text"] is not None:
            return str(resp_json["text"])
        if "data" in resp_json and isinstance(resp_json["data"], dict):
            d = resp_json["data"]
            if "transcript" in d and d["transcript"] is not None:
                return str(d["transcript"])
            if "text" in d and d["text"] is not None:
                return str(d["text"])
        if "result" in resp_json and isinstance(resp_json["result"], dict):
            return str(resp_json["result"].get("transcript", ""))
        if "predictions" in resp_json and isinstance(resp_json["predictions"], list) and resp_json["predictions"]:
            return str(resp_json["predictions"][0].get("transcript", ""))
        return ""

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        """Extracts human-readable sanitized error details from JSON or HTTP response."""
        try:
            err_json = response.json()
            if isinstance(err_json, dict):
                # 1. Gnani standard format: {"success": false, "error": {"message": ..., "type": ...}}
                if "error" in err_json:
                    err_obj = err_json["error"]
                    if isinstance(err_obj, dict):
                        return err_obj.get("message") or err_obj.get("type") or str(err_obj)
                    return str(err_obj)
                # 2. FastAPI detail format: {"detail": [...]} or {"detail": {"message": ...}}
                if "detail" in err_json:
                    detail = err_json["detail"]
                    if isinstance(detail, list):
                        msgs = [f"{d.get('loc', [''])[-1]}: {d.get('msg', '')}" for d in detail if isinstance(d, dict)]
                        return "; ".join(msgs) if msgs else str(detail)
                    if isinstance(detail, dict):
                        return detail.get("message") or detail.get("error_code") or str(detail)
                    return str(detail)
                # 3. Generic message field
                if "message" in err_json:
                    return str(err_json["message"])
        except Exception:
            pass
        return f"HTTP {response.status_code} ({response.reason or 'Error'})"


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
        mime_type: str = "audio/wav",
        output_format: str = "transcribe",
        preferred_language: Optional[str] = None,
        itn_native_numerals: bool = False
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

        # File-based deterministic transcript mapping
        f_lower = (filename or "").lower()
        if "t2t_tanglish" in f_lower:
            return STTResponse(
                transcript="இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்.",
                detected_language="tanglish",
                confidence=0.98,
                provider="mock_prisma",
                processing_status="SUCCESS"
            )
        elif "stt_tamil" in f_lower:
            return STTResponse(
                transcript="டீசல் 400 போட்டேன்",
                detected_language="tamil",
                confidence=0.97,
                provider="mock_prisma",
                processing_status="SUCCESS"
            )
        elif "stt_english" in f_lower:
            return STTResponse(
                transcript="filled diesel 400",
                detected_language="english",
                confidence=0.96,
                provider="mock_prisma",
                processing_status="SUCCESS"
            )
        elif "stt_codmix" in f_lower or "codmix" in f_lower:
            return STTResponse(
                transcript="petrol 300 potten tea 30",
                detected_language="tanglish",
                confidence=0.95,
                provider="mock_prisma",
                processing_status="SUCCESS"
            )
        elif "ambiguous" in f_lower:
            return STTResponse(
                transcript="diesel potten",
                detected_language="tanglish",
                confidence=0.92,
                provider="mock_prisma",
                processing_status="SUCCESS"
            )
        elif "silence" in f_lower:
            return STTResponse(
                transcript="",
                detected_language="tanglish",
                confidence=0.0,
                provider="mock_prisma",
                processing_status="EMPTY"
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


class DisabledPrismaAdapter(PrismaAdapterBase):
    """Adapter used when Prisma STT is explicitly disabled via GNANI_PRISMA_ENABLED=0."""

    def __init__(self, reason: str = "Gnani Prisma STT is disabled by configuration (GNANI_PRISMA_ENABLED=0)."):
        self.reason = reason

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language_hint: str = "indic-auto",
        mime_type: str = "audio/wav",
        output_format: str = "transcribe",
        preferred_language: Optional[str] = None,
        itn_native_numerals: bool = False
    ) -> STTResponse:
        return STTResponse(
            transcript="",
            confidence=0.0,
            detected_language="unknown",
            processing_status="ERROR",
            error=self.reason,
            provider="gnani_prisma_disabled"
        )
