"""
Transaction and Ledger Flask API Routes for T2T DRIVE.
Enforces that every financial transaction, reversal, and adjustment passes
through the explicit confirmation workflow.
"""

from flask import Blueprint, request, current_app, g
from pydantic import ValidationError
from decimal import Decimal

from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth
from app.models.financial import PendingActionType, TransactionType
from app.schemas.financial import (
    ProposeTransactionRequest,
    ConfirmPendingActionRequest,
    AdjustTransactionRequest,
    ReverseTransactionRequest
)
from app.services.idempotency_service import IdempotencyConflictError, OperationInProgressError
from app.services.pending_action_service import (
    PendingActionExpiredError,
    PendingActionCancelledError,
    PendingActionAlreadyConsumedError,
    PendingActionUnauthorizedError
)

transaction_bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")


@transaction_bp.route("/propose", methods=["POST"])
@require_auth
def propose_transaction():
    """
    Step 1: Proposes a financial transaction (income, expense, or owner payment).
    Creates a PENDING action. Does NOT write to the ledger.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = ProposeTransactionRequest(**body)
    except (ValidationError, ValueError, TypeError) as err:
        return error_response(
            code="INVALID_TRANSACTION",
            message=f"Validation failed: {str(err)}",
            status_code=400
        )

    pending_svc = current_app.extensions["pending_action_service"]
    idempotency_svc = current_app.extensions.get("idempotency_service")

    # Map transaction type to pending action type
    action_type_map = {
        TransactionType.INCOME: PendingActionType.ADD_INCOME,
        TransactionType.EXPENSE: PendingActionType.ADD_EXPENSE,
        TransactionType.OWNER_PAYMENT: PendingActionType.ADD_OWNER_PAYMENT,
    }
    action_type = action_type_map.get(req.transaction_type)
    if not action_type:
        return error_response(
            code="INVALID_TRANSACTION_TYPE",
            message=f"Unsupported transaction type: {req.transaction_type}",
            status_code=400
        )

    proposed_data = {
        "vehicle_id": req.vehicle_id,
        "amount": str(req.amount),
        "category": req.category,
        "description": req.description,
        "transaction_date": req.transaction_date,
        "source": req.source,
        "reference_id": req.reference_id
    }

    try:
        if idempotency_svc:
            is_cached, cached_res = idempotency_svc.start_operation(
                driver_id=g.driver_id,
                idempotency_key=req.idempotency_key,
                operation_type="PROPOSE_TRANSACTION",
                payload=proposed_data
            )
            if is_cached:
                return success_response(cached_res)

        result = pending_svc.propose_action(
            driver_id=g.driver_id,
            action_type=action_type,
            proposed_data=proposed_data,
            idempotency_key=req.idempotency_key
        )

        if idempotency_svc:
            idempotency_svc.complete_operation(
                driver_id=g.driver_id,
                idempotency_key=req.idempotency_key,
                operation_type="PROPOSE_TRANSACTION",
                resource_id=result["pending_action_id"],
                response_data=result
            )

        return success_response(result, status_code=201)

    except IdempotencyConflictError as err:
        return error_response(code="IDEMPOTENCY_CONFLICT", message=str(err), status_code=409)
    except OperationInProgressError as err:
        return error_response(code="DUPLICATE_OPERATION", message=str(err), status_code=409)
    except Exception as err:
        return error_response(code="PROPOSAL_FAILED", message=str(err), status_code=400)


@transaction_bp.route("/<pending_action_id>/confirm", methods=["POST"])
@require_auth
def confirm_transaction(pending_action_id):
    """
    Step 2: Explicit driver confirmation of a pending financial action.
    Consumes the action atomically and writes to the append-only ledger.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = ConfirmPendingActionRequest(**body)
    except (ValidationError, ValueError) as err:
        return error_response(
            code="VALIDATION_ERROR",
            message=f"Validation failed: {str(err)}",
            status_code=400
        )

    pending_svc = current_app.extensions["pending_action_service"]
    idempotency_svc = current_app.extensions.get("idempotency_service")

    try:
        if idempotency_svc:
            is_cached, cached_res = idempotency_svc.start_operation(
                driver_id=g.driver_id,
                idempotency_key=req.idempotency_key,
                operation_type="CONFIRM_TRANSACTION",
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
                operation_type="CONFIRM_TRANSACTION",
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
        return error_response(code="FINANCIAL_OPERATION_FAILED", message=str(err), status_code=500)


@transaction_bp.route("", methods=["GET"])
@require_auth
def list_transactions():
    """
    Retrieves paginated ledger transactions for the authenticated driver.
    """
    ledger_svc = current_app.extensions["ledger_service"]
    vehicle_id = request.args.get("vehicle_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 50))))
    except ValueError:
        return error_response(code="INVALID_PAGINATION", message="Page and limit must be positive integers.", status_code=400)

    result = ledger_svc.list_driver_transactions(
        driver_id=g.driver_id,
        vehicle_id=vehicle_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        limit=limit
    )
    return success_response(result)


@transaction_bp.route("/<transaction_id>", methods=["GET"])
@require_auth
def get_transaction(transaction_id):
    """
    Retrieves a single transaction by ID. Enforces driver isolation.
    """
    ledger_svc = current_app.extensions["ledger_service"]
    txn = ledger_svc.get_transaction(transaction_id, driver_id=g.driver_id)
    if not txn:
        return error_response(
            code="TRANSACTION_NOT_FOUND",
            message=f"Transaction '{transaction_id}' not found.",
            status_code=404
        )
    return success_response(txn)


@transaction_bp.route("/<transaction_id>/adjust", methods=["POST"])
@require_auth
def propose_adjustment(transaction_id):
    """
    Proposes an adjustment correction for an existing transaction.
    Creates a PENDING action of type CREATE_ADJUSTMENT.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = AdjustTransactionRequest(**body)
    except (ValidationError, ValueError) as err:
        return error_response(code="INVALID_ADJUSTMENT", message=str(err), status_code=400)

    ledger_svc = current_app.extensions["ledger_service"]
    existing = ledger_svc.get_transaction(transaction_id, driver_id=g.driver_id)
    if not existing:
        return error_response(code="TRANSACTION_NOT_FOUND", message=f"Transaction '{transaction_id}' not found.", status_code=404)

    pending_svc = current_app.extensions["pending_action_service"]
    proposed_data = {
        "original_transaction_id": transaction_id,
        "new_amount": str(req.new_amount),
        "reason": req.reason
    }

    try:
        result = pending_svc.propose_action(
            driver_id=g.driver_id,
            action_type=PendingActionType.CREATE_ADJUSTMENT,
            proposed_data=proposed_data,
            idempotency_key=req.idempotency_key
        )
        return success_response(result, status_code=201)
    except Exception as err:
        return error_response(code="PROPOSAL_FAILED", message=str(err), status_code=400)


@transaction_bp.route("/<transaction_id>/reverse", methods=["POST"])
@require_auth
def propose_reversal(transaction_id):
    """
    Proposes a reversal of an existing transaction.
    Creates a PENDING action of type CREATE_REVERSAL.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = ReverseTransactionRequest(**body)
    except (ValidationError, ValueError) as err:
        return error_response(code="INVALID_REVERSAL", message=str(err), status_code=400)

    ledger_svc = current_app.extensions["ledger_service"]
    existing = ledger_svc.get_transaction(transaction_id, driver_id=g.driver_id)
    if not existing:
        return error_response(code="TRANSACTION_NOT_FOUND", message=f"Transaction '{transaction_id}' not found.", status_code=404)

    pending_svc = current_app.extensions["pending_action_service"]
    proposed_data = {
        "original_transaction_id": transaction_id,
        "reason": req.reason
    }

    try:
        result = pending_svc.propose_action(
            driver_id=g.driver_id,
            action_type=PendingActionType.CREATE_REVERSAL,
            proposed_data=proposed_data,
            idempotency_key=req.idempotency_key
        )
        return success_response(result, status_code=201)
    except Exception as err:
        return error_response(code="PROPOSAL_FAILED", message=str(err), status_code=400)
