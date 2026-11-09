"""
Passenger Public Access REST API Routes for T2T DRIVE.
Exposes lightweight, token-authorized endpoints for passengers:
trip inspection, initial agreement, change proposals, mutual confirmations,
consent management, disputes, and transparent digital receipts.
Zero app installation or driver login required.
"""

from flask import Blueprint, request, current_app
from decimal import Decimal

from app.utils.responses import success_response, error_response
from app.models.trip import ProposalType
from app.models.financial import quantize_money

passenger_bp = Blueprint("passenger", __name__, url_prefix="/api/passenger")


def _get_token_from_request():
    """Extracts passenger token from Authorization header, X-Passenger-Token, or query param."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return request.headers.get("X-Passenger-Token") or request.args.get("token")


@passenger_bp.route("/trips/<trip_id>", methods=["GET"])
def get_passenger_trip(trip_id):
    """Retrieves passenger-safe trip details using secure temporary token."""
    raw_token = _get_token_from_request()
    if not raw_token:
        return error_response(code="UNAUTHORIZED", message="Missing passenger access token.", status_code=401)

    trip_svc = current_app.extensions["trip_service"]
    try:
        trip_data = trip_svc.get_passenger_trip_view(trip_id, raw_token)
        return success_response({"trip": trip_data})
    except Exception as e:
        return error_response(code="ACCESS_DENIED", message=str(e), status_code=403)


@passenger_bp.route("/trips/<trip_id>/agreement", methods=["POST"])
def respond_initial_agreement(trip_id):
    """Passenger accepts or declines the initial trip fare proposal."""
    raw_token = _get_token_from_request()
    if not raw_token:
        return error_response(code="UNAUTHORIZED", message="Missing passenger access token.", status_code=401)

    data = request.get_json(silent=True) or {}
    accepted = bool(data.get("accepted"))

    trip_svc = current_app.extensions["trip_service"]
    try:
        updated_trip = trip_svc.respond_to_initial_agreement(
            trip_id=trip_id,
            raw_token=raw_token,
            accepted=accepted
        )
        return success_response({"trip": updated_trip})
    except Exception as e:
        return error_response(code="AGREEMENT_FAILED", message=str(e), status_code=400)


@passenger_bp.route("/trips/<trip_id>/propose-change", methods=["POST"])
def passenger_propose_change(trip_id):
    """Passenger proposes a destination change, stop, or fare adjustment."""
    raw_token = _get_token_from_request()
    if not raw_token:
        return error_response(code="UNAUTHORIZED", message="Missing passenger access token.", status_code=401)

    # Validate token permissions
    access_svc = current_app.extensions["passenger_access_service"]
    try:
        access_svc.validate_passenger_token(trip_id, raw_token)
    except Exception as e:
        return error_response(code="UNAUTHORIZED", message=str(e), status_code=403)

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
            proposed_by="PASSENGER",
            proposed_value=proposed_val,
            reason=reason
        )
        return success_response({"proposal": proposal.to_dict()}, status_code=201)
    except Exception as e:
        return error_response(code="PROPOSAL_FAILED", message=str(e), status_code=400)


@passenger_bp.route("/trips/<trip_id>/respond-proposal", methods=["POST"])
def passenger_respond_proposal(trip_id):
    """Passenger accepts or declines a change proposal."""
    raw_token = _get_token_from_request()
    if not raw_token:
        return error_response(code="UNAUTHORIZED", message="Missing passenger access token.", status_code=401)

    access_svc = current_app.extensions["passenger_access_service"]
    try:
        access_svc.validate_passenger_token(trip_id, raw_token)
    except Exception as e:
        return error_response(code="UNAUTHORIZED", message=str(e), status_code=403)

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
            responder="PASSENGER",
            accepted=accepted
        )
        return success_response({"trip": trip.to_passenger_dict(), "proposal_status": status.value})
    except Exception as e:
        return error_response(code="RESPONSE_FAILED", message=str(e), status_code=400)


@passenger_bp.route("/trips/<trip_id>/consent", methods=["POST"])
def update_passenger_consent(trip_id):
    """Passenger grants or withdraws consent for continuous in-cabin listening."""
    raw_token = _get_token_from_request()
    if not raw_token:
        return error_response(code="UNAUTHORIZED", message="Missing passenger access token.", status_code=401)

    access_svc = current_app.extensions["passenger_access_service"]
    try:
        access_svc.validate_passenger_token(trip_id, raw_token)
    except Exception as e:
        return error_response(code="UNAUTHORIZED", message=str(e), status_code=403)

    data = request.get_json(silent=True) or {}
    consent = bool(data.get("consent") if data.get("consent") is not None else data.get("consented", False))

    trip_svc = current_app.extensions["trip_service"]
    continuous_svc = current_app.extensions.get("continuous_listening_service")

    try:
        res = trip_svc.update_continuous_listening_consent(trip_id, "PASSENGER", consent)
        if not consent and continuous_svc:
            continuous_svc.stop_continuous_session(trip_id, reason="PASSENGER_WITHDREW_CONSENT")
        return success_response(res)
    except Exception as e:
        return error_response(code="CONSENT_ERROR", message=str(e), status_code=400)


@passenger_bp.route("/trips/<trip_id>/dispute", methods=["POST"])
def passenger_raise_dispute(trip_id):
    """Passenger flags a dispute regarding fare, route, or payment."""
    raw_token = _get_token_from_request()
    if not raw_token:
        return error_response(code="UNAUTHORIZED", message="Missing passenger access token.", status_code=401)

    access_svc = current_app.extensions["passenger_access_service"]
    try:
        access_svc.validate_passenger_token(trip_id, raw_token)
    except Exception as e:
        return error_response(code="UNAUTHORIZED", message=str(e), status_code=403)

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "Disputed by passenger")

    trip_svc = current_app.extensions["trip_service"]
    try:
        updated = trip_svc.raise_dispute(trip_id, reason=reason, raised_by="PASSENGER")
        return success_response({"trip": updated.to_passenger_dict()})
    except Exception as e:
        return error_response(code="DISPUTE_FAILED", message=str(e), status_code=400)


@passenger_bp.route("/trips/<trip_id>/receipt", methods=["GET"])
def get_passenger_receipt(trip_id):
    """Retrieves mobile-friendly shared digital trip receipt."""
    raw_token = _get_token_from_request()
    if not raw_token:
        return error_response(code="UNAUTHORIZED", message="Missing passenger access token.", status_code=401)

    reconciliation_svc = current_app.extensions["trip_reconciliation_service"]
    try:
        receipt = reconciliation_svc.generate_passenger_receipt(trip_id, raw_token)
        return success_response({"receipt": receipt})
    except Exception as e:
        return error_response(code="RECEIPT_ERROR", message=str(e), status_code=400)
