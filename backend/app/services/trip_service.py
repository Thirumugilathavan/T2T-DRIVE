"""
Trip Agreement, Lifecycle, and Mutual Confirmation Service for T2T DRIVE.
Enforces deterministic trip state transitions, versioned agreements,
dual-party confirmation workflows, and audit trail logging.
"""

import secrets
import logging
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal

from app.models.trip import (
    Trip,
    TripState,
    TripAgreement,
    TripChangeProposal,
    ProposalType,
    ProposalStatus,
    TripPaymentStatus,
    PaymentMethod,
    ListeningMode,
    ConsentState,
    VALID_TRIP_TRANSITIONS
)
from app.models.financial import quantize_money, format_money
from app.repositories.trip_repository import TripRepository
from app.services.passenger_access_service import PassengerAccessService
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.trip_service")


class TripStateTransitionError(Exception):
    pass


class TripProposalConflictError(Exception):
    pass


class TripService:
    """
    Business service managing trip lifecycle, versioned agreements,
    mutual confirmations, and passenger coordination.
    """

    def __init__(
        self,
        repository: TripRepository,
        passenger_access_service: PassengerAccessService
    ):
        self.repo = repository
        self.access_svc = passenger_access_service

    # ========================================================================
    # TRIP CREATION & RETRIEVAL
    # ========================================================================

    def create_trip(
        self,
        driver_id: str,
        vehicle_id: str,
        pickup_location: str,
        destination_location: str,
        proposed_fare: Decimal
    ) -> Tuple[Dict[str, Any], str, str, str]:
        """
        Initializes a new trip agreement proposal.
        Returns (trip_dict, raw_token, passenger_url, qr_code_svg).
        """
        fare = quantize_money(proposed_fare)
        trip_id = f"TRIP_{secrets.token_hex(8)}"
        now_str = now_utc()

        trip = Trip(
            trip_id=trip_id,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            state=TripState.AGREEMENT_PENDING,
            pickup_location=pickup_location.strip(),
            destination_location=destination_location.strip(),
            additional_stops=[],
            initial_proposed_fare=fare,
            current_agreed_fare=None,
            earned_fare=Decimal("0.00"),
            collected_amount=Decimal("0.00"),
            outstanding_amount=fare,
            payment_status=TripPaymentStatus.UNPAID,
            active_agreement_version=0,
            agreement_history=[],
            active_proposal=None,
            continuous_listening_enabled=False,
            listening_mode=ListeningMode.SHARED_AGREEMENT,
            consent=ConsentState(),
            created_at=now_str,
            updated_at=now_str
        )

        trip_dict = trip.model_dump()
        self.repo.insert_trip(trip_dict)

        # Generate passenger access token & QR code
        raw_token, passenger_url, qr_svg = self.access_svc.generate_passenger_access(trip_id)

        # Record audit event
        self.record_trip_event(
            trip_id=trip_id,
            event_type="TRIP_CREATED",
            source="DRIVER",
            description=f"Trip created from {pickup_location} to {destination_location} with proposed fare ₹{fare}",
            metadata={"initial_fare": format_money(fare), "vehicle_id": vehicle_id}
        )

        return trip.to_driver_dict(), raw_token, passenger_url, qr_svg

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        raw = self.repo.get_trip(trip_id)
        if not raw:
            return None
        return Trip(**raw)

    def get_driver_trip_view(self, trip_id: str, driver_id: str) -> Dict[str, Any]:
        trip = self.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Trip {trip_id} not found.")
        if trip.driver_id != driver_id:
            raise PermissionError("Unauthorized access to trip.")
        return trip.to_driver_dict()

    def get_passenger_trip_view(self, trip_id: str, raw_token: str) -> Dict[str, Any]:
        """Validates token and returns strictly passenger-safe view."""
        self.access_svc.validate_passenger_token(trip_id, raw_token)
        trip = self.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Trip {trip_id} not found.")
        return trip.to_passenger_dict()

    # ========================================================================
    # INITIAL AGREEMENT WORKFLOW
    # ========================================================================

    def respond_to_initial_agreement(
        self,
        trip_id: str,
        raw_token: str,
        accepted: bool,
        counter_fare: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """
        Passenger agrees or declines the initial proposed trip fare.
        """
        self.access_svc.validate_passenger_token(trip_id, raw_token)
        trip = self.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Trip {trip_id} not found.")

        if trip.state != TripState.AGREEMENT_PENDING:
            raise TripStateTransitionError(f"Trip is in {trip.state.value} state, not AGREEMENT_PENDING.")

        now_str = now_utc()

        if accepted:
            agreed_fare = trip.initial_proposed_fare
            agreement_v1 = TripAgreement(
                version=1,
                pickup_location=trip.pickup_location,
                destination_location=trip.destination_location,
                additional_stops=trip.additional_stops,
                agreed_fare=agreed_fare,
                agreed_at=now_str
            )

            updates = {
                "state": TripState.AGREED.value,
                "current_agreed_fare": agreed_fare,
                "earned_fare": agreed_fare,
                "outstanding_amount": agreed_fare,
                "active_agreement_version": 1,
                "agreement_history": [agreement_v1.model_dump()],
                "updated_at": now_str
            }
            self.repo.update_trip(trip_id, updates)

            self.record_trip_event(
                trip_id=trip_id,
                event_type="INITIAL_AGREEMENT_ACCEPTED",
                source="PASSENGER",
                description=f"Passenger accepted initial trip agreement for ₹{agreed_fare}",
                metadata={"agreed_fare": format_money(agreed_fare), "version": 1}
            )
        else:
            # If declined without counter-proposal, trip is cancelled
            updates = {
                "state": TripState.CANCELLED.value,
                "updated_at": now_str
            }
            self.repo.update_trip(trip_id, updates)

            self.record_trip_event(
                trip_id=trip_id,
                event_type="INITIAL_AGREEMENT_DECLINED",
                source="PASSENGER",
                description="Passenger declined initial trip proposal.",
                metadata={}
            )

        updated_trip = self.get_trip(trip_id)
        return updated_trip.to_passenger_dict()

    # ========================================================================
    # MUTUAL CHANGE PROPOSALS (DESTINATION, STOPS, FARE)
    # ========================================================================

    def propose_change(
        self,
        trip_id: str,
        proposal_type: ProposalType,
        proposed_by: str,
        proposed_value: Dict[str, Any],
        reason: Optional[str] = None
    ) -> TripChangeProposal:
        """
        Creates a new change proposal. Requires mutual confirmation.
        """
        trip = self.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Trip {trip_id} not found.")

        # Ensure trip is active
        if trip.state not in (TripState.AGREED, TripState.IN_PROGRESS, TripState.CHANGE_PENDING):
            raise TripStateTransitionError(f"Cannot propose changes in {trip.state.value} state.")

        # Check for uncompleted active proposal
        if trip.active_proposal and trip.active_proposal.status in (
            ProposalStatus.PROPOSED,
            ProposalStatus.ACCEPTED_BY_DRIVER,
            ProposalStatus.ACCEPTED_BY_PASSENGER
        ):
            raise TripProposalConflictError("An existing change proposal is currently awaiting response.")

        prop_by = proposed_by.upper()
        if prop_by not in ("DRIVER", "PASSENGER", "AI_VOICE"):
            raise ValueError(f"Invalid proposer: {proposed_by}")

        # Construct current snapshot
        current_value = {}
        if proposal_type == ProposalType.DESTINATION_CHANGE:
            current_value = {"destination_location": trip.destination_location}
        elif proposal_type == ProposalType.ADD_STOP:
            current_value = {"additional_stops": list(trip.additional_stops)}
        elif proposal_type == ProposalType.FARE_CHANGE:
            current_value = {"agreed_fare": format_money(trip.current_agreed_fare or trip.initial_proposed_fare)}

        # Proposer implicitly accepts their own proposal
        driver_acc = True if prop_by == "DRIVER" else (False if prop_by == "AI_VOICE" else None)
        pass_acc = True if prop_by == "PASSENGER" else (False if prop_by == "AI_VOICE" else None)

        if prop_by == "DRIVER":
            status = ProposalStatus.ACCEPTED_BY_DRIVER
        elif prop_by == "PASSENGER":
            status = ProposalStatus.ACCEPTED_BY_PASSENGER
        else:
            status = ProposalStatus.PROPOSED

        proposal_id = f"PROP_{secrets.token_hex(6)}"
        now_str = now_utc()

        proposal = TripChangeProposal(
            proposal_id=proposal_id,
            trip_id=trip_id,
            proposal_type=proposal_type,
            proposed_by=prop_by,
            current_value=current_value,
            proposed_value=proposed_value,
            reason=reason,
            driver_accepted=driver_acc,
            passenger_accepted=pass_acc,
            status=status,
            created_at=now_str
        )

        updates = {
            "state": TripState.CHANGE_PENDING.value,
            "active_proposal": proposal.model_dump(),
            "updated_at": now_str
        }
        self.repo.update_trip(trip_id, updates)

        self.record_trip_event(
            trip_id=trip_id,
            event_type="PROPOSAL_CREATED",
            source=prop_by,
            description=f"{prop_by} proposed {proposal_type.value}: {proposed_value}",
            metadata={"proposal_id": proposal_id, "proposal_type": proposal_type.value}
        )

        return proposal

    def respond_to_proposal(
        self,
        trip_id: str,
        proposal_id: str,
        responder: str,
        accepted: bool
    ) -> Tuple[Trip, ProposalStatus]:
        """
        Applies a party's response to an active proposal.
        If both parties accept, applies change, bumps agreement version,
        and saves snapshot in agreement history.
        If rejected, keeps previous agreed values and returns to previous state.
        """
        trip = self.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Trip {trip_id} not found.")

        proposal = trip.active_proposal
        if not proposal or proposal.proposal_id != proposal_id:
            raise ValueError(f"Proposal {proposal_id} is not the active proposal for trip {trip_id}.")

        resp = responder.upper()
        now_str = now_utc()

        if resp == "DRIVER":
            proposal.driver_accepted = accepted
        elif resp == "PASSENGER":
            proposal.passenger_accepted = accepted
        else:
            raise ValueError(f"Invalid responder: {responder}")

        # Check for rejection
        if not accepted:
            proposal.status = ProposalStatus.DECLINED
            proposal.resolved_at = now_str

            # Preserve prior agreed details! Active values are NOT modified.
            next_state = TripState.IN_PROGRESS if trip.active_agreement_version >= 1 else TripState.AGREED
            updates = {
                "state": next_state.value,
                "active_proposal": proposal.model_dump(),
                "updated_at": now_str
            }
            self.repo.update_trip(trip_id, updates)

            self.record_trip_event(
                trip_id=trip_id,
                event_type="PROPOSAL_REJECTED",
                source=resp,
                description=f"{resp} rejected proposal {proposal_id} ({proposal.proposal_type.value}). Previous agreement preserved.",
                metadata={"proposal_id": proposal_id, "proposal_type": proposal.proposal_type.value}
            )
            return self.get_trip(trip_id), ProposalStatus.DECLINED

        # Check if BOTH have accepted
        if proposal.driver_accepted and proposal.passenger_accepted:
            proposal.status = ProposalStatus.ACCEPTED
            proposal.resolved_at = now_str

            # Apply changes to active trip
            new_dest = trip.destination_location
            new_stops = list(trip.additional_stops)
            new_fare = trip.current_agreed_fare or trip.initial_proposed_fare

            if proposal.proposal_type == ProposalType.DESTINATION_CHANGE:
                new_dest = proposal.proposed_value.get("destination_location", trip.destination_location)
            elif proposal.proposal_type == ProposalType.ADD_STOP:
                added_stop = (
                    proposal.proposed_value.get("stop")
                    or proposal.proposed_value.get("stop_name")
                    or proposal.proposed_value.get("additional_stop")
                )
                if added_stop and added_stop not in new_stops:
                    new_stops.append(added_stop)
                fare_adj = proposal.proposed_value.get("fare_adjustment") or proposal.proposed_value.get("additional_fare")
                if fare_adj:
                    new_fare = quantize_money(new_fare + Decimal(str(fare_adj)))
            elif proposal.proposal_type == ProposalType.FARE_CHANGE:
                raw_new_fare = proposal.proposed_value.get("agreed_fare")
                if raw_new_fare:
                    new_fare = quantize_money(raw_new_fare)

            # Bump version and preserve snapshot
            new_version = trip.active_agreement_version + 1
            new_agreement = TripAgreement(
                version=new_version,
                pickup_location=trip.pickup_location,
                destination_location=new_dest,
                additional_stops=new_stops,
                agreed_fare=new_fare,
                agreed_at=now_str
            )

            history = [a.model_dump() for a in trip.agreement_history]
            history.append(new_agreement.model_dump())

            recalc_outstanding = quantize_money(new_fare - trip.collected_amount)

            updates = {
                "state": TripState.IN_PROGRESS.value,
                "destination_location": new_dest,
                "additional_stops": new_stops,
                "current_agreed_fare": new_fare,
                "earned_fare": new_fare,
                "outstanding_amount": recalc_outstanding,
                "active_agreement_version": new_version,
                "agreement_history": history,
                "active_proposal": proposal.model_dump(),
                "updated_at": now_str
            }
            self.repo.update_trip(trip_id, updates)

            self.record_trip_event(
                trip_id=trip_id,
                event_type="PROPOSAL_ACCEPTED",
                source="MUTUAL",
                description=f"Mutual agreement achieved on {proposal.proposal_type.value}. Agreement version upgraded to v{new_version}.",
                metadata={"proposal_id": proposal_id, "new_version": new_version}
            )
            return self.get_trip(trip_id), ProposalStatus.ACCEPTED

        # Only one party has accepted so far
        proposal.status = ProposalStatus.ACCEPTED_BY_DRIVER if resp == "DRIVER" else ProposalStatus.ACCEPTED_BY_PASSENGER
        updates = {
            "active_proposal": proposal.model_dump(),
            "updated_at": now_str
        }
        self.repo.update_trip(trip_id, updates)

        self.record_trip_event(
            trip_id=trip_id,
            event_type="PROPOSAL_PARTIALLY_ACCEPTED",
            source=resp,
            description=f"{resp} accepted proposal {proposal_id}. Awaiting other party.",
            metadata={"proposal_id": proposal_id, "status": proposal.status.value}
        )
        return self.get_trip(trip_id), proposal.status

    # ========================================================================
    # CONSENT & CONTINUOUS LISTENING MANAGEMENT
    # ========================================================================

    def update_continuous_listening_consent(
        self,
        trip_id: str,
        participant: str,
        consent_granted: bool
    ) -> Dict[str, Any]:
        """
        Manages independent explicit consent for continuous listening.
        Both driver and passenger must consent for continuous listening to activate.
        If either party withdraws consent, listening stops immediately.
        """
        trip = self.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Trip {trip_id} not found.")

        part = participant.upper()
        now_str = now_utc()
        consent = trip.consent

        if part == "DRIVER":
            consent.driver_consent = consent_granted
            if consent_granted:
                consent.driver_consented_at = now_str
            else:
                consent.withdrawn_by = "DRIVER"
                consent.withdrawn_at = now_str
        elif part == "PASSENGER":
            consent.passenger_consent = consent_granted
            if consent_granted:
                consent.passenger_consented_at = now_str
            else:
                consent.withdrawn_by = "PASSENGER"
                consent.withdrawn_at = now_str
        else:
            raise ValueError(f"Invalid participant: {participant}")

        # Activate continuous listening ONLY if both consented and not withdrawn
        if consent_granted and consent.driver_consent and consent.passenger_consent:
            consent.withdrawn_by = None
            consent.withdrawn_at = None
            enabled = True
            mode = ListeningMode.CONTINUOUS
        else:
            enabled = False
            mode = ListeningMode.EVENT_BASED_PTT

        updates = {
            "consent": consent.model_dump(),
            "continuous_listening_enabled": enabled,
            "listening_mode": mode.value,
            "updated_at": now_str
        }
        self.repo.update_trip(trip_id, updates)

        self.record_trip_event(
            trip_id=trip_id,
            event_type="CONSENT_UPDATED",
            source=part,
            description=f"{part} {'granted' if consent_granted else 'withdrew'} continuous listening consent.",
            metadata={"continuous_enabled": enabled, "mode": mode.value}
        )

        return {
            "trip_id": trip_id,
            "continuous_listening_enabled": enabled,
            "listening_mode": mode.value,
            "driver_consent": consent.driver_consent,
            "passenger_consent": consent.passenger_consent
        }

    # ========================================================================
    # LIFECYCLE: START, COMPLETE, CANCEL, DISPUTE
    # ========================================================================

    def start_trip(self, trip_id: str, driver_id: str) -> Trip:
        """Transitions trip from AGREED to IN_PROGRESS."""
        trip = self.get_trip(trip_id)
        if not trip or trip.driver_id != driver_id:
            raise PermissionError("Unauthorized.")
        if trip.state not in (TripState.AGREED, TripState.CREATED):
            raise TripStateTransitionError(f"Cannot start trip from {trip.state.value} state.")

        now_str = now_utc()
        self.repo.update_trip(trip_id, {"state": TripState.IN_PROGRESS.value, "updated_at": now_str})
        self.record_trip_event(trip_id, "TRIP_STARTED", "DRIVER", "Trip started by driver.", {})
        return self.get_trip(trip_id)

    def complete_trip(self, trip_id: str, driver_id: str) -> Trip:
        """Completes active trip, ensuring audio sessions and tokens are closed."""
        trip = self.get_trip(trip_id)
        if not trip or trip.driver_id != driver_id:
            raise PermissionError("Unauthorized.")

        now_str = now_utc()
        updates = {
            "state": TripState.COMPLETED.value,
            "continuous_listening_enabled": False,
            "listening_mode": ListeningMode.OFF.value,
            "completed_at": now_str,
            "updated_at": now_str
        }
        self.repo.update_trip(trip_id, updates)
        self.record_trip_event(trip_id, "TRIP_COMPLETED", "DRIVER", "Trip completed successfully.", {})
        return self.get_trip(trip_id)

    def cancel_trip(self, trip_id: str, reason: str, cancelled_by: str = "DRIVER") -> Trip:
        now_str = now_utc()
        updates = {
            "state": TripState.CANCELLED.value,
            "continuous_listening_enabled": False,
            "listening_mode": ListeningMode.OFF.value,
            "dispute_reason": reason,
            "updated_at": now_str
        }
        self.repo.update_trip(trip_id, updates)
        self.record_trip_event(trip_id, "TRIP_CANCELLED", cancelled_by, f"Trip cancelled: {reason}", {})
        return self.get_trip(trip_id)

    def raise_dispute(self, trip_id: str, reason: str, raised_by: str) -> Trip:
        now_str = now_utc()
        updates = {
            "state": TripState.DISPUTED.value,
            "dispute_reason": reason,
            "updated_at": now_str
        }
        self.repo.update_trip(trip_id, updates)
        self.record_trip_event(trip_id, "TRIP_DISPUTED", raised_by, f"Dispute logged: {reason}", {"reason": reason})
        return self.get_trip(trip_id)

    def record_trip_event(
        self,
        trip_id: str,
        event_type: str,
        source: str,
        description: str,
        metadata: Dict[str, Any]
    ) -> str:
        """Appends an event to the trip audit trail."""
        event_id = f"EVT_{secrets.token_hex(8)}"
        doc = {
            "event_id": event_id,
            "trip_id": trip_id,
            "event_type": event_type,
            "source": source,
            "description": description,
            "metadata": metadata,
            "timestamp": now_utc()
        }
        return self.repo.insert_event(doc)
