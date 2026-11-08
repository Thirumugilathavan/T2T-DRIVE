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
@require_auth
def chat():
    """
    Primary conversational endpoint. Processes natural voice/text input
    through the LangGraph state machine.
    """
    body = request.get_json(silent=True) or {}
    message = body.get("message", "").strip()

    if not message:
        return error_response(
            code="INVALID_MESSAGE",
            message="Field 'message' is required and must not be empty.",
            status_code=400
        )

    session_id = body.get("session_id")
    language = body.get("language")

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
