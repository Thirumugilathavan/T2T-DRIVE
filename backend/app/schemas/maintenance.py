"""
Pydantic Request and Response Schemas for Vehicle Maintenance.
"""

from typing import Optional, List, Dict, Any
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict


class MaintenanceCreateSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_id: str = Field(..., description="Vehicle registration or ID")
    maintenance_category: str = Field(..., description="Service category (e.g. ENGINE_OIL, BRAKE_SERVICING)")
    description: str = Field(..., description="Specific work description")
    cost: Decimal = Field(..., description="Service cost in INR (>= 0)")
    service_date: Optional[str] = Field(default=None, description="Date of service (YYYY-MM-DD)")
    odometer_reading: Optional[int] = Field(default=None, description="Odometer reading in km")
    service_provider: Optional[str] = Field(default="Local Garage", description="Workshop or mechanic name")
    next_service_date: Optional[str] = Field(default=None, description="Next service due date (YYYY-MM-DD)")
    next_service_odometer: Optional[int] = Field(default=None, description="Next service due km")
    notes: Optional[str] = Field(default="", description="Additional notes")
    record_financial_expense: bool = Field(
        default=False,
        description="If True, creates/links a Phase 2 financial expense transaction"
    )


class MaintenanceUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    maintenance_category: Optional[str] = None
    description: Optional[str] = None
    cost: Optional[Decimal] = None
    service_date: Optional[str] = None
    odometer_reading: Optional[int] = None
    service_provider: Optional[str] = None
    next_service_date: Optional[str] = None
    next_service_odometer: Optional[int] = None
    notes: Optional[str] = None


class MaintenanceResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    maintenance_id: str
    driver_id: str
    vehicle_id: str
    maintenance_category: str
    category_label: str
    description: str
    service_date: str
    odometer_reading: Optional[int]
    service_provider: Optional[str]
    cost: str
    next_service_date: Optional[str]
    next_service_odometer: Optional[int]
    financial_transaction_id: Optional[str]
    has_receipt: bool
    notes: Optional[str]
    created_at: str
    updated_at: str
