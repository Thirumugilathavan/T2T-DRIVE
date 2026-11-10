import os
from flask import Blueprint, current_app
from app.utils.responses import success_response, error_response
from app.database.connection import db_manager

health_bp = Blueprint("health", __name__, url_prefix="/api/health")

@health_bp.route("", methods=["GET"], strict_slashes=False)
@health_bp.route("/", methods=["GET"], strict_slashes=False)
def health_check():
    """Structured health check verifying Flask backend, database, and provider statuses."""
    cfg = current_app.config
    is_connected = db_manager.is_connected()
    is_mock = db_manager.is_mock()

    environment = "production" if (os.getenv("RENDER") or cfg.get("ENV") == "production") else cfg.get("ENV", "development")

    voice_mode = cfg.get("VOICE_PROVIDER_MODE", "mock").lower()
    has_key = bool(cfg.get("GNANI_API_KEY", "").strip())
    prisma_live = bool(voice_mode == "live" and has_key and cfg.get("GNANI_PRISMA_ENABLED"))
    timbre_live = bool(voice_mode == "live" and has_key and cfg.get("GNANI_TIMBRE_ENABLED"))
    llm_configured = bool(cfg.get("LLM_API_KEY"))

    data = {
        "status": "UP",
        "service": "T2T DRIVE Backend",
        "version": "1.0.0-phase1",
        "environment": environment,
        "database": {
            "connected": is_connected,
            "mode": "MOCK" if is_mock else ("LIVE_ATLAS" if is_connected else "DISCONNECTED"),
            "name": cfg.get("DB_NAME", "t2t_drive")
        },
        "providers": {
            "voice_mode": voice_mode,
            "gnani_prisma": "LIVE" if prisma_live else "MOCK",
            "gnani_timbre": "LIVE" if timbre_live else "MOCK",
            "llm_adapter": {
                "mode": cfg.get("AI_EXTRACTION_MODE", "rule_based"),
                "configured": llm_configured,
                "model": cfg.get("LLM_MODEL", "gnani-evon")
            }
        }
    }
    return success_response(data)

@health_bp.route("/db", methods=["GET"], strict_slashes=False)
@health_bp.route("/db/", methods=["GET"], strict_slashes=False)
def database_health():
    """Checks MongoDB Atlas connectivity and connection mode."""
    is_connected = db_manager.is_connected()
    is_mock = db_manager.is_mock()

    data = {
        "database_connected": is_connected,
        "database_mode": "MOCK" if is_mock else "LIVE_ATLAS",
        "database_name": current_app.config.get("DB_NAME")
    }

    if not is_connected:
        return error_response(
            code="DATABASE_UNAVAILABLE",
            message="Database connection could not be established.",
            details=data,
            status_code=503
        )

    return success_response(data)
