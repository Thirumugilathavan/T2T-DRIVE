"""
Unit tests for Gnani Timbre TTS Adapter in T2T DRIVE Voice Pipeline.
Tests MockTimbreAdapter WAV generation, language mapping, timeout handling,
and live TimbreAdapter HTTP error recovery.
"""

import pytest
import base64
from unittest.mock import MagicMock
import httpx

from app.voice.timbre_adapter import TimbreAdapter, MockTimbreAdapter


def test_mock_timbre_synthesizes_valid_wav():
    mock = MockTimbreAdapter()
    res = mock.synthesize("வணக்கம், இன்றைய கணக்கு தயார்.", language="ta-IN")

    assert res.processing_status == "SUCCESS"
    assert res.provider == "mock_timbre"
    assert res.content_type == "audio/wav"
    assert res.audio_bytes.startswith(b"RIFF")
    assert res.audio_base64 is not None

    # Verify base64 decodes back to original bytes
    decoded = base64.b64decode(res.audio_base64)
    assert decoded == res.audio_bytes


def test_mock_timbre_rejects_empty_text():
    mock = MockTimbreAdapter()
    res = mock.synthesize("")
    assert res.processing_status == "ERROR"
    assert "empty" in res.error.lower()


def test_mock_timbre_timeout_and_failure():
    mock = MockTimbreAdapter()
    mock.should_timeout = True
    res_to = mock.synthesize("Sample text")
    assert res_to.processing_status == "ERROR"
    assert "timed out" in res_to.error.lower()

    mock.should_timeout = False
    mock.should_fail = True
    mock.failure_reason = "Timbre server down"
    res_fail = mock.synthesize("Sample text")
    assert res_fail.processing_status == "ERROR"
    assert "down" in res_fail.error.lower()


def test_live_timbre_adapter_init():
    with pytest.raises(ValueError):
        TimbreAdapter(api_key="")

    adapter = TimbreAdapter(api_key="secret_gnani_key")
    assert adapter.api_key == "secret_gnani_key"
    assert adapter._map_language_code("tanglish") == "ta-IN"
    assert adapter._map_language_code("english") == "en-IN"


def test_live_timbre_binary_audio_response(monkeypatch):
    adapter = TimbreAdapter(api_key="test_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "audio/wav"}
    mock_resp.content = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_client), __exit__=MagicMock())))

    res = adapter.synthesize("Test speech", language="ta-IN")
    assert res.processing_status == "SUCCESS"
    assert res.audio_bytes.startswith(b"RIFF")
    assert res.audio_base64 is not None


def test_live_timbre_base64_json_response(monkeypatch):
    adapter = TimbreAdapter(api_key="test_key")
    dummy_audio = b"RIFF\x24\x00\x00\x00WAVE"
    dummy_b64 = base64.b64encode(dummy_audio).decode("ascii")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"audio_base64": dummy_b64}
    mock_resp.content = b'{"audio_base64":"..."}'

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_client), __exit__=MagicMock())))

    res = adapter.synthesize("Test speech")
    assert res.processing_status == "SUCCESS"
    assert res.audio_bytes == dummy_audio


def test_live_timbre_http_errors(monkeypatch):
    adapter = TimbreAdapter(api_key="test_key")

    # 401 Unauthorized
    mock_resp_401 = MagicMock(status_code=401, text="Unauthorized")
    mock_client_401 = MagicMock()
    mock_client_401.post.return_value = mock_resp_401
    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_client_401), __exit__=MagicMock())))

    res_401 = adapter.synthesize("Test")
    assert res_401.processing_status == "ERROR"
    assert "authentication failed" in res_401.error.lower()
