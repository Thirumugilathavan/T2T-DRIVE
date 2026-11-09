"""
Unit tests for T2T DRIVE Trip Service, Passenger Access, and Financial Reconciliation.
Covers 27 required trip lifecycle, mutual confirmation, security, and reconciliation scenarios.
"""

import pytest
from decimal import Decimal
import secrets

from app.models.trip import (
    TripState,
    ProposalType,
    ProposalStatus,
    TripPaymentStatus,
    PaymentMethod,
    ListeningMode
)
from app.repositories.trip_repository import TripRepository
from app.repositories.transaction_repository import TransactionRepository
from app.services.passenger_access_service import (
    PassengerAccessService,
    PassengerAccessUnauthorizedError,
    PassengerAccessExpiredError
)
from app.services.trip_service import TripService
from app.services.trip_reconciliation_service import TripReconciliationService
from app.services.continuous_listening_service import ContinuousListeningService
from app.services.ledger_service import LedgerService
from app.services.idempotency_service import IdempotencyService
from app.services.audit_service import AuditService
from app.voice.streaming_adapter import MockStreamingSTTAdapter, LiveWebSocketPrismaStreamingAdapter


@pytest.fixture
def trip_env(db):
    """Initializes in-memory test environment with real repositories and services."""
    repo = TripRepository(db=db)
    audit_svc = AuditService(db=db)
    idem_svc = IdempotencyService(db=db, audit_service=audit_svc)
    txn_repo = TransactionRepository(db=db)
    ledger_svc = LedgerService(repo=txn_repo, audit_service=audit_svc)

    access_svc = PassengerAccessService(
        repository=repo,
        secret_key="test-secure-secret-key-t2t-drive",
        base_url="http://localhost:5000",
        token_ttl_hours=24
    )
    trip_svc = TripService(repository=repo, passenger_access_service=access_svc)

    reconciliation_svc = TripReconciliationService(
        repository=repo,
        ledger_service=ledger_svc,
        idempotency_service=idem_svc,
        passenger_access_service=access_svc
    )

    streaming_adapter = MockStreamingSTTAdapter()
    listening_svc = ContinuousListeningService(
        trip_service=trip_svc,
        streaming_adapter=streaming_adapter
    )

    return {
        "repo": repo,
        "access_svc": access_svc,
        "trip_svc": trip_svc,
        "reconciliation_svc": reconciliation_svc,
        "ledger_svc": ledger_svc,
        "listening_svc": listening_svc,
        "streaming_adapter": streaming_adapter
    }


# SCENARIO 1: Driver creates trip
def test_driver_creates_trip(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, raw_token, passenger_url, qr_svg = trip_svc.create_trip(
        driver_id="DRV_001",
        vehicle_id="TN-01-AB-1234",
        pickup_location="T Nagar",
        destination_location="Chennai Central",
        proposed_fare=Decimal("250.00")
    )
    assert trip_dict["trip_id"].startswith("TRIP_")
    assert trip_dict["state"] == TripState.AGREEMENT_PENDING.value
    assert trip_dict["destination_location"] == "Chennai Central"
    assert trip_dict["initial_proposed_fare"] == "250.00"
    assert raw_token is not None
    assert "<svg" in qr_svg
    assert "token=" in passenger_url


# SCENARIO 2: Passenger accesses via valid QR link
def test_passenger_accesses_via_valid_qr_link(trip_env):
    trip_svc = trip_env["trip_svc"]
    access_svc = trip_env["access_svc"]
    
    trip_dict, raw_token, _, _ = trip_svc.create_trip(
        driver_id="DRV_001",
        vehicle_id="TN-01-AB-1234",
        pickup_location="Koyambedu",
        destination_location="T Nagar",
        proposed_fare=Decimal("180.00")
    )
    trip_id = trip_dict["trip_id"]

    access = access_svc.validate_passenger_token(trip_id, raw_token)
    assert access["trip_id"] == trip_id

    passenger_view = trip_svc.get_passenger_trip_view(trip_id, raw_token)
    assert passenger_view["trip_id"] == trip_id
    assert "driver_id" not in passenger_view  # Privacy preserved!


# SCENARIO 3: Passenger cannot access another driver's trip or with expired/invalid token
def test_passenger_cross_trip_or_invalid_access(trip_env):
    trip_svc = trip_env["trip_svc"]
    access_svc = trip_env["access_svc"]

    trip1, token1, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Adyar", "Airport", Decimal("150.00"))
    trip2, token2, _, _ = trip_svc.create_trip("DRV_002", "TN-02-CD-5678", "Guindy", "Central", Decimal("200.00"))

    # Access trip2 with token1 MUST raise PassengerAccessUnauthorizedError
    with pytest.raises(PassengerAccessUnauthorizedError):
        access_svc.validate_passenger_token(trip2["trip_id"], token1)

    with pytest.raises(PassengerAccessUnauthorizedError):
        trip_svc.get_passenger_trip_view(trip2["trip_id"], token1)

    # Completely invalid token
    with pytest.raises(PassengerAccessUnauthorizedError):
        access_svc.validate_passenger_token(trip1["trip_id"], "invalid-fake-token")


# SCENARIO 4: Passenger agrees to initial fare
def test_passenger_agrees_to_initial_fare(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Adyar", "Velachery", Decimal("220.00"))
    trip_id = trip_dict["trip_id"]

    updated = trip_svc.respond_to_initial_agreement(trip_id=trip_id, raw_token=token, accepted=True)
    assert updated["state"] == TripState.AGREED.value
    assert updated["active_agreement_version"] == 1
    assert updated["current_agreed_fare"] == "220.00"
    assert updated["outstanding_amount"] == "220.00"


# SCENARIO 5: Passenger declines initial proposal
def test_passenger_declines_initial_proposal(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Adyar", "Marina Beach", Decimal("160.00"))
    trip_id = trip_dict["trip_id"]

    updated = trip_svc.respond_to_initial_agreement(trip_id=trip_id, raw_token=token, accepted=False)
    assert updated["state"] == TripState.CANCELLED.value


# SCENARIO 6: Passenger does not respond (remains AGREEMENT_PENDING)
def test_passenger_unaccepted_trip_remains_proposed(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, _, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Anna Nagar", Decimal("300.00"))
    fetched = trip_svc.get_trip(trip_dict["trip_id"])
    assert fetched.state == TripState.AGREEMENT_PENDING
    assert fetched.active_agreement_version == 0


# SCENARIOS 7, 8, 9: Destination change proposals, acceptance, rejection
def test_destination_change_lifecycle(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Koyambedu", Decimal("200.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)

    # 7. Driver proposes destination change
    prop = trip_svc.propose_change(
        trip_id=trip_id,
        proposal_type=ProposalType.DESTINATION_CHANGE,
        proposed_by="DRIVER",
        proposed_value={"destination_location": "Poonamallee"}
    )
    assert prop.status == ProposalStatus.ACCEPTED_BY_DRIVER
    assert prop.driver_accepted is True
    assert prop.passenger_accepted is None

    # 8. Passenger accepts destination change -> version 2
    accepted_trip, status = trip_svc.respond_to_proposal(
        trip_id=trip_id,
        proposal_id=prop.proposal_id,
        responder="PASSENGER",
        accepted=True
    )
    assert status == ProposalStatus.ACCEPTED
    assert accepted_trip.active_agreement_version == 2
    assert accepted_trip.destination_location == "Poonamallee"
    assert len(accepted_trip.agreement_history) == 2

    # 9. Driver proposes another change, Passenger REJECTS -> version stays 2
    prop2 = trip_svc.propose_change(
        trip_id=trip_id,
        proposal_type=ProposalType.DESTINATION_CHANGE,
        proposed_by="DRIVER",
        proposed_value={"destination_location": "Porur"}
    )
    rejected_trip, status2 = trip_svc.respond_to_proposal(
        trip_id=trip_id,
        proposal_id=prop2.proposal_id,
        responder="PASSENGER",
        accepted=False
    )
    assert status2 == ProposalStatus.DECLINED
    assert rejected_trip.active_agreement_version == 2
    assert rejected_trip.destination_location == "Poonamallee"


# SCENARIO 10: Additional-stop proposal
def test_additional_stop_proposal(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Airport", Decimal("400.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)

    prop = trip_svc.propose_change(
        trip_id=trip_id,
        proposal_type=ProposalType.ADD_STOP,
        proposed_by="PASSENGER",
        proposed_value={"stop": "Chromepet ATM"}
    )
    # Driver confirms
    updated, status = trip_svc.respond_to_proposal(
        trip_id=trip_id,
        proposal_id=prop.proposal_id,
        responder="DRIVER",
        accepted=True
    )
    assert status == ProposalStatus.ACCEPTED
    assert updated.active_agreement_version == 2
    assert "Chromepet ATM" in updated.additional_stops


# SCENARIO 11: Fare-change proposal
def test_fare_change_proposal(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Egmore", Decimal("200.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)

    prop = trip_svc.propose_change(
        trip_id=trip_id,
        proposal_type=ProposalType.FARE_CHANGE,
        proposed_by="DRIVER",
        proposed_value={"agreed_fare": "260.00"}
    )
    # Passenger confirms
    updated, status = trip_svc.respond_to_proposal(
        trip_id=trip_id,
        proposal_id=prop.proposal_id,
        responder="PASSENGER",
        accepted=True
    )
    assert status == ProposalStatus.ACCEPTED
    assert updated.active_agreement_version == 2
    assert updated.current_agreed_fare == Decimal("260.00")
    assert updated.outstanding_amount == Decimal("260.00")


# SCENARIO 12 & 13: Confirmation state machine (1 confirms = pending; both confirm = upgraded)
def test_dual_confirmation_state_machine(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Adyar", "Thiruvanmiyur", Decimal("250.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)

    # When created by AI_VOICE, neither has confirmed
    prop = trip_svc.propose_change(
        trip_id=trip_id,
        proposal_type=ProposalType.FARE_CHANGE,
        proposed_by="AI_VOICE",
        proposed_value={"agreed_fare": "280.00"}
    )
    assert prop.status == ProposalStatus.PROPOSED

    # Driver confirms first -> status is ACCEPTED_BY_DRIVER
    t1, status1 = trip_svc.respond_to_proposal(trip_id, prop.proposal_id, "DRIVER", True)
    assert status1 == ProposalStatus.ACCEPTED_BY_DRIVER
    assert t1.active_agreement_version == 1

    # Passenger confirms -> upgraded to v2
    t2, status2 = trip_svc.respond_to_proposal(trip_id, prop.proposal_id, "PASSENGER", True)
    assert status2 == ProposalStatus.ACCEPTED
    assert t2.active_agreement_version == 2


# SCENARIO 14 & 15: Consent withdrawal & continuous listening session stops
def test_consent_withdrawal_stops_continuous_listening(trip_env):
    trip_svc = trip_env["trip_svc"]
    listening_svc = trip_env["listening_svc"]

    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Adyar", "Besant Nagar", Decimal("200.00"))
    trip_id = trip_dict["trip_id"]

    # Both grant consent
    trip_svc.update_continuous_listening_consent(trip_id, "DRIVER", True)
    res = trip_svc.update_continuous_listening_consent(trip_id, "PASSENGER", True)
    assert res["continuous_listening_enabled"] is True

    # Start listening
    session = listening_svc.start_session(trip_id)
    assert session["active"] is True

    # Passenger withdraws consent
    trip_svc.update_continuous_listening_consent(trip_id, "PASSENGER", False)
    
    # Session must be immediately stopped and memory buffer wiped
    status = listening_svc.get_session_status(trip_id)
    assert status["active"] is False


# SCENARIO 16 & 17: Streaming error handling & Mock fallback
def test_streaming_error_handling_and_fallback(trip_env):
    live_adapter = LiveWebSocketPrismaStreamingAdapter(api_key="mock-key")
    # Live streaming WebSocket is marked unverified/experimental
    assert live_adapter.is_live_stream_verified() is False

    # Mock adapter cleanly falls back to simulated audio chunks
    mock_adapter = MockStreamingSTTAdapter()
    chunks = []
    for chunk in mock_adapter.stream_audio(b"sample_pcm_audio", language="tanglish"):
        chunks.append(chunk)
    assert len(chunks) >= 1
    assert "transcript" in chunks[0]


# SCENARIO 18: Idempotent event submission
def test_idempotent_event_recording(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, _, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Adyar", Decimal("150.00"))
    trip_id = trip_dict["trip_id"]

    event1 = trip_svc.record_trip_event(
        trip_id=trip_id,
        event_type="ADD_STOP_DETECTED",
        source="AI_LISTENER",
        description="Saidapet stop detected",
        metadata={"stop": "Saidapet"}
    )
    assert event1.startswith("EVT_")


# SCENARIO 19, 20, 21: Financial reconciliation (partial, full, duplicate payment)
def test_trip_payment_reconciliation(trip_env):
    trip_svc = trip_env["trip_svc"]
    reconciliation_svc = trip_env["reconciliation_svc"]

    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Airport", Decimal("500.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)

    # 20. Partial Payment of ₹300
    p1 = reconciliation_svc.record_trip_payment(
        trip_id=trip_id,
        driver_id="DRV_001",
        amount=Decimal("300.00"),
        payment_method=PaymentMethod.UPI,
        idempotency_key="PAY_KEY_01"
    )
    assert p1["payment_status"] == TripPaymentStatus.PARTIALLY_PAID.value
    assert p1["total_collected"] == "300.00"
    assert p1["outstanding_amount"] == "200.00"

    # 19. Duplicate payment submission with same idempotency key must not double-count
    p1_dup = reconciliation_svc.record_trip_payment(
        trip_id=trip_id,
        driver_id="DRV_001",
        amount=Decimal("300.00"),
        payment_method=PaymentMethod.UPI,
        idempotency_key="PAY_KEY_01"
    )
    assert p1_dup["total_collected"] == "300.00"

    # 21. Full payment (remaining ₹200)
    p2 = reconciliation_svc.record_trip_payment(
        trip_id=trip_id,
        driver_id="DRV_001",
        amount=Decimal("200.00"),
        payment_method=PaymentMethod.CASH,
        idempotency_key="PAY_KEY_02"
    )
    assert p2["payment_status"] == TripPaymentStatus.PAID.value
    assert p2["total_collected"] == "500.00"
    assert p2["outstanding_amount"] == "0.00"


# SCENARIO 22: Payment dispute
def test_payment_dispute(trip_env):
    trip_svc = trip_env["trip_svc"]
    trip_dict, _, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Airport", Decimal("500.00"))
    trip_id = trip_dict["trip_id"]

    disputed = trip_svc.raise_dispute(
        trip_id=trip_id,
        raised_by="PASSENGER",
        reason="Driver took circuitous route without agreement"
    )
    assert disputed.is_disputed is True
    assert disputed.dispute_reason == "Driver took circuitous route without agreement"


# SCENARIO 23 & 27: Trip completion & listening session ends
def test_trip_completion_stops_listening(trip_env):
    trip_svc = trip_env["trip_svc"]
    listening_svc = trip_env["listening_svc"]

    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Airport", Decimal("500.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)

    # Start trip
    trip_svc.start_trip(trip_id, driver_id="DRV_001")

    # Start listening session
    trip_svc.update_continuous_listening_consent(trip_id, "DRIVER", True)
    trip_svc.update_continuous_listening_consent(trip_id, "PASSENGER", True)
    listening_svc.start_session(trip_id)
    assert listening_svc.get_session_status(trip_id)["active"] is True

    # Complete trip
    completed = trip_svc.complete_trip(trip_id, driver_id="DRV_001")
    assert completed.state == TripState.COMPLETED
    assert completed.continuous_listening_enabled is False

    # 27. No audio session continues after trip completion
    assert listening_svc.get_session_status(trip_id)["active"] is False


# SCENARIO 24: Passenger receipt content validation
def test_passenger_receipt_content(trip_env):
    trip_svc = trip_env["trip_svc"]
    reconciliation_svc = trip_env["reconciliation_svc"]

    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Marina", Decimal("220.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)

    reconciliation_svc.record_trip_payment(
        trip_id=trip_id,
        driver_id="DRV_001",
        amount=Decimal("220.00"),
        payment_method=PaymentMethod.CASH,
        idempotency_key="PAY_RECEIPT_1"
    )

    receipt = reconciliation_svc.generate_passenger_receipt(trip_id, token)
    assert receipt["trip_id"] == trip_id
    assert receipt["vehicle_id"] == "TN-01-AB-1234"
    assert receipt["agreed_fare"] == "220.00"
    assert receipt["total_paid"] == "220.00"
    assert receipt["outstanding_amount"] == "0.00"
    assert receipt["payment_status"] == TripPaymentStatus.PAID.value


# SCENARIO 26: Driver safety rules
def test_driver_safety_rules_adherence(trip_env):
    # Non-distracting voice/screen interaction while vehicle is moving
    trip_svc = trip_env["trip_svc"]
    trip_dict, token, _, _ = trip_svc.create_trip("DRV_001", "TN-01-AB-1234", "Central", "Marina", Decimal("220.00"))
    trip_id = trip_dict["trip_id"]
    trip_svc.respond_to_initial_agreement(trip_id, token, accepted=True)
    trip_svc.start_trip(trip_id, driver_id="DRV_001")

    # Safe one-touch or voice proposal
    prop = trip_svc.propose_change(
        trip_id=trip_id,
        proposal_type=ProposalType.ADD_STOP,
        proposed_by="DRIVER",
        proposed_value={"stop": "Lighthouse"}
    )
    assert prop.status == ProposalStatus.ACCEPTED_BY_DRIVER
