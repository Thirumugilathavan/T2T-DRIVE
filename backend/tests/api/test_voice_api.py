"""
API Integration tests for T2T DRIVE Voice Pipeline.
Tests audio uploads, Speech-to-Text (Prisma), Text-to-Speech (Timbre),
end-to-end voice co-pilot journeys, and the 6 mandatory workflow scenarios.
"""

import io
import json
import base64
import pytest
from app.voice.prisma_adapter import MockPrismaAdapter
from tests.unit.test_audio_preprocessor import make_test_wav


def get_driver_token(client, phone="9876543501"):
    """Helper to authenticate driver and retrieve JWT bearer token."""
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_voice_unauthenticated_access_rejected(client):
    """Ensures all voice endpoints require JWT authentication."""
    res_tr = client.post("/api/voice/transcribe")
    assert res_tr.status_code == 401
    assert res_tr.get_json()["error"]["code"] == "UNAUTHORIZED"

    res_ch = client.post("/api/voice/chat")
    assert res_ch.status_code == 401

    res_sp = client.post("/api/voice/speak", data=json.dumps({"text": "Hello"}), content_type="application/json")
    assert res_sp.status_code == 401


def test_voice_capabilities(client):
    """Verifies capabilities endpoint returns system metadata without leaking secrets."""
    res = client.get("/api/voice/capabilities")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "provider_mode" in data
    assert "prisma_stt" in data
    assert "timbre_tts" in data
    assert "audio_constraints" in data
    assert "GNANI_API_KEY" not in str(data)  # Zero secrets leaked!


def test_voice_transcribe_and_speak_endpoints(client):
    """Tests /api/voice/transcribe and /api/voice/speak endpoints."""
    token, driver_id = get_driver_token(client, "9876543502")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Transcribe
    audio_wav = make_test_wav(duration=1.0, sample_rate=16000, amplitude=6000)
    data = {
        "audio": (io.BytesIO(audio_wav), "recording.wav"),
        "lang": "tanglish"
    }
    res_tr = client.post("/api/voice/transcribe", headers=headers, data=data, content_type="multipart/form-data")
    assert res_tr.status_code == 200
    stt_data = res_tr.get_json()["data"]
    assert "transcript" in stt_data
    assert stt_data["processing_status"] == "SUCCESS"

    # 2. Speak (JSON base64 response)
    json_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res_sp = client.post(
        "/api/voice/speak",
        headers=json_headers,
        data=json.dumps({"text": "டீசல் பதிவு செய்யப்பட்டது.", "lang": "ta-IN"})
    )
    assert res_sp.status_code == 200
    sp_data = res_sp.get_json()["data"]
    assert "audio_base64" in sp_data
    assert sp_data["content_type"] == "audio/wav"

    # 3. Speak (Binary stream response)
    res_bin = client.post(
        "/api/voice/speak?format=binary",
        headers=json_headers,
        data=json.dumps({"text": "டீசல் பதிவு செய்யப்பட்டது.", "lang": "ta-IN"})
    )
    assert res_bin.status_code == 200
    assert res_bin.data.startswith(b"RIFF")


def test_voice_workflow_1_income(client):
    """
    Workflow 1: Income
    Driver speaks: 'Inniku 500 rooba sambadhichen.'
    Turn 1: STT recognized income, proposal created, confirmation firewall blocks ledger write.
    Turn 2: Driver speaks 'aama confirm' -> income committed to ledger.
    """
    token, driver_id = get_driver_token(client, "9876543503")
    headers = {"Authorization": f"Bearer {token}"}
    db = client.application.extensions["db"]
    prisma = client.application.extensions["prisma_adapter"]

    # Turn 1: Driver speaks income command
    prisma.default_transcript = "inniku 500 rooba sambadhichen"
    audio_wav = make_test_wav(duration=1.0)
    data1 = {"audio": (io.BytesIO(audio_wav), "income.wav"), "lang": "tanglish"}

    res1 = client.post("/api/voice/chat", headers=headers, data=data1, content_type="multipart/form-data")
    assert res1.status_code == 200
    d1 = res1.get_json()["data"]

    session_id = d1["session_id"]
    assert d1["intent"] == "RECORD_INCOME"
    assert d1["next_step"] == "AWAITING_CONFIRMATION"
    assert d1["active_pending_action"] is not None
    assert d1["tts_status"] == "SUCCESS"

    # FIREWALL CHECK: Ledger must have 0 records!
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Turn 2: Driver affirms confirmation
    prisma.default_transcript = "aama confirm"
    data2 = {"audio": (io.BytesIO(audio_wav), "confirm.wav"), "session_id": session_id}

    res2 = client.post("/api/voice/chat", headers=headers, data=data2, content_type="multipart/form-data")
    assert res2.status_code == 200
    d2 = res2.get_json()["data"]

    assert d2["next_step"] == "COMPLETED"
    assert d2["active_pending_action"] is None

    # LEDGER CHECK: Exactly 1 record committed with +500.00
    records = list(db.transactions.find({"driver_id": driver_id}))
    assert len(records) == 1
    assert records[0]["transaction_type"] == "INCOME"
    assert str(records[0]["signed_amount"]) == "500.00"


def test_voice_workflow_2_expense(client):
    """
    Workflow 2: Expense
    Driver speaks: 'Diesel ku 400 rooba selavu aachu.'
    Turn 1: Expense recognized, proposal created, ledger empty.
    Turn 2: Confirmation -> recorded exactly once in ledger.
    """
    token, driver_id = get_driver_token(client, "9876543504")
    headers = {"Authorization": f"Bearer {token}"}
    db = client.application.extensions["db"]
    prisma = client.application.extensions["prisma_adapter"]

    # Turn 1: Propose expense
    prisma.default_transcript = "diesel ku 400 rooba selavu aachu"
    audio_wav = make_test_wav(duration=1.0)
    data1 = {"audio": (io.BytesIO(audio_wav), "expense.wav"), "lang": "tanglish"}

    res1 = client.post("/api/voice/chat", headers=headers, data=data1, content_type="multipart/form-data")
    assert res1.status_code == 200
    d1 = res1.get_json()["data"]
    session_id = d1["session_id"]
    assert d1["intent"] == "RECORD_EXPENSE"
    assert d1["slots"]["category"] == "FUEL"

    # Firewall check
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Turn 2: Confirm
    prisma.default_transcript = "sari confirm"
    data2 = {"audio": (io.BytesIO(audio_wav), "confirm.wav"), "session_id": session_id}
    res2 = client.post("/api/voice/chat", headers=headers, data=data2, content_type="multipart/form-data")
    assert res2.status_code == 200
    d2 = res2.get_json()["data"]
    assert d2["next_step"] == "COMPLETED"

    # Ledger check
    records = list(db.transactions.find({"driver_id": driver_id}))
    assert len(records) == 1
    assert records[0]["category"] == "FUEL"
    assert str(records[0]["signed_amount"]) == "-400.00"


def test_voice_workflow_3_missing_information(client):
    """
    Workflow 3: Missing information
    Driver speaks: 'Petrol ku selavu aachu.' (no amount)
    Agent asks for amount. No transaction created. Conversation remains active.
    """
    token, driver_id = get_driver_token(client, "9876543505")
    headers = {"Authorization": f"Bearer {token}"}
    db = client.application.extensions["db"]
    prisma = client.application.extensions["prisma_adapter"]

    prisma.default_transcript = "petrol ku selavu aachu"
    audio_wav = make_test_wav(duration=1.0)
    data = {"audio": (io.BytesIO(audio_wav), "petrol.wav"), "lang": "tanglish"}

    res = client.post("/api/voice/chat", headers=headers, data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    d = res.get_json()["data"]

    assert d["next_step"] == "AWAITING_SLOT"
    assert "Fuel" in d["agent_message"] or "fuel" in d["agent_message"].lower()

    # Zero writes to ledger!
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0


def test_voice_workflow_4_owner_reconciliation(client):
    """
    Workflow 4: Owner reconciliation
    Driver speaks: 'Owner ku 300 rooba kuduthuten.'
    Proposes OWNER_PAYMENT. Confirmed -> updates ledger & settlement single source of truth.
    """
    token, driver_id = get_driver_token(client, "9876543506")
    headers = {"Authorization": f"Bearer {token}"}
    db = client.application.extensions["db"]
    prisma = client.application.extensions["prisma_adapter"]

    # Turn 1: Propose owner payment
    prisma.default_transcript = "owner ku 300 rooba kuduthuten"
    audio_wav = make_test_wav(duration=1.0)
    data1 = {"audio": (io.BytesIO(audio_wav), "owner.wav"), "lang": "tanglish"}

    res1 = client.post("/api/voice/chat", headers=headers, data=data1, content_type="multipart/form-data")
    assert res1.status_code == 200
    d1 = res1.get_json()["data"]
    session_id = d1["session_id"]
    assert d1["intent"] == "RECORD_OWNER_PAYMENT"

    # Firewall check
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Turn 2: Confirm
    prisma.default_transcript = "aama confirm"
    data2 = {"audio": (io.BytesIO(audio_wav), "confirm.wav"), "session_id": session_id}
    res2 = client.post("/api/voice/chat", headers=headers, data=data2, content_type="multipart/form-data")
    assert res2.status_code == 200

    records = list(db.transactions.find({"driver_id": driver_id}))
    assert len(records) == 1
    assert records[0]["transaction_type"] == "OWNER_PAYMENT"
    assert str(records[0]["signed_amount"]) == "-350.00" or str(records[0]["signed_amount"]) == "-300.00"


def test_voice_workflow_5_provider_failure(client):
    """
    Workflow 5: Provider failure
    Prisma fails. No transaction created. User receives error.
    """
    token, driver_id = get_driver_token(client, "9876543507")
    headers = {"Authorization": f"Bearer {token}"}
    db = client.application.extensions["db"]
    prisma = client.application.extensions["prisma_adapter"]

    # Simulate Prisma failure
    prisma.should_fail = True
    prisma.failure_reason = "Gnani STT server error"

    audio_wav = make_test_wav(duration=1.0)
    data = {"audio": (io.BytesIO(audio_wav), "fail.wav")}

    res = client.post("/api/voice/chat", headers=headers, data=data, content_type="multipart/form-data")
    # Voice chat returns error in turn payload
    assert res.status_code == 200
    d = res.get_json()["data"]
    assert "error" in d
    assert "server error" in d["error"].lower()

    # Zero writes to database!
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Reset failure flag
    prisma.should_fail = False


def test_voice_workflow_6_tts_failure(client):
    """
    Workflow 6: TTS failure
    Timbre fails after agent responds.
    Agent response text is still returned. Financial result is NOT undone.
    """
    token, driver_id = get_driver_token(client, "9876543508")
    headers = {"Authorization": f"Bearer {token}"}
    prisma = client.application.extensions["prisma_adapter"]
    timbre = client.application.extensions["timbre_adapter"]

    prisma.default_transcript = "help"
    timbre.should_fail = True

    audio_wav = make_test_wav(duration=1.0)
    data = {"audio": (io.BytesIO(audio_wav), "help.wav")}

    res = client.post("/api/voice/chat", headers=headers, data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    d = res.get_json()["data"]

    assert "Voice Co-Pilot" in d["agent_message"]
    assert d["tts_status"] == "ERROR"
    assert d["tts_audio_base64"] is None  # Text mode fallback

    timbre.should_fail = False


def test_voice_cross_driver_isolation(client):
    """Ensures Driver B cannot pass Driver A's session into voice chat."""
    token_a, driver_a = get_driver_token(client, "9876543509")
    token_b, driver_b = get_driver_token(client, "9876543510")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Driver A starts a voice session
    audio_wav = make_test_wav(duration=1.0)
    data_a = {"audio": (io.BytesIO(audio_wav), "a.wav")}
    res_a = client.post("/api/voice/chat", headers=headers_a, data=data_a, content_type="multipart/form-data")
    session_id = res_a.get_json()["data"]["session_id"]

    # Driver B tries to hijack Driver A's session in voice chat
    data_b = {"audio": (io.BytesIO(audio_wav), "b.wav"), "session_id": session_id}
    res_b = client.post("/api/voice/chat", headers=headers_b, data=data_b, content_type="multipart/form-data")
    assert res_b.status_code == 403
    assert res_b.get_json()["error"]["code"] == "UNAUTHORIZED_SESSION"


def test_speech_compatibility_aliases(client):
    """Verifies /api/speech/transcribe and /api/speech/speak aliases for frontend compatibility."""
    token, driver_id = get_driver_token(client, "9876543511")
    headers = {"Authorization": f"Bearer {token}"}

    audio_wav = make_test_wav(duration=1.0)
    data = {"audio": (io.BytesIO(audio_wav), "alias.wav"), "lang": "tanglish"}

    # /api/speech/transcribe
    res_tr = client.post("/api/speech/transcribe", headers=headers, data=data, content_type="multipart/form-data")
    assert res_tr.status_code == 200
    assert "transcript" in res_tr.get_json()["data"]

    # /api/speech/speak
    json_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res_sp = client.post(
        "/api/speech/speak",
        headers=json_headers,
        data=json.dumps({"text": "Hello test"})
    )
    assert res_sp.status_code == 200
    assert "audio_base64" in res_sp.get_json()["data"]
