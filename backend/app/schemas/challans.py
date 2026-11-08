"""
Pydantic Request and Response Schemas for Traffic Challans.
"""

from typing import Optional, List, Dict, Any
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict


class ChallanCreateSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    challan_number: str = Field(..., description="Official traffic challan notice number")
    vehicle_id: str = Field(..., description="Vehicle ID")
    registration_number: Optional[str] = Field(default=None, description="Vehicle registration number")
    challan_date: Optional[str] = Field(default=None, description="Date of violation (YYYY-MM-DD)")
    issuing_authority: Optional[str] = Field(default="Traffic Police", description="Issuing agency")
    violation_description: str = Field(..., description="Description of violation")
    fine_amount: Decimal = Field(..., description="Fine amount in INR (> 0)")
    notes: Optional[str] = Field(default="", description="Additional remarks")


class ChallanPaymentSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    payment_date: str = Field(..., description="Date payment was made (YYYY-MM-DD)")
    payment_reference: str = Field(..., description="Receipt / UPI / Netbanking transaction reference")
    notes: Optional[str] = Field(default="", description="Payment notes")


class ChallanStatusUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = Field(..., description="New status: PAID, DISPUTED, CANCELLED, UNDER_REVIEW")
    reason: Optional[str] = Field(default="", description="Reason for status change")
    payment_reference: Optional[str] = None
    payment_date: Optional[str] = None


class ChallanResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    challan_id: str
    challan_number: str
    driver_id: str
    vehicle_id: str
    registration_number: str
    challan_date: str
    issuing_authority: Optional[str]
    violation_description: str
    fine_amount: str
    payment_status: str
    payment_date: Optional[str]
    payment_reference: Optional[str]
    has_file: bool
    notes: Optional[str]
    ocr_extracted: bool
    official_verified: bool
    created_at: str
    updated_at: str
