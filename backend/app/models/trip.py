"""
Domain models and schemas for Trip Agreements, Passenger Participation,
Mutual Confirmations, and Trip Events in T2T DRIVE.
Enforces Decimal monetary representation, strict state transitions,
and versioned agreement history.
"""

from enum import Enum
from decimal import Decimal
import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator
from app.models.financial import quantize_money, format_money
from app.utils.dates import now_utc, today_ist


def format_timestamp(v: Any) -> Optional[str]:
    """Helper to ensure timestamps serialize safely as ISO-8601 strings."""
    if v is None:
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    return str(v)


# ============================================================================
# ENUM DEFINITIONS
# ============================================================================

class TripState(str, Enum):
    CREATED = "CREATED"
    AGREEMENT_PENDING = "AGREEMENT_PENDING"
    AGREED = "AGREED"
    IN_PROGRESS = "IN_PROGRESS"
    CHANGE_PENDING = "CHANGE_PENDING"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


class ProposalType(str, Enum):
    DESTINATION_CHANGE = "DESTINATION_CHANGE"
    ADD_STOP = "ADD_STOP"
    FARE_CHANGE = "FARE_CHANGE"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED_BY_DRIVER = "ACCEPTED_BY_DRIVER"
    ACCEPTED_BY_PASSENGER = "ACCEPTED_BY_PASSENGER"
    ACCEPTED = "ACCEPTED"
    DECLINED_BY_DRIVER = "DECLINED_BY_DRIVER"
    DECLINED_BY_PASSENGER = "DECLINED_BY_PASSENGER"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    DISPUTED = "DISPUTED"


class TripPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    PAYMENT_DISPUTED = "PAYMENT_DISPUTED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    UPI = "UPI"


class ListeningMode(str, Enum):
    OFF = "OFF"
    SHARED_AGREEMENT = "SHARED_AGREEMENT"
    EVENT_BASED_PTT = "EVENT_BASED_PTT"
    CONTINUOUS = "CONTINUOUS"


# Valid state transitions graph for deterministic lifecycle
VALID_TRIP_TRANSITIONS: Dict[TripState, List[TripState]] = {
    TripState.CREATED: [TripState.AGREEMENT_PENDING, TripState.CANCELLED],
    TripState.AGREEMENT_PENDING: [TripState.AGREED, TripState.CANCELLED, TripState.DISPUTED],
    TripState.AGREED: [TripState.IN_PROGRESS, TripState.CANCELLED, TripState.CHANGE_PENDING],
    TripState.IN_PROGRESS: [TripState.CHANGE_PENDING, TripState.PAYMENT_PENDING, TripState.COMPLETED, TripState.DISPUTED],
    TripState.CHANGE_PENDING: [TripState.IN_PROGRESS, TripState.PAYMENT_PENDING, TripState.DISPUTED, TripState.CANCELLED],
    TripState.PAYMENT_PENDING: [TripState.COMPLETED, TripState.DISPUTED],
    TripState.COMPLETED: [TripState.DISPUTED],
    TripState.CANCELLED: [],
    TripState.DISPUTED: [TripState.COMPLETED, TripState.CANCELLED]
}


# ============================================================================
# SUB-MODELS
# ============================================================================

class ConsentState(BaseModel):
    """Tracks independent explicit consent for continuous listening."""
    driver_consent: bool = False
    passenger_consent: bool = False
    driver_consented_at: Optional[Union[str, datetime.datetime]] = None
    passenger_consented_at: Optional[Union[str, datetime.datetime]] = None
    withdrawn_by: Optional[str] = None
    withdrawn_at: Optional[Union[str, datetime.datetime]] = None

    @property
    def is_mutually_consented(self) -> bool:
        return self.driver_consent and self.passenger_consent and not self.withdrawn_at


class TripAgreement(BaseModel):
    """Immutable versioned snapshot of agreed trip parameters."""
    version: int = Field(ge=1)
    pickup_location: str
    destination_location: str
    additional_stops: List[str] = Field(default_factory=list)
    agreed_fare: Decimal = Field(gt=Decimal("0.00"))
    agreed_at: Union[str, datetime.datetime]

    @field_validator("agreed_fare", mode="before")
    @classmethod
    def validate_fare(cls, v: Any) -> Decimal:
        return quantize_money(v)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "pickup_location": self.pickup_location,
            "destination_location": self.destination_location,
            "additional_stops": list(self.additional_stops),
            "agreed_fare": format_money(self.agreed_fare),
            "agreed_at": format_timestamp(self.agreed_at)
        }


class TripChangeProposal(BaseModel):
    """Proposal for changing destination, stops, or fare requiring mutual acceptance."""
    proposal_id: str
    trip_id: str
    proposal_type: ProposalType
    proposed_by: str  # "DRIVER" | "PASSENGER" | "AI_VOICE"
    current_value: Dict[str, Any]
    proposed_value: Dict[str, Any]
    reason: Optional[str] = None
    driver_accepted: Optional[bool] = None
    passenger_accepted: Optional[bool] = None
    status: ProposalStatus = ProposalStatus.PROPOSED
    created_at: Union[str, datetime.datetime]
    resolved_at: Optional[Union[str, datetime.datetime]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "trip_id": self.trip_id,
            "proposal_type": self.proposal_type.value,
            "proposed_by": self.proposed_by,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "reason": self.reason,
            "driver_accepted": self.driver_accepted,
            "passenger_accepted": self.passenger_accepted,
            "status": self.status.value,
            "created_at": format_timestamp(self.created_at),
            "resolved_at": format_timestamp(self.resolved_at)
        }


class TripEvent(BaseModel):
    """Audit log entry capturing significant trip events without storing full transcripts."""
    event_id: str
    trip_id: str
    event_type: str  # e.g., "TRIP_CREATED", "PROPOSAL_CREATED", "MUTUAL_CONFIRMATION"
    source: str      # "DRIVER" | "PASSENGER" | "VOICE" | "SYSTEM"
    description: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: Union[str, datetime.datetime]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trip_id": self.trip_id,
            "event_type": self.event_type,
            "source": self.source,
            "description": self.description,
            "metadata": self.metadata,
            "timestamp": format_timestamp(self.timestamp)
        }


class PassengerAccess(BaseModel):
    """Token authentication metadata scoped strictly to a single trip."""
    trip_id: str
    token_hash: str
    created_at: Union[str, datetime.datetime]
    expires_at: Union[str, datetime.datetime]
    is_revoked: bool = False
    access_count: int = 0
    last_accessed_at: Optional[Union[str, datetime.datetime]] = None


class TripPayment(BaseModel):
    """Individual payment installment towards an agreed trip fare."""
    payment_id: str
    trip_id: str
    driver_id: str
    amount: Decimal = Field(gt=Decimal("0.00"))
    payment_method: PaymentMethod
    transaction_id: Optional[str] = None  # Reference to financial transaction ledger
    collected_at: Union[str, datetime.datetime]
    notes: Optional[str] = None

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Decimal:
        return quantize_money(v)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "trip_id": self.trip_id,
            "driver_id": self.driver_id,
            "amount": format_money(self.amount),
            "payment_method": self.payment_method.value,
            "transaction_id": self.transaction_id,
            "collected_at": format_timestamp(self.collected_at),
            "notes": self.notes
        }


# ============================================================================
# ROOT TRIP DOMAIN MODEL
# ============================================================================

class Trip(BaseModel):
    """Complete root entity for a shared T2T DRIVE trip."""
    trip_id: str
    driver_id: str
    vehicle_id: str
    state: TripState = TripState.CREATED
    pickup_location: str
    destination_location: str
    additional_stops: List[str] = Field(default_factory=list)
    initial_proposed_fare: Decimal = Field(gt=Decimal("0.00"))
    current_agreed_fare: Optional[Decimal] = None
    earned_fare: Decimal = Field(default=Decimal("0.00"))
    collected_amount: Decimal = Field(default=Decimal("0.00"))
    outstanding_amount: Decimal = Field(default=Decimal("0.00"))
    payment_status: TripPaymentStatus = TripPaymentStatus.UNPAID
    payment_method: Optional[PaymentMethod] = None
    active_agreement_version: int = 0
    agreement_history: List[TripAgreement] = Field(default_factory=list)
    active_proposal: Optional[TripChangeProposal] = None
    continuous_listening_enabled: bool = False
    listening_mode: ListeningMode = ListeningMode.OFF
    consent: ConsentState = Field(default_factory=ConsentState)
    created_at: Union[str, datetime.datetime]
    updated_at: Union[str, datetime.datetime]
    completed_at: Optional[Union[str, datetime.datetime]] = None
    dispute_reason: Optional[str] = None

    @property
    def is_disputed(self) -> bool:
        return bool(self.dispute_reason)

    @field_validator("initial_proposed_fare", "current_agreed_fare", "earned_fare", "collected_amount", "outstanding_amount", mode="before")
    @classmethod
    def validate_money_fields(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        return quantize_money(v)

    def to_driver_dict(self) -> Dict[str, Any]:
        """Full representation for the authenticated driver."""
        return {
            "trip_id": self.trip_id,
            "driver_id": self.driver_id,
            "vehicle_id": self.vehicle_id,
            "state": self.state.value,
            "pickup_location": self.pickup_location,
            "destination_location": self.destination_location,
            "additional_stops": list(self.additional_stops),
            "initial_proposed_fare": format_money(self.initial_proposed_fare),
            "current_agreed_fare": format_money(self.current_agreed_fare) if self.current_agreed_fare else None,
            "earned_fare": format_money(self.earned_fare),
            "collected_amount": format_money(self.collected_amount),
            "outstanding_amount": format_money(self.outstanding_amount),
            "payment_status": self.payment_status.value,
            "payment_method": self.payment_method.value if self.payment_method else None,
            "active_agreement_version": self.active_agreement_version,
            "agreement_history": [a.to_dict() for a in self.agreement_history],
            "active_proposal": self.active_proposal.to_dict() if self.active_proposal else None,
            "continuous_listening_enabled": self.continuous_listening_enabled,
            "listening_mode": self.listening_mode.value,
            "consent": self.consent.model_dump(),
            "created_at": format_timestamp(self.created_at),
            "updated_at": format_timestamp(self.updated_at),
            "completed_at": format_timestamp(self.completed_at),
            "dispute_reason": self.dispute_reason
        }

    def to_passenger_dict(self) -> Dict[str, Any]:
        """
        Data-minimizing view for passenger:
        Excludes driver's private phone number, owner settlements, total earnings,
        and internal financial calculations.
        """
        return {
            "trip_id": self.trip_id,
            "vehicle_id": self.vehicle_id,
            "state": self.state.value,
            "pickup_location": self.pickup_location,
            "destination_location": self.destination_location,
            "additional_stops": list(self.additional_stops),
            "initial_proposed_fare": format_money(self.initial_proposed_fare),
            "current_agreed_fare": format_money(self.current_agreed_fare) if self.current_agreed_fare else None,
            "collected_amount": format_money(self.collected_amount),
            "outstanding_amount": format_money(self.outstanding_amount),
            "payment_status": self.payment_status.value,
            "payment_method": self.payment_method.value if self.payment_method else None,
            "active_agreement_version": self.active_agreement_version,
            "active_proposal": self.active_proposal.to_dict() if self.active_proposal else None,
            "continuous_listening_enabled": self.continuous_listening_enabled,
            "listening_mode": self.listening_mode.value,
            "consent_status": {
                "driver_consented": self.consent.driver_consent,
                "passenger_consented": self.consent.passenger_consent,
                "is_active": self.consent.is_mutually_consented
            },
            "created_at": format_timestamp(self.created_at),
            "updated_at": format_timestamp(self.updated_at),
            "completed_at": format_timestamp(self.completed_at)
        }
