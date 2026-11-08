"""
Voice REST API Routes for T2T DRIVE.
Exposes endpoints for audio upload, speech-to-text, end-to-end voice co-pilot chat,
and text-to-speech synthesis with JWT authentication.
Supports both /api/voice and /api/speech prefixes for full frontend compatibility.
"""

from flask import Blueprint, request, current_app, g, send_file, Response
import io

from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth
from app.voice.schemas import TTSRequest

voice_bp = Blueprint("voice", __name__, url_prefix="/api/voice")
speech_bp = Blueprint("speech", __name__, url_prefix="/api/speech")


def _handle_transcribe_request():
    """Helper implementing audio transcription logic."""
    audio_file = request.files.get("audio") or request.files.get("file") or request.files.get("audio_file")
    if not audio_file:
        return error_response(
            code="MISSING_AUDIO_FILE",
            message="No audio file provided. Pass audio file in 'audio' or 'file' field.",
            status_code=400
        )

    filename = audio_file.filename or "audio.wav"
    audio_bytes = audio_file.read()

    lang = request.form.get("lang") or request.form.get("language") or "tanglish"
    voice_svc = current_app.extensions["voice_service"]

    stt_res = voice_svc.transcribe_audio(
        audio_bytes=audio_bytes,
        filename=filename,
        language_hint=lang
    )

    if stt_res.processing_status == "ERROR":
        return error_response(
            code="TRANSCRIPTION_FAILED",
            message=stt_res.error or "Failed to transcribe audio.",
            status_code=400
        )

    return success_response(stt_res.model_dump())


def _handle_speak_request():
    """Helper implementing text-to-speech synthesis logic."""
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    if not text:
        return error_response(
            code="MISSING_TEXT",
            message="Field 'text' is required and must not be empty.",
            status_code=400
        )

    lang = body.get("lang") or body.get("language") or "ta-IN"
    voice = body.get("voice", "Kaveri")
    speed = float(body.get("speed", 1.0))

    voice_svc = current_app.extensions["voice_service"]
    tts_res = voice_svc.synthesize_speech(
        text=text,
        language=lang,
        voice=voice,
        speed=speed
    )

    if tts_res.processing_status != "SUCCESS":
        return error_response(
            code="TTS_FAILED",
            message=tts_res.error or "Text-to-speech synthesis failed.",
            status_code=500
        )

    # Return raw binary audio if format=binary query param or Accept: audio/wav is requested
    binary_requested = request.args.get("format") == "binary" or "audio" in request.headers.get("Accept", "")
    if binary_requested and tts_res.audio_bytes:
        return Response(tts_res.audio_bytes, mimetype=tts_res.content_type)

    return success_response({
        "audio_base64": tts_res.audio_base64,
        "content_type": tts_res.content_type,
        "provider": tts_res.provider,
        "status": tts_res.processing_status
    })


# ============================================================================
# PRIMARY VOICE ENDPOINTS (/api/voice)
# ============================================================================

@voice_bp.route("/transcribe", methods=["POST"])
@require_auth
def transcribe():
    """Transcribes an uploaded audio file via Gnani Prisma STT."""
    return _handle_transcribe_request()


@voice_bp.route("/chat", methods=["POST"])
@require_auth
def voice_chat():
    """
    Primary end-to-end Voice Co-Pilot endpoint:
    1. Transcribes audio via Gnani Prisma.
    2. Feeds transcript to Phase 3 LangGraph Conversational Agent.
    3. Enforces Confirmation Firewall & Phase 2 Financial Ledger.
    4. Generates speech output via Gnani Timbre TTS.
    """
    audio_file = request.files.get("audio") or request.files.get("file") or request.files.get("audio_file")
    if not audio_file:
        return error_response(
            code="MISSING_AUDIO_FILE",
            message="No audio file provided. Pass audio file in 'audio' or 'file' field.",
            status_code=400
        )

    filename = audio_file.filename or "audio.wav"
    audio_bytes = audio_file.read()

    session_id = request.form.get("session_id")
    lang = request.form.get("lang") or request.form.get("language") or "tanglish"
    generate_tts_str = request.form.get("generate_tts", "true").lower()
    generate_tts = generate_tts_str in ("true", "1", "yes")

    voice_svc = current_app.extensions["voice_service"]
    try:
        turn_response = voice_svc.process_voice_turn(
            driver_id=g.driver_id,
            audio_bytes=audio_bytes,
            filename=filename,
            session_id=session_id,
            language_hint=lang,
            generate_tts=generate_tts
        )
        return success_response(turn_response.model_dump())
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED_SESSION", message=str(pe), status_code=403)
    except Exception as e:
        current_app.logger.error("Voice chat turn failed for driver %s: %s", g.driver_id, e)
        return error_response(code="VOICE_PROCESSING_ERROR", message=str(e), status_code=500)


@voice_bp.route("/speak", methods=["POST"])
@require_auth
def speak():
    """Synthesizes text into speech audio via Gnani Timbre TTS."""
    return _handle_speak_request()


@voice_bp.route("/capabilities", methods=["GET"])
def capabilities():
    """Public capability discovery endpoint (no credentials leaked)."""
    cfg = current_app.config
    mode = cfg.get("VOICE_PROVIDER_MODE", "mock")
    prisma_live = bool(cfg.get("GNANI_API_KEY") and cfg.get("GNANI_PRISMA_ENABLED"))
    timbre_live = bool(cfg.get("GNANI_API_KEY") and cfg.get("GNANI_TIMBRE_ENABLED"))

    return success_response({
        "provider_mode": mode,
        "prisma_stt": {
            "status": "LIVE" if prisma_live else "MOCK",
            "model": "prisma-v3.0",
            "supported_languages": ["ta-IN", "en-IN", "indic-auto", "tanglish"]
        },
        "timbre_tts": {
            "status": "LIVE" if timbre_live else "MOCK",
            "model": "timbre-v2.5",
            "voices": ["Kaveri", "Nalini", "Shivani"]
        },
        "audio_constraints": {
            "max_upload_mb": cfg.get("VOICE_MAX_UPLOAD_MB", 10),
            "max_duration_seconds": cfg.get("VOICE_MAX_DURATION_SECONDS", 60),
            "supported_formats": ["wav", "mp3", "ogg", "webm", "m4a", "aac"]
        }
    })


# ============================================================================
# COMPATIBILITY ALIASES (/api/speech for existing frontend/js/api.js)
# ============================================================================

@speech_bp.route("/transcribe", methods=["POST"])
@require_auth
def speech_transcribe_alias():
    """Alias for /api/speech/transcribe."""
    return _handle_transcribe_request()


@speech_bp.route("/speak", methods=["POST"])
@require_auth
def speech_speak_alias():
    """Alias for /api/speech/speak."""
    return _handle_speak_request()
