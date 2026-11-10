"""
Integration tests for Frontend Voice Fixes in T2T DRIVE.
Verifies all 13 scenarios for Task 5 and Task 6 offline without live API calls.
"""

import io
import json
import base64
import random
import pytest
from pathlib import Path
from unittest.mock import patch

from app.voice.prisma_adapter import MockPrismaAdapter
from app.voice.timbre_adapter import MockTimbreAdapter
from app.voice.schemas import STTResponse

AUDIO_DIR = Path(__file__).resolve().parent / "test_audio"


class MultiAudioMockPrisma(MockPrismaAdapter):
    """Custom mock Prisma adapter returning specific transcripts per audio file."""
    def __init__(self):
        super().__init__()
        self.file_map = {
            "tamil": ("இன்னைக்கு நான் ஐநூறு ரூபாய் சம்பாதிச்சேன்", "ta-IN"),
            "tanglish": ("Inniku collection 1500, petrol 300, owner-ku 200 kuduthen", "tanglish"),
            "english": ("Today income is 800 rupees and diesel expense is 250", "en-IN"),
            "codmix": ("Tea and tiffin 60 rupees aachu", "codemix"),
            "expense": ("Diesel 350 rupees potten", "tanglish"),
            "cancel": ("Tea and snacks 120 rupees", "tanglish"),
        }

    def transcribe(self, audio_bytes, filename="audio.wav", language_hint="tanglish", mime_type="audio/wav"):
        if self.should_fail:
            return STTResponse(
                transcript="",
                provider="mock-prisma",
                processing_status="ERROR",
                error=self.failure_reason
            )
        for key, (transcript, lang) in self.file_map.items():
            if key in filename.lower():
                return STTResponse(
                    transcript=transcript,
                    detected_language=lang,
                    confidence=0.96,
                    provider="mock-prisma",
                    processing_status="SUCCESS"
                )
        return super().transcribe(audio_bytes, filename, language_hint, mime_type)


def get_driver_token(client):
    """Helper to authenticate driver and retrieve JWT bearer token with unique phone to avoid rate limit."""
    phone = f"98{random.randint(10000000, 99999999)}"
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


@pytest.fixture
def auth_fixture(client):
    """Creates a test driver JWT token for authenticated requests."""
    token, driver_id = get_driver_token(client)
    return {"Authorization": f"Bearer {token}"}, driver_id


@pytest.fixture
def auth_headers(auth_fixture):
    return auth_fixture[0]


@pytest.fixture
def driver_id(auth_fixture):
    return auth_fixture[1]


@pytest.fixture
def mock_voice_service(app):
    """Replaces voice service adapters with multi-audio mocks."""
    voice_svc = app.extensions["voice_service"]
    original_prisma = voice_svc.prisma
    original_timbre = voice_svc.timbre

    mock_prisma = MultiAudioMockPrisma()
    mock_timbre = MockTimbreAdapter()

    voice_svc.prisma = mock_prisma
    voice_svc.timbre = mock_timbre

    yield voice_svc, mock_prisma, mock_timbre

    voice_svc.prisma = original_prisma
    voice_svc.timbre = original_timbre


# ----------------------------------------------------------------------------
# Scenario 1: Successful Tamil Voice Request
# ----------------------------------------------------------------------------
def test_scenario_1_tamil_voice_request(client, auth_headers, mock_voice_service):
    wav_path = AUDIO_DIR / "stt_tamil.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {
        "audio": (io.BytesIO(audio_bytes), "stt_tamil.wav"),
        "lang": "ta-IN",
        "generate_tts": "true"
    }
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    assert body["transcript"] == "இன்னைக்கு நான் ஐநூறு ரூபாய் சம்பாதிச்சேன்"
    assert body["agent_message"] != ""
    assert body["reply_text"] == body["agent_message"]
    assert body["tts_status"] == "SUCCESS"
    assert body["tts_audio_base64"] is not None


# ----------------------------------------------------------------------------
# Scenario 2: Successful Tanglish Voice Request
# ----------------------------------------------------------------------------
def test_scenario_2_tanglish_voice_request(client, auth_headers, mock_voice_service):
    wav_path = AUDIO_DIR / "stt_tanglish.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {
        "audio": (io.BytesIO(audio_bytes), "stt_tanglish.wav"),
        "lang": "tanglish",
        "generate_tts": "true"
    }
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    assert "1500" in body["transcript"]
    assert body["agent_message"] != ""
    assert body["tts_status"] == "SUCCESS"
    assert body["tts_audio_base64"] is not None


# ----------------------------------------------------------------------------
# Scenario 3: Successful English Voice Request
# ----------------------------------------------------------------------------
def test_scenario_3_english_voice_request(client, auth_headers, mock_voice_service):
    wav_path = AUDIO_DIR / "stt_english.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {
        "audio": (io.BytesIO(audio_bytes), "stt_english.wav"),
        "lang": "en-IN",
        "generate_tts": "true"
    }
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    assert "800" in body["transcript"]
    assert body["agent_message"] != ""
    assert body["tts_status"] == "SUCCESS"


# ----------------------------------------------------------------------------
# Scenario 4: Code-mixed Voice Request
# ----------------------------------------------------------------------------
def test_scenario_4_codemixed_voice_request(client, auth_headers, mock_voice_service):
    wav_path = AUDIO_DIR / "stt_codmix.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {
        "audio": (io.BytesIO(audio_bytes), "stt_codmix.wav"),
        "lang": "codemix",
        "generate_tts": "true"
    }
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    assert "60" in body["transcript"]
    assert body["intent"] == "RECORD_EXPENSE"
    assert body["active_pending_action"] is not None


# ----------------------------------------------------------------------------
# Scenario 5: Assistant Response Appears with Robust Compatibility Fields
# ----------------------------------------------------------------------------
def test_scenario_5_response_compatibility_fields(client, auth_headers, mock_voice_service):
    wav_path = AUDIO_DIR / "stt_tamil.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {"audio": (io.BytesIO(audio_bytes), "stt_tamil.wav")}
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    # Verify both agent_message and reply_text are non-empty and identical
    assert "agent_message" in body
    assert "reply_text" in body
    assert body["agent_message"] == body["reply_text"]
    assert len(body["agent_message"]) > 0


# ----------------------------------------------------------------------------
# Scenario 6: Gnani Audio Decodable into Valid WAV
# ----------------------------------------------------------------------------
def test_scenario_6_audio_format_decodability(client, auth_headers, mock_voice_service):
    wav_path = AUDIO_DIR / "stt_tamil.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {"audio": (io.BytesIO(audio_bytes), "stt_tamil.wav")}
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    b64_audio = body.get("tts_audio_base64")
    assert b64_audio is not None
    decoded = base64.b64decode(b64_audio)
    # Check standard WAV RIFF header
    assert decoded[:4] == b"RIFF"
    assert decoded[8:12] == b"WAVE"


# ----------------------------------------------------------------------------
# Scenario 7: STT Failure Handling
# ----------------------------------------------------------------------------
def test_scenario_7_stt_failure(client, auth_headers, mock_voice_service):
    voice_svc, mock_prisma, _ = mock_voice_service
    mock_prisma.should_fail = True
    mock_prisma.failure_reason = "Speech recognition network timeout"

    wav_path = AUDIO_DIR / "stt_tamil.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {"audio": (io.BytesIO(audio_bytes), "stt_tamil.wav")}
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    assert body["transcript"] == ""
    assert body["tts_status"] == "SKIPPED"
    assert body["next_step"] == "IDLE"
    assert body["active_pending_action"] is None


# ----------------------------------------------------------------------------
# Scenario 8: TTS Failure with Text Response Preserved
# ----------------------------------------------------------------------------
def test_scenario_8_tts_failure_preserves_text_and_conversation(client, auth_headers, mock_voice_service, app):
    voice_svc, _, mock_timbre = mock_voice_service
    mock_timbre.should_fail = True
    mock_timbre.failure_reason = "TTS synthesis service unavailable"

    wav_path = AUDIO_DIR / "stt_tamil.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {"audio": (io.BytesIO(audio_bytes), "stt_tamil.wav")}
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    assert body["tts_status"] == "ERROR"
    assert body["agent_message"] != ""
    assert body["reply_text"] != ""

    # Verify messages were saved in MongoDB
    db = app.extensions["db"]
    session_id = body["session_id"]
    msgs = list(db.conversation_messages.find({"session_id": session_id}))
    assert len(msgs) >= 2


# ----------------------------------------------------------------------------
# Scenario 9: Pending Financial Confirmation & Ledger Isolation
# ----------------------------------------------------------------------------
def test_scenario_9_pending_confirmation_and_ledger_isolation(client, auth_headers, mock_voice_service, app, driver_id):
    db = app.extensions["db"]
    initial_tx = db.transactions.count_documents({"driver_id": driver_id})

    wav_path = AUDIO_DIR / "stt_tanglish.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    # 1. Voice Turn proposes expense
    data = {"audio": (io.BytesIO(audio_bytes), "expense_test.wav")}
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()["data"]

    pending_act = body.get("active_pending_action")
    assert pending_act is not None
    pending_id = pending_act["pending_action_id"]

    # 2. Verify ledger was NOT mutated
    assert db.transactions.count_documents({"driver_id": driver_id}) == initial_tx

    # 3. Explicit confirmation
    confirm_res = client.post("/api/agent/confirm", json={"pending_id": pending_id, "yes_or_no": True}, headers=auth_headers)
    assert confirm_res.status_code == 200

    # 4. Verify exactly 1 transaction was logged
    assert db.transactions.count_documents({"driver_id": driver_id}) == initial_tx + 1


# ----------------------------------------------------------------------------
# Scenario 10: User Cancellation
# ----------------------------------------------------------------------------
def test_scenario_10_user_cancellation(client, auth_headers, mock_voice_service, app, driver_id):
    db = app.extensions["db"]
    initial_tx = db.transactions.count_documents({"driver_id": driver_id})

    wav_path = AUDIO_DIR / "stt_tanglish.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    # 1. Voice Turn
    data = {"audio": (io.BytesIO(audio_bytes), "cancel_test.wav")}
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    body = res.get_json()["data"]
    pending_id = body["active_pending_action"]["pending_action_id"]

    # 2. Explicit Cancel
    cancel_res = client.post("/api/agent/confirm", json={"pending_id": pending_id, "yes_or_no": False}, headers=auth_headers)
    assert cancel_res.status_code == 200

    # 3. Zero transactions created
    assert db.transactions.count_documents({"driver_id": driver_id}) == initial_tx
    # Pending action marked CANCELLED
    pending_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert pending_doc["status"] == "CANCELLED"


# ----------------------------------------------------------------------------
# Scenario 11: Authentication Failure
# ----------------------------------------------------------------------------
def test_scenario_11_unauthenticated_request_rejected(client):
    wav_path = AUDIO_DIR / "stt_tamil.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {"audio": (io.BytesIO(audio_bytes), "stt_tamil.wav")}
    res = client.post("/api/voice/chat", data=data, content_type="multipart/form-data")
    assert res.status_code == 401
    err = res.get_json()["error"]
    assert err["code"] == "UNAUTHORIZED"


# ----------------------------------------------------------------------------
# Scenario 12: MongoDB Failure Handling
# ----------------------------------------------------------------------------
def test_scenario_12_mongodb_failure(client, auth_headers, mock_voice_service, app):
    db = app.extensions["db"]
    wav_path = AUDIO_DIR / "stt_tamil.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    data = {"audio": (io.BytesIO(audio_bytes), "stt_tamil.wav")}

    with patch.object(db.conversation_messages, "insert_one", side_effect=Exception("Simulated DB Connection Error")):
        res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
        assert res.status_code == 500
        err = res.get_json()["error"]
        assert err["code"] == "VOICE_PROCESSING_ERROR"


# ----------------------------------------------------------------------------
# Scenario 13: Repeated Submission / Idempotency Prevention
# ----------------------------------------------------------------------------
def test_scenario_13_repeated_submission_prevention(client, auth_headers, mock_voice_service, app, driver_id):
    db = app.extensions["db"]
    initial_tx = db.transactions.count_documents({"driver_id": driver_id})

    wav_path = AUDIO_DIR / "stt_tanglish.wav"
    audio_bytes = wav_path.read_bytes() if wav_path.exists() else b"RIFF....WAVEfmt " + b"\x00" * 200

    # 1. Voice Turn
    data = {"audio": (io.BytesIO(audio_bytes), "expense_test.wav")}
    res = client.post("/api/voice/chat", data=data, headers=auth_headers, content_type="multipart/form-data")
    body = res.get_json()["data"]
    pending_id = body["active_pending_action"]["pending_action_id"]

    # 2. First confirmation
    res1 = client.post("/api/agent/confirm", json={"pending_id": pending_id, "yes_or_no": True}, headers=auth_headers)
    assert res1.status_code == 200
    assert db.transactions.count_documents({"driver_id": driver_id}) == initial_tx + 1

    # 3. Repeated / Duplicate confirmation (replay attack or double click)
    res2 = client.post("/api/agent/confirm", json={"pending_id": pending_id, "yes_or_no": True}, headers=auth_headers)
    # Should succeed idempotently or return existing result without creating a 2nd transaction
    assert db.transactions.count_documents({"driver_id": driver_id}) == initial_tx + 1
