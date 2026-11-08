"""
REST API Routes for Reminders & Notification Tracking.
Provides endpoints for listing, acknowledging, and triggering idempotent reminder scans.
"""

import logging
from flask import Blueprint, request, current_app

from app.utils.decorators import token_required
from app.utils.responses import success_response, error_response

logger = logging.getLogger("t2t_drive.reminder_routes")

reminder_bp = Blueprint("reminder_bp", __name__, url_prefix="/api/reminders")


def _get_reminder_service():
    return current_app.extensions["reminder_service"]


@reminder_bp.route("", methods=["GET"])
@token_required
def list_reminders():
    """Lists reminders for the authenticated driver."""
    driver_id = request.driver_id
    rem_svc = _get_reminder_service()
    status = request.args.get("status")

    reminders = rem_svc.list_reminders(driver_id=driver_id, status=status)
    return success_response(
        data={"reminders": reminders, "total": len(reminders)},
        message="Reminders retrieved."
    )


@reminder_bp.route("/scan", methods=["POST"])
@token_required
def trigger_scan():
    """
    Triggers an idempotent reminder scan for the authenticated driver.
    Generates new notifications for documents matching milestone thresholds.
    """
    driver_id = request.driver_id
    rem_svc = _get_reminder_service()
    data = request.get_json(silent=True) or {}
    ref_date = data.get("reference_date")

    result = rem_svc.scan_all_reminders(driver_id=driver_id, reference_date=ref_date)
    return success_response(data=result, message="Reminder scan completed successfully.")


@reminder_bp.route("/<reminder_id>/acknowledge", methods=["POST"])
@token_required
def acknowledge_reminder(reminder_id: str):
    """Marks a reminder as ACKNOWLEDGED."""
    driver_id = request.driver_id
    rem_svc = _get_reminder_service()

    ok = rem_svc.acknowledge_reminder(reminder_id=reminder_id, driver_id=driver_id)
    if ok:
        return success_response(message="Reminder acknowledged.")
    return error_response(code="NOT_FOUND", message="Reminder not found.", status_code=404)
