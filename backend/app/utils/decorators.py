from functools import wraps
from flask import request, g, current_app
import jwt
from app.utils.responses import error_response

def require_auth(f):
    """
    Decorator enforcing cryptographic JWT token authentication.
    Extracts verified driver identity and sets `g.driver_id` and `g.session_id`.
    Rejects any unauthenticated or tampered request with HTTP 401.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error_response(
                code="UNAUTHORIZED",
                message="Missing or malformed Authorization header. Expected 'Bearer <token>'.",
                status_code=401
            )

        token = auth_header.split(" ", 1)[1].strip()
        auth_service = current_app.extensions.get("auth_service")

        try:
            payload = auth_service.decode_jwt_token(token)
            # Store verified claims in Flask g context
            g.driver_id = payload.get("sub")
            g.session_id = payload.get("session_id")
            g.jti = payload.get("jti")
            g.token_exp = payload.get("exp")
            g.is_demo = bool(payload.get("is_demo", False))
            g.role = payload.get("role", "DRIVER")
            request.driver_id = g.driver_id
            request.is_demo = g.is_demo

            if not g.driver_id:
                return error_response(
                    code="UNAUTHORIZED",
                    message="Token missing driver subject claim.",
                    status_code=401
                )

            # Server-Side Revocation Check
            if g.jti and auth_service.is_token_revoked(g.jti):
                return error_response(
                    code="TOKEN_REVOKED",
                    message="This session has been logged out. Please log in again.",
                    status_code=401
                )

        except jwt.ExpiredSignatureError:
            return error_response(
                code="TOKEN_EXPIRED",
                message="Authentication token has expired. Please log in again.",
                status_code=401
            )
        except jwt.PyJWTError as err:
            return error_response(
                code="INVALID_TOKEN",
                message="Invalid authentication token.",
                details=str(err),
                status_code=401
            )

        return f(*args, **kwargs)

    return decorated_function


# Compatibility alias
token_required = require_auth
