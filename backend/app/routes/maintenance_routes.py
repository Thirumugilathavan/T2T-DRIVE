"""
REST API Routes for Vehicle Maintenance Management.
Integrates maintenance service records with the Phase 2 financial ledger.
"""

import logging
from decimal import Decimal
from flask import Blueprint, request, current_app

from app.utils.decorators import token_required
from app.utils.responses import success_response, error_response
from app.utils.dates import today_ist
from app.schemas.maintenance import MaintenanceCreateSchema, MaintenanceUpdateSchema

logger = logging.getLogger("t2t_drive.maintenance_routes")

maintenance_bp = Blueprint("maintenance_bp", __name__, url_prefix="/api/maintenance")


def _get_maintenance_service():
    return current_app.extensions["maintenance_service"]


@maintenance_bp.route("", methods=["POST"])
@token_required
def create_maintenance():
    """
    Logs a vehicle service or repair.
    If 'record_financial_expense' is True, enforces confirmation firewall by returning
    a PENDING financial action that must be confirmed by the driver.
    """
    driver_id = request.driver_id
    maint_svc = _get_maintenance_service()
    data = request.get_json() or {}

    vehicle_id = data.get("vehicle_id")
    category = data.get("maintenance_category") or data.get("category") or data.get("type")
    description = data.get("description")
    cost_raw = data.get("cost")

    if not vehicle_id or not category or not description or cost_raw is None:
        return error_response(
            code="VALIDATION_ERROR",
            message="Fields 'vehicle_id', 'maintenance_category', 'description', and 'cost' are required.",
            status_code=400
        )

    try:
        cost = Decimal(str(cost_raw))
        if cost < 0:
            return error_response(code="VALIDATION_ERROR", message="Cost cannot be negative.", status_code=400)
    except Exception:
        return error_response(code="VALIDATION_ERROR", message="Invalid cost format.", status_code=400)

    record_financial = bool(data.get("record_financial_expense", False))

    try:
        if record_financial and cost > 0:
            # Route through the financial confirmation firewall
            proposal = maint_svc.propose_maintenance_with_expense(
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                maintenance_category_str=category,
                description=description,
                cost=cost,
                service_date=data.get("service_date"),
                odometer_reading=data.get("odometer_reading"),
                service_provider=data.get("service_provider"),
                next_service_date=data.get("next_service_date"),
                next_service_odometer=data.get("next_service_odometer"),
                notes=data.get("notes", "")
            )
            return success_response(
                data=proposal,
                message="Maintenance expense proposed. Please confirm transaction to commit to financial ledger.",
                status_code=202
            )
        else:
            # Standalone maintenance record without immediate ledger debit
            record = maint_svc.add_maintenance_record(
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                maintenance_category_str=category,
                description=description,
                cost=cost,
                service_date=data.get("service_date"),
                odometer_reading=data.get("odometer_reading"),
                service_provider=data.get("service_provider"),
                next_service_date=data.get("next_service_date"),
                next_service_odometer=data.get("next_service_odometer"),
                notes=data.get("notes", "")
            )
            return success_response(
                data={"maintenance": record, "saved": True},
                message="Maintenance log created successfully.",
                status_code=201
            )
    except ValueError as ve:
        return error_response(code="VALIDATION_ERROR", message=str(ve), status_code=400)
    except Exception as e:
        logger.error("Failed to create maintenance log: %s", e, exc_info=True)
        return error_response(code="INTERNAL_ERROR", message=str(e), status_code=500)


@maintenance_bp.route("", methods=["GET"])
@token_required
def list_maintenance():
    """Lists maintenance history for driver."""
    driver_id = request.driver_id
    maint_svc = _get_maintenance_service()
    vehicle_id = request.args.get("vehicle_id")
    category = request.args.get("category")

    records = maint_svc.list_maintenance(driver_id=driver_id, vehicle_id=vehicle_id, category=category)
    return success_response(
        data={"maintenance_records": records, "total": len(records)},
        message="Maintenance records retrieved."
    )


@maintenance_bp.route("/upcoming", methods=["GET"])
@token_required
def upcoming_services():
    """Retrieves scheduled future services."""
    driver_id = request.driver_id
    maint_svc = _get_maintenance_service()
    vehicle_id = request.args.get("vehicle_id")

    upcoming = maint_svc.get_upcoming_services(driver_id=driver_id, vehicle_id=vehicle_id)
    return success_response(data={"upcoming_services": upcoming, "count": len(upcoming)})


@maintenance_bp.route("/overdue", methods=["GET"])
@token_required
def overdue_services():
    """Retrieves overdue services based on date or odometer."""
    driver_id = request.driver_id
    maint_svc = _get_maintenance_service()
    vehicle_id = request.args.get("vehicle_id")
    odo_raw = request.args.get("odometer")
    odo = int(odo_raw) if odo_raw and odo_raw.isdigit() else None

    overdue = maint_svc.get_overdue_services(driver_id=driver_id, vehicle_id=vehicle_id, current_odometer=odo)
    return success_response(data={"overdue_services": overdue, "count": len(overdue)})


@maintenance_bp.route("/summary", methods=["GET"])
@token_required
def spending_summary():
    """Calculates maintenance expenditure breakdown over date range."""
    driver_id = request.driver_id
    maint_svc = _get_maintenance_service()

    start_date = request.args.get("start_date", "2026-01-01")
    end_date = request.args.get("end_date", today_ist())
    vehicle_id = request.args.get("vehicle_id")

    summary = maint_svc.get_spending_summary(
        driver_id=driver_id,
        start_date=start_date,
        end_date=end_date,
        vehicle_id=vehicle_id
    )
    return success_response(data=summary, message="Maintenance spending summary calculated.")


@maintenance_bp.route("/<maintenance_id>", methods=["GET"])
@token_required
def get_maintenance(maintenance_id: str):
    """Retrieves maintenance log details."""
    driver_id = request.driver_id
    maint_svc = _get_maintenance_service()

    try:
        doc = maint_svc.get_maintenance(maintenance_id=maintenance_id, driver_id=driver_id)
        return success_response(data=doc)
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Record not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized access.", status_code=403)


@maintenance_bp.route("/<maintenance_id>", methods=["PUT"])
@token_required
def update_maintenance(maintenance_id: str):
    """Updates maintenance record details."""
    driver_id = request.driver_id
    maint_svc = _get_maintenance_service()
    data = request.get_json() or {}

    try:
        updated = maint_svc.update_maintenance(maintenance_id=maintenance_id, driver_id=driver_id, updates=data)
        return success_response(data=updated, message="Maintenance log updated.")
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Record not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized.", status_code=403)
