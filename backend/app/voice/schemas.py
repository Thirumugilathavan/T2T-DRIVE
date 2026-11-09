"""
Pydantic schemas and dataclasses for T2T DRIVE Voice Pipeline.
Defines schemas for audio validation, STT transcriptions, TTS synthesis,
audio quality metrics, and unified voice conversational interactions.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class AudioValidationResult(BaseModel):
    """Result of audio file security and format validation."""
    is_valid: bool
    format: str  # wav, mp3, ogg, webm, m4a, aac
    mime_type: str
    file_size_bytes: int
    duration_seconds: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    error: Optional[str] = None


class STTResponse(BaseModel):
    """Normalized response from Speech-to-Text provider (Prisma or Mock)."""
    transcript: str
    detected_language: str = "tanglish"
    confidence: Optional[float] = None
    provider: str  # "gnani_prisma" or "mock_prisma"
    processing_status: str = "SUCCESS"  # SUCCESS, EMPTY, ERROR
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    
    # Phase 6 Acoustic Intelligence Enrichments
    audio_quality: Optional[str] = None  # GOOD, MODERATE, POOR, VERY_POOR, UNUSABLE
    snr_db: Optional[float] = None
    noise_type: Optional[str] = None
    preprocessing_applied: Optional[List[str]] = None
    analysis_report: Optional[Dict[str, Any]] = None


class TTSRequest(BaseModel):
    """Input parameters for Text-to-Speech synthesis (Timbre or Mock)."""
    text: str = Field(..., min_length=1, max_length=2000)
    language: str = Field(default="ta-IN")  # ta-IN, en-IN, or tanglish
    voice: str = Field(default="Kaveri")
    format: str = Field(default="wav")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class TTSResponse(BaseModel):
    """Normalized response from Text-to-Speech provider (Timbre or Mock)."""
    audio_bytes: Optional[bytes] = None
    audio_base64: Optional[str] = None
    content_type: str = "audio/wav"
    provider: str  # "gnani_timbre" or "mock_timbre"
    processing_status: str = "SUCCESS"  # SUCCESS, ERROR
    error: Optional[str] = None


class VoiceTurnResponse(BaseModel):
    """Unified response for an end-to-end voice conversational turn."""
    session_id: str
    transcript: str
    detected_language: str
    confidence: Optional[float] = None
    stt_provider: str
    agent_message: str
    agent_voice_text: str
    intent: Optional[str] = None
    slots: Dict[str, Any] = Field(default_factory=dict)
    next_step: str = "IDLE"
    active_pending_action: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None
    tts_audio_base64: Optional[str] = None
    tts_provider: Optional[str] = None
    tts_status: str = "SKIPPED"  # SUCCESS, ERROR, SKIPPED
    error: Optional[str] = None

    # Phase 6 Noise Intelligence Enrichments
    audio_quality: Optional[str] = None
    noise_classification: Optional[Dict[str, Any]] = None
    snr_estimate: Optional[Dict[str, Any]] = None
    vad_result: Optional[Dict[str, Any]] = None
    preprocessing: Optional[Dict[str, Any]] = None
    speech_confidence: Optional[Dict[str, Any]] = None
    retry_advisory: Optional[Dict[str, Any]] = None
    clarification_required: bool = False
