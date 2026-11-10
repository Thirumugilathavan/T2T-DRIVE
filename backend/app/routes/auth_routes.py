from flask import Blueprint, request, current_app, g
from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

@auth_bp.route("/request-otp", methods=["POST"])
def request_otp():
    """Generates and delivers OTP to driver phone with rate limiting."""
    body = request.get_json(silent=True) or {}
    phone = body.get("phone", "").strip()

    if not phone:
        return error_response(
            code="VALIDATION_ERROR",
            message="Field 'phone' is required.",
            status_code=400
        )

    auth_service = current_app.extensions["auth_service"]
    try:
        result = auth_service.request_otp(phone)
    except ValueError as err:
        return error_response(
            code="INVALID_PHONE",
            message=str(err),
            status_code=400
        )

    if not result.get("success"):
        return error_response(
            code=result.get("error", "OTP_FAILED"),
            message=result.get("message", "Failed to send OTP."),
            status_code=429 if result.get("error") == "RATE_LIMIT_EXCEEDED" else 400
        )

    return success_response(result)


@auth_bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    """Verifies OTP and issues signed JWT access token."""
    body = request.get_json(silent=True) or {}
    phone = body.get("phone", "").strip()
    otp = str(body.get("otp", "")).strip()

    if not phone or not otp:
        return error_response(
            code="VALIDATION_ERROR",
            message="Both 'phone' and 'otp' are required fields.",
            status_code=400
        )

    auth_service = current_app.extensions["auth_service"]
    try:
        result = auth_service.verify_otp(phone, otp)
    except ValueError as err:
        return error_response(
            code="INVALID_PHONE",
            message=str(err),
            status_code=400
        )

    if not result.get("success"):
        return error_response(
            code=result.get("error", "VERIFICATION_FAILED"),
            message=result.get("message", "OTP verification failed."),
            status_code=400
        )

    return success_response(result)


@auth_bp.route("/verify-pin", methods=["POST"])
def verify_pin():
    """Fallback 4-digit PIN verification."""
    body = request.get_json(silent=True) or {}
    phone = body.get("phone", "").strip()
    pin = str(body.get("pin", "")).strip()

    if not phone or not pin:
        return error_response(
            code="VALIDATION_ERROR",
            message="Both 'phone' and 'pin' are required fields.",
            status_code=400
        )

    auth_service = current_app.extensions["auth_service"]
    try:
        result = auth_service.verify_pin(phone, pin)
    except ValueError as err:
        return error_response(
            code="INVALID_PHONE",
            message=str(err),
            status_code=400
        )

    if not result.get("success"):
        return error_response(
            code=result.get("error", "PIN_FAILED"),
            message=result.get("message", "PIN verification failed."),
            status_code=401
        )

    return success_response(result)


@auth_bp.route("/me", methods=["GET"])
@require_auth
def get_current_driver():
    """Returns profile of current authenticated driver. Enforces token subject."""
    db = current_app.extensions["db"]
    driver = db.drivers.find_one({"driver_id": g.driver_id})

    if not driver:
        return error_response(
            code="DRIVER_NOT_FOUND",
            message="Driver profile not found.",
            status_code=404
        )

    return success_response({
        "driver_id": driver["driver_id"],
        "name": driver.get("name", "Auto Driver"),
        "phone": driver["phone"],
        "preferred_language": driver.get("preferred_language", "tanglish"),
        "default_vehicle_id": driver.get("default_vehicle_id"),
        "status": driver.get("status", "ACTIVE")
    })


@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    """Terminates session for authenticated driver and revokes token server-side."""
    auth_service = current_app.extensions["auth_service"]
    auth_service.revoke_token(
        jti=g.jti,
        session_id=g.session_id,
        driver_id=g.driver_id,
        exp_timestamp=g.token_exp
    )
    return success_response({
        "message": "Successfully logged out.",
        "session_id": g.session_id
    })


@auth_bp.route("/demo-session", methods=["POST", "GET"])
@auth_bp.route("/session", methods=["POST", "GET"])
def demo_session():
    """
    Issues an isolated JWT access token for academic/evaluation guest demo (DRV_DEMO_GUEST).
    Embeds is_demo=True claim and role='DEMO'.
    Direct ledger modifications and real financial writes are strictly blocked.
    """
    db = current_app.extensions["db"]
    auth_service = current_app.extensions["auth_service"]
    driver_id = "DRV_DEMO_GUEST"
    driver = db.drivers.find_one({"driver_id": driver_id})
    if not driver:
        driver = {
            "driver_id": driver_id,
            "name": "Demo Guest Driver",
            "phone": "+919999900000",
            "preferred_language": "tanglish",
            "default_vehicle_id": "TN-01-DEMO-2026",
            "status": "ACTIVE",
            "is_demo": True
        }
        db.drivers.insert_one(driver)

    token = auth_service.generate_jwt_token(driver_id, is_demo=True, role="DEMO")
    return success_response({
        "token": token,
        "is_demo": True,
        "driver": {
            "driver_id": driver["driver_id"],
            "name": driver.get("name", "Demo Guest Driver"),
            "phone": driver.get("phone", "+919999900000"),
            "preferred_language": driver.get("preferred_language", "tanglish"),
            "default_vehicle_id": driver.get("default_vehicle_id", "TN-01-DEMO-2026"),
            "is_demo": True
        }
    })
