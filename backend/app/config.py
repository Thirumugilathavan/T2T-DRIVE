import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of backend
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)


class Config:
    """Base Configuration with deterministic defaults."""
    ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    TESTING = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-t2t-drive-2026")
    PORT = int(os.getenv("PORT", "5000"))
    HOST = os.getenv("HOST", "0.0.0.0")

    # Allowed CORS Origins
    _origins = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:5500,http://localhost:5000"
    )
    ALLOWED_ORIGINS = [origin.strip() for origin in _origins.split(",") if origin.strip()]

    # MongoDB Atlas
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/t2t_drive")
    DB_NAME = os.getenv("DB_NAME", "t2t_drive")

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

    # Gnani Services Configuration (Provisional / Configurable)
    GNANI_BASE_URL = os.getenv("GNANI_BASE_URL", "https://api.vachana.ai")
    GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")
    GNANI_PRISMA_ENDPOINT = os.getenv("GNANI_PRISMA_ENDPOINT", "https://api.vachana.ai/stt/v3")
    GNANI_TIMBRE_ENDPOINT = os.getenv("GNANI_TIMBRE_ENDPOINT", "https://api.vachana.ai/api/v1/tts/inference")
    GNANI_EVON_INFERENCE_URL = os.getenv("GNANI_EVON_INFERENCE_URL", "http://localhost:8000/v1/chat/completions")
    GNANI_EVON_MODEL_NAME = os.getenv("GNANI_EVON_MODEL_NAME", "gnani-evon")


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    MONGODB_URI = "mongomock://localhost/t2t_drive_test"
    DB_NAME = "t2t_drive_test"
    SMS_PROVIDER_MODE = "mock"
    JWT_SECRET = "test-jwt-secret-only"
    OTP_HASH_SECRET = "test-otp-hash-secret-only"


class ProductionConfig(Config):
    DEBUG = False

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


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    return config_by_name.get(env, DevelopmentConfig)
