"""
REST API Routes for Traffic Challans & Violation Assistance.
Enforces authentication, status transition rules, and untrusted OCR confirmation.
"""

import io
import logging
from decimal import Decimal
from flask import Blueprint, request, current_app, send_file
from werkzeug.exceptions import BadRequest

from app.utils.decorators import token_required
from app.utils.responses import success_response, error_response
from app.schemas.challans import ChallanCreateSchema, ChallanPaymentSchema, ChallanStatusUpdateSchema

logger = logging.getLogger("t2t_drive.challan_routes")

challan_bp = Blueprint("challan_bp", __name__, url_prefix="/api/challans")


def _get_challan_service():
    return current_app.extensions["challan_service"]


@challan_bp.route("", methods=["POST"])
@token_required
def create_challan():
    """Creates a new challan record with optional file attachment."""
    driver_id = request.driver_id
    challan_svc = _get_challan_service()

    file_bytes = None
    filename = None

    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()
        if "file" in request.files:
            uploaded = request.files["file"]
            if uploaded and uploaded.filename:
                filename = uploaded.filename
                file_bytes = uploaded.read()

    required = ["challan_number", "vehicle_id", "violation_description", "fine_amount"]
    for f in required:
        if not data.get(f):
            return error_response(code="VALIDATION_ERROR", message=f"Field '{f}' is required.", status_code=400)

    try:
        saved = challan_svc.add_challan(
            driver_id=driver_id,
            challan_number=data["challan_number"],
            vehicle_id=data["vehicle_id"],
            registration_number=data.get("registration_number", data["vehicle_id"]),
            violation_description=data["violation_description"],
            fine_amount=Decimal(str(data["fine_amount"])),
            challan_date=data.get("challan_date"),
            issuing_authority=data.get("issuing_authority"),
            notes=data.get("notes", ""),
            file_bytes=file_bytes,
            filename=filename,
            ocr_extracted=bool(data.get("ocr_extracted", False))
        )
        return success_response(
            data={"challan": saved, "saved": True},
            message="Challan registered successfully.",
            status_code=201
        )
    except ValueError as ve:
        return error_response(code="VALIDATION_ERROR", message=str(ve), status_code=400)
    except Exception as e:
        logger.error("Failed to add challan: %s", e, exc_info=True)
        return error_response(code="INTERNAL_ERROR", message=str(e), status_code=500)


@challan_bp.route("/ocr-preview", methods=["POST"])
@token_required
def ocr_preview():
    """
    Accepts an uploaded challan image/PDF and returns candidate extracted fields.
    Note: Output is UNTRUSTED and requires driver confirmation before saving.
    """
    challan_svc = _get_challan_service()

    if "file" not in request.files:
        return error_response(code="BAD_REQUEST", message="No file uploaded.", status_code=400)

    uploaded = request.files["file"]
    if not uploaded or not uploaded.filename:
        return error_response(code="BAD_REQUEST", message="Empty filename.", status_code=400)

    try:
        file_bytes = uploaded.read()
        extracted = challan_svc.extract_from_upload(file_bytes=file_bytes, filename=uploaded.filename)
        return success_response(
            data=extracted,
            message="Challan fields previewed via OCR. Please verify details before saving."
        )
    except Exception as e:
        logger.error("OCR preview failed: %s", e)
        return error_response(code="OCR_ERROR", message=str(e), status_code=400)


@challan_bp.route("", methods=["GET"])
@token_required
def list_challans():
    """Lists challans for the authenticated driver with optional filters."""
    driver_id = request.driver_id
    challan_svc = _get_challan_service()
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")

    challans = challan_svc.list_challans(driver_id=driver_id, vehicle_id=vehicle_id, status=status)
    return success_response(
        data={"challans": challans, "total": len(challans)},
        message="Challans retrieved successfully."
    )


@challan_bp.route("/unpaid", methods=["GET"])
@token_required
def list_unpaid_challans():
    """Lists outstanding unpaid challans."""
    driver_id = request.driver_id
    challan_svc = _get_challan_service()
    vehicle_id = request.args.get("vehicle_id")

    challans = challan_svc.list_challans(driver_id=driver_id, vehicle_id=vehicle_id, status="UNPAID")
    total_fine = sum(Decimal(str(c["fine_amount"])) for c in challans)
    return success_response(
        data={"unpaid_challans": challans, "count": len(challans), "total_fine_amount": str(total_fine)},
        message="Unpaid challans retrieved."
    )


@challan_bp.route("/<challan_id>", methods=["GET"])
@token_required
def get_challan(challan_id: str):
    """Retrieves challan details."""
    driver_id = request.driver_id
    challan_svc = _get_challan_service()

    try:
        doc = challan_svc.get_challan(challan_id=challan_id, driver_id=driver_id)
        return success_response(data=doc)
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Challan not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized access.", status_code=403)


@challan_bp.route("/<challan_id>/file", methods=["GET"])
@token_required
def get_challan_file(challan_id: str):
    """Streams attached notice or payment receipt."""
    driver_id = request.driver_id
    challan_svc = _get_challan_service()

    try:
        file_bytes, content_type = challan_svc.get_challan_file(challan_id=challan_id, driver_id=driver_id)
        return send_file(
            io.BytesIO(file_bytes),
            mimetype=content_type,
            as_attachment=False
        )
    except FileNotFoundError as fe:
        return error_response(code="NOT_FOUND", message=str(fe), status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized.", status_code=403)


@challan_bp.route("/<challan_id>/payment", methods=["POST"])
@challan_bp.route("/<challan_id>/pay", methods=["POST"])
@token_required
def pay_challan(challan_id: str):
    """Records payment information for a challan."""
    driver_id = request.driver_id
    challan_svc = _get_challan_service()
    data = request.get_json() or {}

    payment_ref = data.get("payment_reference")
    payment_date = data.get("payment_date")

    if not payment_ref or not payment_date:
        return error_response(
            code="VALIDATION_ERROR",
            message="Both 'payment_reference' and 'payment_date' are required to record payment.",
            status_code=400
        )

    try:
        paid = challan_svc.record_payment(
            challan_id=challan_id,
            driver_id=driver_id,
            payment_date=payment_date,
            payment_reference=payment_ref,
            notes=data.get("notes")
        )
        return success_response(data=paid, message="Challan payment recorded successfully.")
    except (ValueError, BadRequest) as e:
        return error_response(code="VALIDATION_ERROR", message=str(e), status_code=400)
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Challan not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized.", status_code=403)


@challan_bp.route("/<challan_id>/status", methods=["PUT"])
@token_required
def update_status(challan_id: str):
    """Updates challan status (e.g. DISPUTED, CANCELLED)."""
    driver_id = request.driver_id
    challan_svc = _get_challan_service()
    data = request.get_json() or {}

    status = data.get("status")
    if not status:
        return error_response(code="VALIDATION_ERROR", message="'status' is required.", status_code=400)

    try:
        updated = challan_svc.update_status(
            challan_id=challan_id,
            driver_id=driver_id,
            new_status_str=status,
            reason=data.get("reason", "")
        )
        return success_response(data=updated, message="Challan status updated.")
    except ValueError as ve:
        return error_response(code="VALIDATION_ERROR", message=str(ve), status_code=400)
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Challan not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized.", status_code=403)
