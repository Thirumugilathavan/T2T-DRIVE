from flask import Blueprint, current_app
from app.utils.responses import success_response, error_response
from app.database.connection import db_manager

health_bp = Blueprint("health", __name__, url_prefix="/api/health")

@health_bp.route("", methods=["GET"])
def health_check():
    """Basic health check verifying Flask backend application is responsive."""
    return success_response({
        "status": "UP",
        "service": "T2T DRIVE Backend",
        "version": "1.0.0-phase1",
        "environment": current_app.config.get("ENV", "development")
    })

@health_bp.route("/db", methods=["GET"])
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
