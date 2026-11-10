"""
REST API Routes for Driver and Vehicle Document Management.
Enforces authentication, driver authorization, and safe file streaming.
"""

import io
import logging
from flask import Blueprint, request, current_app, send_file
from werkzeug.exceptions import BadRequest

from app.utils.decorators import token_required
from app.utils.responses import success_response, error_response
from app.schemas.documents import DocumentCreateSchema, DocumentUpdateSchema

logger = logging.getLogger("t2t_drive.document_routes")

document_bp = Blueprint("document_bp", __name__, url_prefix="/api/documents")


def _get_document_service():
    return current_app.extensions["document_service"]


@document_bp.route("", methods=["POST"])
@token_required
def create_document():
    """
    Registers a new vehicle or driver document.
    Accepts application/json or multipart/form-data (with optional file upload).
    """
    driver_id = request.driver_id
    doc_svc = _get_document_service()

    file_bytes = None
    filename = None

    if request.is_json:
        data = request.get_json() or {}
    else:
        # Multipart form data
        data = request.form.to_dict()
        if "file" in request.files:
            uploaded = request.files["file"]
            if uploaded and uploaded.filename:
                filename = uploaded.filename
                file_bytes = uploaded.read()

    doc_type = data.get("type") or data.get("document_type")
    if not doc_type:
        return error_response(code="VALIDATION_ERROR", message="Field 'document_type' or 'type' is required.", status_code=400)

    try:
        saved = doc_svc.add_document(
            driver_id=driver_id,
            document_type_str=doc_type,
            document_number=data.get("number") or data.get("document_number"),
            expiry_date=data.get("expiry") or data.get("expiry_date"),
            vehicle_id=data.get("vehicle_id"),
            issue_date=data.get("issue_date"),
            issuing_authority=data.get("issuing_authority"),
            file_bytes=file_bytes,
            filename=filename,
            notes=data.get("notes", "")
        )
        return success_response(
            data={"document": saved, "saved": True},
            message="Document registered successfully.",
            status_code=201
        )
    except PermissionError as pe:
        return error_response(code="FORBIDDEN", message=str(pe), status_code=403)
    except ValueError as ve:
        return error_response(code="VALIDATION_ERROR", message=str(ve), status_code=400)
    except Exception as e:
        logger.error("Failed to add document: %s", e, exc_info=True)
        return error_response(code="INTERNAL_ERROR", message=str(e), status_code=500)


@document_bp.route("/ocr-preview", methods=["POST"])
@token_required
def ocr_preview():
    """
    Accepts an uploaded vehicle/driver document image or PDF and returns candidate extracted fields.
    Note: Output is UNVERIFIED simulated OCR and requires explicit driver confirmation before saving.
    """
    doc_svc = _get_document_service()

    if "file" not in request.files:
        return error_response(code="BAD_REQUEST", message="No file uploaded.", status_code=400)

    uploaded = request.files["file"]
    if not uploaded or not uploaded.filename:
        return error_response(code="BAD_REQUEST", message="Empty filename.", status_code=400)

    try:
        file_bytes = uploaded.read()
        extracted = doc_svc.extract_from_upload(file_bytes=file_bytes, filename=uploaded.filename)
        return success_response(
            data=extracted,
            message="Document fields previewed via OCR. Please verify details before saving."
        )
    except ValueError as ve:
        return error_response(code="INVALID_DOCUMENT_FILE", message=str(ve), status_code=400)
    except Exception as e:
        logger.error("Document OCR preview failed: %s", e)
        return error_response(code="OCR_ERROR", message=str(e), status_code=400)


@document_bp.route("", methods=["GET"])
@token_required
def list_documents():
    """Lists documents belonging to the authenticated driver."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()
    vehicle_id = request.args.get("vehicle_id")

    docs = doc_svc.list_documents(driver_id=driver_id, vehicle_id=vehicle_id, active_only=True)
    return success_response(
        data={"documents": docs, "total": len(docs)},
        message="Documents retrieved successfully."
    )


@document_bp.route("/compliance", methods=["GET"])
@token_required
def get_compliance():
    """Retrieves fleet RTO compliance summary and alert counts."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()
    vehicle_id = request.args.get("vehicle_id")

    summary = doc_svc.get_compliance_status(driver_id=driver_id, vehicle_id=vehicle_id)
    return success_response(data=summary, message="Compliance status retrieved.")


@document_bp.route("/expiring", methods=["GET"])
@token_required
def get_expiring():
    """Retrieves critical and expiring documents."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()
    vehicle_id = request.args.get("vehicle_id")

    docs = doc_svc.list_documents(driver_id=driver_id, vehicle_id=vehicle_id, active_only=True)
    expiring = [d for d in docs if d.get("days_left") is not None and d.get("days_left") <= 30]
    return success_response(data={"expiring_documents": expiring, "count": len(expiring)})


@document_bp.route("/<document_id>", methods=["GET"])
@token_required
def get_document(document_id: str):
    """Retrieves document metadata."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()

    try:
        doc = doc_svc.get_document(document_id=document_id, driver_id=driver_id)
        return success_response(data=doc)
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Document not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized access to document.", status_code=403)


@document_bp.route("/<document_id>/file", methods=["GET"])
@token_required
def download_document_file(document_id: str):
    """Streams private document file after verifying driver authorization."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()

    try:
        file_bytes, content_type = doc_svc.get_document_file(document_id=document_id, driver_id=driver_id)
        return send_file(
            io.BytesIO(file_bytes),
            mimetype=content_type,
            as_attachment=False,
            download_name=f"{document_id}.pdf" if "pdf" in content_type else f"{document_id}.jpg"
        )
    except FileNotFoundError as fe:
        return error_response(code="NOT_FOUND", message=str(fe), status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized access to document file.", status_code=403)


@document_bp.route("/<document_id>", methods=["PUT"])
@token_required
def update_document(document_id: str):
    """Updates document metadata fields."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()
    data = request.get_json() or {}

    try:
        updated = doc_svc.update_document(document_id=document_id, driver_id=driver_id, updates=data)
        return success_response(data=updated, message="Document updated successfully.")
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Document not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized.", status_code=403)


@document_bp.route("/<document_id>/replace", methods=["POST"])
@token_required
def replace_document_file(document_id: str):
    """Replaces document uploaded file."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()

    if "file" not in request.files:
        return error_response(code="BAD_REQUEST", message="No file uploaded.", status_code=400)

    uploaded = request.files["file"]
    if not uploaded or not uploaded.filename:
        return error_response(code="BAD_REQUEST", message="Empty filename.", status_code=400)

    try:
        file_bytes = uploaded.read()
        updated = doc_svc.replace_document_file(
            document_id=document_id,
            driver_id=driver_id,
            file_bytes=file_bytes,
            filename=uploaded.filename
        )
        return success_response(data=updated, message="Document file replaced successfully.")
    except (ValueError, BadRequest) as e:
        return error_response(code="VALIDATION_ERROR", message=str(e), status_code=400)
    except FileNotFoundError:
        return error_response(code="NOT_FOUND", message="Document not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized.", status_code=403)


@document_bp.route("/<document_id>", methods=["DELETE"])
@token_required
def delete_document(document_id: str):
    """Marks document inactive (soft delete)."""
    driver_id = request.driver_id
    doc_svc = _get_document_service()

    try:
        success = doc_svc.delete_document(document_id=document_id, driver_id=driver_id)
        if success:
            return success_response(message="Document deleted successfully.")
        return error_response(code="NOT_FOUND", message="Document not found.", status_code=404)
    except PermissionError:
        return error_response(code="FORBIDDEN", message="Unauthorized.", status_code=403)
