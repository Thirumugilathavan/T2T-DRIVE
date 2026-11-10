import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of backend
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)


def parse_bool_env(var_name: str, default: bool = True) -> tuple[bool, str]:
    """
    Safely parses boolean environment variables supporting standard conventions:
    '1', 'true', 'True', 'TRUE', 'yes', 'on', 'enable', 'enabled' -> True
    '0', 'false', 'False', 'FALSE', 'no', 'off', 'disable', 'disabled' -> False
    Handles leading/trailing whitespace and surrounding single or double quotes.
    Returns (bool_value, diagnostic_source_string).
    """
    raw = os.getenv(var_name)
    if raw is None:
        return default, f"default ({default})"
    cleaned = raw.strip().strip("\"'").strip().lower()
    if cleaned in ("1", "true", "t", "yes", "y", "on", "enable", "enabled"):
        return True, f"env:{var_name}='{raw.strip()}' -> True"
    if cleaned in ("0", "false", "f", "no", "n", "off", "disable", "disabled", ""):
        return False, f"env:{var_name}='{raw.strip()}' -> False"
    return default, f"env:{var_name}='{raw.strip()}' (unrecognized, using default {default})"


class Config:
    """Base Configuration with deterministic defaults."""
    ENV = os.getenv("FLASK_ENV", "production" if os.getenv("RENDER") else "development").lower()
    DEBUG = parse_bool_env("FLASK_DEBUG", default=False)[0]
    TESTING = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-t2t-drive-2026")
    PORT = int(os.getenv("PORT", "5000"))
    HOST = os.getenv("HOST", "0.0.0.0")

    # Frontend Delivery & Base URL Configuration (Phase 6 / Render Deployment)
    FRONTEND_DIR = os.getenv("FRONTEND_DIR", str((BASE_DIR.parent / "frontend").resolve()))
    BASE_URL = os.getenv("BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "http://localhost:5000")).rstrip("/")

    # Allowed CORS Origins
    _origins = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:5500,http://localhost:5000"
    )
    ALLOWED_ORIGINS = [origin.strip() for origin in _origins.split(",") if origin.strip()]
    _render_url = os.getenv("RENDER_EXTERNAL_URL")
    if _render_url and _render_url.strip() not in ALLOWED_ORIGINS:
        ALLOWED_ORIGINS.append(_render_url.strip())

    # MongoDB Atlas (supports MONGODB_URI, MONGO_URI, and MONGODB_URL with whitespace/quote stripping)
    _mongo_env = (
        os.getenv("MONGODB_URI")
        or os.getenv("MONGO_URI")
        or os.getenv("MONGODB_URL")
        or "mongodb://localhost:27017/t2t_drive"
    )
    MONGODB_URI = _mongo_env.strip().strip("\"'")
    DB_NAME = os.getenv("DB_NAME", "t2t_drive").strip().strip("\"'")

    # JWT Authentication
    JWT_SECRET = os.getenv("JWT_SECRET", "jwt-secret-t2t-drive-key-2026")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_EXPIRATION_HOURS = int(os.getenv("JWT_ACCESS_EXPIRATION_HOURS", "24"))

    # Dedicated Server-Side OTP Hashing Secret (HMAC-SHA-256)
    # Distinct from JWT_SECRET and SECRET_KEY
    OTP_HASH_SECRET = os.getenv("OTP_HASH_SECRET", "dev-otp-hash-secret-t2t-drive-2026")

    # SMS Adapter Configuration
    SMS_PROVIDER_MODE = os.getenv("SMS_PROVIDER_MODE", "mock").lower()
    SMS_API_KEY = os.getenv("SMS_API_KEY", "")
    SMS_SENDER_ID = os.getenv("SMS_SENDER_ID", "T2TDRV")
    OTP_EXPIRATION_MINUTES = 5
    OTP_RATE_LIMIT_PER_WINDOW = 3
    OTP_WINDOW_MINUTES = 10

    # Gnani Services Configuration (Phase 3 & Phase 4)
    GNANI_BASE_URL = os.getenv("GNANI_BASE_URL", "https://api.vachana.ai")
    GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")
    GNANI_PRISMA_ENDPOINT = os.getenv("GNANI_PRISMA_ENDPOINT", "https://api.vachana.ai/stt/v3")
    GNANI_TIMBRE_ENDPOINT = os.getenv("GNANI_TIMBRE_ENDPOINT", "https://api.vachana.ai/api/v1/tts/inference")
    GNANI_EVON_INFERENCE_URL = os.getenv("GNANI_EVON_INFERENCE_URL", "http://localhost:8000/v1/chat/completions")
    GNANI_EVON_MODEL_NAME = os.getenv("GNANI_EVON_MODEL_NAME", "gnani-evon")

    # External AI Extraction / LLM Provider Configuration
    LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("AI_EXTRACTION_API_KEY", os.getenv("GNANI_EVON_API_KEY", "")))
    LLM_INFERENCE_URL = os.getenv("LLM_INFERENCE_URL", os.getenv("GNANI_EVON_INFERENCE_URL", "http://localhost:8000/v1/chat/completions"))
    LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("GNANI_EVON_MODEL_NAME", "gnani-evon"))
    AI_EXTRACTION_MODE = os.getenv("AI_EXTRACTION_MODE", "rule_based").lower()
    AI_EXTRACTION_ENABLED = parse_bool_env("AI_EXTRACTION_ENABLED", default=False)[0]

    # Voice Pipeline Configuration (Phase 4)
    VOICE_PROVIDER_MODE = os.getenv("VOICE_PROVIDER_MODE", "live" if os.getenv("GNANI_API_KEY") else "mock").lower().strip().strip("\"'")
    GNANI_PRISMA_ENABLED = parse_bool_env("GNANI_PRISMA_ENABLED", default=True)[0]
    GNANI_TIMBRE_ENABLED = parse_bool_env("GNANI_TIMBRE_ENABLED", default=True)[0]
    VOICE_MAX_UPLOAD_MB = int(os.getenv("VOICE_MAX_UPLOAD_MB", "10"))
    VOICE_MAX_DURATION_SECONDS = int(os.getenv("VOICE_MAX_DURATION_SECONDS", "60"))
    VOICE_TEMP_DIRECTORY = os.getenv("VOICE_TEMP_DIRECTORY", "")

    # Phase 5: Documents, Challans, Maintenance, and Reminders Configuration
    DOCUMENT_STORAGE_MODE = os.getenv("DOCUMENT_STORAGE_MODE", "local")
    DOCUMENT_STORAGE_PATH = os.getenv("DOCUMENT_STORAGE_PATH", str(BASE_DIR / "uploads" / "documents"))
    DOCUMENT_MAX_UPLOAD_MB = int(os.getenv("DOCUMENT_MAX_UPLOAD_MB", "10"))
    DOCUMENT_ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg"]
    DOCUMENT_EXPIRY_THRESHOLDS = [30, 15, 7, 1, 0]
    OCR_ENABLED = parse_bool_env("OCR_ENABLED", default=True)[0]
    OCR_PROVIDER = os.getenv("OCR_PROVIDER", "mock")
    REMINDER_NOTIFICATION_MODE = os.getenv("REMINDER_NOTIFICATION_MODE", "mock")

    # Phase 6: Advanced Noise-Aware Speech Intelligence & Quality Analysis
    AUDIO_NOISE_ANALYSIS_ENABLED = parse_bool_env("AUDIO_NOISE_ANALYSIS_ENABLED", default=True)[0]
    AUDIO_SNR_ENABLED = parse_bool_env("AUDIO_SNR_ENABLED", default=True)[0]
    AUDIO_VAD_ENABLED = parse_bool_env("AUDIO_VAD_ENABLED", default=True)[0]
    AUDIO_ADAPTIVE_PREPROCESSING_ENABLED = parse_bool_env("AUDIO_ADAPTIVE_PREPROCESSING_ENABLED", default=True)[0]
    AUDIO_NOISE_REDUCTION_ENABLED = parse_bool_env("AUDIO_NOISE_REDUCTION_ENABLED", default=True)[0]
    AUDIO_MAX_RETRIES = int(os.getenv("AUDIO_MAX_RETRIES", "3"))
    AUDIO_QUALITY_THRESHOLD = os.getenv("AUDIO_QUALITY_THRESHOLD", "POOR")
    AUDIO_MIN_SPEECH_DURATION = float(os.getenv("AUDIO_MIN_SPEECH_DURATION", "0.2"))
    AUDIO_MAX_PROCESSING_DURATION = float(os.getenv("AUDIO_MAX_PROCESSING_DURATION", "5.0"))


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    VOICE_PROVIDER_MODE = "mock"
    GNANI_PRISMA_ENABLED = False
    GNANI_TIMBRE_ENABLED = False
    GNANI_API_KEY = ""
    MONGODB_URI = "mongomock://localhost/t2t_drive_test"
    DB_NAME = "t2t_drive_test"
    SMS_PROVIDER_MODE = "mock"
    JWT_SECRET = "test-jwt-secret-only"
    OTP_HASH_SECRET = "test-otp-hash-secret-only"
    DOCUMENT_STORAGE_PATH = str(BASE_DIR / "uploads" / "test_documents")


class ProductionConfig(Config):
    DEBUG = False
    VOICE_PROVIDER_MODE = os.getenv("VOICE_PROVIDER_MODE", "live" if os.getenv("GNANI_API_KEY") else "mock").lower().strip().strip("\"'")
    GNANI_PRISMA_ENABLED = parse_bool_env("GNANI_PRISMA_ENABLED", default=True)[0]
    GNANI_TIMBRE_ENABLED = parse_bool_env("GNANI_TIMBRE_ENABLED", default=True)[0]

    @classmethod
    def validate(cls):
        """
        Validates that all required secrets are provided and meet strength criteria.
        Refuses to start with development placeholders or short keys.
        Never prints secret values in error messages.
        """
        secret_key = os.getenv("SECRET_KEY", "").strip()
        if not secret_key or secret_key.startswith("dev-") or len(secret_key) < 32:
            raise ValueError(
                "CRITICAL: Production SECRET_KEY must be explicitly set and at least 32 characters long."
            )

        jwt_secret = os.getenv("JWT_SECRET", "").strip()
        if not jwt_secret or jwt_secret.startswith("dev-") or "t2t-drive" in jwt_secret.lower() or len(jwt_secret) < 32:
            raise ValueError(
                "CRITICAL: Production JWT_SECRET must be explicitly set and at least 32 characters long."
            )

        otp_secret = os.getenv("OTP_HASH_SECRET", "").strip()
        if not otp_secret or otp_secret.startswith("dev-") or "t2t-drive" in otp_secret.lower() or len(otp_secret) < 32:
            raise ValueError(
                "CRITICAL: Production OTP_HASH_SECRET must be explicitly set and at least 32 characters long."
            )

        # Enforce Real Gnani AI Voice Configuration in Live Production Mode
        voice_mode = os.getenv("VOICE_PROVIDER_MODE", "live" if os.getenv("GNANI_API_KEY") else "mock").lower()
        if voice_mode == "live":
            gnani_key = os.getenv("GNANI_API_KEY", "").strip()
            if not gnani_key or gnani_key.startswith("dev-") or gnani_key.startswith("mock-") or len(gnani_key) < 8:
                raise ValueError(
                    "CRITICAL: Production GNANI_API_KEY must be set to a valid provider key when VOICE_PROVIDER_MODE='live'. "
                    "Silent fallback to mock responses is strictly forbidden in production."
                )


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    return config_by_name.get(env, DevelopmentConfig)
