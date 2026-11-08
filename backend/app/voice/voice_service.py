"""
Voice Service for T2T DRIVE.
Coordinates audio validation, preprocessing, Gnani Prisma STT,
the Phase 3 conversational agent, and Gnani Timbre TTS playback.
Enforces the Confirmation Firewall: speech never writes directly to the ledger.
"""

import logging
from typing import Optional, Dict, Any, Tuple

from app.voice.schemas import (
    AudioValidationResult,
    STTResponse,
    TTSResponse,
    VoiceTurnResponse
)
from app.voice.audio_validator import AudioValidator, AudioValidationError
from app.voice.audio_preprocessor import AudioPreprocessor
from app.voice.prisma_adapter import PrismaAdapterBase
from app.voice.timbre_adapter import TimbreAdapterBase

logger = logging.getLogger("t2t_drive.voice_service")


class VoiceService:
    """
    Unified voice orchestration service for T2T DRIVE.
    """

    def __init__(
        self,
        prisma_adapter: PrismaAdapterBase,
        timbre_adapter: TimbreAdapterBase,
        agent_service,
        validator: Optional[AudioValidator] = None,
        preprocessor: Optional[AudioPreprocessor] = None
    ):
        self.prisma = prisma_adapter
        self.timbre = timbre_adapter
        self.agent = agent_service
        self.validator = validator or AudioValidator()
        self.preprocessor = preprocessor or AudioPreprocessor()

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language_hint: str = "indic-auto"
    ) -> STTResponse:
        """
        Validates, inspects, and transcribes incoming audio data.
        """
        # 1. Validation
        val_result = self.validator.validate_bytes(audio_bytes, client_filename=filename)
        if not val_result.is_valid:
            logger.warning("Audio validation failed: %s", val_result.error)
            return STTResponse(
                transcript="",
                provider="validator",
                processing_status="ERROR",
                error=val_result.error
            )

        # 2. Preprocessing & Inspection
        prep_result = self.preprocessor.inspect_and_preprocess(
            audio_bytes,
            audio_format=val_result.format
        )

        if not prep_result["is_processable"]:
            logger.warning("Audio preprocessing rejected: %s", prep_result["error"])
            return STTResponse(
                transcript="",
                provider="preprocessor",
                processing_status="ERROR" if not prep_result["is_silent"] else "EMPTY",
                duration_seconds=prep_result["duration_seconds"],
                error=prep_result["error"]
            )

        # 3. Call Prisma STT Adapter
        stt_response = self.prisma.transcribe(
            audio_bytes=prep_result["audio_bytes"],
            filename=filename,
            language_hint=language_hint,
            mime_type=val_result.mime_type
        )
        stt_response.duration_seconds = prep_result["duration_seconds"]
        return stt_response

    def synthesize_speech(
        self,
        text: str,
        language: str = "ta-IN",
        voice: str = "Kaveri",
        speed: float = 1.0
    ) -> TTSResponse:
        """
        Converts text to speech using Timbre.
        """
        if not text or not text.strip():
            return TTSResponse(
                provider="timbre",
                processing_status="ERROR",
                error="Cannot synthesize empty text."
            )

        return self.timbre.synthesize(
            text=text,
            language=language,
            voice=voice,
            speed=speed
        )

    def process_voice_turn(
        self,
        driver_id: str,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        session_id: Optional[str] = None,
        language_hint: str = "tanglish",
        generate_tts: bool = True
    ) -> VoiceTurnResponse:
        """
        Complete end-to-end voice co-pilot workflow:
        1. Transcribe audio via Prisma STT.
        2. Feed transcript to Phase 3 LangGraph agent.
        3. Enforce confirmation firewall & financial services.
        4. Synthesize agent response via Timbre TTS.
        """
        # 1. Transcribe audio
        stt_res = self.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            language_hint=language_hint
        )

        if stt_res.processing_status != "SUCCESS" or not stt_res.transcript:
            logger.info("STT unsuccessful (%s): %s", stt_res.processing_status, stt_res.error)
            return VoiceTurnResponse(
                session_id=session_id or "new_session",
                transcript="",
                detected_language=stt_res.detected_language,
                confidence=stt_res.confidence,
                stt_provider=stt_res.provider,
                agent_message=stt_res.error or "Voice could not be recognized. Please try speaking again.",
                agent_voice_text=stt_res.error or "Voice not recognized.",
                next_step="IDLE",
                tts_status="SKIPPED",
                error=stt_res.error
            )

        # 2. Invoke Phase 3 Agent with authenticated driver identity
        agent_result = self.agent.process_message(
            driver_id=driver_id,
            message=stt_res.transcript,
            session_id=session_id,
            language=stt_res.detected_language or language_hint
        )

        # 3. Text-to-Speech synthesis for agent response
        tts_base64 = None
        tts_provider = None
        tts_status = "SKIPPED"

        voice_text = agent_result.get("voice_text") or agent_result.get("message")
        if generate_tts and voice_text:
            tts_res = self.synthesize_speech(
                text=voice_text,
                language="ta-IN" if agent_result.get("language") in ("tamil", "tanglish") else "en-IN"
            )
            if tts_res.processing_status == "SUCCESS":
                tts_base64 = tts_res.audio_base64
                tts_provider = tts_res.provider
                tts_status = "SUCCESS"
            else:
                logger.warning("TTS generation failed (falling back to text): %s", tts_res.error)
                tts_status = "ERROR"

        return VoiceTurnResponse(
            session_id=agent_result.get("session_id", session_id or ""),
            transcript=stt_res.transcript,
            detected_language=stt_res.detected_language,
            confidence=stt_res.confidence,
            stt_provider=stt_res.provider,
            agent_message=agent_result.get("message", ""),
            agent_voice_text=agent_result.get("voice_text", ""),
            intent=agent_result.get("intent"),
            slots=agent_result.get("slots", {}),
            next_step=agent_result.get("next_step", "IDLE"),
            active_pending_action=agent_result.get("active_pending_action"),
            execution_result=agent_result.get("execution_result"),
            tts_audio_base64=tts_base64,
            tts_provider=tts_provider,
            tts_status=tts_status,
            error=agent_result.get("error")
        )
