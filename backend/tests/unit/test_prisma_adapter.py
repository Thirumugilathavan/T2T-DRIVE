"""
Unit tests for Gnani Prisma STT Adapter in T2T DRIVE Voice Pipeline.
Tests MockPrismaAdapter scenarios, language mapping, timeout handling,
and live PrismaAdapter HTTP error recovery.
"""

import pytest
from unittest.mock import MagicMock, patch
import httpx

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
    assert adapter._map_language_code("tanglish") == "ta-IN,en-IN"
    assert adapter._map_language_code("tamil") == "ta-IN"
    assert adapter._map_language_code("english") == "en-IN"


def test_live_prisma_adapter_success_flow(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "transcript": "diesel 400 potten",
        "language_detected": "tanglish",
        "confidence": 0.94
    }

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_client), __exit__=MagicMock())))

    res = adapter.transcribe(b"audio_bytes", language_hint="tanglish")
    assert res.processing_status == "SUCCESS"
    assert res.transcript == "diesel 400 potten"
    assert res.detected_language == "tanglish"
    assert res.confidence == 0.94


def test_live_prisma_adapter_http_errors(monkeypatch):
    adapter = PrismaAdapter(api_key="test_key")

    # 401 Unauthorized
    mock_resp_401 = MagicMock(status_code=401, text="Unauthorized")
    mock_client_401 = MagicMock()
    mock_client_401.post.return_value = mock_resp_401
    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_client_401), __exit__=MagicMock())))

    res_401 = adapter.transcribe(b"audio_bytes")
    assert res_401.processing_status == "ERROR"
    assert "authentication failed" in res_401.error.lower()

    # 429 Rate Limit
    mock_resp_429 = MagicMock(status_code=429, text="Rate limit exceeded")
    mock_client_429 = MagicMock()
    mock_client_429.post.return_value = mock_resp_429
    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_client_429), __exit__=MagicMock())))

    res_429 = adapter.transcribe(b"audio_bytes")
    assert res_429.processing_status == "ERROR"
    assert "rate limit" in res_429.error.lower()
