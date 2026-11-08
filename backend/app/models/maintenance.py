"""
Vehicle Maintenance and Service Domain Models for T2T DRIVE.
Enforces non-negative monetary costs, odometer validation, service categories,
and seamless integration with the Phase 2 financial ledger.
"""

from enum import Enum
from typing import Optional, Any
from decimal import Decimal
import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.models.financial import quantize_money, format_money
from app.utils.dates import now_utc, today_ist


class MaintenanceCategory(str, Enum):
    ENGINE_OIL = "ENGINE_OIL"
    TYRE_REPLACEMENT = "TYRE_REPLACEMENT"
    TYRE_PRESSURE = "TYRE_PRESSURE"
    BRAKE_SERVICING = "BRAKE_SERVICING"
    BATTERY_MAINTENANCE = "BATTERY_MAINTENANCE"
    GENERAL_SERVICING = "GENERAL_SERVICING"
    AIR_FILTER = "AIR_FILTER"
    CLUTCH_SERVICING = "CLUTCH_SERVICING"
    ENGINE_REPAIR = "ENGINE_REPAIR"
    ELECTRICAL_REPAIR = "ELECTRICAL_REPAIR"
    PUNCTURE_REPAIR = "PUNCTURE_REPAIR"
    OTHER_MAINTENANCE = "OTHER_MAINTENANCE"


# Friendly human descriptions mapping
CATEGORY_LABELS = {
    MaintenanceCategory.ENGINE_OIL: "Engine Oil & Oil Filter Change",
    MaintenanceCategory.TYRE_REPLACEMENT: "Tyre Replacement / Tube",
    MaintenanceCategory.TYRE_PRESSURE: "Tyre Pressure / Air Check",
    MaintenanceCategory.BRAKE_SERVICING: "Brake Liner & Drum Check / Replacement",
    MaintenanceCategory.BATTERY_MAINTENANCE: "Battery Water & Electricals",
    MaintenanceCategory.GENERAL_SERVICING: "General Tune-up & Lubrication",
    MaintenanceCategory.AIR_FILTER: "Air Filter Cleaning / Replacement",
    MaintenanceCategory.CLUTCH_SERVICING: "Clutch Wire & Accelerator Cable",
    MaintenanceCategory.ENGINE_REPAIR: "Engine Overhaul / Repair",
    MaintenanceCategory.ELECTRICAL_REPAIR: "Lighting & Horn Wiring",
    MaintenanceCategory.PUNCTURE_REPAIR: "Puncture / Patch Repair",
    MaintenanceCategory.OTHER_MAINTENANCE: "Other Vehicle Maintenance",
}


def normalize_maintenance_category(raw_cat: str) -> MaintenanceCategory:
    """Normalizes string inputs to MaintenanceCategory enum."""
    cleaned = raw_cat.strip().upper()
    
    if "OIL" in cleaned:
        return MaintenanceCategory.ENGINE_OIL
    if "BRAKE" in cleaned:
        return MaintenanceCategory.BRAKE_SERVICING
    if "CLUTCH" in cleaned:
        return MaintenanceCategory.CLUTCH_SERVICING
    if "BATTERY" in cleaned:
        return MaintenanceCategory.BATTERY_MAINTENANCE
    if "PUNCTURE" in cleaned or "PUNCHER" in cleaned:
        return MaintenanceCategory.PUNCTURE_REPAIR
    if "TYRE" in cleaned or "TIRE" in cleaned:
        return MaintenanceCategory.TYRE_REPLACEMENT
    if "AIR" in cleaned or "FILTER" in cleaned:
        return MaintenanceCategory.AIR_FILTER
    if "ELECTRICAL" in cleaned or "WIRE" in cleaned or "LIGHT" in cleaned:
        return MaintenanceCategory.ELECTRICAL_REPAIR
    if "GENERAL" in cleaned or "SERVICE" in cleaned or "SERVICING" in cleaned:
        return MaintenanceCategory.GENERAL_SERVICING
    if "ENGINE" in cleaned:
        return MaintenanceCategory.ENGINE_REPAIR

    for mc in MaintenanceCategory:
        if mc.value == cleaned:
            return mc

    return MaintenanceCategory.OTHER_MAINTENANCE


class MaintenanceRecord(BaseModel):
    """
    Vehicle maintenance and service record.
    Can be associated with an underlying financial transaction in the immutable ledger.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    maintenance_id: str = Field(..., description="Unique maintenance ID (e.g. MNT_...)")
    driver_id: str = Field(..., description="Authenticated driver ID")
    vehicle_id: str = Field(..., description="Vehicle ID")
    maintenance_category: MaintenanceCategory = Field(..., description="Type of maintenance")
    description: str = Field(..., description="Work description (e.g. Changed oil, replaced brake shoe)")
    service_date: str = Field(default_factory=today_ist, description="Date service performed (YYYY-MM-DD)")
    odometer_reading: Optional[int] = Field(default=None, description="Current odometer reading in km")
    service_provider: Optional[str] = Field(default="Local Garage", description="Workshop / mechanic name")
    cost: Decimal = Field(..., description="Total cost incurred (non-negative INR)")
    next_service_date: Optional[str] = Field(default=None, description="Scheduled next service date (YYYY-MM-DD)")
    next_service_odometer: Optional[int] = Field(default=None, description="Scheduled next service odometer (km)")
    receipt_reference: Optional[str] = Field(default=None, description="Receipt or invoice storage reference")
    financial_transaction_id: Optional[str] = Field(default=None, description="Linked Phase 2 ledger transaction ID")
    notes: Optional[str] = Field(default="", description="Optional additional details")
    created_at: datetime.datetime = Field(default_factory=now_utc)
    updated_at: datetime.datetime = Field(default_factory=now_utc)

    @field_validator("maintenance_category", mode="before")
    @classmethod
    def validate_category(cls, v: Any) -> MaintenanceCategory:
        if isinstance(v, MaintenanceCategory):
            return v
        if isinstance(v, str):
            return normalize_maintenance_category(v)
        raise ValueError(f"Invalid maintenance category: {v}")

    @field_validator("cost", mode="before")
    @classmethod
    def validate_cost(cls, v: Any) -> Decimal:
        dec = quantize_money(v)
        if dec < Decimal("0"):
            raise ValueError(f"Maintenance cost cannot be negative, got: {dec}")
        return dec

    @field_validator("odometer_reading", "next_service_odometer")
    @classmethod
    def validate_odometer(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError(f"Odometer reading cannot be negative, got: {v}")
        return v
