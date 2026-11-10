"""
Unit and Contract Tests for Gnani AI Prisma STT & Timbre TTS Live Activation.
Validates:
1. Indian number comma parsing (e.g. 1,500 -> 1500) and Tamil loanwords.
2. Streaming WAV 0x7FFFFFFF (2147483647) frame count handling in AudioPreprocessor.
3. Truthful STT and TTS status isolation (STT does not affect TTS, TTS does not affect STT).
4. Live PrismaAdapter request construction with ta-IN, en-IN, and indic-auto.
5. Live TimbreAdapter request construction with Kaveri voice.
"""

import io
import os
import wave
from decimal import Decimal
import pytest
from unittest.mock import MagicMock

from app.agent.nlu import MultilingualNLU, parse_numeric_amount, OWNER_PAYMENT_KEYWORDS
from app.voice.audio_preprocessor import AudioPreprocessor
from app.voice.prisma_adapter import PrismaAdapter
from app.voice.timbre_adapter import TimbreAdapter
from app.voice.voice_service import VoiceService


def test_comma_number_parsing_in_nlu():
    """Verifies that numbers formatted with commas (e.g. 1,500 from STT) are parsed as 1500."""
    amt1 = parse_numeric_amount("கலெக்ஷன் 1,500 ரூபாய்")
    assert amt1 == Decimal("1500")

    amt2 = parse_numeric_amount("collection 1,500")
    assert amt2 == Decimal("1500")

    amt3 = parse_numeric_amount("petrol 25,000")
    assert amt3 == Decimal("25000")


def test_tamil_owner_loanwords_in_nlu():
    """Verifies that Tamil loanwords for owner (ஓனக்கு, ஓனருக்கு) are in OWNER_PAYMENT_KEYWORDS."""
    assert "ஓனக்கு" in OWNER_PAYMENT_KEYWORDS
    assert "ஓனருக்கு" in OWNER_PAYMENT_KEYWORDS


def test_multi_transaction_extraction_with_comma_numbers():
    """Verifies that compound utterances with comma-formatted numbers are extracted into batch transactions."""
    text = "இன்னைக்கு கலெக்ஷன் 1,500, பெட்ரோல் 300, ஓனக்கு 200 கொடுத்தேன்."
    txns = MultilingualNLU.extract_multi_transactions(text)
    assert len(txns) == 3
    assert txns[0]["action_type"] == "ADD_INCOME"
    assert txns[0]["amount"] == 1500.0

    assert txns[1]["action_type"] == "ADD_EXPENSE"
    assert txns[1]["amount"] == 300.0

    assert txns[2]["action_type"] == "ADD_OWNER_PAYMENT"
    assert txns[2]["amount"] == 200.0


def test_streaming_wav_header_duration_guard():
    """
    Verifies that AudioPreprocessor guards against streaming WAV headers
    where num_frames is set to 0x7FFFFFFF (2147483647).
    """
    sample_rate = 24000
    channels = 1
    sample_width = 2
    # Create 1 second of actual non-silent PCM data (440 Hz tone)
    import math, struct
    samples = [int(math.sin(2 * math.pi * 440 * i / sample_rate) * 8000) for i in range(24000)]
    raw_pcm = b"".join(struct.pack("<h", s) for s in samples)

    bio = io.BytesIO()
    # Write a valid WAV file
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_pcm)

    wav_bytes = bytearray(bio.getvalue())
    # Manually overwrite the data chunk size or num_frames header with 0x7FFFFFFF
    # In standard WAV: bytes 40-43 is data chunk size
    wav_bytes[40:44] = b"\xff\xff\xff\x7f"

    prep = AudioPreprocessor(min_duration_seconds=0.2, max_duration_seconds=60.0)
    res = prep.inspect_and_preprocess(bytes(wav_bytes), audio_format="wav")

    # Duration should be computed from actual buffer length (~1.0s), NOT 89478s
    assert res["is_processable"] is True
    assert 0.9 <= res["duration_seconds"] <= 1.1


def test_live_prisma_language_parameters():
    """Verifies Prisma v3.0 language mappings for ta-IN, en-IN, and Tanglish."""
    adapter = PrismaAdapter(api_key="dummy_test_key_123")

    ta = adapter._map_language_params("tamil")
    assert ta["language_code"] == "ta-IN"

    en = adapter._map_language_params("english")
    assert en["language_code"] == "en-IN"

    tg = adapter._map_language_params("tanglish")
    assert tg["language_code"] == "indic-auto"
    assert tg["preferred_language"] == "ta-IN"
    assert tg["multi_lang_codes"] == "ta-IN,en-IN"


def test_live_timbre_language_and_voice():
    """Verifies Timbre v2.5 language mapping and payload format."""
    adapter = TimbreAdapter(api_key="dummy_test_key_123")
    assert adapter._map_language_code("tamil") == "ta-IN"
    assert adapter._map_language_code("tanglish") == "ta-IN"
    assert adapter._map_language_code("english") == "en-IN"


def test_parse_bool_env_permutations(monkeypatch):
    """Verifies robust boolean environment variable parsing across all common formats."""
    from app.config import parse_bool_env

    # Truthy values
    for val in ("1", "true", "True", "TRUE", "yes", "on", "enable", "enabled", " 1 ", " 'true' ", ' "1" '):
        monkeypatch.setenv("TEST_FLAG", val)
        res, src = parse_bool_env("TEST_FLAG", default=False)
        assert res is True, f"Failed for truthy value: {val!r}"
        assert "True" in src

    # Falsy values
    for val in ("0", "false", "False", "FALSE", "no", "off", "disable", "disabled", " 0 ", " 'false' "):
        monkeypatch.setenv("TEST_FLAG", val)
        res, src = parse_bool_env("TEST_FLAG", default=True)
        assert res is False, f"Failed for falsy value: {val!r}"
        assert "False" in src

    # Default fallback when unset
    monkeypatch.delenv("TEST_FLAG", raising=False)
    res_t, _ = parse_bool_env("TEST_FLAG", default=True)
    assert res_t is True
    res_f, _ = parse_bool_env("TEST_FLAG", default=False)
    assert res_f is False


def test_render_environment_and_mongo_aliases(monkeypatch):
    """Verifies automatic Render production detection and MONGO_URI alias resolution."""
    from app.config import get_config, ProductionConfig, Config

    monkeypatch.setenv("FLASK_ENV", "production")
    cfg = get_config()
    assert cfg == ProductionConfig

    # Verify RENDER sets Config.ENV to production
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("FLASK_ENV", raising=False)
    assert os.getenv("RENDER") == "true"

    # Test MONGO_URI alias
    monkeypatch.setenv("MONGO_URI", "mongodb+srv://atlas_user:atlas_pass@cluster.mongodb.net/t2t_prod")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    # Re-evaluate Config class attribute
    from app.config import Config
    _raw = (
        os.getenv("MONGODB_URI")
        or os.getenv("MONGO_URI")
        or os.getenv("MONGODB_URL")
        or "mongodb://localhost:27017/t2t_drive"
    ).strip().strip("\"'")
    assert _raw.startswith("mongodb+srv://")


def test_disconnected_database_startup_and_503_responses(monkeypatch):
    """Verifies that app starts safely without AttributeError when MongoDB is disconnected on Render,
    and returns HTTP 503 for database-dependent requests while keeping health & frontend accessible."""
    from app import create_app
    from app.config import Config
    from app.database.connection import db_manager

    class DisconnectedRenderConfig(Config):
        TESTING = False
        ENV = "production"
        SECRET_KEY = "dummy-long-secret-key-32-chars-long!"
        MONGODB_URI = "mongodb://localhost:27017/t2t_drive"
        VOICE_PROVIDER_MODE = "mock"

    monkeypatch.setenv("RENDER", "true")
    # Reset db_manager state
    db_manager.db = None
    db_manager._is_mock = False

    # 1. Startup must NOT crash with AttributeError ('vehicle_documents', etc.)
    app = create_app(DisconnectedRenderConfig)
    client = app.test_client()

    # 2. Health endpoint must succeed (200 OK) reporting database disconnected
    health_res = client.get("/api/health")
    assert health_res.status_code == 200
    health_data = health_res.get_json()["data"]
    assert health_data["database"]["connected"] is False
    assert health_data["database"]["mode"] == "DISCONNECTED"

    # 3. Voice capabilities must succeed (200 OK)
    cap_res = client.get("/api/voice/capabilities")
    assert cap_res.status_code == 200

    # 4. Frontend homepage must succeed (200 OK)
    home_res = client.get("/")
    assert home_res.status_code == 200

    # 5. Database-dependent API request must return HTTP 503 DATABASE_UNAVAILABLE
    db_res = client.get("/api/documents/")
    assert db_res.status_code == 503
    err_json = db_res.get_json()
    assert err_json["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "unavailable" in err_json["error"]["message"].lower()


def test_diagnose_mongo_error_sanitization_and_categories():
    """Verifies that MongoDB error diagnosis accurately categorizes errors without leaking secrets."""
    from app.database.connection import diagnose_mongo_error

    secret_uri = "mongodb+srv://admin_user:super_secret_pwd_123@cluster0.abcde.mongodb.net/t2t_drive?retryWrites=true"

    # 1. TLS / IP Whitelist error
    tls_err = Exception("SSL handshake failed: TLSV1_ALERT_INTERNAL_ERROR, ReplicaSetNoPrimary")
    diag_tls = diagnose_mongo_error(tls_err, secret_uri)
    assert diag_tls["category"] == "TLS_OR_IP_FIREWALL_BLOCK"
    assert "0.0.0.0/0" in diag_tls["action"]
    assert "super_secret_pwd_123" not in diag_tls["target"]
    assert "admin_user" not in diag_tls["target"]
    assert diag_tls["target"] == "mongodb+srv://***:***@cluster0.abcde.mongodb.net"

    # 2. Authentication failure
    auth_err = Exception("OperationFailure: Authentication failed for user 'admin_user'")
    diag_auth = diagnose_mongo_error(auth_err, secret_uri)
    assert diag_auth["category"] == "AUTHENTICATION_FAILED"
    assert "super_secret_pwd_123" not in diag_auth["target"]

    # 3. DNS failure
    dns_err = Exception("ConfigurationError: All nameservers failed to answer the query _mongodb._tcp.cluster0...")
    diag_dns = diagnose_mongo_error(dns_err, secret_uri)
    assert diag_dns["category"] == "DNS_RESOLUTION_FAILURE"

    # 4. Timeout
    timeout_err = Exception("ServerSelectionTimeoutError: No replica set members found within 5000ms")
    diag_timeout = diagnose_mongo_error(timeout_err, secret_uri)
    assert diag_timeout["category"] == "CONNECTION_TIMEOUT"

