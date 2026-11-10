"""
Unit and Configuration Tests for Production Voice Provider Configuration.
Verifies that:
1. Live mode strictly requires GNANI_API_KEY and never silently falls back to mock adapters.
2. ProductionConfig.validate() enforces real GNANI_API_KEY when VOICE_PROVIDER_MODE="live".
3. GNANI_PRISMA_ENABLED and GNANI_TIMBRE_ENABLED flags are strictly respected.
4. Disabled adapters produce explicit errors and never claim success or substitute mock data.
5. Mock mode remains available for local dev and automated testing without consuming credits.
6. GNANI_API_KEY is never exposed via API endpoints or logs.
"""

import os
import pytest
from app import create_app
from app.config import ProductionConfig, TestingConfig
from app.voice.prisma_adapter import PrismaAdapter, MockPrismaAdapter, DisabledPrismaAdapter
from app.voice.timbre_adapter import TimbreAdapter, MockTimbreAdapter, DisabledTimbreAdapter


class TestProductionVoiceConfiguration:
    """Verifies strict configuration rules for real Gnani AI voice integration."""

    def test_live_mode_without_api_key_fails_fast_without_mock_fallback(self):
        """Live mode must fail initialization if GNANI_API_KEY is empty."""
        class BadLiveConfig(TestingConfig):
            VOICE_PROVIDER_MODE = "live"
            GNANI_API_KEY = ""
            GNANI_PRISMA_ENABLED = True
            GNANI_TIMBRE_ENABLED = True

        with pytest.raises(ValueError) as excinfo:
            create_app(BadLiveConfig)

        err_msg = str(excinfo.value)
        assert "GNANI_API_KEY is not configured" in err_msg
        assert "Silent fallback to mock is strictly forbidden" in err_msg

    def test_live_mode_with_api_key_initializes_real_gnani_adapters(self):
        """Live mode with valid key and enabled flags instantiates live Gnani adapters."""
        class GoodLiveConfig(TestingConfig):
            VOICE_PROVIDER_MODE = "live"
            GNANI_API_KEY = "test_live_gnani_key_998877"
            GNANI_PRISMA_ENABLED = True
            GNANI_TIMBRE_ENABLED = True

        app = create_app(GoodLiveConfig)
        assert isinstance(app.extensions["prisma_adapter"], PrismaAdapter)
        assert isinstance(app.extensions["timbre_adapter"], TimbreAdapter)
        assert app.extensions["voice_service"].prisma == app.extensions["prisma_adapter"]
        assert app.extensions["voice_service"].timbre == app.extensions["timbre_adapter"]

    def test_capabilities_endpoint_reports_live_status(self):
        """Capabilities endpoint reflects live STT/TTS status without leaking the key."""
        class GoodLiveConfig(TestingConfig):
            VOICE_PROVIDER_MODE = "live"
            GNANI_API_KEY = "super_secret_gnani_production_key_12345"
            GNANI_PRISMA_ENABLED = True
            GNANI_TIMBRE_ENABLED = True

        app = create_app(GoodLiveConfig)
        with app.test_client() as client:
            res = client.get("/api/voice/capabilities")
            assert res.status_code == 200
            data = res.get_json()["data"]

            assert data["provider_mode"] == "live"
            assert data["prisma_stt"]["status"] == "LIVE"
            assert data["timbre_tts"]["status"] == "LIVE"

            # Key must never be present anywhere in response
            raw_text = res.get_data(as_text=True)
            assert "super_secret_gnani" not in raw_text
            assert "12345" not in raw_text

    def test_prisma_disabled_flag_respected(self):
        """When GNANI_PRISMA_ENABLED is False, live mode uses DisabledPrismaAdapter."""
        class PrismaDisabledConfig(TestingConfig):
            VOICE_PROVIDER_MODE = "live"
            GNANI_API_KEY = "test_live_key_prisma_disabled"
            GNANI_PRISMA_ENABLED = False
            GNANI_TIMBRE_ENABLED = True

        app = create_app(PrismaDisabledConfig)
        prisma = app.extensions["prisma_adapter"]
        assert isinstance(prisma, DisabledPrismaAdapter)

        # Transcribe call must fail explicitly with ERROR, not mock transcript
        res = prisma.transcribe(b"RIFFmock", filename="test.wav")
        assert res.processing_status == "ERROR"
        assert "disabled" in res.error.lower()
        assert res.transcript == ""
        assert res.provider == "gnani_prisma_disabled"

    def test_timbre_disabled_flag_respected(self):
        """When GNANI_TIMBRE_ENABLED is False, live mode uses DisabledTimbreAdapter."""
        class TimbreDisabledConfig(TestingConfig):
            VOICE_PROVIDER_MODE = "live"
            GNANI_API_KEY = "test_live_key_timbre_disabled"
            GNANI_PRISMA_ENABLED = True
            GNANI_TIMBRE_ENABLED = False

        app = create_app(TimbreDisabledConfig)
        timbre = app.extensions["timbre_adapter"]
        assert isinstance(timbre, DisabledTimbreAdapter)

        # Synthesize call must fail explicitly with ERROR, not mock audio
        res = timbre.synthesize("Vanakkam", language="ta-IN")
        assert res.processing_status == "ERROR"
        assert "disabled" in res.error.lower()
        assert res.audio_bytes is None
        assert res.provider == "gnani_timbre_disabled"

    def test_mock_mode_remains_available_for_tests(self):
        """Mock mode must instantiate mock adapters cleanly for local development."""
        app = create_app(TestingConfig)
        assert isinstance(app.extensions["prisma_adapter"], MockPrismaAdapter)
        assert isinstance(app.extensions["timbre_adapter"], MockTimbreAdapter)

    def test_production_config_validation(self, monkeypatch):
        """ProductionConfig.validate() enforces GNANI_API_KEY when VOICE_PROVIDER_MODE='live'."""
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        monkeypatch.setenv("JWT_SECRET", "b" * 32)
        monkeypatch.setenv("OTP_HASH_SECRET", "c" * 32)
        monkeypatch.setenv("VOICE_PROVIDER_MODE", "live")
        monkeypatch.delenv("GNANI_API_KEY", raising=False)

        with pytest.raises(ValueError) as exc:
            ProductionConfig.validate()
        assert "Production GNANI_API_KEY must be set" in str(exc.value)

        # Placeholder key must also be rejected
        monkeypatch.setenv("GNANI_API_KEY", "mock-gnani-key-1234")
        with pytest.raises(ValueError) as exc:
            ProductionConfig.validate()
        assert "Production GNANI_API_KEY must be set" in str(exc.value)

        # Genuine production key passes
        monkeypatch.setenv("GNANI_API_KEY", "prod_gnani_live_api_key_valid_998877")
        ProductionConfig.validate()  # Must not raise
