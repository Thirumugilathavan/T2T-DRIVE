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


# ============================================================================
# OWNER-DRIVER VEHICLE MANAGEMENT & OUTSTANDING RENT
# ============================================================================

@settlement_bp.route("/vehicles", methods=["POST"])
@require_auth
def register_or_update_vehicle():
    """
    Registers or updates vehicle rental configuration and driver assignment.
    """
    body = request.get_json(silent=True) or {}
    vehicle_id = body.get("vehicle_id") or body.get("registration_number")
    if not vehicle_id:
        return error_response(code="INVALID_REQUEST", message="vehicle_id is required.", status_code=400)

    owner_id = body.get("owner_id") or g.driver_id
    vehicle_type = body.get("vehicle_type", "AUTO_RICKSHAW")
    registration_number = body.get("registration_number", vehicle_id)
    rent_type = body.get("rent_type", "FIXED_RENT")
    rent_amount_raw = body.get("rent_amount", "350.00")
    rent_frequency = body.get("rent_frequency", "DAILY").upper()
    assigned_driver_ids = body.get("assigned_driver_ids", [])

    try:
        rent_amount = Decimal(str(rent_amount_raw))
    except Exception:
        return error_response(code="INVALID_RENT", message="Invalid rent_amount format.", status_code=400)

    settle_svc = current_app.extensions["settlement_service"]
    try:
        vehicle = settle_svc.register_or_update_vehicle(
            vehicle_id=vehicle_id,
            owner_id=owner_id,
            vehicle_type=vehicle_type,
            registration_number=registration_number,
            rent_type=rent_type,
            rent_amount=rent_amount,
            rent_frequency=rent_frequency,
            assigned_driver_ids=assigned_driver_ids,
            actor_id=g.driver_id
        )
        return success_response({"vehicle": vehicle}, status_code=201)
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED", message=str(pe), status_code=403)
    except Exception as err:
        return error_response(code="VEHICLE_REGISTRATION_FAILED", message=str(err), status_code=400)


@settlement_bp.route("/vehicles", methods=["GET"])
@require_auth
def list_vehicles():
    """
    Lists vehicles accessible to the authenticated driver or owner.
    """
    settle_svc = current_app.extensions["settlement_service"]
    vehicles = settle_svc.list_vehicles(owner_id=g.driver_id, driver_id=g.driver_id)
    return success_response({"vehicles": vehicles, "total": len(vehicles)})


@settlement_bp.route("/vehicles/<vehicle_id>", methods=["GET"])
@require_auth
def get_vehicle(vehicle_id):
    """
    Retrieves vehicle configuration and rental terms.
    """
    settle_svc = current_app.extensions["settlement_service"]
    vehicle = settle_svc.get_vehicle(vehicle_id, actor_id=g.driver_id)
    if not vehicle:
        return error_response(code="VEHICLE_NOT_FOUND", message=f"Vehicle '{vehicle_id}' not found.", status_code=404)
    return success_response({"vehicle": vehicle})


@settlement_bp.route("/vehicles/<vehicle_id>/assign", methods=["POST"])
@require_auth
def assign_vehicle_driver(vehicle_id):
    """
    Assigns or links a driver to an existing vehicle.
    """
    body = request.get_json(silent=True) or {}
    driver_id = body.get("driver_id")
    if not driver_id:
        return error_response(code="INVALID_REQUEST", message="driver_id is required.", status_code=400)

    settle_svc = current_app.extensions["settlement_service"]
    try:
        vehicle = settle_svc.assign_driver_to_vehicle(
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            owner_id=g.driver_id
        )
        return success_response({"vehicle": vehicle})
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED", message=str(pe), status_code=403)
    except ValueError as ve:
        return error_response(code="VEHICLE_NOT_FOUND", message=str(ve), status_code=404)
    except Exception as err:
        return error_response(code="ASSIGNMENT_FAILED", message=str(err), status_code=400)


@settlement_bp.route("/outstanding", methods=["GET"])
@require_auth
def get_outstanding_rent():
    """
    Queries driver's current carried-forward outstanding rent and latest settlement.
    """
    settle_svc = current_app.extensions["settlement_service"]
    vehicle_id = request.args.get("vehicle_id")
    outstanding = settle_svc.get_outstanding_rent(driver_id=g.driver_id, vehicle_id=vehicle_id)
    return success_response(outstanding)
