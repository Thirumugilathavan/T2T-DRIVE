"""
Financial Summary and Audit Flask API Routes for T2T DRIVE.
Exposes daily, weekly, monthly, and custom summaries alongside append-only audit trail.
"""

from flask import Blueprint, request, current_app, g
from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth

finance_bp = Blueprint("finance", __name__, url_prefix="/api/finance")


@finance_bp.route("/summary/daily", methods=["GET"])
@require_auth
def get_daily_summary():
    """Returns daily financial summary for a given date in IST."""
    summary_svc = current_app.extensions["summary_service"]
    date_str = request.args.get("date")
    vehicle_id = request.args.get("vehicle_id")

    try:
        res = summary_svc.get_daily_summary(driver_id=g.driver_id, date_str=date_str, vehicle_id=vehicle_id)
        return success_response(res)
    except ValueError as err:
        return error_response(code="INVALID_DATE", message=str(err), status_code=400)


@finance_bp.route("/summary/weekly", methods=["GET"])
@require_auth
def get_weekly_summary():
    """Returns weekly financial summary (Monday-to-Sunday) in IST."""
    summary_svc = current_app.extensions["summary_service"]
    reference_date = request.args.get("date")
    vehicle_id = request.args.get("vehicle_id")

    try:
        res = summary_svc.get_weekly_summary(driver_id=g.driver_id, reference_date=reference_date, vehicle_id=vehicle_id)
        return success_response(res)
    except ValueError as err:
        return error_response(code="INVALID_DATE", message=str(err), status_code=400)


@finance_bp.route("/summary/monthly", methods=["GET"])
@require_auth
def get_monthly_summary():
    """Returns monthly financial summary in IST."""
    summary_svc = current_app.extensions["summary_service"]
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    vehicle_id = request.args.get("vehicle_id")

    try:
        res = summary_svc.get_monthly_summary(driver_id=g.driver_id, year=year, month=month, vehicle_id=vehicle_id)
        return success_response(res)
    except ValueError as err:
        return error_response(code="INVALID_DATE", message=str(err), status_code=400)


@finance_bp.route("/summary/custom", methods=["GET"])
@require_auth
def get_custom_summary():
    """Returns summary for an arbitrary custom date range."""
    summary_svc = current_app.extensions["summary_service"]
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    vehicle_id = request.args.get("vehicle_id")

    if not start_date or not end_date:
        return error_response(
            code="VALIDATION_ERROR",
            message="Both 'start_date' and 'end_date' query parameters are required.",
            status_code=400
        )

    try:
        res = summary_svc.get_custom_summary(
            driver_id=g.driver_id,
            start_date=start_date,
            end_date=end_date,
            vehicle_id=vehicle_id
        )
        return success_response(res)
    except ValueError as err:
        return error_response(code="INVALID_DATE_RANGE", message=str(err), status_code=400)


@finance_bp.route("/audit", methods=["GET"])
@require_auth
def get_audit_logs():
    """Returns append-only audit trail for the authenticated driver."""
    audit_svc = current_app.extensions.get("audit_service")
    if not audit_svc:
        return error_response(code="SERVICE_UNAVAILABLE", message="Audit service unavailable.", status_code=503)

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 50))))
    except ValueError:
        return error_response(code="INVALID_PAGINATION", message="Page and limit must be positive integers.", status_code=400)

    skip = (page - 1) * limit
    logs = audit_svc.list_driver_audit_logs(driver_id=g.driver_id, limit=limit, skip=skip)
    return success_response({
        "audit_logs": logs,
        "page": page,
        "limit": limit
    })
