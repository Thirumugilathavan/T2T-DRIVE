"""
Traffic Challan and Violation Domain Models for T2T DRIVE.
Enforces strict monetary types, valid state transitions, and audit records.
"""

from enum import Enum
from typing import Optional, Any
from decimal import Decimal
import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.models.financial import quantize_money, format_money
from app.utils.dates import now_utc, today_ist


class ChallanStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CANCELLED = "CANCELLED"


# Valid state transitions
VALID_CHALLAN_TRANSITIONS = {
    ChallanStatus.UNPAID: {ChallanStatus.PAID, ChallanStatus.DISPUTED, ChallanStatus.CANCELLED},
    ChallanStatus.DISPUTED: {ChallanStatus.UNDER_REVIEW, ChallanStatus.PAID, ChallanStatus.CANCELLED, ChallanStatus.UNPAID},
    ChallanStatus.UNDER_REVIEW: {ChallanStatus.DISPUTED, ChallanStatus.PAID, ChallanStatus.CANCELLED, ChallanStatus.UNPAID},
    ChallanStatus.PAID: set(),  # Terminal state (settled payment)
    ChallanStatus.CANCELLED: set(),  # Terminal state (waived/voided)
}


class Challan(BaseModel):
    """
    Traffic challan record associated with a driver and vehicle.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    challan_id: str = Field(..., description="Unique internal challan ID (e.g. CHLN_...)")
    challan_number: str = Field(..., description="Official challan number (e.g. TN1234567890)")
    driver_id: str = Field(..., description="Authenticated driver ID")
    vehicle_id: str = Field(..., description="Vehicle ID")
    registration_number: str = Field(..., description="Vehicle registration plate")
    challan_date: str = Field(default_factory=today_ist, description="Date violation occurred (YYYY-MM-DD)")
    issuing_authority: Optional[str] = Field(default="Traffic Police Department", description="Issuing RTO/Police authority")
    violation_description: str = Field(..., description="Description of violation (e.g. Signal jump, No helmet/seatbelt)")
    fine_amount: Decimal = Field(..., description="Fine amount in INR (strictly > 0)")
    payment_status: ChallanStatus = Field(default=ChallanStatus.UNPAID, description="Current payment state")
    payment_date: Optional[str] = Field(default=None, description="Date fine was settled (YYYY-MM-DD)")
    payment_reference: Optional[str] = Field(default=None, description="UPI / Netbanking / Receipt transaction ref")
    file_reference: Optional[str] = Field(default=None, description="Storage key for uploaded notice or receipt")
    notes: Optional[str] = Field(default="", description="Driver or admin remarks")
    ocr_extracted: bool = Field(default=False, description="True if fields originated from OCR extraction")
    user_confirmed: bool = Field(default=True, description="True once driver explicitly reviews & confirms details")
    official_verified: bool = Field(default=False, description="True only if authorized government API confirmed")
    created_at: datetime.datetime = Field(default_factory=now_utc)
    updated_at: datetime.datetime = Field(default_factory=now_utc)

    @field_validator("fine_amount", mode="before")
    @classmethod
    def validate_fine_amount(cls, v: Any) -> Decimal:
        dec = quantize_money(v)
        if dec <= Decimal("0"):
            raise ValueError(f"Challan fine amount must be strictly positive (> 0), got: {dec}")
        return dec

    def can_transition_to(self, new_status: ChallanStatus) -> bool:
        """Verifies if the status transition is permitted."""
        if self.payment_status == new_status:
            return True
        allowed = VALID_CHALLAN_TRANSITIONS.get(self.payment_status, set())
        return new_status in allowed
