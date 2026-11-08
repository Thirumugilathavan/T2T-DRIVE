"""
Conversational Agent REST API Routes for T2T DRIVE.
Exposes endpoints for driver chat, session management, and message history.
Enforces JWT authentication and session-level driver isolation.
"""

from flask import Blueprint, request, current_app, g
from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth

agent_bp = Blueprint("agent", __name__, url_prefix="/api/agent")


@agent_bp.route("/chat", methods=["POST"])
@agent_bp.route("/message", methods=["POST"])
@require_auth
def chat():
    """
    Primary conversational endpoint. Processes natural voice/text input
    through the LangGraph state machine.
    Supports both /chat and /message endpoints.
    """
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or body.get("text") or "").strip()

    if not message:
        return error_response(
            code="INVALID_MESSAGE",
            message="Field 'message' or 'text' is required and must not be empty.",
            status_code=400
        )

    session_id = body.get("session_id") or body.get("session")
    language = body.get("language") or body.get("lang")

    agent_svc = current_app.extensions["agent_service"]
    try:
        response_data = agent_svc.process_message(
            driver_id=g.driver_id,
            message=message,
            session_id=session_id,
            language=language
        )
        return success_response(response_data)
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED_SESSION", message=str(pe), status_code=403)
    except Exception as e:
        current_app.logger.error("Chat error for driver %s: %s", g.driver_id, e)
        return error_response(code="AGENT_PROCESSING_ERROR", message=str(e), status_code=500)


@agent_bp.route("/confirm", methods=["POST"])
@require_auth
def agent_confirm():
    """Direct button confirmation endpoint compatible with frontend/js/api.js."""
    body = request.get_json(silent=True) or {}
    pending_id = body.get("pending_id") or body.get("pending_action_id")
    decision = body.get("yes_or_no", True)

    if not pending_id:
        return error_response(
            code="MISSING_PENDING_ID",
            message="Field 'pending_id' is required.",
            status_code=400
        )

    pending_svc = current_app.extensions["pending_action_service"]
    try:
        if decision:
            exec_key = f"AGENT_BTN_EXEC_{pending_id}"
            res = pending_svc.confirm_action(
                pending_action_id=pending_id,
                driver_id=g.driver_id,
                idempotency_key=exec_key
            )
        else:
            res = pending_svc.cancel_action(
                pending_action_id=pending_id,
                driver_id=g.driver_id,
                reason="Driver clicked Cancel button"
            )
        return success_response(res)
    except Exception as e:
        current_app.logger.error("Agent confirm error for driver %s: %s", g.driver_id, e)
        return error_response(code="CONFIRM_ERROR", message=str(e), status_code=400)


@agent_bp.route("/sessions", methods=["POST"])
@require_auth
def create_session():
    """Explicitly initializes a new conversation session."""
    body = request.get_json(silent=True) or {}
    language = body.get("language", "tanglish")
    vehicle_id = body.get("vehicle_id")

    agent_svc = current_app.extensions["agent_service"]
    session = agent_svc.create_session(
        driver_id=g.driver_id,
        language=language,
        vehicle_id=vehicle_id
    )
    return success_response(session, status_code=201)


@agent_bp.route("/sessions", methods=["GET"])
@require_auth
def list_sessions():
    """Retrieves all conversation sessions belonging to the authenticated driver."""
    limit = request.args.get("limit", 20, type=int)
    agent_svc = current_app.extensions["agent_service"]
    sessions = agent_svc.list_sessions(driver_id=g.driver_id, limit=limit)
    return success_response(sessions)


@agent_bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth
def get_session_details(session_id: str):
    """Retrieves session metadata and full message history."""
    agent_svc = current_app.extensions["agent_service"]
    try:
        session = agent_svc.get_session(session_id=session_id, driver_id=g.driver_id)
        if not session:
            return error_response(code="SESSION_NOT_FOUND", message=f"Session '{session_id}' not found.", status_code=404)

        messages = agent_svc.get_session_messages(session_id=session_id, driver_id=g.driver_id)
        return success_response({
            "session": session,
            "messages": messages
        })
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED_SESSION", message=str(pe), status_code=403)
