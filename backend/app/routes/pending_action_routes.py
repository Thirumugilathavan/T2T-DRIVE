"""
Pending Action Management Flask API Routes for T2T DRIVE.
Allows drivers to inspect active pending confirmation requests or cancel them.
"""

from flask import Blueprint, request, current_app, g
from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth
from app.services.pending_action_service import PendingActionUnauthorizedError

pending_action_bp = Blueprint("pending_actions", __name__, url_prefix="/api/pending-actions")


@pending_action_bp.route("", methods=["GET"])
@require_auth
def list_pending_actions():
    """Lists pending actions for the authenticated driver."""
    pending_svc = current_app.extensions["pending_action_service"]
    status = request.args.get("status")
    actions = pending_svc.list_driver_pending_actions(driver_id=g.driver_id, status=status)
    return success_response(actions)


@pending_action_bp.route("/<pending_action_id>", methods=["GET"])
@require_auth
def get_pending_action(pending_action_id):
    """Retrieves a single pending action. Scoped strictly to authenticated driver."""
    pending_svc = current_app.extensions["pending_action_service"]
    action = pending_svc.get_pending_action(pending_action_id=pending_action_id, driver_id=g.driver_id)
    if not action:
        return error_response(
            code="PENDING_ACTION_NOT_FOUND",
            message=f"Pending action '{pending_action_id}' not found.",
            status_code=404
        )
    return success_response(action)


@pending_action_bp.route("/<pending_action_id>/cancel", methods=["POST"])
@require_auth
def cancel_pending_action(pending_action_id):
    """Cancels an unconfirmed pending action."""
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "Cancelled by driver")

    pending_svc = current_app.extensions["pending_action_service"]
    try:
        result = pending_svc.cancel_action(
            pending_action_id=pending_action_id,
            driver_id=g.driver_id,
            reason=reason
        )
        return success_response(result)
    except PendingActionUnauthorizedError as err:
        return error_response(code="UNAUTHORIZED_FINANCIAL_ACCESS", message=str(err), status_code=403)
    except ValueError as err:
        return error_response(code="INVALID_OPERATION", message=str(err), status_code=400)
    except Exception as err:
        return error_response(code="CANCELLATION_FAILED", message=str(err), status_code=500)
