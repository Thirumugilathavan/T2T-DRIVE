"""
API Integration tests for Noise Intelligence in T2T DRIVE Voice Pipeline.
Tests POST /api/voice/analyze-audio and enriched voice chat responses.
"""

import io
import json
import pytest
from tests.unit.test_audio_metrics import create_test_wav


def get_auth_token(client, phone="9876543901"):
    """Helper to authenticate driver and retrieve JWT bearer token."""
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    return ver_res.get_json()["data"]["token"]


def test_analyze_audio_requires_auth(client):
    res = client.post("/api/voice/analyze-audio")
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_analyze_audio_missing_file(client):
    token = get_auth_token(client, phone="9876543902")
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post("/api/voice/analyze-audio", headers=headers)
    assert res.status_code == 400
    assert "No audio file" in res.get_json()["error"]["message"]


def test_analyze_audio_success(client):
    token = get_auth_token(client, phone="9876543903")
    headers = {"Authorization": f"Bearer {token}"}

    wav_bytes = create_test_wav(duration=1.2, sample_rate=16000, frequency=440.0, amplitude=12000)
    data = {
        "file": (io.BytesIO(wav_bytes), "test_audio.wav", "audio/wav"),
        "language": "tanglish"
    }

    res = client.post(
        "/api/voice/analyze-audio",
        headers=headers,
        data=data,
        content_type="multipart/form-data"
    )

    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    report = body["data"]

    assert "overall_quality" in report
    assert "metrics" in report
    assert report["metrics"]["sample_rate"] == 16000
    assert report["metrics"]["duration_seconds"] == 1.2
    assert "snr" in report
    assert "noise_classification" in report
    assert "vad" in report
    assert "confidence" in report


def test_voice_chat_includes_noise_metadata(client):
    token = get_auth_token(client, phone="9876543904")
    headers = {"Authorization": f"Bearer {token}"}

    wav_bytes = create_test_wav(duration=1.0, sample_rate=16000, frequency=440.0, amplitude=10000)
    data = {
        "audio": (io.BytesIO(wav_bytes), "input.wav", "audio/wav"),
        "language_hint": "tanglish"
    }

    res = client.post(
        "/api/voice/chat",
        headers=headers,
        data=data,
        content_type="multipart/form-data"
    )

    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    turn_data = body["data"]

    assert "audio_quality" in turn_data
    assert "snr_estimate" in turn_data
    assert "noise_classification" in turn_data
    assert "vad_result" in turn_data
    assert "speech_confidence" in turn_data
