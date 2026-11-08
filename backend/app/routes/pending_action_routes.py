"""
Pending Action Management Flask API Routes for T2T DRIVE.
Allows drivers to inspect active pending confirmation requests or cancel them.
"""

from flask import Blueprint, request, current_app, g
from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth
from app.services.pending_action_service import (
    PendingActionUnauthorizedError,
    PendingActionExpiredError,
    PendingActionCancelledError,
    PendingActionAlreadyConsumedError
)
from app.services.idempotency_service import (
    IdempotencyConflictError,
    OperationInProgressError
)

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


@pending_action_bp.route("/<pending_action_id>/confirm", methods=["POST"])
@require_auth
def confirm_pending_action(pending_action_id):
    """
    Explicit driver confirmation of any pending action (expense, income, settlement, maintenance).
    Consumes the action atomically and commits to the ledger.
    """
    body = request.get_json(silent=True) or {}
    idempotency_key = body.get("idempotency_key") or f"CONFIRM_{pending_action_id}"

    pending_svc = current_app.extensions["pending_action_service"]
    idempotency_svc = current_app.extensions.get("idempotency_service")

    try:
        if idempotency_svc:
            is_cached, cached_res = idempotency_svc.start_operation(
                driver_id=g.driver_id,
                idempotency_key=idempotency_key,
                operation_type="CONFIRM_PENDING_ACTION",
                payload={"pending_action_id": pending_action_id}
            )
            if is_cached:
                return success_response(cached_res)

        result = pending_svc.confirm_action(
            pending_action_id=pending_action_id,
            driver_id=g.driver_id,
            idempotency_key=idempotency_key
        )

        if idempotency_svc:
            idempotency_svc.complete_operation(
                driver_id=g.driver_id,
                idempotency_key=idempotency_key,
                operation_type="CONFIRM_PENDING_ACTION",
                resource_id=result.get("transaction_id", pending_action_id),
                response_data=result
            )

        return success_response(result, status_code=200)

    except PendingActionUnauthorizedError as err:
        return error_response(code="UNAUTHORIZED_FINANCIAL_ACCESS", message=str(err), status_code=403)
    except PendingActionExpiredError as err:
        return error_response(code="PENDING_ACTION_EXPIRED", message=str(err), status_code=410)
    except PendingActionCancelledError as err:
        return error_response(code="PENDING_ACTION_CANCELLED", message=str(err), status_code=400)
    except PendingActionAlreadyConsumedError as err:
        return error_response(code="PENDING_ACTION_ALREADY_CONSUMED", message=str(err), status_code=400)
    except IdempotencyConflictError as err:
        return error_response(code="IDEMPOTENCY_CONFLICT", message=str(err), status_code=409)
    except OperationInProgressError as err:
        return error_response(code="DUPLICATE_OPERATION", message=str(err), status_code=409)
    except ValueError as err:
        return error_response(code="INVALID_CONFIRMATION", message=str(err), status_code=400)
    except Exception as err:
        return error_response(code="CONFIRMATION_FAILED", message=str(err), status_code=500)


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
