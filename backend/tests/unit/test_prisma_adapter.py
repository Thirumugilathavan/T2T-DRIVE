"""
Unit tests for Gnani Prisma STT Adapter in T2T DRIVE Voice Pipeline.
Tests MockPrismaAdapter scenarios, language mapping, timeout handling,
and live PrismaAdapter error scenarios:
- Successful responses
- HTTP errors (401, 429, 500)
- Connection termination (ConnectionError, SSLEOFError)
- Timeout handling (requests.exceptions.Timeout)
- Malformed responses (Invalid JSON, empty transcript)
- Strict single-call verification (Zero automatic retries)
"""

import pytest
from unittest.mock import MagicMock, patch
import requests

from app.voice.prisma_adapter import PrismaAdapter, MockPrismaAdapter


def test_mock_prisma_language_responses():
    mock = MockPrismaAdapter()

    # Tamil
    res_ta = mock.transcribe(b"dummy", language_hint="ta")
    assert res_ta.processing_status == "SUCCESS"
    assert "டீசல்" in res_ta.transcript
    assert res_ta.detected_language == "tamil"
    assert res_ta.provider == "mock_prisma"

    # Tanglish
    res_tg = mock.transcribe(b"dummy", language_hint="tanglish")
    assert res_tg.processing_status == "SUCCESS"
    assert "potten" in res_tg.transcript
    assert res_tg.detected_language == "tanglish"

    # English
    res_en = mock.transcribe(b"dummy", language_hint="en")
    assert res_en.processing_status == "SUCCESS"
    assert "diesel" in res_en.transcript
    assert res_en.detected_language == "english"


def test_mock_prisma_default_override():
    mock = MockPrismaAdapter(default_transcript="savari 1200 aachu")
    res = mock.transcribe(b"dummy")
    assert res.transcript == "savari 1200 aachu"


def test_mock_prisma_timeout_and_failure():
    mock = MockPrismaAdapter()
    mock.should_timeout = True
    res_to = mock.transcribe(b"dummy")
    assert res_to.processing_status == "ERROR"
    assert "timed out" in res_to.error.lower()

    mock.should_timeout = False
    mock.should_fail = True
    mock.failure_reason = "Simulated API outage"
    res_fail = mock.transcribe(b"dummy")
    assert res_fail.processing_status == "ERROR"
    assert "outage" in res_fail.error.lower()


def test_live_prisma_adapter_init():
    with pytest.raises(ValueError):
        PrismaAdapter(api_key="")

    adapter = PrismaAdapter(api_key="gnani_secret_key_123")
    assert adapter.api_key == "gnani_secret_key_123"
    assert adapter.timeout == 60.0  # Configurable 60s default

    # Test single-locale language codes
    assert adapter._map_language_code("tanglish") == "indic-auto"
    assert adapter._map_language_code("tamil") == "ta-IN"
    assert adapter._map_language_code("english") == "en-IN"

    # Test full language parameter dictionary
    ta_params = adapter._map_language_params("tamil")
    assert ta_params["language_code"] == "ta-IN"
    assert ta_params["preferred_language"] == "ta-IN"
    assert "multi_lang_codes" not in ta_params

    tg_params = adapter._map_language_params("tanglish")
    assert tg_params["language_code"] == "indic-auto"
    assert tg_params["preferred_language"] == "ta-IN"
    assert tg_params["multi_lang_codes"] == "ta-IN,en-IN"

    en_params = adapter._map_language_params("english")
    assert en_params["language_code"] == "en-IN"
    assert en_params["preferred_language"] == "en-IN"


def test_live_prisma_adapter_request_payload(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")
    mock_session = MagicMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "success": True,
        "request_id": "req-123",
        "transcript": "இன்னைக்கு நான் ஐநூறு ரூபாய் சம்பாதிச்சேன்",
        "detected_language_code": "ta-IN",
        "confidence": 0.97
    }
    mock_session.post.return_value = mock_resp
    monkeypatch.setattr(requests, "Session", MagicMock(return_value=mock_session))

    res = adapter.transcribe(
        audio_bytes=b"sample_wav_bytes",
        filename="stt_tamil_16k.wav",
        language_hint="ta-IN",
        output_format="transcribe",
        preferred_language="ta-IN",
        itn_native_numerals=False
    )
    assert res.processing_status == "SUCCESS"
    assert "ஐநூறு" in res.transcript
    assert res.detected_language == "ta-IN"
    assert res.confidence == 0.97

    # Verify the exact multipart payload passed to post()
    call_kwargs = mock_session.post.call_args[1]
    assert call_kwargs["headers"]["X-API-Key-ID"] == "test_key"
    assert call_kwargs["headers"]["Connection"] == "close"
    assert call_kwargs["data"]["model"] == "prisma-v3.0"
    assert call_kwargs["data"]["language_code"] == "ta-IN"
    assert call_kwargs["data"]["preferred_language"] == "ta-IN"
    assert call_kwargs["data"]["format"] == "transcribe"
    assert call_kwargs["data"]["itn_native_numerals"] == "false"
    assert "audio_file" in call_kwargs["files"]
    assert call_kwargs["files"]["audio_file"][0] == "stt_tamil_16k.wav"
    assert call_kwargs["files"]["audio_file"][1] == b"sample_wav_bytes"
    assert call_kwargs["verify"] is True
    assert call_kwargs["timeout"] == 60.0


def test_live_prisma_adapter_success_flow(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "transcript": "diesel 400 potten",
        "language_detected": "tanglish",
        "confidence": 0.94
    }

    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    monkeypatch.setattr(requests, "Session", MagicMock(return_value=mock_session))

    res = adapter.transcribe(b"audio_bytes", language_hint="tanglish")
    assert res.processing_status == "SUCCESS"
    assert res.transcript == "diesel 400 potten"
    assert res.detected_language == "tanglish"
    assert res.confidence == 0.94
    assert mock_session.post.call_count == 1  # Exactly 1 call, no retries


def test_live_prisma_adapter_http_errors(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")
    mock_session = MagicMock()
    monkeypatch.setattr(requests, "Session", MagicMock(return_value=mock_session))

    # 401 Unauthorized
    mock_session.post.return_value = MagicMock(status_code=401, text="Unauthorized")
    res_401 = adapter.transcribe(b"audio_bytes")
    assert res_401.processing_status == "ERROR"
    assert "authentication failed" in res_401.error.lower()

    # 429 Rate Limit
    mock_session.post.return_value = MagicMock(status_code=429, text="Rate limit exceeded")
    res_429 = adapter.transcribe(b"audio_bytes")
    assert res_429.processing_status == "ERROR"
    assert "rate limit" in res_429.error.lower()

    # 500 Internal Server Error
    mock_session.post.return_value = MagicMock(status_code=500, text="Internal Gateway Error")
    res_500 = adapter.transcribe(b"audio_bytes")
    assert res_500.processing_status == "ERROR"
    assert "500" in res_500.error


def test_live_prisma_adapter_connection_termination(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")
    mock_session = MagicMock()
    monkeypatch.setattr(requests, "Session", MagicMock(return_value=mock_session))

    # Simulate SSLEOFError / unexpected EOF
    mock_session.post.side_effect = requests.exceptions.SSLError(
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1082)"
    )
    res_ssl = adapter.transcribe(b"audio_bytes")
    assert res_ssl.processing_status == "ERROR"
    assert "ssl error" in res_ssl.error.lower()
    assert mock_session.post.call_count == 1  # Zero retries

    # Simulate abrupt TCP connection reset
    mock_session.post.side_effect = requests.exceptions.ConnectionError("Connection reset by peer")
    res_conn = adapter.transcribe(b"audio_bytes")
    assert res_conn.processing_status == "ERROR"
    assert "connection error" in res_conn.error.lower()
    assert mock_session.post.call_count == 2  # Total 2 distinct calls across 2 tests, zero auto-retries


def test_live_prisma_adapter_timeout(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")
    mock_session = MagicMock()
    monkeypatch.setattr(requests, "Session", MagicMock(return_value=mock_session))

    mock_session.post.side_effect = requests.exceptions.Timeout("HTTPSConnectionPool read timed out (read timeout=60)")
    res_to = adapter.transcribe(b"audio_bytes")
    assert res_to.processing_status == "ERROR"
    assert "timed out" in res_to.error.lower()
    assert mock_session.post.call_count == 1  # Zero retries


def test_live_prisma_adapter_malformed_responses(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")
    mock_session = MagicMock()
    monkeypatch.setattr(requests, "Session", MagicMock(return_value=mock_session))

    # Case 1: Malformed non-JSON response (e.g. HTML proxy error page returning 200)
    mock_resp_bad_json = MagicMock(status_code=200, text="<html>502 Bad Gateway</html>")
    mock_resp_bad_json.json.side_effect = ValueError("No JSON object could be decoded")
    mock_session.post.return_value = mock_resp_bad_json

    res_bad = adapter.transcribe(b"audio_bytes")
    assert res_bad.processing_status == "ERROR"
    assert "malformed" in res_bad.error.lower()

    # Case 2: Valid JSON but missing/empty transcript
    mock_resp_empty = MagicMock(status_code=200)
    mock_resp_empty.json.return_value = {"transcript": "", "language_detected": "ta-IN"}
    mock_session.post.return_value = mock_resp_empty

    res_empty = adapter.transcribe(b"audio_bytes")
    assert res_empty.processing_status == "EMPTY"
    assert "empty transcript" in res_empty.error.lower()
