"""
Reminder and Notification Domain Models for T2T DRIVE.
Enforces idempotent reminder generation, configurable threshold tracking,
and multi-channel delivery tracking.
"""

from enum import Enum
from typing import Optional
import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.utils.dates import now_utc, today_ist


class ReminderType(str, Enum):
    DOCUMENT_EXPIRY = "DOCUMENT_EXPIRY"
    SERVICE_DUE = "SERVICE_DUE"
    CHALLAN_DUE = "CHALLAN_DUE"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"


class VehicleReminder(BaseModel):
    """
    Idempotent reminder record generated for upcoming document expiries,
    vehicle services, or unpaid challans.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    reminder_id: str = Field(..., description="Unique reminder ID (e.g. REM_...)")
    driver_id: str = Field(..., description="Driver identifier")
    vehicle_id: Optional[str] = Field(default=None, description="Vehicle ID")
    reminder_type: ReminderType = Field(..., description="Type of reminder")
    reference_id: str = Field(..., description="Associated document_id, maintenance_id, or challan_id")
    threshold_days: int = Field(..., description="Threshold milestone (e.g. 30, 15, 7, 1, 0)")
    due_date: str = Field(..., description="Due / Expiry date (YYYY-MM-DD)")
    title: str = Field(..., description="Short reminder headline")
    message: str = Field(..., description="Full friendly notification text in Tamil/Tanglish/English")
    status: ReminderStatus = Field(default=ReminderStatus.PENDING)
    delivered_via: Optional[str] = Field(default=None, description="MOCK, SMS, IN_APP")
    delivered_at: Optional[datetime.datetime] = Field(default=None)
    idempotency_key: str = Field(..., description="Deduplication key: {driver_id}_{reference_id}_{threshold_days}_{due_date}")
    created_at: datetime.datetime = Field(default_factory=now_utc)
    updated_at: datetime.datetime = Field(default_factory=now_utc)
