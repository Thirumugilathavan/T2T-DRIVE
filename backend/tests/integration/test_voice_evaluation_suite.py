"""
T2T DRIVE — Comprehensive Voice Intelligence & Multilingual Reliability Evaluation Suite.
Workstream A: Noise-Aware Multilingual Voice Reliability Audit.

Evaluates:
1. Clean Tamil speech (stt_tamil_16k.wav)
2. Tanglish compound multi-action speech (T2T_Tanglish_Test_Audio.wav)
3. English speech (stt_english.wav)
4. Code-mixed speech (stt_codmix.wav)
5. Vehicle engine noise acoustic resilience
6. Low-volume speech normalization
7. Silence detection and pre-flight safeguards
8. Ambiguous amount extraction and clarification prompts
9. Explicit confirmation firewall enforcement
10. TTS synthesis and spoken language matching
"""

import io
import os
import json
import time
from pathlib import Path
from decimal import Decimal
import pytest

from app import create_app
from app.config import TestingConfig
from app.agent.nlu import MultilingualNLU, AgentIntent
from tests.benchmarks.synthetic_audio_generator import SyntheticAudioGenerator

AUDIO_DIR = Path(__file__).resolve().parent.parent / "test_audio"


@pytest.fixture(scope="module")
def app_and_client():
    app = create_app("testing")
    with app.test_client() as client:
        yield app, client


def _get_auth_headers(client, phone="+919876543888"):
    res_otp = client.post("/api/auth/request-otp", json={"phone": phone})
    otp = res_otp.get_json()["data"].get("_mock_otp", "123456")
    res_ver = client.post("/api/auth/verify-otp", json={"phone": phone, "otp": otp})
    token = res_ver.get_json()["data"]["token"]
    driver_id = res_ver.get_json()["data"]["driver"]["driver_id"]
    return {"Authorization": f"Bearer {token}"}, driver_id


class TestVoiceEvaluationSuite:
    """Rigorous reproducible evaluation of noise-aware multilingual voice pipeline."""

    def test_01_clean_tamil_speech_evaluation(self, app_and_client):
        """Clean Tamil speech audio fixture processing."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543801")
        tamil_wav = AUDIO_DIR / "stt_tamil_16k.wav"
        assert tamil_wav.is_file(), f"Missing audio fixture: {tamil_wav}"

        start_time = time.perf_counter()
        with open(tamil_wav, "rb") as f:
            audio_bytes = f.read()

        res = client.post(
            "/api/voice/chat",
            headers=headers,
            data={
                "audio": (io.BytesIO(audio_bytes), "stt_tamil_16k.wav"),
                "lang": "ta-IN",
                "generate_tts": "true"
            },
            content_type="multipart/form-data"
        )
        latency_ms = (time.perf_counter() - start_time) * 1000

        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "டீசல் 400 போட்டேன்" in data["transcript"]
        assert data["detected_language"] in ("tamil", "ta-IN", "ta")
        assert data["next_step"] == "AWAITING_CONFIRMATION"
        assert data["tts_status"] == "SUCCESS"
        assert data["tts_audio_base64"] is not None
        assert latency_ms < 5000  # Latency threshold

    def test_02_tanglish_multi_action_speech_evaluation(self, app_and_client):
        """Tanglish multi-action compound utterance (Income 1500, Fuel 300, Owner 200)."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543802")
        tanglish_wav = AUDIO_DIR / "T2T_Tanglish_Test_Audio.wav"
        assert tanglish_wav.is_file(), f"Missing audio fixture: {tanglish_wav}"

        with open(tanglish_wav, "rb") as f:
            audio_bytes = f.read()

        res = client.post(
            "/api/voice/chat",
            headers=headers,
            data={
                "audio": (io.BytesIO(audio_bytes), "T2T_Tanglish_Test_Audio.wav"),
                "lang": "tanglish",
                "generate_tts": "true"
            },
            content_type="multipart/form-data"
        )
        assert res.status_code == 200
        data = res.get_json()["data"]

        # Expected semantic interpretation:
        # Collection: 1500, Petrol: 300, Owner: 200
        assert "1500" in data["transcript"]
        assert "300" in data["transcript"]
        assert "200" in data["transcript"]
        assert data["next_step"] == "AWAITING_CONFIRMATION"
        assert "active_pending_action" in data
        pending = data["active_pending_action"]
        assert pending["action_type"] == "ADD_BATCH_TRANSACTIONS"

        # Check extracted transactions
        txns = pending["proposed_data"]["transactions"]
        assert len(txns) == 3
        income_item = next(t for t in txns if t["category"] == "FARE")
        fuel_item = next(t for t in txns if t["category"] == "FUEL")
        owner_item = next(t for t in txns if t["category"] == "OWNER_RENT")

        assert Decimal(str(income_item["amount"])) == Decimal("1500.00")
        assert Decimal(str(fuel_item["amount"])) == Decimal("300.00")
        assert Decimal(str(owner_item["amount"])) == Decimal("200.00")

    def test_03_english_speech_evaluation(self, app_and_client):
        """English driver speech audio fixture processing."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543803")
        eng_wav = AUDIO_DIR / "stt_english.wav"
        assert eng_wav.is_file(), f"Missing audio fixture: {eng_wav}"

        with open(eng_wav, "rb") as f:
            audio_bytes = f.read()

        res = client.post(
            "/api/voice/chat",
            headers=headers,
            data={
                "audio": (io.BytesIO(audio_bytes), "stt_english.wav"),
                "lang": "en-IN",
                "generate_tts": "false"
            },
            content_type="multipart/form-data"
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "400" in data["transcript"]
        assert data["next_step"] == "AWAITING_CONFIRMATION"
        pending = data["active_pending_action"]
        assert Decimal(str(pending["proposed_data"]["amount"])) == Decimal("400.00")

    def test_04_code_mixed_speech_evaluation(self, app_and_client):
        """Code-mixed Tamil-English speech audio fixture processing."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543804")
        codmix_wav = AUDIO_DIR / "stt_codmix.wav"
        assert codmix_wav.is_file(), f"Missing audio fixture: {codmix_wav}"

        with open(codmix_wav, "rb") as f:
            audio_bytes = f.read()

        res = client.post(
            "/api/voice/chat",
            headers=headers,
            data={
                "audio": (io.BytesIO(audio_bytes), "stt_codmix.wav"),
                "lang": "tanglish",
                "generate_tts": "false"
            },
            content_type="multipart/form-data"
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "300" in data["transcript"]
        assert data["next_step"] == "AWAITING_CONFIRMATION"

    def test_05_acoustic_engine_noise_resilience(self, app_and_client):
        """Verifies Phase 6 Noise Intelligence under severe auto-rickshaw engine rumble."""
        app, client = app_and_client
        generator = SyntheticAudioGenerator(sample_rate=16000, seed=123)
        # Synthesize 2.0s of vehicle engine noise mixed with speech formants
        noisy_bytes, _, _ = generator.generate_composite(duration=2.0, condition="ENGINE_NOISE")

        voice_svc = app.extensions["voice_service"]
        analysis = voice_svc.noise_service.analyze_audio(
            audio_bytes=noisy_bytes,
            audio_format="wav",
            language="tanglish"
        )

        assert analysis.noise_classification is not None
        assert analysis.snr is not None
        assert analysis.snr["snr_db"] < 25.0  # Demonstrates engine noise detection

    def test_06_low_volume_speech_normalization(self, app_and_client):
        """Verifies peak-safe normalization on low-amplitude driver utterance."""
        app, client = app_and_client
        generator = SyntheticAudioGenerator(sample_rate=16000, seed=456)
        low_vol_bytes, _, _ = generator.generate_composite(duration=2.0, condition="LOW_VOLUME")

        voice_svc = app.extensions["voice_service"]
        optimal_bytes, report, prep_res = voice_svc.noise_service.prepare_for_stt(
            low_vol_bytes,
            audio_format="wav",
            language="tanglish"
        )
        assert len(optimal_bytes) > 0
        assert prep_res is not None
        assert "PEAK_SAFE_NORMALIZATION" in prep_res.applied_transformations

    def test_07_silence_detection_and_safeguards(self, app_and_client):
        """Pure silence / muted microphone detection guards against hallucinations."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543807")
        generator = SyntheticAudioGenerator(sample_rate=16000, seed=789)
        silent_bytes, _, _ = generator.generate_composite(duration=1.5, condition="SILENCE")

        res = client.post(
            "/api/voice/chat",
            headers=headers,
            data={
                "audio": (io.BytesIO(silent_bytes), "silence.wav"),
                "lang": "tanglish",
                "generate_tts": "false"
            },
            content_type="multipart/form-data"
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        # Must NOT propose or execute any financial transaction on silence
        assert data["next_step"] in ("IDLE", "AWAITING_INPUT")
        assert data.get("active_pending_action") is None

    def test_08_ambiguous_amount_triggers_clarification(self, app_and_client):
        """Utterance stating an expense without amount prompts clarification instead of writing."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543808")
        generator = SyntheticAudioGenerator(sample_rate=16000)
        audio_bytes, _, _ = generator.generate_composite(duration=1.0, condition="CLEAN")

        res = client.post(
            "/api/voice/chat",
            headers=headers,
            data={
                "audio": (io.BytesIO(audio_bytes), "ambiguous_diesel.wav"),
                "lang": "tanglish",
                "generate_tts": "false"
            },
            content_type="multipart/form-data"
        )
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "diesel" in data["transcript"].lower()
        # Missing amount must prompt clarification, not execute
        assert data["next_step"] == "AWAITING_SLOT"
        assert "amount" in data["agent_message"].lower() or "evvalavu" in data["agent_message"].lower()

    def test_09_explicit_confirmation_firewall(self, app_and_client):
        """Confirmation gate ensures ZERO writes on cancellation."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543809")
        db = app.extensions["db"]

        # Step 1: Propose expense via text/voice
        agent_svc = app.extensions["agent_service"]
        turn1 = agent_svc.process_message(
            driver_id=driver_id,
            message="petrol 350 potten",
            session_id=None,
            language="tanglish"
        )
        assert turn1["next_step"] == "AWAITING_CONFIRMATION"
        pending_id = turn1["active_pending_action"]["pending_action_id"]

        # Ledger must have 0 transactions prior to confirmation
        tx_count_before = db.transactions.count_documents({"driver_id": driver_id})

        # Step 2: Driver cancels ("vendaam / no")
        turn2 = agent_svc.process_message(
            driver_id=driver_id,
            message="vendaam cancel pannu",
            session_id=turn1["session_id"],
            language="tanglish"
        )
        assert turn2["next_step"] == "IDLE"

        # Ledger must STILL have 0 transactions
        tx_count_after = db.transactions.count_documents({"driver_id": driver_id})
        assert tx_count_after == tx_count_before

        # Pending action status must be REJECTED/CANCELLED
        p_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
        assert p_doc["status"] in ("REJECTED", "CANCELLED")

    def test_10_tts_synthesis_and_language_selection(self, app_and_client):
        """Timbre TTS synthesis produces correct language audio."""
        app, client = app_and_client
        headers, driver_id = _get_auth_headers(client, "+919876543810")

        # Tamil synthesis
        res_ta = client.post(
            "/api/voice/speak",
            headers=headers,
            json={"text": "நன்றி. உங்கள் கணக்கு பதிவானது.", "lang": "ta-IN", "voice": "Kaveri"}
        )
        assert res_ta.status_code == 200
        data_ta = res_ta.get_json()["data"]
        assert data_ta["audio_base64"] is not None
        assert data_ta["status"] == "SUCCESS"

        # English synthesis
        res_en = client.post(
            "/api/voice/speak",
            headers=headers,
            json={"text": "Thank you. Transaction recorded.", "lang": "en-IN", "voice": "Nalini"}
        )
        assert res_en.status_code == 200
        data_en = res_en.get_json()["data"]
        assert data_en["audio_base64"] is not None
        assert data_en["status"] == "SUCCESS"
