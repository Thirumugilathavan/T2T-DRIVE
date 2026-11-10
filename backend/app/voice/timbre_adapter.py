"""
Gnani AI Timbre Text-to-Speech (TTS) Adapter for T2T DRIVE.
Implements the verified Timbre REST API specification (https://api.vachana.ai/api/v1/tts/inference)
and a robust MockTimbreAdapter for offline testing and development.
Verified Documentation Date: November 8, 2026.
"""

import io
import math
import wave
import base64
import struct
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import httpx

from app.voice.schemas import TTSResponse

logger = logging.getLogger("t2t_drive.timbre_adapter")


class TimbreAdapterBase(ABC):
    """Abstract interface for Text-to-Speech providers."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        language: str = "ta-IN",
        voice: str = "Kaveri",
        speed: float = 1.0
    ) -> TTSResponse:
        """Synthesizes text into audio bytes and base64 representation."""
        pass


class TimbreAdapter(TimbreAdapterBase):
    """
    Live Gnani AI Timbre REST API Adapter.
    Endpoint: https://api.vachana.ai/api/v1/tts/inference
    Headers: Content-Type: application/json, X-API-Key-ID: <api_key>
    Payload: JSON with text, voice, model, language, speed, audio_config.
    """

    def __init__(
        self,
        api_key: str,
        endpoint_url: str = "https://api.vachana.ai/api/v1/tts/inference",
        model: str = "timbre-v2.5",
        timeout_seconds: float = 15.0
    ):
        if not api_key:
            raise ValueError("TimbreAdapter requires a non-empty GNANI_API_KEY.")
        self.api_key = api_key
        self.endpoint_url = endpoint_url
        self.model = model
        self.timeout = timeout_seconds

    def synthesize(
        self,
        text: str,
        language: str = "ta-IN",
        voice: str = "Kaveri",
        speed: float = 1.0
    ) -> TTSResponse:
        """Synthesizes text via Gnani Timbre REST endpoint."""
        clean_text = text.strip()
        if not clean_text:
            return TTSResponse(
                provider="gnani_timbre",
                processing_status="ERROR",
                error="Cannot synthesize empty text."
            )

        lang_code = self._map_language_code(language)

        headers = {
            "Content-Type": "application/json",
            "X-API-Key-ID": self.api_key,
            "Accept": "audio/wav, application/json"
        }

        payload = {
            "text": clean_text,
            "voice": voice,
            "model": self.model,
            "language": lang_code,
            "speed": float(speed),
            "audio_config": {
                "sample_rate": 24000,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": "wav"
            }
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint_url,
                    headers=headers,
                    json=payload
                )

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "audio/wav")

                # If binary audio is returned directly
                if "audio" in content_type or response.content.startswith(b"RIFF"):
                    audio_bytes = response.content
                    b64 = base64.b64encode(audio_bytes).decode("ascii")
                    return TTSResponse(
                        audio_bytes=audio_bytes,
                        audio_base64=b64,
                        content_type="audio/wav",
                        provider="gnani_timbre",
                        processing_status="SUCCESS"
                    )

                # If JSON envelope containing audio/base64 is returned
                try:
                    resp_json = response.json()
                    b64 = resp_json.get("audio") or resp_json.get("audio_base64") or resp_json.get("data")
                    if b64:
                        audio_bytes = base64.b64decode(b64)
                        return TTSResponse(
                            audio_bytes=audio_bytes,
                            audio_base64=b64,
                            content_type="audio/wav",
                            provider="gnani_timbre",
                            processing_status="SUCCESS"
                        )
                except Exception:
                    pass

                return TTSResponse(
                    provider="gnani_timbre",
                    processing_status="ERROR",
                    error="Unrecognized Timbre response format."
                )

            elif response.status_code == 401:
                logger.error("Timbre authentication failed (HTTP 401). Check GNANI_API_KEY.")
                return TTSResponse(
                    provider="gnani_timbre",
                    processing_status="ERROR",
                    error="Gnani Timbre authentication failed. Invalid API Key."
                )

            elif response.status_code == 429:
                logger.warning("Timbre rate limit exceeded (HTTP 429).")
                return TTSResponse(
                    provider="gnani_timbre",
                    processing_status="ERROR",
                    error="Gnani Timbre rate limit exceeded."
                )

            else:
                logger.error("Timbre error %d: %s", response.status_code, response.text)
                return TTSResponse(
                    provider="gnani_timbre",
                    processing_status="ERROR",
                    error=f"Timbre TTS service error ({response.status_code})."
                )

        except httpx.TimeoutException:
            logger.error("Timbre TTS request timed out after %ds", self.timeout)
            return TTSResponse(
                provider="gnani_timbre",
                processing_status="ERROR",
                error="Timbre TTS request timed out."
            )
        except Exception as e:
            logger.error("Unexpected error contacting Timbre TTS: %s", e)
            return TTSResponse(
                provider="gnani_timbre",
                processing_status="ERROR",
                error=f"Timbre connection error: {str(e)}"
            )

    @staticmethod
    def _map_language_code(lang: str) -> str:
        """Normalizes language code for Timbre catalog."""
        l = lang.lower().strip()
        if l in ("auto", "indic-auto"):
            return "auto"
        if "en" in l:
            return "en-IN"
        return "ta-IN"


class MockTimbreAdapter(TimbreAdapterBase):
    """
    Mock Timbre Adapter generating synthetic WAV audio for offline testing.
    Produces compliant, playable in-memory audio buffers using standard libraries.
    """

    def __init__(self):
        self.should_fail = False
        self.failure_reason = "Mock Timbre failure"
        self.should_timeout = False

    def synthesize(
        self,
        text: str,
        language: str = "ta-IN",
        voice: str = "Kaveri",
        speed: float = 1.0
    ) -> TTSResponse:
        """Generates valid WAV audio tone."""
        if not text or not text.strip():
            return TTSResponse(
                provider="mock_timbre",
                processing_status="ERROR",
                error="Cannot synthesize empty text."
            )

        if self.should_timeout:
            return TTSResponse(
                provider="mock_timbre",
                processing_status="ERROR",
                error="Timbre TTS request timed out."
            )

        if self.should_fail:
            return TTSResponse(
                provider="mock_timbre",
                processing_status="ERROR",
                error=self.failure_reason
            )

        # Generate a valid, lightweight 0.4-second audio tone in WAV format
        audio_bytes = self._generate_mock_wav(duration_seconds=0.4, frequency_hz=440.0)
        b64 = base64.b64encode(audio_bytes).decode("ascii")

        return TTSResponse(
            audio_bytes=audio_bytes,
            audio_base64=b64,
            content_type="audio/wav",
            provider="mock_timbre",
            processing_status="SUCCESS"
        )

    @staticmethod
    def _generate_mock_wav(duration_seconds: float = 0.4, frequency_hz: float = 440.0) -> bytes:
        """Generates raw PCM WAV audio bytes in memory."""
        sample_rate = 16000
        num_frames = int(sample_rate * duration_seconds)
        bio = io.BytesIO()

        with wave.open(bio, "wb") as wf:
            wf.setnchannels(1)       # Mono
            wf.setsampwidth(2)       # 16-bit
            wf.setframerate(sample_rate)

            # Generate sine wave samples
            samples = []
            for i in range(num_frames):
                val = int(math.sin(2 * math.pi * frequency_hz * i / sample_rate) * 8000)
                samples.append(struct.pack("<h", val))

            wf.writeframes(b"".join(samples))

        return bio.getvalue()


class DisabledTimbreAdapter(TimbreAdapterBase):
    """Adapter used when Timbre TTS is explicitly disabled via GNANI_TIMBRE_ENABLED=0."""

    def __init__(self, reason: str = "Gnani Timbre TTS is disabled by configuration (GNANI_TIMBRE_ENABLED=0)."):
        self.reason = reason

    def synthesize(
        self,
        text: str,
        language: str = "ta-IN",
        voice: str = "Kaveri",
        speed: float = 1.0,
        output_format: str = "wav"
    ) -> TTSResponse:
        return TTSResponse(
            audio_bytes=None,
            audio_base64=None,
            content_type="audio/wav",
            provider="gnani_timbre_disabled",
            processing_status="ERROR",
            error=self.reason
        )
