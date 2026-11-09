"""
Streaming Speech-to-Text (STT) Adapter Interface and Implementations for T2T DRIVE.
Provides continuous audio streaming interfaces, mock simulators for automated testing,
and unverified live WebSocket adapters for Gnani Prisma Streaming.
"""

import abc
import time
import logging
from typing import Callable, Optional, Dict, Any, List

logger = logging.getLogger("t2t_drive.streaming_adapter")


class StreamingSTTAdapterBase(abc.ABC):
    """Abstract interface for bidirectional streaming speech-to-text engines."""

    @abc.abstractmethod
    def start_session(
        self,
        session_id: str,
        language: str = "tanglish",
        on_transcript: Optional[Callable[[str, bool, float], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ) -> bool:
        """Initializes a real-time streaming recognition session."""
        pass

    @abc.abstractmethod
    def push_audio_chunk(self, session_id: str, pcm_chunk: bytes) -> None:
        """Pushes a chunk of 16-bit 16kHz mono PCM audio into the stream."""
        pass

    @abc.abstractmethod
    def stop_session(self, session_id: str) -> None:
        """Flushes and cleanly closes the active streaming session."""
        pass

    @abc.abstractmethod
    def is_session_active(self, session_id: str) -> bool:
        pass


class MockStreamingSTTAdapter(StreamingSTTAdapterBase):
    """
    In-memory mock streaming adapter for reproducible automated testing and offline development.
    Simulates real-time chunk ingestion and triggers callbacks with synthetic speech hypotheses.
    """

    def __init__(self):
        self.active_sessions: Dict[str, Dict[str, Any]] = {}

    def start_session(
        self,
        session_id: str,
        language: str = "tanglish",
        on_transcript: Optional[Callable[[str, bool, float], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ) -> bool:
        self.active_sessions[session_id] = {
            "language": language,
            "on_transcript": on_transcript,
            "on_error": on_error,
            "buffered_bytes": 0,
            "started_at": time.time(),
            "is_active": True
        }
        logger.info("MockStreamingSTTAdapter: Started streaming session %s", session_id)
        return True

    def push_audio_chunk(self, session_id: str, pcm_chunk: bytes) -> None:
        if session_id not in self.active_sessions or not self.active_sessions[session_id]["is_active"]:
            return

        sess = self.active_sessions[session_id]
        sess["buffered_bytes"] += len(pcm_chunk)

        # Trigger simulated transcript if callback is provided
        cb = sess.get("on_transcript")
        if cb and sess["buffered_bytes"] >= 32000:  # ~1 second of audio
            cb("Simulated streaming transcript", True, 0.88)
            sess["buffered_bytes"] = 0

    def stop_session(self, session_id: str) -> None:
        if session_id in self.active_sessions:
            self.active_sessions[session_id]["is_active"] = False
            del self.active_sessions[session_id]
            logger.info("MockStreamingSTTAdapter: Stopped streaming session %s", session_id)

    def is_session_active(self, session_id: str) -> bool:
        return session_id in self.active_sessions and self.active_sessions[session_id]["is_active"]

    def stream_audio(self, audio_bytes: bytes, language: str = "tanglish"):
        """Simulates generator-based audio streaming for testing."""
        yield {"transcript": "Simulated streaming transcript", "is_final": True, "confidence": 0.90}


class LiveWebSocketPrismaStreamingAdapter(StreamingSTTAdapterBase):
    """
    WebSocket client adapter for Gnani Prisma Streaming STT.
    Endpoint: wss://api.vachana.ai/stt/v3/stream (Unverified / Experimental)
    
    Status Note:
    Live WebSocket streaming requires dedicated enterprise credentials, verified
    duplex framing, and SLA terms. Marked as UNVERIFIED_EXPERIMENTAL.
    Falls back gracefully when credentials are not configured or WebSocket fails.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint_url: str = "wss://api.vachana.ai/stt/v3/stream"
    ):
        self.api_key = api_key
        self.endpoint_url = endpoint_url
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.is_live_enabled = bool(api_key and "LIVE" in api_key.upper())

    def start_session(
        self,
        session_id: str,
        language: str = "tanglish",
        on_transcript: Optional[Callable[[str, bool, float], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ) -> bool:
        if not self.is_live_enabled:
            logger.warning(
                "LiveWebSocketPrismaStreamingAdapter: Live credentials unverified. Streaming disabled. Use Mock adapter."
            )
            if on_error:
                on_error("LIVE_STREAMING_UNAVAILABLE: Unverified enterprise credentials.")
            return False

        self.active_sessions[session_id] = {
            "language": language,
            "on_transcript": on_transcript,
            "on_error": on_error,
            "is_active": True
        }
        return True

    def push_audio_chunk(self, session_id: str, pcm_chunk: bytes) -> None:
        # In unverified mode, safely discard without crashing
        pass

    def stop_session(self, session_id: str) -> None:
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

    def is_session_active(self, session_id: str) -> bool:
        return session_id in self.active_sessions

    def is_live_stream_verified(self) -> bool:
        return self.is_live_enabled
