"""
Driver Trip Management REST API Routes for T2T DRIVE.
Exposes endpoints for trip creation, QR link generation, mutual change proposals,
payment collections, and consent-based continuous listening sessions.
"""

from flask import Blueprint, request, current_app, g
from decimal import Decimal

from app.utils.responses import success_response, error_response
from app.utils.decorators import require_auth
from app.models.trip import ProposalType, PaymentMethod
from app.models.financial import quantize_money

trip_bp = Blueprint("trips", __name__, url_prefix="/api/trips")


@trip_bp.route("", methods=["POST"])
@require_auth
def create_trip():
    """Driver creates a new trip agreement proposal."""
    data = request.get_json(silent=True) or {}
    pickup = data.get("pickup_location") or data.get("pickup") or "Current Location"
    destination = data.get("destination_location") or data.get("destination")
    fare_raw = data.get("proposed_fare") if data.get("proposed_fare") is not None else (data.get("initial_fare") if data.get("initial_fare") is not None else data.get("fare"))
    vehicle_id = data.get("vehicle_id") or "TN-01-AB-1234"

    if not destination or fare_raw is None:
        return error_response(
            code="INVALID_TRIP_DATA",
            message="destination and proposed_fare (or initial_fare) are required.",
            status_code=400
        )

    try:
        fare = quantize_money(Decimal(str(fare_raw)))
        if fare <= Decimal("0.00"):
            return error_response(code="INVALID_FARE", message="Fare must be greater than zero.", status_code=400)
    except Exception:
        return error_response(code="INVALID_FARE", message="Proposed fare must be a valid number.", status_code=400)

    trip_svc = current_app.extensions["trip_service"]
    try:
        trip_data, raw_token, passenger_url, qr_svg = trip_svc.create_trip(
            driver_id=g.driver_id,
            vehicle_id=vehicle_id,
            pickup_location=pickup,
            destination_location=destination,
            proposed_fare=fare
        )
        return success_response({
            "trip": trip_data,
            "passenger_access_token": raw_token,
            "passenger_url": passenger_url,
            "qr_code_svg": qr_svg
        }, status_code=201)
    except Exception as e:
        current_app.logger.error("Create trip failed: %s", e)
        return error_response(code="TRIP_CREATION_FAILED", message=str(e), status_code=500)


@trip_bp.route("/active", methods=["GET"])
@require_auth
def get_active_trip():
    """Retrieves driver's currently active trip."""
    trip_repo = current_app.extensions["trip_repository"]
    active = trip_repo.get_active_trip_for_driver(g.driver_id)
    return success_response({"trip": active})


@trip_bp.route("/<trip_id>", methods=["GET"])
@require_auth
def get_trip(trip_id):
    """Retrieves detailed driver trip view."""
    trip_svc = current_app.extensions["trip_service"]
    try:
        trip_data = trip_svc.get_driver_trip_view(trip_id, g.driver_id)
        return success_response({"trip": trip_data})
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED", message=str(pe), status_code=403)
    except ValueError as ve:
        return error_response(code="NOT_FOUND", message=str(ve), status_code=404)


@trip_bp.route("/<trip_id>/start", methods=["POST"])
@require_auth
def start_trip(trip_id):
    """Transitions trip to IN_PROGRESS."""
    trip_svc = current_app.extensions["trip_service"]
    try:
        updated = trip_svc.start_trip(trip_id, g.driver_id)
        return success_response({"trip": updated.to_driver_dict()})
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED", message=str(pe), status_code=403)
    except Exception as e:
        return error_response(code="STATE_ERROR", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/complete", methods=["POST"])
@require_auth
def complete_trip(trip_id):
    """Completes active trip."""
    trip_svc = current_app.extensions["trip_service"]
    continuous_svc = current_app.extensions.get("continuous_listening_service")
    if continuous_svc:
        continuous_svc.stop_continuous_session(trip_id, reason="TRIP_COMPLETED")

    try:
        updated = trip_svc.complete_trip(trip_id, g.driver_id)
        return success_response({"trip": updated.to_driver_dict()})
    except Exception as e:
        return error_response(code="COMPLETE_FAILED", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/cancel", methods=["POST"])
@require_auth
def cancel_trip(trip_id):
    """Cancels trip."""
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "Cancelled by driver")
    trip_svc = current_app.extensions["trip_service"]
    continuous_svc = current_app.extensions.get("continuous_listening_service")
    if continuous_svc:
        continuous_svc.stop_continuous_session(trip_id, reason="TRIP_CANCELLED")

    try:
        updated = trip_svc.cancel_trip(trip_id, reason=reason, cancelled_by="DRIVER")
        return success_response({"trip": updated.to_driver_dict()})
    except Exception as e:
        return error_response(code="CANCEL_FAILED", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/propose-change", methods=["POST"])
@require_auth
def propose_change(trip_id):
    """Driver proposes a destination, additional stop, or fare change."""
    data = request.get_json(silent=True) or {}
    prop_type_str = data.get("proposal_type")
    proposed_val = data.get("proposed_value") or data.get("proposed_changes")
    reason = data.get("reason")

    if not prop_type_str or not proposed_val:
        return error_response(code="INVALID_PROPOSAL", message="proposal_type and proposed_value required.", status_code=400)

    try:
        prop_type = ProposalType(prop_type_str)
    except ValueError:
        return error_response(code="INVALID_PROPOSAL_TYPE", message=f"Invalid type {prop_type_str}", status_code=400)

    trip_svc = current_app.extensions["trip_service"]
    try:
        proposal = trip_svc.propose_change(
            trip_id=trip_id,
            proposal_type=prop_type,
            proposed_by="DRIVER",
            proposed_value=proposed_val,
            reason=reason
        )
        return success_response({"proposal": proposal.to_dict()}, status_code=201)
    except Exception as e:
        return error_response(code="PROPOSAL_FAILED", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/respond-proposal", methods=["POST"])
@require_auth
def respond_proposal(trip_id):
    """Driver responds to a proposal."""
    data = request.get_json(silent=True) or {}
    trip_svc = current_app.extensions["trip_service"]
    trip_obj = trip_svc.get_trip(trip_id)
    if not trip_obj:
        return error_response(code="TRIP_NOT_FOUND", message=f"Trip {trip_id} not found", status_code=404)

    proposal_id = data.get("proposal_id") or (trip_obj.active_proposal.proposal_id if trip_obj.active_proposal else None)
    accepted = bool(data.get("accepted") if data.get("accepted") is not None else data.get("accept", True))

    if not proposal_id:
        return error_response(code="MISSING_PROPOSAL_ID", message="No active proposal found for this trip.", status_code=400)
    try:
        trip, status = trip_svc.respond_to_proposal(
            trip_id=trip_id,
            proposal_id=proposal_id,
            responder="DRIVER",
            accepted=accepted
        )
        return success_response({"trip": trip.to_driver_dict(), "proposal_status": status.value})
    except Exception as e:
        return error_response(code="RESPONSE_FAILED", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/payments", methods=["POST"])
@require_auth
def record_payment(trip_id):
    """Records trip payment with ledger reconciliation."""
    data = request.get_json(silent=True) or {}
    amount_raw = data.get("amount")
    method_str = data.get("payment_method", "CASH").upper()
    idempotency_key = data.get("idempotency_key") or request.headers.get("X-Idempotency-Key")

    if amount_raw is None or not idempotency_key:
        return error_response(code="INVALID_PAYMENT", message="amount and idempotency_key are required.", status_code=400)

    try:
        amount = quantize_money(Decimal(str(amount_raw)))
        method = PaymentMethod(method_str)
    except Exception as ve:
        return error_response(code="INVALID_PAYMENT_DATA", message=str(ve), status_code=400)

    reconciliation_svc = current_app.extensions["trip_reconciliation_service"]
    try:
        res = reconciliation_svc.record_trip_payment(
            trip_id=trip_id,
            amount=amount,
            payment_method=method,
            idempotency_key=idempotency_key,
            driver_id=g.driver_id,
            notes=data.get("notes")
        )
        return success_response(res, status_code=201)
    except PermissionError as pe:
        return error_response(code="UNAUTHORIZED", message=str(pe), status_code=403)
    except Exception as e:
        return error_response(code="PAYMENT_ERROR", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/consent", methods=["POST"])
@require_auth
def update_driver_consent(trip_id):
    """Driver updates consent for continuous listening."""
    data = request.get_json(silent=True) or {}
    consent = bool(data.get("consent") if data.get("consent") is not None else data.get("consented", False))

    trip_svc = current_app.extensions["trip_service"]
    continuous_svc = current_app.extensions.get("continuous_listening_service")

    try:
        res = trip_svc.update_continuous_listening_consent(trip_id, "DRIVER", consent)
        if not consent and continuous_svc:
            continuous_svc.stop_continuous_session(trip_id, reason="DRIVER_WITHDREW_CONSENT")
        return success_response(res)
    except Exception as e:
        return error_response(code="CONSENT_ERROR", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/listening/start", methods=["POST"])
@require_auth
def start_listening(trip_id):
    """Starts continuous listening session if both parties have consented."""
    continuous_svc = current_app.extensions.get("continuous_listening_service")
    if not continuous_svc:
        return error_response(code="SERVICE_UNAVAILABLE", message="Continuous listening service not active.", status_code=503)

    try:
        res = continuous_svc.start_continuous_session(trip_id)
        return success_response(res)
    except Exception as e:
        return error_response(code="START_LISTENING_FAILED", message=str(e), status_code=400)


@trip_bp.route("/<trip_id>/listening/stop", methods=["POST"])
@require_auth
def stop_listening(trip_id):
    """Stops continuous listening session immediately."""
    continuous_svc = current_app.extensions.get("continuous_listening_service")
    if continuous_svc:
        continuous_svc.stop_continuous_session(trip_id, reason="STOPPED_BY_DRIVER")
    return success_response({"trip_id": trip_id, "is_active": False, "listening_mode": "EVENT_BASED_PTT"})


@trip_bp.route("/<trip_id>/events", methods=["GET"])
@require_auth
def get_trip_events(trip_id):
    """Lists audit trail events for the trip."""
    trip_repo = current_app.extensions["trip_repository"]
    events = trip_repo.list_events_for_trip(trip_id)
    return success_response({"trip_id": trip_id, "events": events})
