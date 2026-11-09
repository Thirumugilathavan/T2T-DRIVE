"""
Voice Service for T2T DRIVE.
Coordinates audio validation, preprocessing, Gnani Prisma STT,
the Phase 3 conversational agent, and Gnani Timbre TTS playback.
Enforces the Confirmation Firewall: speech never writes directly to the ledger.
Phase 6: Enriched with advanced noise intelligence, SNR estimation, VAD,
adaptive filtering, and multi-dimensional speech confidence.
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
from app.voice.noise.noise_service import NoiseService, AudioAnalysisReport
from app.voice.noise.snr_estimator import SNREstimate, SNRQuality
from app.voice.noise.noise_classifier import NoiseClassification, NoiseType
from app.voice.noise.vad import VADResult
from app.voice.noise.speech_confidence import ConfidenceDirective

logger = logging.getLogger("t2t_drive.voice_service")


class VoiceService:
    """
    Unified voice orchestration service for T2T DRIVE.
    Integrates Gnani Prisma STT, Gnani Timbre TTS, LangGraph agent, and Phase 6 Noise Intelligence.
    """

    def __init__(
        self,
        prisma_adapter: PrismaAdapterBase,
        timbre_adapter: TimbreAdapterBase,
        agent_service,
        validator: Optional[AudioValidator] = None,
        preprocessor: Optional[AudioPreprocessor] = None,
        noise_service: Optional[NoiseService] = None
    ):
        self.prisma = prisma_adapter
        self.timbre = timbre_adapter
        self.agent = agent_service
        self.validator = validator or AudioValidator()
        self.preprocessor = preprocessor or AudioPreprocessor()
        self.noise_service = noise_service or NoiseService()

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language_hint: str = "indic-auto"
    ) -> STTResponse:
        """
        Validates, inspects, adaptively filters, and transcribes incoming audio data.
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

        # 2. Basic Preprocessing & Inspection
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

        # 3. Phase 6 Noise Intelligence & Adaptive Preprocessing
        optimal_bytes, analysis_report, prep_result_noise = self.noise_service.prepare_for_stt(
            audio_bytes=prep_result["audio_bytes"],
            audio_format=val_result.format,
            language=language_hint
        )

        # 4. If noise intelligence determines audio is unusable (e.g. pure silence)
        if not analysis_report.should_proceed_to_stt:
            logger.info("Noise pre-flight rejected audio: %s", analysis_report.rejection_reason)
            return STTResponse(
                transcript="",
                provider="noise_service",
                processing_status="EMPTY" if analysis_report.overall_quality == "UNUSABLE" else "ERROR",
                duration_seconds=prep_result["duration_seconds"],
                error=analysis_report.rejection_reason or "Audio quality insufficient for recognition.",
                audio_quality=analysis_report.overall_quality,
                snr_db=analysis_report.snr.get("snr_db"),
                noise_type=analysis_report.noise_classification.get("primary_category"),
                analysis_report=analysis_report.to_dict()
            )

        # 5. Call Prisma STT Adapter with optimal audio bytes
        stt_response = self.prisma.transcribe(
            audio_bytes=optimal_bytes,
            filename=filename,
            language_hint=language_hint,
            mime_type=val_result.mime_type
        )
        stt_response.duration_seconds = prep_result["duration_seconds"]
        stt_response.audio_quality = analysis_report.overall_quality
        stt_response.snr_db = analysis_report.snr.get("snr_db")
        stt_response.noise_type = analysis_report.noise_classification.get("primary_category")
        stt_response.preprocessing_applied = (
            prep_result_noise.applied_transformations if prep_result_noise else []
        )
        stt_response.analysis_report = analysis_report.to_dict()
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
        1. Transcribe audio via Prisma STT (with noise pre-flight).
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

        rep = stt_res.analysis_report or {}
        retry_adv = rep.get("retry_advisory")

        if stt_res.processing_status != "SUCCESS" or not stt_res.transcript:
            logger.info("STT unsuccessful (%s): %s", stt_res.processing_status, stt_res.error)
            msg = (
                (retry_adv.get("display_message") if retry_adv else None) or
                stt_res.error or
                "Voice could not be recognized. Please try speaking again."
            )
            voice_txt = (
                (retry_adv.get("voice_prompt") if retry_adv else None) or
                stt_res.error or
                "Voice not recognized."
            )

            return VoiceTurnResponse(
                session_id=session_id or "new_session",
                transcript="",
                detected_language=stt_res.detected_language,
                confidence=stt_res.confidence,
                stt_provider=stt_res.provider,
                agent_message=msg,
                agent_voice_text=voice_txt,
                next_step="IDLE",
                tts_status="SKIPPED",
                error=stt_res.error,
                audio_quality=stt_res.audio_quality,
                noise_classification=rep.get("noise_classification"),
                snr_estimate=rep.get("snr"),
                vad_result=rep.get("vad"),
                preprocessing=rep.get("preprocessing"),
                retry_advisory=retry_adv
            )

        # 2. Invoke Phase 3 Agent with authenticated driver identity
        agent_result = self.agent.process_message(
            driver_id=driver_id,
            message=stt_res.transcript,
            session_id=session_id,
            language=stt_res.detected_language or language_hint
        )

        # 3. Multi-dimensional confidence evaluation
        speech_conf_dict = None
        clarification_req = False
        if rep:
            try:
                speech_conf = self.noise_service.confidence_evaluator.evaluate(
                    noise_class=NoiseClassification(
                        primary_category=NoiseType(rep["noise_classification"]["primary_category"]),
                        secondary_categories=[
                            NoiseType(c) for c in rep["noise_classification"].get("secondary_categories", [])
                        ],
                        confidence=rep["noise_classification"].get("confidence", 0.8),
                        supporting_metrics=rep["noise_classification"].get("supporting_metrics", {}),
                        is_reliable=rep["noise_classification"].get("is_reliable", True),
                        suggested_strategy=rep["noise_classification"].get("suggested_strategy", "PROCEED")
                    ),
                    snr_est=SNREstimate(
                        snr_db=rep["snr"].get("snr_db"),
                        quality=SNRQuality(rep["snr"].get("quality", "UNKNOWN")),
                        speech_level_dbfs=rep["snr"].get("speech_level_dbfs"),
                        noise_floor_dbfs=rep["snr"].get("noise_floor_dbfs"),
                        estimation_method=rep["snr"].get("estimation_method", "heuristic"),
                        is_reliable=rep["snr"].get("is_reliable", True)
                    ),
                    vad_res=VADResult(
                        has_speech=rep["vad"].get("has_speech", True),
                        total_duration_seconds=rep["vad"].get("total_duration_seconds", 0.0),
                        speech_duration_seconds=rep["vad"].get("speech_duration_seconds", 0.0),
                        silence_duration_seconds=rep["vad"].get("silence_duration_seconds", 0.0),
                        speech_percentage=rep["vad"].get("speech_percentage", 0.0),
                        leading_silence_seconds=rep["vad"].get("leading_silence_seconds", 0.0),
                        trailing_silence_seconds=rep["vad"].get("trailing_silence_seconds", 0.0),
                        max_pause_seconds=rep["vad"].get("max_pause_seconds", 0.0),
                        num_speech_segments=rep["vad"].get("num_speech_segments", 0),
                        speech_segments=[],
                        is_reliable=rep["vad"].get("is_reliable", True),
                        confidence=rep["vad"].get("confidence", 0.9)
                    ),
                    intent=agent_result.get("intent"),
                    intent_confidence=float(agent_result.get("confidence", 0.8) or 0.8),
                    slots=agent_result.get("slots", {}),
                    missing_slots=agent_result.get("missing_slots", []),
                    stt_confidence=stt_res.confidence
                )
                speech_conf_dict = speech_conf.to_dict()
                clarification_req = speech_conf.directive == ConfidenceDirective.ASK_FOR_CLARIFICATION
            except Exception as ce:
                logger.warning("Multi-dimensional confidence evaluation skipped: %s", ce)

        # 4. Text-to-Speech synthesis for agent response
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
            error=agent_result.get("error"),
            audio_quality=stt_res.audio_quality,
            noise_classification=rep.get("noise_classification"),
            snr_estimate=rep.get("snr"),
            vad_result=rep.get("vad"),
            preprocessing=rep.get("preprocessing"),
            speech_confidence=speech_conf_dict,
            retry_advisory=retry_adv,
            clarification_required=clarification_req
        )
