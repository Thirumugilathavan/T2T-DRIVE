"""
Settlement Flask API Routes for T2T DRIVE.
Manages owner-driver rental reconciliations and versioning.
Requires explicit confirmation for settlement creation and recalculation.
"""

from flask import Blueprint, request, current_app, g
from pydantic import ValidationError
from decimal import Decimal

from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth
from app.models.financial import PendingActionType
from app.schemas.financial import (
    ProposeSettlementRequest,
    ConfirmPendingActionRequest,
    RecalculateSettlementRequest
)
from app.services.idempotency_service import IdempotencyConflictError, OperationInProgressError
from app.services.pending_action_service import (
    PendingActionExpiredError,
    PendingActionCancelledError,
    PendingActionAlreadyConsumedError,
    PendingActionUnauthorizedError
)

settlement_bp = Blueprint("settlements", __name__, url_prefix="/api/settlements")


@settlement_bp.route("/propose", methods=["POST"])
@require_auth
def propose_settlement():
    """
    Step 1: Proposes an owner-driver settlement for a vehicle and date.
    Creates a PENDING action. Does NOT finalize the settlement.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = ProposeSettlementRequest(**body)
    except (ValidationError, ValueError) as err:
        return error_response(code="INVALID_SETTLEMENT", message=str(err), status_code=400)

    pending_svc = current_app.extensions["pending_action_service"]
    proposed_data = {
        "vehicle_id": req.vehicle_id,
        "settlement_date": req.settlement_date,
        "shift_id": req.shift_id,
        "previous_balance": str(req.previous_balance)
    }

    try:
        result = pending_svc.propose_action(
            driver_id=g.driver_id,
            action_type=PendingActionType.CREATE_SETTLEMENT,
            proposed_data=proposed_data,
            idempotency_key=req.idempotency_key
        )
        return success_response(result, status_code=201)
    except Exception as err:
        return error_response(code="PROPOSAL_FAILED", message=str(err), status_code=400)


@settlement_bp.route("/<pending_action_id>/confirm", methods=["POST"])
@require_auth
def confirm_settlement(pending_action_id):
    """
    Step 2: Explicit driver confirmation of a proposed settlement.
    Reconciles against the ledger and creates the version 1 settlement record.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = ConfirmPendingActionRequest(**body)
    except (ValidationError, ValueError) as err:
        return error_response(code="VALIDATION_ERROR", message=str(err), status_code=400)

    pending_svc = current_app.extensions["pending_action_service"]
    idempotency_svc = current_app.extensions.get("idempotency_service")

    try:
        if idempotency_svc:
            is_cached, cached_res = idempotency_svc.start_operation(
                driver_id=g.driver_id,
                idempotency_key=req.idempotency_key,
                operation_type="CONFIRM_SETTLEMENT",
                payload={"pending_action_id": pending_action_id}
            )
            if is_cached:
                return success_response(cached_res)

        result = pending_svc.confirm_action(
            pending_action_id=pending_action_id,
            driver_id=g.driver_id,
            idempotency_key=req.idempotency_key
        )

        if idempotency_svc:
            idempotency_svc.complete_operation(
                driver_id=g.driver_id,
                idempotency_key=req.idempotency_key,
                operation_type="CONFIRM_SETTLEMENT",
                resource_id=result.get("settlement_id", pending_action_id),
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
        return error_response(code="SETTLEMENT_CONFLICT", message=str(err), status_code=400)
    except Exception as err:
        return error_response(code="FINANCIAL_OPERATION_FAILED", message=str(err), status_code=500)


@settlement_bp.route("", methods=["GET"])
@require_auth
def list_settlements():
    """Lists settlements for the authenticated driver."""
    settle_svc = current_app.extensions["settlement_service"]
    vehicle_id = request.args.get("vehicle_id")

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 50))))
    except ValueError:
        return error_response(code="INVALID_PAGINATION", message="Page and limit must be positive integers.", status_code=400)

    skip = (page - 1) * limit
    results = settle_svc.list_driver_settlements(
        driver_id=g.driver_id,
        vehicle_id=vehicle_id,
        limit=limit,
        skip=skip
    )
    return success_response({
        "settlements": results,
        "page": page,
        "limit": limit
    })


@settlement_bp.route("/<settlement_id>", methods=["GET"])
@require_auth
def get_settlement(settlement_id):
    """Retrieves a single settlement by ID. Scoped strictly to authenticated driver."""
    settle_svc = current_app.extensions["settlement_service"]
    doc = settle_svc.get_settlement(settlement_id, driver_id=g.driver_id)
    if not doc:
        return error_response(
            code="SETTLEMENT_NOT_FOUND",
            message=f"Settlement '{settlement_id}' not found.",
            status_code=404
        )
    return success_response(doc)


@settlement_bp.route("/<settlement_id>/recalculate", methods=["POST"])
@require_auth
def propose_recalculation(settlement_id):
    """
    Proposes recalculation of an existing settlement.
    Creates a PENDING action of type RECALCULATE_SETTLEMENT.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = RecalculateSettlementRequest(**body)
    except (ValidationError, ValueError) as err:
        return error_response(code="INVALID_REQUEST", message=str(err), status_code=400)

    settle_svc = current_app.extensions["settlement_service"]
    existing = settle_svc.get_settlement(settlement_id, driver_id=g.driver_id)
    if not existing:
        return error_response(code="SETTLEMENT_NOT_FOUND", message=f"Settlement '{settlement_id}' not found.", status_code=404)

    pending_svc = current_app.extensions["pending_action_service"]
    proposed_data = {
        "settlement_id": settlement_id,
        "reason": req.reason
    }

    try:
        result = pending_svc.propose_action(
            driver_id=g.driver_id,
            action_type=PendingActionType.RECALCULATE_SETTLEMENT,
            proposed_data=proposed_data,
            idempotency_key=req.idempotency_key
        )
        return success_response(result, status_code=201)
    except Exception as err:
        return error_response(code="PROPOSAL_FAILED", message=str(err), status_code=400)
