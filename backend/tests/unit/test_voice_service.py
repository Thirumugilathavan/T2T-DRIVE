"""
Unit tests for Voice Service in T2T DRIVE Voice Pipeline.
Tests integration between Audio Validator, Preprocessor, Prisma STT,
Phase 3 Conversational Agent, and Timbre TTS.
"""

from unittest.mock import MagicMock
from app.voice.voice_service import VoiceService
from app.voice.prisma_adapter import MockPrismaAdapter
from app.voice.timbre_adapter import MockTimbreAdapter
from app.voice.audio_validator import AudioValidator
from app.voice.audio_preprocessor import AudioPreprocessor
from tests.unit.test_audio_preprocessor import make_test_wav


def test_voice_service_transcribe_success():
    prisma = MockPrismaAdapter(default_transcript="diesel 450 potten")
    timbre = MockTimbreAdapter()
    agent = MagicMock()

    service = VoiceService(
        prisma_adapter=prisma,
        timbre_adapter=timbre,
        agent_service=agent
    )

    audio_bytes = make_test_wav(duration=1.0, sample_rate=16000, amplitude=6000)
    res = service.transcribe_audio(audio_bytes, filename="voice.wav", language_hint="tanglish")

    assert res.processing_status == "SUCCESS"
    assert res.transcript == "diesel 450 potten"
    assert res.duration_seconds == 1.0


def test_voice_service_transcribe_validation_rejection():
    prisma = MockPrismaAdapter()
    timbre = MockTimbreAdapter()
    agent = MagicMock()

    service = VoiceService(prisma_adapter=prisma, timbre_adapter=timbre, agent_service=agent)
    res = service.transcribe_audio(b"", filename="voice.wav")

    assert res.processing_status == "ERROR"
    assert "empty" in res.error.lower()


def test_voice_service_process_voice_turn_success():
    prisma = MockPrismaAdapter(default_transcript="diesel 400 potten")
    timbre = MockTimbreAdapter()

    agent = MagicMock()
    agent.process_message.return_value = {
        "session_id": "SESS_TEST_1",
        "message": "Vandi TN-01-AB-1234-kku ₹400.00 pathivu seiyava?",
        "voice_text": "Vandi TN-01-AB-1234-kku roobai 400 pathivu seiyava?",
        "intent": "RECORD_EXPENSE",
        "slots": {"amount": 400.0, "category": "FUEL"},
        "next_step": "AWAITING_CONFIRMATION",
        "active_pending_action": {"pending_action_id": "PEND_100"}
    }

    service = VoiceService(
        prisma_adapter=prisma,
        timbre_adapter=timbre,
        agent_service=agent
    )

    audio_bytes = make_test_wav(duration=1.0, sample_rate=16000, amplitude=6000)
    turn_res = service.process_voice_turn(
        driver_id="DRV_123",
        audio_bytes=audio_bytes,
        filename="command.wav",
        language_hint="tanglish"
    )

    assert turn_res.transcript == "diesel 400 potten"
    assert turn_res.intent == "RECORD_EXPENSE"
    assert turn_res.next_step == "AWAITING_CONFIRMATION"
    assert turn_res.active_pending_action["pending_action_id"] == "PEND_100"
    assert turn_res.tts_status == "SUCCESS"
    assert turn_res.tts_audio_base64 is not None

    agent.process_message.assert_called_once_with(
        driver_id="DRV_123",
        message="diesel 400 potten",
        session_id=None,
        language="tanglish"
    )


def test_voice_service_stt_failure_prevents_agent_invocation():
    prisma = MockPrismaAdapter()
    prisma.should_fail = True
    prisma.failure_reason = "Speech recognition network timeout"

    timbre = MockTimbreAdapter()
    agent = MagicMock()

    service = VoiceService(prisma_adapter=prisma, timbre_adapter=timbre, agent_service=agent)
    audio_bytes = make_test_wav(duration=1.0, sample_rate=16000, amplitude=6000)

    turn_res = service.process_voice_turn(
        driver_id="DRV_123",
        audio_bytes=audio_bytes,
        filename="cmd.wav"
    )

    assert turn_res.transcript == ""
    assert "network timeout" in turn_res.error.lower()
    # Agent was NOT invoked! No financial operation possible!
    agent.process_message.assert_not_called()


def test_voice_service_tts_failure_preserves_text_response():
    prisma = MockPrismaAdapter(default_transcript="inniku kanaku sollu")
    timbre = MockTimbreAdapter()
    timbre.should_fail = True  # Simulate Timbre failure

    agent = MagicMock()
    agent.process_message.return_value = {
        "session_id": "SESS_TEST_2",
        "message": "Inniku varumanam ₹1200, selavu ₹400.",
        "voice_text": "Inniku varumanam roobai 1200.",
        "intent": "GET_SUMMARY"
    }

    service = VoiceService(prisma_adapter=prisma, timbre_adapter=timbre, agent_service=agent)
    audio_bytes = make_test_wav(duration=1.0, sample_rate=16000, amplitude=6000)

    turn_res = service.process_voice_turn(
        driver_id="DRV_123",
        audio_bytes=audio_bytes,
        filename="summary.wav"
    )

    assert turn_res.transcript == "inniku kanaku sollu"
    assert "Inniku varumanam ₹1200" in turn_res.agent_message
    assert turn_res.tts_status == "ERROR"
    assert turn_res.tts_audio_base64 is None  # Graceful fallback to text
